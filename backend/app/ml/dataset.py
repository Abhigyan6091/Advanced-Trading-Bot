"""Training dataset construction.

Builds (features, label) pairs by walking historical bars exactly once,
computing each row's features from only the bars up to that index -- the same
window a live decision would have seen -- and its label by looking forward
from there. Rows are then split walk-forward: earlier rows train, later rows
test. Never shuffled -- a random split would let the model train on data from
after the period it is evaluated on, which is a subtler form of the same
look-ahead leak the backtester guards against.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain import Bar, Position, Side
from app.ml.features import FEATURE_NAMES, compute_features
from app.ml.labels import LabelConfig, label_series


@dataclass(frozen=True)
class Dataset:
    rows: list[dict[str, Decimal]]
    labels: list[bool]
    timestamps: list[object]

    def __len__(self) -> int:
        return len(self.rows)

    def to_vectors(self) -> tuple[list[list[float]], list[int]]:
        from app.ml.features import features_to_vector

        return (
            [features_to_vector(r) for r in self.rows],
            [1 if y else 0 for y in self.labels],
        )


def build_dataset(
    bars: list[Bar],
    side: Side,
    label_config: LabelConfig | None = None,
    equity: Decimal = Decimal("100000"),
    risk_fraction: Decimal = Decimal("0.02"),
) -> Dataset:
    """Build a labeled dataset for one symbol and one trade direction.

    Each row represents opening a fresh position from flat, sized at
    ``risk_fraction`` of ``equity`` -- the same fraction the live pipeline
    proposes before risk sizing (see ``TradingPipeline._proposed_quantity``).
    A flat starting position and zero drawdown keep every row's label
    attributable to market conditions at that bar rather than to whatever a
    hypothetical portfolio happened to be doing at the time.
    """
    labeled = label_series(bars, side, label_config)
    flat = Position.flat(bars[0].symbol if bars else "")

    rows: list[dict[str, Decimal]] = []
    labels: list[bool] = []
    timestamps: list[object] = []

    for i, example in enumerate(labeled):
        if example is None:
            continue
        price = bars[i].close
        quantity = (equity * risk_fraction) / price if price > 0 else Decimal("0")

        # Features see only bars[:i+1] -- the window a decision at this bar
        # would actually have had, regardless of how far the label looked
        # forward to resolve.
        features = compute_features(
            bars[: i + 1],
            existing_position=flat,
            side=side,
            quantity=quantity,
            price=price,
            drawdown=Decimal("0"),
            equity=equity,
        )
        if features is None:
            continue

        rows.append(features)
        labels.append(example.adverse)
        timestamps.append(bars[i].close_time)

    return Dataset(rows=rows, labels=labels, timestamps=timestamps)


def walk_forward_split(dataset: Dataset, train_fraction: float = 0.7) -> tuple[Dataset, Dataset]:
    """Split chronologically: the first share trains, the remainder tests.

    No shuffling. ``timestamps`` are already in bar order because the dataset
    was built by a single forward walk, so slicing by position is slicing by
    time.
    """
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be strictly between 0 and 1")

    cut = int(len(dataset) * train_fraction)
    train = Dataset(dataset.rows[:cut], dataset.labels[:cut], dataset.timestamps[:cut])
    test = Dataset(dataset.rows[cut:], dataset.labels[cut:], dataset.timestamps[cut:])
    return train, test


__all__ = ["Dataset", "FEATURE_NAMES", "build_dataset", "walk_forward_split"]
