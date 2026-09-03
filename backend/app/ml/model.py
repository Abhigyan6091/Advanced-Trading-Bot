"""The adverse-outcome model.

A thin, explainable wrapper around a gradient-boosted tree classifier.
XGBoost is chosen over a deeper model for exactly the reason this section
exists: it exposes per-feature importances directly, so the risk score it
feeds stays inspectable rather than becoming a second opaque black box next
to the one it is meant to guard against.

The model is optional everywhere it is used. A missing or unloadable model
file is not an error -- ``AdverseOutcomeModel.load`` returns ``None``, and the
risk check that consumes it degrades to a neutral pass. This is what makes the
feature "disabled by config without breaking the pipeline": the absence of a
trained model IS the disabled state, nothing else has to know about it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.ml.dataset import Dataset
from app.ml.features import FEATURE_NAMES

log = get_logger(__name__)

DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[3] / "models" / "adverse_outcome.json"


@dataclass(frozen=True)
class TrainingReport:
    """What training produced, for the operator to judge before trusting it."""

    train_size: int
    test_size: int
    train_adverse_rate: float
    test_adverse_rate: float
    test_auc: float
    test_average_precision: float
    feature_importances: dict[str, float]

    def summary(self) -> str:
        lines = [
            f"Train examples : {self.train_size}  ({self.train_adverse_rate:.1%} adverse)",
            f"Test examples  : {self.test_size}  ({self.test_adverse_rate:.1%} adverse)",
            f"Test ROC AUC   : {self.test_auc:.3f}",
            f"Test avg prec. : {self.test_average_precision:.3f}",
            "Feature importances:",
        ]
        for name, weight in sorted(
            self.feature_importances.items(), key=lambda kv: -kv[1]
        ):
            lines.append(f"  {name:<16} {weight:.3f}")
        return "\n".join(lines)


class AdverseOutcomeModel:
    """Predicts the probability that a proposed trade ends adversely.

    Wraps ``xgboost.XGBClassifier``. Feature order is fixed by
    ``app.ml.features.FEATURE_NAMES`` and saved alongside the model, so a
    mismatched model file is detected rather than silently misapplied.
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = params or {
            "n_estimators": 200,
            "max_depth": 3,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "eval_metric": "logloss",
        }
        self._booster: Any = None
        self._feature_names: tuple[str, ...] = FEATURE_NAMES

    @property
    def is_fitted(self) -> bool:
        return self._booster is not None

    def fit(self, train: Dataset, test: Dataset | None = None) -> TrainingReport:
        """Fit on ``train`` and, if given, report generalisation on ``test``."""
        from xgboost import XGBClassifier

        X_train, y_train = train.to_vectors()
        if len(set(y_train)) < 2:
            raise ValueError(
                "training data has only one class; cannot fit a classifier. "
                "Widen the date range or adjust the label thresholds."
            )

        positive = sum(y_train)
        negative = len(y_train) - positive
        # Class imbalance is the norm here -- most trades are not adverse --
        # so the positive class is upweighted rather than left to be ignored.
        scale_pos_weight = (negative / positive) if positive else 1.0

        model = XGBClassifier(**self.params, scale_pos_weight=scale_pos_weight)
        model.fit(X_train, y_train)
        self._booster = model

        report = self._evaluate(train, test or train, is_test_self=test is None)
        log.info(
            "ml.model.fit",
            train_size=len(train),
            test_auc=report.test_auc,
            positive_rate=report.train_adverse_rate,
        )
        return report

    def _evaluate(self, train: Dataset, test: Dataset, is_test_self: bool) -> TrainingReport:
        from sklearn.metrics import average_precision_score, roc_auc_score

        X_test, y_test = test.to_vectors()
        probs = self._booster.predict_proba(X_test)[:, 1]

        auc = roc_auc_score(y_test, probs) if len(set(y_test)) > 1 else float("nan")
        ap = average_precision_score(y_test, probs) if len(set(y_test)) > 1 else float("nan")

        return TrainingReport(
            train_size=len(train),
            test_size=0 if is_test_self else len(test),
            train_adverse_rate=sum(train.labels) / len(train.labels) if train.labels else 0.0,
            test_adverse_rate=sum(test.labels) / len(test.labels) if test.labels else 0.0,
            test_auc=float(auc),
            test_average_precision=float(ap),
            feature_importances=self.feature_importances(),
        )

    def predict_proba(self, features: dict[str, Decimal]) -> Decimal | None:
        """Probability of an adverse outcome, or ``None`` if unfitted."""
        if not self.is_fitted:
            return None
        vector = [[float(features[name]) for name in self._feature_names]]
        probability = self._booster.predict_proba(vector)[0, 1]
        return Decimal(str(round(float(probability), 6)))

    def feature_importances(self) -> dict[str, float]:
        if not self.is_fitted:
            return {}
        raw = self._booster.feature_importances_
        return {name: float(w) for name, w in zip(self._feature_names, raw, strict=True)}

    # --- persistence -----------------------------------------------------

    def save(self, path: Path = DEFAULT_MODEL_PATH) -> None:
        if not self.is_fitted:
            raise ValueError("cannot save an unfitted model")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._booster.save_model(str(path))

        meta_path = path.with_suffix(".meta.json")
        import json

        meta_path.write_text(
            json.dumps(
                {
                    "feature_names": list(self._feature_names),
                    "params": self.params,
                }
            )
        )
        log.info("ml.model.saved", path=str(path))

    @classmethod
    def load(cls, path: Path = DEFAULT_MODEL_PATH) -> AdverseOutcomeModel | None:
        """Load a saved model, or return ``None`` if none exists or is invalid.

        This is the sole gate for the "ML disabled by default" behaviour: a
        fresh checkout has no model file, so every caller of this method gets
        ``None`` and the risk engine runs its seven checks exactly as it did
        before this feature existed.
        """
        meta_path = path.with_suffix(".meta.json")
        if not path.exists() or not meta_path.exists():
            return None

        import json

        try:
            from xgboost import XGBClassifier

            meta = json.loads(meta_path.read_text())
            feature_names = tuple(meta["feature_names"])
            if feature_names != FEATURE_NAMES:
                log.warning(
                    "ml.model.feature_mismatch",
                    saved=feature_names,
                    current=FEATURE_NAMES,
                )
                return None

            model = XGBClassifier()
            model.load_model(str(path))

            instance = cls(params=meta.get("params"))
            instance._booster = model
            instance._feature_names = feature_names
            return instance
        except Exception as exc:  # noqa: BLE001 - any load failure means "absent"
            log.warning("ml.model.load_failed", error=str(exc))
            return None
