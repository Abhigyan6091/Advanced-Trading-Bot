"""ML-assisted risk analysis.

A lightweight, explainable adverse-outcome model that assists the risk
engine's score -- it never authorises or blocks a trade by itself, and its
absence (no trained model on disk) leaves the platform running exactly as it
did before this package existed. See app.risk.checks.MLAdverseOutcomeCheck for
how the engine consumes it.
"""

from functools import lru_cache
from pathlib import Path

from app.ml.dataset import Dataset, build_dataset, walk_forward_split
from app.ml.features import (
    FEATURE_NAMES,
    MIN_BARS,
    compute_features,
    compute_market_features,
    features_to_vector,
    position_pct,
)
from app.ml.labels import LabelConfig, LabeledExample, label_series
from app.ml.model import DEFAULT_MODEL_PATH, AdverseOutcomeModel, TrainingReport


@lru_cache
def get_default_model(path: Path = DEFAULT_MODEL_PATH) -> AdverseOutcomeModel | None:
    """The trained model at ``path``, cached for the life of the process.

    A model is loaded from disk at most once per process rather than once per
    request -- loading an XGBoost booster is not free, and the model file
    does not change while the process is running. Returns ``None`` (and stays
    cached as ``None``) when no model is present, which is the normal state
    for a fresh checkout: the ML check then passes neutrally forever, exactly
    as if this package did not exist.
    """
    return AdverseOutcomeModel.load(path)


__all__ = [
    "DEFAULT_MODEL_PATH",
    "FEATURE_NAMES",
    "MIN_BARS",
    "AdverseOutcomeModel",
    "Dataset",
    "LabelConfig",
    "LabeledExample",
    "TrainingReport",
    "build_dataset",
    "compute_features",
    "compute_market_features",
    "features_to_vector",
    "get_default_model",
    "label_series",
    "position_pct",
    "walk_forward_split",
]
