"""Backtester behaviour, and the look-ahead guarantees it rests on.

The tests in TestNoLookAhead are the reason to trust anything the backtester
reports. A backtest that can see the future produces confident numbers that
cannot be achieved, which is worse than having no backtest at all.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.backtest import Backtester, LookAheadError
from app.core.money import apply_bps
from app.domain import Bar, SignalAction
from app.risk import RiskEngine, RiskLimits
from app.strategies import BaseStrategy, StrategyDecision, build
from tests.conftest import make_bars

RISING = [60000 + 200 * i for i in range(60)]
CHOPPY = [60000, 61000, 59500, 62000, 58000, 63000, 57500, 64000] * 8


class RecordingStrategy(BaseStrategy):
    """Records every window it is shown, so the test can inspect them."""

    name = "recording"

    def __init__(self) -> None:
        self.windows: list[list[Bar]] = []

    @property
    def min_bars(self) -> int:
        return 3

    def _decide(self, bars, closes) -> StrategyDecision:
        self.windows.append(list(bars))
        return StrategyDecision.hold()


class AlwaysBuy(BaseStrategy):
    """Buys on every bar, so execution mechanics are easy to observe."""

    name = "always_buy"

    @property
    def min_bars(self) -> int:
        return 2

    def _decide(self, bars, closes) -> StrategyDecision:
        return StrategyDecision(SignalAction.BUY, Decimal("1"))


class BuyOnce(BaseStrategy):
    """Buys on exactly one bar."""

    name = "buy_once"

    def __init__(self, at_index: int = 5) -> None:
        self.at_index = at_index

    @property
    def min_bars(self) -> int:
        return 2

    def _decide(self, bars, closes) -> StrategyDecision:
        if len(bars) - 1 == self.at_index:
            return StrategyDecision(SignalAction.BUY, Decimal("1"))
        return StrategyDecision.hold()


class TestNoLookAhead:
    """The structural guarantee: decide on bar t, fill at bar t+1's open."""

    def test_a_strategy_never_receives_a_future_bar(self):
        strategy = RecordingStrategy()
        bars = make_bars(RISING)
        Backtester(strategy).run(bars)

        for i, window in enumerate(strategy.windows):
            expected_last = bars[i + strategy.min_bars - 1]
            assert window[-1].open_time == expected_last.open_time
            assert all(b.open_time <= window[-1].open_time for b in window)

    def test_windows_grow_by_exactly_one_bar(self):
        strategy = RecordingStrategy()
        Backtester(strategy).run(make_bars(RISING))
        lengths = [len(w) for w in strategy.windows]
        assert lengths == list(range(strategy.min_bars, len(RISING)))

    def test_fills_occur_at_the_next_bar_open_not_the_signal_bar_close(self, btc):
        """The single most important assertion in the backtester.

        Filling at the signal bar's own close means trading on a price that was
        only knowable once that bar had finished.
        """
        bars = make_bars(RISING)
        result = Backtester(BuyOnce(at_index=5), instrument=btc, slippage_bps="0").run(bars)

        assert result.fills, "expected one fill"
        fill = result.fills[0]

        signal_bar = bars[5]
        execution_bar = bars[6]

        assert fill.price == btc.round_price(execution_bar.open)
        assert fill.price != btc.round_price(signal_bar.close) or (
            execution_bar.open == signal_bar.close
        )
        assert fill.executed_at >= signal_bar.close_time

    def test_slippage_is_applied_to_the_next_open(self, btc):
        bars = make_bars(RISING)
        result = Backtester(BuyOnce(at_index=5), instrument=btc, slippage_bps="10").run(bars)
        expected = btc.round_price(apply_bps(bars[6].open, Decimal("10")))
        assert result.fills[0].price == expected

    def test_the_final_bar_produces_no_trade(self):
        """It has no successor, so a signal there could only fill on itself."""
        bars = make_bars(RISING)
        result = Backtester(AlwaysBuy()).run(bars)
        assert result.bars_processed == len(bars) - 1
        for outcome in result.outcomes:
            assert outcome.signal.bar_close_time <= bars[-2].close_time

    def test_a_signal_from_the_future_is_refused(self):
        """A defensive assertion: a future refactor must fail loudly.

        If a signal could ever be filled on a bar that opened before the signal
        existed, the backtest is reporting unachievable results.
        """
        bars = make_bars(RISING)
        backtester = Backtester(AlwaysBuy())
        future_signal_time = bars[10].close_time

        with pytest.raises(LookAheadError, match="cannot be executed"):
            backtester._assert_no_look_ahead(future_signal_time, bars[5])

    def test_truncating_the_data_does_not_change_earlier_results(self):
        """Results up to bar n must not depend on bars after n."""
        bars = make_bars(RISING)
        full = Backtester(BuyOnce(at_index=5), slippage_bps="0").run(bars)
        short = Backtester(BuyOnce(at_index=5), slippage_bps="0").run(bars[:30])

        assert full.equity_curve[:29] == short.equity_curve[:29]
        assert len(full.fills) == len(short.fills) == 1
        assert full.fills[0].price == short.fills[0].price


