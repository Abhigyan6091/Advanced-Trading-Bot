"""Train the adverse-outcome model from stored bar history.

Builds a walk-forward-split dataset from the bars already in Postgres (seed
one first if the table is empty), trains an XGBoost classifier, reports its
out-of-sample AUC and feature importances, and -- only if the operator asks
for it -- saves the model to models/adverse_outcome.json.

The model is never saved silently: a mediocre fit should not quietly start
influencing live risk decisions. Review the printed report, and pass --save
once satisfied.

    python -m scripts.train_risk_model --symbol BTCUSDT [--save]
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope
from app.domain import Side
from app.marketdata import BarRepository
from app.ml import AdverseOutcomeModel, LabelConfig, build_dataset, walk_forward_split

log = get_logger("train_risk_model")

#: Both directions are trained together: an adverse-outcome model should
#: generalise across long and short entries, not learn one side only.
SIDES = (Side.BUY, Side.SELL)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--bars", type=int, default=1500, help="bars to load for training")
    parser.add_argument("--horizon", type=int, default=24, help="label resolution window, in bars")
    parser.add_argument("--stop-atr", type=str, default="1.5")
    parser.add_argument("--target-atr", type=str, default="2.0")
    parser.add_argument(
        "--train-fraction", type=float, default=0.7, help="walk-forward split point"
    )
    parser.add_argument(
        "--save", action="store_true", help="persist the model to models/adverse_outcome.json"
    )
    args = parser.parse_args()

    configure_logging("INFO", "console")

    label_config = LabelConfig(
        horizon=args.horizon,
        stop_atr_multiple=Decimal(args.stop_atr),
        target_atr_multiple=Decimal(args.target_atr),
    )

    with session_scope() as session:
        bars = BarRepository(session).get_bars(args.symbol, args.interval, limit=args.bars)

    if len(bars) < 100:
        print(
            f"Only {len(bars)} bars stored for {args.symbol} at {args.interval}. "
            "Run `python -m scripts.seed --reset` first, or lower --bars.",
            file=sys.stderr,
        )
        return 1

    print(f"Building dataset from {len(bars)} bars ({args.symbol}, {args.interval})...")

    train_rows: list[dict] = []
    train_labels: list[bool] = []
    train_timestamps: list = []
    test_rows: list[dict] = []
    test_labels: list[bool] = []
    test_timestamps: list = []

    # Each side's bars are split walk-forward independently, then the splits
    # are concatenated -- this keeps the "train precedes test" guarantee
    # while still training on both directions.
    for side in SIDES:
        dataset = build_dataset(bars, side, label_config=label_config)
        train, test = walk_forward_split(dataset, args.train_fraction)
        train_rows.extend(train.rows)
        train_labels.extend(train.labels)
        train_timestamps.extend(train.timestamps)
        test_rows.extend(test.rows)
        test_labels.extend(test.labels)
        test_timestamps.extend(test.timestamps)

    from app.ml.dataset import Dataset

    train_set = Dataset(train_rows, train_labels, train_timestamps)
    test_set = Dataset(test_rows, test_labels, test_timestamps)

    if len(train_set) < 20 or len(test_set) < 10:
        print(
            f"Too few labeled examples (train={len(train_set)}, test={len(test_set)}) "
            "to train meaningfully. Increase --bars or shorten --horizon.",
            file=sys.stderr,
        )
        return 1

    print(f"Training on {len(train_set)} examples, testing on {len(test_set)}...")

    model = AdverseOutcomeModel()
    report = model.fit(train_set, test_set)

    print()
    print(report.summary())
    print()

    if args.save:
        model.save()
        print("Saved to models/adverse_outcome.json")
        print("The risk engine will pick it up on next process start (ml_risk_enabled=true).")
    else:
        print("Not saved. Re-run with --save to persist this model.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
