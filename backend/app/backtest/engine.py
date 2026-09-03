"""Event-driven backtester.

Reuses the live strategy, risk engine, broker protocol and portfolio. Only the
market data source and the clock differ. If a backtest and live trading
disagree, that is a bug rather than an expected difference.

**The look-ahead rule.** A signal computed from the bar closing at time *t* is
filled at the *open of bar t+1*. Never at bar *t*'s close — that price is only
knowable once the bar has finished, so trading on it means acting on
information that did not exist at the decision point. The loop enforces this
structurally: the strategy is handed bars ``[0..i]`` and execution happens
against ``bars[i+1].open``, so there is no code path where the two can be the
same bar.

Two further leaks are closed:

* the strategy only ever receives a slice ending at the current bar, so it
  cannot index past the present even accidentally;
* the risk engine marks the portfolio using bar *i*'s close, which is known at
  the decision point, rather than the fill price it has not yet received.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.analytics import (
    PerformanceReport,
    TradeRecord,
    build_report,
    realized_volatility_annualised,
)
from app.brokers import PaperBroker
from app.core.logging import get_logger
from app.core.money import ZERO, D
from app.domain import Bar, Fill, Instrument, RiskAction, Side
from app.portfolio import Portfolio
from app.risk import RiskEngine
from app.strategies import BaseStrategy
from app.trading import TradeOutcome, TradingPipeline

log = get_logger(__name__)


class LookAheadError(RuntimeError):
    """A signal was about to be executed on data it could not have seen."""


@dataclass
class BacktestResult:
    """Everything a backtest produced, including what it refused to trade."""

    strategy: str
    symbol: str
    interval: str

    equity_curve: list[Decimal] = field(default_factory=list)
    timestamps: list[object] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)
    outcomes: list[TradeOutcome] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)

    starting_balance: Decimal = ZERO
    bars_processed: int = 0

    #: Positions still open at the end of the run, and their mark-to-market
    #: P&L. Reported separately because they are not round trips and so do not
    #: appear in win rate or profit factor.
    open_positions: tuple = ()
    open_position_pnl: Decimal = ZERO

    @property
    def report(self) -> PerformanceReport:
        return build_report(self.equity_curve, self.trades, self.interval)

    @property
    def rejections(self) -> list[TradeOutcome]:
        return [o for o in self.outcomes if o.rejected]

    @property
    def signals_generated(self) -> int:
        return len(self.outcomes)

    def rejection_reasons(self) -> dict[str, int]:
        """How often each risk check refused a trade.

        The most useful diagnostic a backtest produces: it says whether a
        strategy underperformed because its ideas were poor or because the risk
        limits never let it express them.
        """
        counts: dict[str, int] = {}
        for outcome in self.rejections:
            for check in outcome.decision.failed_checks:
                counts[check.name] = counts.get(check.name, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def summary(self) -> str:
        lines = [
            f"Strategy        : {self.strategy}",
            f"Symbol          : {self.symbol} ({self.interval})",
            f"Bars processed  : {self.bars_processed}",
            f"Signals         : {self.signals_generated}"
            f"  (executed {len(self.fills)}, rejected {len(self.rejections)})",
            "",
            self.report.summary(),
        ]
        if self.open_positions:
            held = ", ".join(f"{p.symbol} {p.signed_quantity}" for p in self.open_positions)
            lines += [
                "",
                f"Still open      : {held}",
                f"  unrealised    : {self.open_position_pnl:.2f}"
                "  (not counted in win rate or profit factor)",
            ]
        reasons = self.rejection_reasons()
        if reasons:
            lines += ["", "Rejected by:"]
            lines += [f"  {name}: {count}" for name, count in reasons.items()]
        return "\n".join(lines)


class Backtester:
    """Replays historical bars through the live trading pipeline."""

    def __init__(
        self,
        strategy: BaseStrategy,
        risk_engine: RiskEngine | None = None,
        starting_balance: Decimal | str = "100000",
        commission_rate: Decimal | str = "0.0004",
        slippage_bps: Decimal | str = "2",
        instrument: Instrument | None = None,
        interval: str = "1h",
    ) -> None:
        self.strategy = strategy
        self.risk_engine = risk_engine or RiskEngine()
        self.starting_balance = D(starting_balance)
        self.commission_rate = D(commission_rate)
        self.slippage_bps = D(slippage_bps)
        self.instrument = instrument
        self.interval = interval

    def run(self, bars: list[Bar]) -> BacktestResult:
        """Replay ``bars``, one decision per bar."""
        if len(bars) < self.strategy.min_bars + 1:
            raise ValueError(
                f"need at least {self.strategy.min_bars + 1} bars to backtest "
                f"{self.strategy.name}, got {len(bars)}"
            )

        symbol = bars[0].symbol
        instruments = {symbol: self.instrument} if self.instrument else {}

        broker = PaperBroker(
            commission_rate=self.commission_rate,
            slippage_bps=self.slippage_bps,
            instruments=instruments,
        )
        portfolio = Portfolio(self.starting_balance)
        pipeline = TradingPipeline(
            risk_engine=self.risk_engine,
            broker=broker,
            portfolio=portfolio,
            instruments=instruments,
        )

        result = BacktestResult(
            strategy=self.strategy.name,
            symbol=symbol,
            interval=self.interval,
            starting_balance=self.starting_balance,
        )

        realized_before = ZERO

        # Stop one short of the end: the final bar has no successor to fill
        # against, so a signal there could only be executed on its own close.
        for i in range(len(bars) - 1):
            decision_bar = bars[i]
            execution_bar = bars[i + 1]

            # Mark and record equity for THIS bar's close before evaluating
            # anything new. This must happen first, not last: a signal decided
            # here fills at execution_bar's OPEN, which is chronologically
            # AFTER decision_bar's close. Recording equity after applying that
            # fill (the previous ordering) would book a position acquired at
            # t+1 into the curve point for t, valued at t's price -- a swing
            # that only existed because of when the code happened to look,
            # and that unwound itself on the very next bar. Fills from a prior
            # iteration are correctly already reflected here, since those
            # executed at THIS bar's open, before THIS bar's close.
            portfolio.set_mark(symbol, decision_bar.close, when=decision_bar.close_time)
            result.equity_curve.append(portfolio.equity)
            result.timestamps.append(decision_bar.close_time)
            result.bars_processed += 1

            if i + 1 >= self.strategy.min_bars:
                window = bars[: i + 1]
                signal = self.strategy.evaluate(window)

                if signal is not None and signal.is_actionable:
                    self._assert_no_look_ahead(signal.bar_close_time, execution_bar)

                    # Fill at the NEXT bar's open, the first price actually
                    # obtainable after the decision.
                    broker.set_mark(symbol, execution_bar.open)
                    # Stamp the decision, order and fill with the bar they
                    # happened on rather than wall-clock time.
                    pipeline.set_time(execution_bar.open_time)

                    # The volatility check must see the same figure a live run
                    # would compute from this window -- previously this was
                    # never passed here, so every backtest silently ran with
                    # volatility=None and that check never actually engaged.
                    volatility = realized_volatility_annualised(
                        [b.close for b in window], interval=self.interval
                    )
                    outcome = pipeline.handle_signal(signal, volatility=volatility)
                    result.outcomes.append(outcome)

                    if outcome.fills:
                        result.fills.extend(outcome.fills)
                        realized_now = portfolio.realized_pnl
                        if realized_now != realized_before:
                            # Net of commission, matching the convention the
                            # live performance endpoint uses (app.api.routes.
                            # performance) -- a trade that only lost its
                            # commission must not count as a win in either
                            # place, and the two must agree on the same fills.
                            commission = sum((f.commission for f in outcome.fills), ZERO)
                            result.trades.append(
                                TradeRecord(symbol, realized_now - realized_before - commission)
                            )
                            realized_before = realized_now

        # Mark to the final bar so the closing equity reflects all data.
        portfolio.set_mark(symbol, bars[-1].close, when=bars[-1].close_time)
        result.equity_curve.append(portfolio.equity)
        result.timestamps.append(bars[-1].close_time)

        final = portfolio.snapshot()
        result.open_positions = final.open_positions
        result.open_position_pnl = final.unrealized_pnl

        log.info(
            "backtest.complete",
            strategy=self.strategy.name,
            symbol=symbol,
            bars=result.bars_processed,
            signals=result.signals_generated,
            executed=len(result.fills),
            rejected=len(result.rejections),
        )
        return result

    @staticmethod
    def _assert_no_look_ahead(signal_close_time, execution_bar: Bar) -> None:
        """The signal's bar must have closed before the execution bar opens.

        A defensive assertion rather than a test: if a future refactor lets a
        signal be filled on its own bar, the backtest fails loudly instead of
        quietly reporting results that cannot be achieved.
        """
        if signal_close_time > execution_bar.open_time:
            raise LookAheadError(
                f"signal from a bar closing at {signal_close_time} cannot be "
                f"executed on a bar opening at {execution_bar.open_time}"
            )


__all__ = ["Backtester", "BacktestResult", "LookAheadError", "RiskAction", "Side"]
