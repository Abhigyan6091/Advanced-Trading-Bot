"""Indicators, checked against values computed by hand.

Every expected number here is derivable with a calculator from the definition
of the indicator — no reference library is trusted, because a bug reproduced
identically in two places is still a bug.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.strategies.indicators import (
    atr,
    ema,
    macd,
    realized_volatility,
    rsi,
    sma,
    stddev,
    true_range,
    zscore,
)


def dec(*values) -> list[Decimal]:
    return [Decimal(str(v)) for v in values]


class TestLengthAndWarmup:
    """Results align index-for-index with the input series."""

    @pytest.mark.parametrize(
        "fn",
        [
            lambda v: sma(v, 3),
            lambda v: ema(v, 3),
            lambda v: rsi(v, 3),
            lambda v: stddev(v, 3),
            lambda v: zscore(v, 3),
        ],
        ids=["sma", "ema", "rsi", "stddev", "zscore"],
    )
    def test_output_length_matches_input(self, fn):
        values = dec(1, 2, 3, 4, 5, 6, 7, 8)
        assert len(fn(values)) == len(values)

    def test_warmup_positions_are_none(self):
        result = sma(dec(1, 2, 3, 4), 3)
        assert result[0] is None and result[1] is None
        assert result[2] == Decimal("2")

    def test_too_short_a_series_is_all_none(self):
        assert ema(dec(1, 2), 5) == [None, None]

    def test_period_must_be_positive(self):
        with pytest.raises(ValueError, match="period must be at least 1"):
            sma(dec(1, 2, 3), 0)


class TestSma:
    def test_hand_computed(self):
        # (1+2+3)/3 = 2 ; (2+3+4)/3 = 3 ; (3+4+5)/3 = 4
        assert sma(dec(1, 2, 3, 4, 5), 3) == [None, None, Decimal(2), Decimal(3), Decimal(4)]


class TestEma:
    def test_hand_computed(self):
        # period 3 -> alpha = 2/4 = 0.5, seeded with SMA(1,2,3) = 2
        #   ema[3] = 0.5*4 + 0.5*2 = 3
        #   ema[4] = 0.5*5 + 0.5*3 = 4
        result = ema(dec(1, 2, 3, 4, 5), 3)
        assert result[2] == Decimal("2")
        assert result[3] == Decimal("3")
        assert result[4] == Decimal("4")

    def test_constant_series_returns_the_constant(self):
        assert ema([Decimal("7")] * 10, 4)[-1] == Decimal("7")

    def test_faster_period_reacts_more(self):
        prices = dec(*([10] * 20 + [20] * 5))
        assert ema(prices, 3)[-1] > ema(prices, 10)[-1]


class TestRsi:
    def test_hand_computed(self):
        # period 2 on 10, 11, 10, 12 -> changes +1, -1, +2
        #   seed: avg_gain = 0.5, avg_loss = 0.5 -> RS = 1 -> RSI = 50
        #   next: avg_gain = (0.5 + 2)/2 = 1.25, avg_loss = 0.5/2 = 0.25
        #         RS = 5 -> RSI = 100 - 100/6 = 83.333...
        result = rsi(dec(10, 11, 10, 12), 2)
        assert result[2] == Decimal("50")
        assert result[3] is not None
        assert abs(result[3] - Decimal("83.3333")) < Decimal("0.001")

    def test_unbroken_gains_is_100(self):
        assert rsi(dec(10, 11, 12, 13), 3)[-1] == Decimal("100")

    def test_unbroken_losses_is_0(self):
        assert rsi(dec(13, 12, 11, 10), 3)[-1] == Decimal("0")

    def test_bounded_to_0_100(self):
        prices = dec(10, 12, 11, 15, 9, 20, 8, 25, 7, 30, 6)
        for value in rsi(prices, 3):
            if value is not None:
                assert Decimal(0) <= value <= Decimal(100)

    def test_needs_period_plus_one_prices(self):
        # 3 prices give only 2 changes; a period-3 RSI cannot exist yet.
        assert all(v is None for v in rsi(dec(10, 11, 12), 3))


class TestMacd:
    def test_histogram_is_macd_minus_signal(self):
        prices = dec(*range(1, 60))
        macd_line, signal_line, histogram = macd(prices)
        for m, s, h in zip(macd_line, signal_line, histogram, strict=False):
            if m is not None and s is not None:
                assert h == m - s
            else:
                assert h is None

    def test_rising_series_gives_a_positive_macd_line(self):
        macd_line, _, _ = macd(dec(*range(1, 60)))
        assert macd_line[-1] > 0

    def test_falling_series_gives_a_negative_macd_line(self):
        macd_line, _, _ = macd(dec(*range(60, 1, -1)))
        assert macd_line[-1] < 0

    def test_fast_must_be_shorter_than_slow(self):
        with pytest.raises(ValueError, match="fast period must be shorter"):
            macd(dec(*range(1, 60)), fast=26, slow=12)


class TestDispersion:
    def test_stddev_of_a_constant_series_is_zero(self):
        assert stddev([Decimal("5")] * 6, 3)[-1] == Decimal("0")

    def test_stddev_hand_computed(self):
        # window (2, 4, 6): mean 4, variance ((4)+(0)+(4))/3 = 8/3
        result = stddev(dec(2, 4, 6), 3)
        expected = (Decimal(8) / Decimal(3)).sqrt()
        assert abs(result[2] - expected) < Decimal("0.0000001")

    def test_zscore_is_none_without_dispersion(self):
        # A flat window has no scale, so "unusually far" is undefined.
        assert zscore([Decimal("5")] * 6, 3)[-1] is None

    def test_zscore_sign_follows_displacement(self):
        assert zscore(dec(10, 10, 10, 20), 3)[-1] > 0
        assert zscore(dec(10, 10, 10, 1), 3)[-1] < 0


class TestVolatility:
    def test_true_range_undefined_at_first_bar(self):
        highs, lows, closes = dec(10, 12), dec(8, 9), dec(9, 11)
        assert true_range(highs, lows, closes)[0] is None

    def test_true_range_spans_the_gap(self):
        # Gap up: high 12, low 11, previous close 9 -> |12 - 9| = 3 dominates.
        highs, lows, closes = dec(10, 12), dec(8, 11), dec(9, 11)
        assert true_range(highs, lows, closes)[1] == Decimal("3")

    def test_atr_is_positive_for_a_moving_market(self):
        highs = dec(*[10 + i for i in range(20)])
        lows = dec(*[8 + i for i in range(20)])
        closes = dec(*[9 + i for i in range(20)])
        assert atr(highs, lows, closes, 5)[-1] > 0

    def test_realized_volatility_is_zero_for_a_flat_series(self):
        assert realized_volatility([Decimal("100")] * 10, 4)[-1] == Decimal("0")

    def test_realized_volatility_rises_with_dispersion(self):
        calm = realized_volatility(dec(100, 101, 100, 101, 100, 101, 100), 3)[-1]
        wild = realized_volatility(dec(100, 130, 90, 140, 80, 150, 70), 3)[-1]
        assert wild > calm


class TestNoLookAhead:
    """Index i must depend only on inputs at indices <= i.

    Truncating the series must not change any earlier value. This is the
    property that makes the backtester's results trustworthy.
    """

    @pytest.mark.parametrize(
        "fn",
        [
            lambda v: sma(v, 5),
            lambda v: ema(v, 5),
            lambda v: rsi(v, 5),
            lambda v: stddev(v, 5),
            lambda v: zscore(v, 5),
            lambda v: macd(v, 3, 6, 3)[0],
        ],
        ids=["sma", "ema", "rsi", "stddev", "zscore", "macd"],
    )
    def test_truncation_does_not_change_earlier_values(self, fn):
        full = dec(10, 12, 11, 15, 14, 18, 17, 22, 19, 25, 24, 30, 28, 35, 33, 40)
        cut = 11
        assert fn(full)[:cut] == fn(full[:cut])
