"""Triple-barrier labeling, checked against hand-constructed price paths."""

from __future__ import annotations

from decimal import Decimal

from app.domain import Side
from app.ml.labels import LabelConfig, label_series
from tests.conftest import make_bars


def config(horizon=10, stop=Decimal("1.5"), target=Decimal("2.0"), atr_period=5):
    return LabelConfig(
        horizon=horizon, stop_atr_multiple=stop, target_atr_multiple=target, atr_period=atr_period
    )


class TestWarmupAndHorizon:
    def test_bars_before_atr_is_defined_are_unlabeled(self):
        bars = make_bars([100] * 20)
        labels = label_series(bars, Side.BUY, config(atr_period=5))
        assert labels[0] is None
        assert labels[1] is None

    def test_the_tail_within_the_horizon_of_the_end_is_unlabeled(self):
        """An unresolved trade contributes no training signal."""
        bars = make_bars([100 + i for i in range(20)])
        labels = label_series(bars, Side.BUY, config(horizon=10))
        assert labels[-1] is None
        assert labels[-2] is None


class TestLongTradeResolution:
    def test_a_stop_hit_before_target_is_adverse(self):
        # Volatile warm-up so ATR is meaningful, then a sharp drop.
        prices = [100, 102, 99, 103, 98, 104, 97] + [100] + [80] + [100] * 10
        bars = make_bars(prices)
        labels = label_series(bars, Side.BUY, config(atr_period=5, horizon=8))
        entry_index = 7  # the "100" right before the crash
        example = labels[entry_index]
        assert example is not None
        assert example.adverse is True

    def test_a_target_hit_before_stop_is_not_adverse(self):
        prices = [100, 102, 99, 103, 98, 104, 97] + [100] + [130] + [100] * 10
        bars = make_bars(prices)
        labels = label_series(bars, Side.BUY, config(atr_period=5, horizon=8))
        entry_index = 7
        example = labels[entry_index]
        assert example is not None
        assert example.adverse is False

    def test_neither_barrier_touched_resolves_by_final_direction(self):
        # Gentle drift down, never touching either wide barrier.
        prices = [100, 101, 99, 100, 101, 99] + [100, 99.5, 99, 98.5, 98, 97.5, 97, 96.5]
        bars = make_bars(prices)
        cfg = config(atr_period=5, horizon=7, stop=Decimal("10"), target=Decimal("10"))
        labels = label_series(bars, Side.BUY, cfg)
        entry_index = 5
        example = labels[entry_index]
        assert example is not None
        # Ended lower than entry with neither barrier touched -> adverse.
        assert example.adverse is True


class TestShortTradeResolution:
    def test_barriers_are_mirrored_for_a_short(self):
        """A short profits when price falls and is hurt when it rises."""
        prices = [100, 102, 99, 103, 98, 104, 97] + [100] + [130] + [100] * 10
        bars = make_bars(prices)
        labels = label_series(bars, Side.SELL, config(atr_period=5, horizon=8))
        entry_index = 7
        example = labels[entry_index]
        assert example is not None
        # The same rally that helped a long is adverse for a short.
        assert example.adverse is True

    def test_a_fall_is_favourable_for_a_short(self):
        prices = [100, 102, 99, 103, 98, 104, 97] + [100] + [80] + [100] * 10
        bars = make_bars(prices)
        labels = label_series(bars, Side.SELL, config(atr_period=5, horizon=8))
        entry_index = 7
        example = labels[entry_index]
        assert example is not None
        assert example.adverse is False


class TestConservativeAssumption:
    def test_a_bar_touching_both_barriers_counts_as_the_stop(self):
        """Absent intrabar data, the stop is assumed to bind first.

        This is the conservative assumption: it never under-counts adverse
        outcomes.
        """
        from app.domain import Bar

        prices = [100, 102, 99, 103, 98, 104, 97, 100]
        bars = make_bars(prices)
        cfg = config(atr_period=5, horizon=2)

        # Compute the entry ATR the same way label_series does, so the
        # explosive bar below is guaranteed wide enough to cross both
        # barriers regardless of the exact ATR value.
        from app.strategies.indicators import atr as atr_series

        entry_atr = atr_series(
            [b.high for b in bars], [b.low for b in bars], [b.close for b in bars], 5
        )[7]
        assert entry_atr is not None

        entry_price = bars[7].close
        span = entry_atr * cfg.target_atr_multiple * 2  # comfortably past both

        explosive = Bar(
            symbol="BTCUSDT",
            open_time=bars[7].close_time,
            close_time=bars[7].close_time + (bars[7].close_time - bars[6].close_time),
            open=entry_price,
            high=entry_price + span,
            low=max(entry_price - span, Decimal("0.01")),
            close=entry_price,
            volume=Decimal("10"),
        )
        extended = [*bars, explosive, explosive, explosive]

        labels = label_series(extended, Side.BUY, cfg)
        example = labels[7]
        assert example is not None
        assert example.adverse is True
        assert example.bars_to_resolution == 1


class TestBarsToResolution:
    def test_records_how_many_bars_the_resolution_took(self):
        prices = [100, 102, 99, 103, 98, 104, 97] + [100] + [130] + [100] * 10
        bars = make_bars(prices)
        labels = label_series(bars, Side.BUY, config(atr_period=5, horizon=8))
        example = labels[7]
        assert example is not None
        assert example.bars_to_resolution == 1  # the very next bar hits target
