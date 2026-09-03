"""Populate the database with a realistic trading history.

Generates a deterministic synthetic price series, stores it as bars, then runs
the real pipeline over it — the same strategies, risk engine, broker and
portfolio the live system uses. Nothing here fabricates results: every order,
fill and rejection in the database was actually produced by the platform.

Deterministic by design (fixed seed), so the dashboard shows the same figures
on every machine and a screenshot can be reasoned about.

    python -m scripts.seed [--reset]
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from app.core.logging import configure_logging, get_logger
from app.db.repositories import InstrumentRepository
from app.db.session import session_scope
from app.domain import Bar, Instrument
from app.marketdata import BarRepository
from app.risk import RiskLimits
from app.services import TradingService
from app.strategies import build

log = get_logger("seed")

SEED = 20260903
INTERVAL = "1h"
BARS = 720  # 30 days of hourly candles

INSTRUMENTS = [
    Instrument(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        tick_size=Decimal("0.10"),
        step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("100"),
        max_leverage=20,
    ),
    Instrument(
        symbol="ETHUSDT",
        base_asset="ETH",
        quote_asset="USDT",
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("20"),
        max_leverage=20,
    ),
    Instrument(
        symbol="SOLUSDT",
        base_asset="SOL",
        quote_asset="USDT",
        tick_size=Decimal("0.010"),
        step_size=Decimal("0.1"),
        min_quantity=Decimal("0.1"),
        min_notional=Decimal("10"),
        max_leverage=20,
    ),
]

#: symbol -> (starting price, annual drift, hourly volatility)
PROFILES = {
    "BTCUSDT": (Decimal("62000"), 0.00004, 0.006),
    "ETHUSDT": (Decimal("3200"), 0.00002, 0.008),
    "SOLUSDT": (Decimal("145"), -0.00003, 0.013),
}


def generate_bars(symbol: str, start: datetime, count: int) -> list[Bar]:
    """A random walk with drift, a slow cycle and two volatility regimes.

    The cycle gives the reversion strategies something to trade and the regime
    switch gives the risk engine's volatility check something to react to.
    """
    base, drift, vol = PROFILES[symbol]
    rng = random.Random(f"{SEED}-{symbol}")

    price = float(base)
    bars: list[Bar] = []

    for i in range(count):
        # Quiet for the first half, turbulent for the second.
        regime = 1.0 if i < count * 0.55 else 2.4
        cycle = math.sin(i / 42.0) * vol * 0.6
        shock = rng.gauss(0, vol * regime)
        price = max(price * (1 + drift + cycle + shock), float(base) * 0.25)

        open_price = price / (1 + shock / 2) if shock else price
        high = max(open_price, price) * (1 + abs(rng.gauss(0, vol / 3)))
        low = min(open_price, price) * (1 - abs(rng.gauss(0, vol / 3)))

        open_time = start + timedelta(hours=i)
        bars.append(
            Bar(
                symbol=symbol,
                open_time=open_time,
                close_time=open_time + timedelta(hours=1),
                open=_q(open_price),
                high=_q(high),
                low=_q(low),
                close=_q(price),
                volume=Decimal(str(round(rng.uniform(50, 900), 3))),
            )
        )
    return bars


def _q(value: float) -> Decimal:
    return Decimal(str(round(value, 4)))


def reset(session) -> None:
    """Clear generated data. Order matters: children before parents."""
    for table in ("fills", "orders", "risk_decisions", "signals", "bars", "audit_log"):
        session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
    log.info("seed.reset")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the database.")
    parser.add_argument("--reset", action="store_true", help="clear existing data first")
    parser.add_argument("--bars", type=int, default=BARS)
    args = parser.parse_args()

    configure_logging("INFO", "console")

    start = datetime.now(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    ) - timedelta(hours=args.bars)

    with session_scope() as session:
        if args.reset:
            reset(session)

        instruments_repo = InstrumentRepository(session)
        for instrument in INSTRUMENTS:
            instruments_repo.upsert(instrument)
        session.flush()

        bars_repo = BarRepository(session)
        market: dict[str, list[Bar]] = {}
        for instrument in INSTRUMENTS:
            bars = generate_bars(instrument.symbol, start, args.bars)
            bars_repo.save(bars, INTERVAL)
            market[instrument.symbol] = bars
            log.info("seed.bars", symbol=instrument.symbol, count=len(bars))
        session.flush()

        # Slightly tighter limits than the defaults, so the seeded history
        # contains reductions and rejections rather than only approvals.
        service = TradingService(
            session=session,
            limits=RiskLimits(
                max_position_pct=Decimal("0.08"),
                max_portfolio_exposure_pct=Decimal("0.45"),
                max_order_value=Decimal("12000"),
                max_volatility=Decimal("1.20"),
            ),
        )

        strategies = {
            "BTCUSDT": build("ema_crossover", fast=9, slow=21),
            "ETHUSDT": build("macd"),
            "SOLUSDT": build("mean_reversion", period=20, entry_z="1.8"),
        }
        rsi = build("rsi", period=14)

        counts = {"signals": 0, "orders": 0, "rejected": 0}

        # Walk the series bar by bar, exactly as live trading would.
        for i in range(1, args.bars):
            for symbol, bars in market.items():
                window = bars[: i + 1]
                service.set_mark(symbol, bars[i].close)
                # Stamp everything with the bar's own time so the seeded
                # history spans the full period rather than collapsing onto
                # the moment the script happened to run.
                service.set_time(bars[i].close_time)

                for strategy in (strategies[symbol], rsi):
                    signal = strategy.evaluate(window)
                    if signal is None or not signal.is_actionable:
                        continue

                    volatility = _realised_volatility(window)
                    outcome = service.handle_signal(signal, volatility=volatility)

                    counts["signals"] += 1
                    if outcome.order is not None:
                        counts["orders"] += 1
                    if outcome.rejected:
                        counts["rejected"] += 1

        snapshot = service.snapshot()
        log.info(
            "seed.complete",
            **counts,
            equity=str(round(snapshot.equity, 2)),
            realized_pnl=str(round(snapshot.realized_pnl, 2)),
            open_positions=len(snapshot.open_positions),
        )

    print("\nSeed complete.")
    print(f"  signals   : {counts['signals']}")
    print(f"  orders    : {counts['orders']}")
    print(f"  rejected  : {counts['rejected']}")
    print(f"  equity    : {snapshot.equity:,.2f}")
    return 0


def _realised_volatility(bars: list[Bar], lookback: int = 24) -> Decimal | None:
    """Annualised realised volatility over the recent window."""
    from app.strategies.indicators import realized_volatility

    if len(bars) <= lookback:
        return None
    closes = [b.close for b in bars]
    series = realized_volatility(closes, lookback)
    hourly = series[-1]
    if hourly is None:
        return None
    return hourly * Decimal(8760).sqrt()


if __name__ == "__main__":
    sys.exit(main())
