"""Strategy engine behaviour and its structural guarantees."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain import SignalAction
from app.strategies import (
    EmaCrossoverStrategy,
    InsufficientHistory,
    MacdStrategy,
    MeanReversionStrategy,
    RsiStrategy,
    available,
    build,
)
from tests.conftest import make_bars

ALL_STRATEGIES = [
    EmaCrossoverStrategy(fast=3, slow=6),
    RsiStrategy(period=4),
    MacdStrategy(fast=3, slow=6, signal=3),
    MeanReversionStrategy(period=5, entry_z="1.5"),
]
IDS = [s.name for s in ALL_STRATEGIES]


def sweep(strategy, bars):
    """Evaluate the strategy bar by bar, exactly as live trading would.

    Each step sees only the bars up to that point — the same discipline the
    backtester applies.
    """
    out = []
    for i in range(1, len(bars) + 1):
        signal = strategy.evaluate(bars[:i])
        if signal is not None:
            out.append((i - 1, signal))
    return out


class TestContract:
    """Rules that hold for every strategy, regardless of its logic."""

    @pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=IDS)
    def test_returns_none_while_warming_up(self, strategy):
        bars = make_bars(list(range(100, 100 + strategy.min_bars - 1)))
        assert strategy.evaluate(bars) is None

    @pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=IDS)
    def test_produces_a_signal_once_warm(self, strategy):
        bars = make_bars(list(range(100, 100 + strategy.min_bars + 5)))
        assert strategy.evaluate(bars) is not None

    @pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=IDS)
    def test_min_bars_is_tight(self, strategy):
        """At exactly min_bars the indicators must be live.

        An over-stated warm-up is not a harmless safety margin: the strategy
        goes blind to any crossing that happens in the bars it discarded.
        """
        prices = [100 + (3 * i if i % 2 else -2 * i) for i in range(strategy.min_bars)]
        signal = strategy.evaluate(make_bars(prices))
        assert signal is not None
        assert signal.features.get("reason") != "warming_up"

    @pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=IDS)
    def test_signal_is_stamped_with_the_last_bar(self, strategy):
        """The anti-look-ahead guarantee, enforced in the base class."""
        bars = make_bars(list(range(100, 100 + strategy.min_bars + 5)))
        signal = strategy.evaluate(bars)
        assert signal.bar_close_time == bars[-1].close_time
        assert signal.reference_price == bars[-1].close
        assert signal.strategy == strategy.name

    @pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=IDS)
    def test_later_bars_cannot_change_an_earlier_signal(self, strategy):
        """Appending future bars must not alter a decision already made."""
        base = make_bars([100, 102, 101, 105, 103, 108, 106, 111, 109, 114, 112, 118])
        extended = make_bars(
            [100, 102, 101, 105, 103, 108, 106, 111, 109, 114, 112, 118, 60, 200, 40]
        )
        cut = strategy.min_bars + 1
        if cut > len(base):
            pytest.skip("series shorter than warm-up")

        first = strategy.evaluate(base[:cut])
        second = strategy.evaluate(extended[:cut])
        assert (first.action, first.strength) == (second.action, second.strength)

    @pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=IDS)
    def test_hold_signals_carry_no_strength(self, strategy):
        prices = [100 + (i % 2) for i in range(strategy.min_bars + 10)]
        for _, signal in sweep(strategy, make_bars(prices)):
            if signal.action is SignalAction.HOLD:
                assert signal.strength == 0
                assert not signal.is_actionable

    @pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=IDS)
    def test_strength_is_normalised(self, strategy):
        prices = [100, 90, 80, 70, 60, 70, 85, 100, 120, 140, 130, 110, 95, 80, 70, 90, 115]
        for _, signal in sweep(strategy, make_bars(prices)):
            assert Decimal(0) <= signal.strength <= Decimal(1)

    @pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=IDS)
    def test_records_its_parameters_on_the_signal(self, strategy):
        bars = make_bars(list(range(100, 100 + strategy.min_bars + 3)))
        signal = strategy.evaluate(bars)
        for key in strategy.parameters:
            assert key in signal.features


class TestBarWindowValidation:
    def test_mixed_symbols_are_refused(self):
        strategy = EmaCrossoverStrategy(fast=3, slow=6)
        bars = make_bars(list(range(100, 112)))
        bars[-1] = bars[-1].model_copy(update={"symbol": "ETHUSDT"})
        with pytest.raises(ValueError, match="mixes symbols"):
            strategy.evaluate(bars)

    def test_out_of_order_bars_are_refused(self):
        strategy = EmaCrossoverStrategy(fast=3, slow=6)
        bars = make_bars(list(range(100, 112)))
        bars[5], bars[6] = bars[6], bars[5]
        with pytest.raises(ValueError, match="strictly chronological"):
            strategy.evaluate(bars)

    def test_duplicate_timestamps_are_refused(self):
        strategy = EmaCrossoverStrategy(fast=3, slow=6)
        bars = make_bars(list(range(100, 112)))
        bars[6] = bars[6].model_copy(
            update={
                "open_time": bars[5].open_time,
                "close_time": bars[5].close_time + timedelta(minutes=1),
            }
        )
        with pytest.raises(ValueError, match="strictly chronological"):
            strategy.evaluate(bars)

    def test_evaluate_strict_raises_instead_of_returning_none(self):
        strategy = EmaCrossoverStrategy(fast=3, slow=6)
        with pytest.raises(InsufficientHistory, match="needs 7 bars"):
            strategy.evaluate_strict(make_bars([100, 101]))


class TestEmaCrossover:
    strategy = EmaCrossoverStrategy(fast=3, slow=6)

    def test_golden_cross_produces_a_single_buy(self):
        """A cross is an event: it must not re-fire while the trend persists."""
        prices = [100, 98, 96, 94, 92, 90, 88, 95, 103, 112, 122, 133, 145, 158]
        signals = sweep(self.strategy, make_bars(prices))
        buys = [s for _, s in signals if s.action is SignalAction.BUY]
        assert len(buys) == 1
        assert buys[0].features["event"] == "golden_cross"

    def test_death_cross_produces_a_sell(self):
        prices = [100, 103, 106, 110, 115, 121, 128, 120, 110, 98, 85, 71, 56, 40]
        signals = sweep(self.strategy, make_bars(prices))
        sells = [s for _, s in signals if s.action is SignalAction.SELL]
        assert len(sells) == 1
        assert sells[0].features["event"] == "death_cross"

    def test_flat_market_never_trades(self):
        signals = sweep(self.strategy, make_bars([100] * 20))
        assert all(s.action is SignalAction.HOLD for _, s in signals)

    def test_fast_must_be_shorter_than_slow(self):
        with pytest.raises(ValueError, match="fast period must be shorter"):
            EmaCrossoverStrategy(fast=21, slow=9)


class TestRsi:
    strategy = RsiStrategy(period=4, oversold=30, overbought=70)

    def test_buys_on_recovery_out_of_oversold(self):
        prices = [100, 92, 84, 77, 70, 64, 58, 53, 68, 84, 100]
        signals = sweep(self.strategy, make_bars(prices))
        buys = [s for _, s in signals if s.action is SignalAction.BUY]
        assert buys, "expected a recovery out of oversold"
        assert buys[0].features["event"] == "exited_oversold"

    def test_sells_on_fallback_from_overbought(self):
        prices = [100, 110, 121, 133, 146, 161, 177, 195, 170, 148, 128]
        signals = sweep(self.strategy, make_bars(prices))
        sells = [s for _, s in signals if s.action is SignalAction.SELL]
        assert sells, "expected a fallback from overbought"
        assert sells[0].features["event"] == "exited_overbought"

    def test_does_not_buy_while_still_falling(self):
        """The point of waiting for the exit: never catch a falling knife."""
        prices = [100 - 6 * i for i in range(12)]
        signals = sweep(self.strategy, make_bars(prices))
        assert not [s for _, s in signals if s.action is SignalAction.BUY]

    @pytest.mark.parametrize(
        ("oversold", "overbought"), [(70, 30), (0, 70), (30, 100), (50, 50)]
    )
    def test_invalid_thresholds_are_refused(self, oversold, overbought):
        with pytest.raises(ValueError, match="0 < oversold < overbought < 100"):
            RsiStrategy(period=4, oversold=oversold, overbought=overbought)


class TestMacd:
    strategy = MacdStrategy(fast=3, slow=6, signal=3)

    def test_trades_when_the_histogram_changes_sign(self):
        prices = [100, 96, 92, 88, 84, 80, 76, 72, 80, 92, 106, 122, 140, 160, 182]
        signals = sweep(self.strategy, make_bars(prices))
        events = [s.features.get("event") for _, s in signals if s.is_actionable]
        assert "bullish_crossover" in events

    def test_histogram_is_reported_on_every_signal(self):
        prices = [100, 105, 103, 110, 108, 116, 113, 122, 119, 129, 126, 137, 133, 145]
        for _, signal in sweep(self.strategy, make_bars(prices)):
            assert "histogram" in signal.features


class TestMeanReversion:
    strategy = MeanReversionStrategy(period=5, entry_z="1.5")

    def test_buys_a_sharp_dislocation_below_the_mean(self):
        prices = [100, 100, 101, 99, 100, 101, 100, 99, 100, 82]
        signals = sweep(self.strategy, make_bars(prices))
        last = signals[-1][1]
        assert last.action is SignalAction.BUY
        assert last.features["event"] == "below_band"

    def test_sells_a_sharp_dislocation_above_the_mean(self):
        prices = [100, 100, 101, 99, 100, 101, 100, 99, 100, 122]
        signals = sweep(self.strategy, make_bars(prices))
        last = signals[-1][1]
        assert last.action is SignalAction.SELL
        assert last.features["event"] == "above_band"

    def test_holds_inside_the_band(self):
        prices = [100, 101, 99, 100, 101, 99, 100, 101, 99, 100]
        signals = sweep(self.strategy, make_bars(prices))
        assert all(s.action is SignalAction.HOLD for _, s in signals)

    def test_does_not_re_enter_while_price_stays_extreme(self):
        """Requires the move to be newly extreme, not merely extreme."""
        prices = [100, 100, 101, 99, 100, 101, 100, 99, 100, 82, 81, 80]
        signals = sweep(self.strategy, make_bars(prices))
        buys = [s for _, s in signals if s.action is SignalAction.BUY]
        assert len(buys) == 1

    def test_flat_series_has_no_scale(self):
        signals = sweep(self.strategy, make_bars([100] * 12))
        assert all(s.features.get("reason") == "no_dispersion" for _, s in signals)

    def test_entry_z_must_be_positive(self):
        with pytest.raises(ValueError, match="entry_z must be positive"):
            MeanReversionStrategy(period=5, entry_z="0")


class TestRegistry:
    def test_lists_all_four_strategies(self):
        assert available() == ["ema_crossover", "macd", "mean_reversion", "rsi"]

    def test_builds_by_name_with_parameters(self):
        strategy = build("ema_crossover", fast=5, slow=13)
        assert isinstance(strategy, EmaCrossoverStrategy)
        assert strategy.parameters == {"fast": 5, "slow": 13}

    def test_unknown_name_lists_the_alternatives(self):
        with pytest.raises(ValueError, match="unknown strategy 'bollinger'"):
            build("bollinger")
