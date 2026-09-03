"""The adverse-outcome model: fit, predict, persist.

The model is the one component genuinely allowed to be a black box inside;
what is tested here is the explainability contract around it -- feature
importances are always available, and absence (unfitted, or no file to load)
degrades to None rather than a crash.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ml.dataset import Dataset
from app.ml.features import FEATURE_NAMES
from app.ml.model import AdverseOutcomeModel


def separable_dataset(n: int = 200) -> Dataset:
    """A dataset where one feature perfectly predicts the label.

    Not realistic market data -- the point is only to give the classifier
    something a competent fit *should* recover, so a test failure here means
    the wrapper is broken, not that boosting is hard.
    """
    rows: list[dict[str, Decimal]] = []
    labels: list[bool] = []
    for i in range(n):
        adverse = i % 2 == 0
        row = {name: Decimal("0.1") for name in FEATURE_NAMES}
        row["volatility"] = Decimal("2.0") if adverse else Decimal("0.1")
        rows.append(row)
        labels.append(adverse)
    return Dataset(rows=rows, labels=labels, timestamps=list(range(n)))


class TestUnfittedModel:
    def test_is_not_fitted_initially(self):
        assert not AdverseOutcomeModel().is_fitted

    def test_predict_proba_returns_none_when_unfitted(self):
        model = AdverseOutcomeModel()
        features = dict.fromkeys(FEATURE_NAMES, Decimal("0.1"))
        assert model.predict_proba(features) is None

    def test_feature_importances_are_empty_when_unfitted(self):
        assert AdverseOutcomeModel().feature_importances() == {}

    def test_saving_an_unfitted_model_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="unfitted"):
            AdverseOutcomeModel().save(tmp_path / "model.json")


class TestFitting:
    def test_fits_on_a_separable_dataset(self):
        dataset = separable_dataset()
        model = AdverseOutcomeModel()
        report = model.fit(dataset)

        assert model.is_fitted
        assert report.train_size == len(dataset)
        assert 0.0 <= report.train_adverse_rate <= 1.0

    def test_recovers_a_strong_signal_on_separable_data(self):
        """Sanity check on the wrapper, not a claim about real markets."""
        train = separable_dataset(300)
        test = separable_dataset(100)
        model = AdverseOutcomeModel()
        report = model.fit(train, test)

        assert report.test_auc > 0.9

    def test_refuses_to_fit_on_a_single_class(self):
        dataset = Dataset(
            rows=[dict.fromkeys(FEATURE_NAMES, Decimal("0.1"))] * 10,
            labels=[False] * 10,
            timestamps=list(range(10)),
        )
        with pytest.raises(ValueError, match="only one class"):
            AdverseOutcomeModel().fit(dataset)

    def test_feature_importances_cover_every_feature(self):
        model = AdverseOutcomeModel()
        model.fit(separable_dataset())
        importances = model.feature_importances()
        assert set(importances) == set(FEATURE_NAMES)
        assert all(v >= 0 for v in importances.values())

    def test_the_dominant_feature_gets_the_most_weight(self):
        """The one feature that actually separates the classes should show it."""
        model = AdverseOutcomeModel()
        model.fit(separable_dataset())
        importances = model.feature_importances()
        assert importances["volatility"] == max(importances.values())


class TestPrediction:
    def test_predicts_a_probability_in_zero_one(self):
        model = AdverseOutcomeModel()
        model.fit(separable_dataset())
        features = dict.fromkeys(FEATURE_NAMES, Decimal("0.1"))
        features["volatility"] = Decimal("2.0")
        probability = model.predict_proba(features)
        assert probability is not None
        assert Decimal("0") <= probability <= Decimal("1")

    def test_a_higher_risk_input_scores_a_higher_probability(self):
        model = AdverseOutcomeModel()
        model.fit(separable_dataset())

        calm = dict.fromkeys(FEATURE_NAMES, Decimal("0.1"))
        risky = {**calm, "volatility": Decimal("2.0")}

        assert model.predict_proba(risky) > model.predict_proba(calm)


class TestPersistence:
    def test_round_trips_through_save_and_load(self, tmp_path):
        path = tmp_path / "adverse_outcome.json"
        model = AdverseOutcomeModel()
        model.fit(separable_dataset())
        model.save(path)

        loaded = AdverseOutcomeModel.load(path)
        assert loaded is not None
        assert loaded.is_fitted

        features = dict.fromkeys(FEATURE_NAMES, Decimal("0.1"))
        features["volatility"] = Decimal("2.0")
        original = model.predict_proba(features)
        restored = loaded.predict_proba(features)
        assert abs(original - restored) < Decimal("0.001")

    def test_loading_a_missing_file_returns_none_not_an_error(self, tmp_path):
        assert AdverseOutcomeModel.load(tmp_path / "does_not_exist.json") is None

    def test_loading_a_model_with_mismatched_features_returns_none(self, tmp_path):
        path = tmp_path / "model.json"
        model = AdverseOutcomeModel()
        model.fit(separable_dataset())
        model.save(path)

        import json

        meta_path = path.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text())
        meta["feature_names"] = ["some", "other", "schema"]
        meta_path.write_text(json.dumps(meta))

        assert AdverseOutcomeModel.load(path) is None

    def test_a_corrupted_model_file_returns_none_not_a_crash(self, tmp_path):
        path = tmp_path / "model.json"
        model = AdverseOutcomeModel()
        model.fit(separable_dataset())
        model.save(path)

        path.write_text("not valid xgboost json at all")

        assert AdverseOutcomeModel.load(path) is None


class TestTrainingReportSummary:
    def test_summary_renders_every_feature(self):
        model = AdverseOutcomeModel()
        report = model.fit(separable_dataset(300), separable_dataset(100))
        text = report.summary()
        for name in FEATURE_NAMES:
            assert name in text
        assert "ROC AUC" in text
