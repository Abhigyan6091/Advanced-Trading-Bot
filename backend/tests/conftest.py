from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("APP_ENV", "test")

from app.domain import Bar, Fill, Instrument, Side, Signal, SignalAction  # noqa: E402

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def btc() -> Instrument:
    return Instrument(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        tick_size=Decimal("0.10"),
        step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("100"),
        max_leverage=20,
    )


@pytest.fixture
def bar() -> Bar:
    return Bar(
        symbol="BTCUSDT",
        open_time=T0,
        close_time=T0 + timedelta(minutes=1),
        open=Decimal("60000"),
        high=Decimal("60500"),
        low=Decimal("59800"),
        close=Decimal("60200"),
        volume=Decimal("12.5"),
    )


@pytest.fixture
def buy_signal(bar: Bar) -> Signal:
    return Signal(
        strategy="ema_crossover",
        symbol="BTCUSDT",
        action=SignalAction.BUY,
        strength=Decimal("0.8"),
        reference_price=bar.close,
        bar_close_time=bar.close_time,
        features={"ema_fast": "60210", "ema_slow": "60050"},
    )


def make_fill(
    order_id, side: Side, qty: str, price: str, *, at: datetime = T0, commission: str = "0"
) -> Fill:
    return Fill(
        order_id=order_id,
        symbol="BTCUSDT",
        side=side,
        quantity=Decimal(qty),
        price=Decimal(price),
        commission=Decimal(commission),
        executed_at=at,
    )


def make_bars(
    closes: list[str | int | float],
    *,
    symbol: str = "BTCUSDT",
    start: datetime = T0,
    interval_minutes: int = 60,
    spread: str = "0.005",
) -> list[Bar]:
    """Build a chronological bar series from a list of close prices.

    High and low are derived from the close by a fixed fraction, which keeps
    the OHLC invariants satisfied without the fixture having to state four
    numbers per bar.
    """
    step = timedelta(minutes=interval_minutes)
    pad = Decimal(spread)
    bars: list[Bar] = []
    prev_close: Decimal | None = None
    for i, c in enumerate(closes):
        close = Decimal(str(c))
        open_ = prev_close if prev_close is not None else close
        bars.append(
            Bar(
                symbol=symbol,
                open_time=start + i * step,
                close_time=start + (i + 1) * step,
                open=open_,
                high=max(open_, close) * (1 + pad),
                low=min(open_, close) * (1 - pad),
                close=close,
                volume=Decimal("10"),
            )
        )
        prev_close = close
    return bars
