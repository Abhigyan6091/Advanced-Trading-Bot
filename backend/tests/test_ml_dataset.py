"""Dataset construction and the walk-forward split.

The critical property here: a random shuffle would let the model train on
rows from after the period it is evaluated on. Every guarantee below exists
to rule that out.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain import Side
from app.ml.dataset import build_dataset, walk_forward_split
from app.ml.features import FEATURE_NAMES
from app.ml.labels import LabelConfig
from tests.conftest import make_bars

#: Enough bars, with real movement, to produce several labeled examples.
PRICES = [100 + (i % 11) * 4 - (i % 7) * 3 + i // 3 for i in range(120)]


class TestBuildDataset:
    def test_produces_rows_with_the_fixed_feature_schema(self):
        bars = make_bars(PRICES)
        dataset = build_dataset(bars, Side.BUY)
        assert len(dataset) > 0
        for row in dataset.rows:
            assert set(row) == set(FEATURE_NAMES)

    def test_labels_align_one_to_one_with_rows(self):
        bars = make_bars(PRICES)
        dataset = build_dataset(bars, Side.BUY)
        assert len(dataset.labels) == len(dataset.rows) == len(dataset.timestamps)

    def test_timestamps_are_chronological(self):
        bars = make_bars(PRICES)
        dataset = build_dataset(bars, Side.BUY)
        assert dataset.timestamps == sorted(dataset.timestamps)

    def test_an_empty_or_too_short_series_yields_an_empty_dataset(self):
        bars = make_bars([100] * 10)
        dataset = build_dataset(bars, Side.BUY)
        assert len(dataset) == 0

    def test_position_pct_reflects_the_configured_risk_fraction(self):
        bars = make_bars(PRICES)
        dataset = build_dataset(
            bars, Side.BUY, equity=Decimal("100000"), risk_fraction=Decimal("0.02")
        )
        assert len(dataset) > 0
        # Every row opens from flat, so position_pct should be close to the
        # configured risk fraction (exactly, since quantity = equity*frac/price
        # and position_pct recomputes quantity*price/equity).
        for row in dataset.rows:
            assert abs(row["position_pct"] - Decimal("0.02")) < Decimal("0.0001")

    def test_to_vectors_produces_parallel_float_and_int_lists(self):
        bars = make_bars(PRICES)
        dataset = build_dataset(bars, Side.BUY)
        X, y = dataset.to_vectors()
        assert len(X) == len(y) == len(dataset)
        assert all(len(row) == len(FEATURE_NAMES) for row in X)
        assert all(label in (0, 1) for label in y)


class TestWalkForwardSplit:
    def test_splits_by_position_not_randomly(self):
        bars = make_bars(PRICES)
        dataset = build_dataset(bars, Side.BUY)
        train, test = walk_forward_split(dataset, train_fraction=0.7)

        assert len(train) + len(test) == len(dataset)
        assert train.timestamps == dataset.timestamps[: len(train)]
        assert test.timestamps == dataset.timestamps[len(train) :]

    def test_every_train_timestamp_precedes_every_test_timestamp(self):
        """The property that makes the split walk-forward, not just a split."""
        bars = make_bars(PRICES)
        dataset = build_dataset(bars, Side.BUY)
        train, test = walk_forward_split(dataset, train_fraction=0.6)

        if train.timestamps and test.timestamps:
            assert max(train.timestamps) <= min(test.timestamps)

    @pytest.mark.parametrize("fraction", [0.0, 1.0, -0.1, 1.5])
    def test_the_fraction_must_be_strictly_between_zero_and_one(self, fraction):
        bars = make_bars(PRICES)
        dataset = build_dataset(bars, Side.BUY)
        with pytest.raises(ValueError, match="strictly between"):
            walk_forward_split(dataset, train_fraction=fraction)


class TestLabelConfigThreadsThrough:
    def test_a_different_horizon_changes_which_rows_resolve(self):
        bars = make_bars(PRICES)
        short_horizon = build_dataset(bars, Side.BUY, LabelConfig(horizon=5))
        long_horizon = build_dataset(bars, Side.BUY, LabelConfig(horizon=50))
        # A longer horizon leaves fewer bars able to resolve before the data ends.
        assert len(long_horizon) < len(short_horizon)