class TestExecution:
    def test_commission_is_charged(self, btc):
        result = Backtester(
            BuyOnce(at_index=5), instrument=btc, commission_rate="0.001"
        ).run(make_bars(RISING))
        assert result.fills[0].commission > 0

    def test_equity_curve_has_one_point_per_bar(self):
        bars = make_bars(RISING)
        result = Backtester(AlwaysBuy()).run(bars)
        assert len(result.equity_curve) == len(bars)
        assert len(result.timestamps) == len(bars)

    def test_curve_starts_at_the_opening_balance(self):
        result = Backtester(RecordingStrategy(), starting_balance="50000").run(
            make_bars(RISING)
        )
        assert result.equity_curve[0] == Decimal("50000")

    def test_a_strategy_that_never_trades_leaves_equity_flat(self):
        result = Backtester(RecordingStrategy()).run(make_bars(CHOPPY))
        assert result.report.total_return == 0
        assert result.report.max_drawdown == 0
        assert result.fills == []


class TestRiskIntegration:
    def test_the_same_risk_engine_governs_the_backtest(self):
        """Backtests and live trading must share the risk layer, not mirror it."""
        strict = RiskEngine(RiskLimits(max_position_pct=Decimal("0.0001")))
        result = Backtester(AlwaysBuy(), risk_engine=strict).run(make_bars(RISING))
        assert result.rejections
        assert not result.fills

    def test_rejections_are_retained_with_their_reasons(self):
        strict = RiskEngine(RiskLimits(max_order_value=Decimal("10")))
        result = Backtester(AlwaysBuy(), risk_engine=strict).run(make_bars(RISING))
        assert result.rejections
        assert all(o.reasons for o in result.rejections)

    def test_rejection_reasons_are_counted_by_check(self):
        """Says whether a strategy underperformed or was never allowed to try."""
        strict = RiskEngine(RiskLimits(max_position_pct=Decimal("0.0001")))
        result = Backtester(AlwaysBuy(), risk_engine=strict).run(make_bars(RISING))
        counts = result.rejection_reasons()
        assert counts
        assert "position_size" in counts
        assert sum(counts.values()) >= len(result.rejections)


class TestReporting:
    def test_open_positions_are_reported_apart_from_round_trips(self):
        """An unclosed position is not a trade and must not skew win rate."""
        result = Backtester(BuyOnce(at_index=5), slippage_bps="0").run(make_bars(RISING))
        assert result.open_positions
        assert result.report.total_trades == 0
        assert "Still open" in result.summary()
        assert "not counted in win rate" in result.summary()

    def test_summary_includes_the_core_metrics(self):
        result = Backtester(AlwaysBuy()).run(make_bars(RISING))
        text = result.summary()
        for field in ("Total return", "Sharpe ratio", "Max drawdown", "Win rate"):
            assert field in text


class TestValidation:
    def test_too_little_history_is_refused(self):
        strategy = build("ema_crossover", fast=9, slow=21)
        with pytest.raises(ValueError, match="need at least 23 bars"):
            Backtester(strategy).run(make_bars(RISING[:10]))

    def test_real_strategies_run_end_to_end(self, btc):
        for name, params in [
            ("ema_crossover", {"fast": 5, "slow": 13}),
            ("rsi", {"period": 7}),
            ("macd", {"fast": 5, "slow": 13, "signal": 4}),
            ("mean_reversion", {"period": 10, "entry_z": "1.5"}),
        ]:
            result = Backtester(build(name, **params), instrument=btc).run(
                make_bars(CHOPPY)
            )
            assert result.bars_processed > 0
            assert result.strategy == name
            report = result.report
            assert Decimal("-1") <= report.max_drawdown <= Decimal("1")
