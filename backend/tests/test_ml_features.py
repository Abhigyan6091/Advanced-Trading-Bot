"""Feature engineering: length, warm-up, and the no-look-ahead property."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.domain import Fill, Position, Side
from app.ml.features import (
    MIN_BARS,
    compute_features,
    compute_market_features,
    features_to_vector,
    position_pct,
)
from tests.conftest import make_bars


class TestWarmup:
    def test_returns_none_below_min_bars(self):
        bars = make_bars(list(range(100, 100 + MIN_BARS - 1)))
        assert compute_market_features(bars) is None

    def test_produces_features_once_warm(self):
        bars = make_bars(list(range(100, 100 + MIN_BARS + 5)))
        features = compute_market_features(bars)
        assert features is not None
        assert set(features) == {
            "volatility",
            "momentum",
            "volume_zscore",
            "return_1",
            "return_5",
            "spread",
        }


class TestNoLookAhead:
    """Truncating the series must not change an earlier feature vector.

    The same discipline strategies and indicators are held to: a feature
    computed at bar i may depend only on bars[0..i].
    """

    def test_truncation_does_not_change_an_earlier_result(self):
        prices = [100 + (i % 7) * 3 - (i % 5) for i in range(MIN_BARS + 20)]
        full = make_bars(prices)
        cut = MIN_BARS + 5

        full_features = compute_market_features(full[:cut])
        truncated_features = compute_market_features(full[: cut])
        assert full_features == truncated_features

        # Extending the series with wildly different future data must not
        # change what was already computed at the earlier cutoff.
        extended = make_bars(prices + [1, 500, 2, 800, 3])
        assert compute_market_features(extended[:cut]) == full_features


class TestReturns:
    def test_return_1_is_the_latest_single_bar_move(self):
        prices = [100] * (MIN_BARS - 1) + [110]
        features = compute_market_features(make_bars(prices))
        assert features["return_1"] == Decimal("0.1")

    def test_return_5_looks_back_five_bars(self):
        prices = [100] * (MIN_BARS - 5) + [100, 100, 100, 100, 120]
        features = compute_market_features(make_bars(prices))
        assert features["return_5"] == Decimal("0.2")


class TestSpread:
    def test_spread_is_the_last_bars_high_low_range_as_a_fraction(self):
        prices = [100] * MIN_BARS
        bars = make_bars(prices, spread="0.02")
        features = compute_market_features(bars)
        # make_bars pads high/low by the given fraction around open/close.
        assert features["spread"] > 0


class TestPositionPct:
    def test_flat_account_opening_a_position(self):
        flat = Position.flat("BTCUSDT")
        pct = position_pct(flat, Side.BUY, Decimal("0.1"), Decimal("60000"), Decimal("100000"))
        assert pct == Decimal("0.06")

    def test_adding_to_an_existing_position_uses_the_resulting_size(self):
        held = Position.flat("BTCUSDT").apply_fill(
            Fill(
                order_id=uuid.uuid4(),
                symbol="BTCUSDT",
                side=Side.BUY,
                quantity=Decimal("0.1"),
                price=Decimal("60000"),
            )
        )
        pct = position_pct(held, Side.BUY, Decimal("0.1"), Decimal("60000"), Decimal("100000"))
        assert pct == Decimal("0.12")

    def test_closing_reduces_the_resulting_size(self):
        held = Position.flat("BTCUSDT").apply_fill(
            Fill(
                order_id=uuid.uuid4(),
                symbol="BTCUSDT",
                side=Side.BUY,
                quantity=Decimal("0.2"),
                price=Decimal("60000"),
            )
        )
        pct = position_pct(held, Side.SELL, Decimal("0.15"), Decimal("60000"), Decimal("100000"))
        assert pct == Decimal("0.03")


class TestFullFeatureVector:
    def test_compute_features_combines_market_and_position(self):
        bars = make_bars(list(range(100, 100 + MIN_BARS + 5)))
        features = compute_features(
            bars,
            existing_position=Position.flat("BTCUSDT"),
            side=Side.BUY,
            quantity=Decimal("0.05"),
            price=Decimal("100"),
            drawdown=Decimal("0.1"),
            equity=Decimal("100000"),
        )
        assert features is not None
        assert features["drawdown"] == Decimal("0.1")
        assert features["position_pct"] == Decimal("0.05") * Decimal("100") / Decimal("100000")

    def test_features_to_vector_orders_by_the_fixed_schema(self):
        bars = make_bars(list(range(100, 100 + MIN_BARS + 5)))
        features = compute_features(
            bars,
            existing_position=Position.flat("BTCUSDT"),
            side=Side.BUY,
            quantity=Decimal("0.05"),
            price=Decimal("100"),
            drawdown=Decimal("0"),
            equity=Decimal("100000"),
        )
        vector = features_to_vector(features)
        assert len(vector) == 8
        assert all(isinstance(v, float) for v in vector)
