"""Tests for the regime ML service."""
import numpy as np
import pytest

from quantpulse_regime.models.hmm_model import HMMRegimeModel
from quantpulse_regime.models.transformer_model import TransformerRegimeModel, TemporalTransformer
from quantpulse_regime.models.ensemble import EnsemblePredictor
import torch


@pytest.fixture
def synthetic_hmm_data() -> np.ndarray:
    np.random.seed(42)
    return np.random.randn(500, 10).astype(np.float32)


@pytest.fixture
def synthetic_tfm_data() -> tuple[np.ndarray, np.ndarray]:
    np.random.seed(42)
    n, lb, f = 200, 60, 8
    X = np.random.randn(n, lb, f).astype(np.float32)
    y = np.random.randint(0, 4, n)
    return X, y


class TestHMMModel:
    def test_fit_and_predict(self, synthetic_hmm_data: np.ndarray) -> None:
        model = HMMRegimeModel()
        model.fit(synthetic_hmm_data)
        assert model.is_fitted
        labels, probs = model.predict(synthetic_hmm_data[:10])
        assert labels.shape == (10,)
        assert probs.shape == (10, 4)

    def test_labels_in_range(self, synthetic_hmm_data: np.ndarray) -> None:
        model = HMMRegimeModel()
        model.fit(synthetic_hmm_data)
        labels, _ = model.predict(synthetic_hmm_data)
        assert set(labels).issubset({0, 1, 2, 3})

    def test_probs_sum_to_one(self, synthetic_hmm_data: np.ndarray) -> None:
        model = HMMRegimeModel()
        model.fit(synthetic_hmm_data)
        _, probs = model.predict(synthetic_hmm_data[:20])
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-5)

    def test_state_map_covers_all_regimes(self, synthetic_hmm_data: np.ndarray) -> None:
        model = HMMRegimeModel()
        model.fit(synthetic_hmm_data)
        assert set(model.state_map.values()) == {0, 1, 2, 3}


class TestTransformerModel:
    def test_forward_pass_shape(self) -> None:
        net = TemporalTransformer(n_features=8)
        x = torch.randn(4, 60, 8)
        out = net(x)
        assert out.shape == (4, 4)

    def test_fit_and_predict(self, synthetic_tfm_data: tuple) -> None:
        X, y = synthetic_tfm_data
        model = TransformerRegimeModel(n_features=X.shape[2])
        # Quick smoke test — just 2 epochs
        from quantpulse_regime.config import settings
        original_epochs = settings.max_epochs
        settings.max_epochs = 2
        model.fit(X, y)
        settings.max_epochs = original_epochs
        assert model.is_fitted
        probs = model.predict_proba(X[:5])
        assert probs.shape == (5, 4)
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-5)


class TestEnsemble:
    def test_predict_single_returns_valid_regime(self, synthetic_hmm_data, synthetic_tfm_data) -> None:
        hmm = HMMRegimeModel()
        hmm.fit(synthetic_hmm_data)

        X_tfm, y_tfm = synthetic_tfm_data
        tfm = TransformerRegimeModel(n_features=X_tfm.shape[2])
        from quantpulse_regime.config import settings
        settings.max_epochs = 2
        tfm.fit(X_tfm, y_tfm)

        ensemble = EnsemblePredictor(hmm, tfm)
        X_hmm_single = synthetic_hmm_data[0:1]
        X_tfm_single = X_tfm[0:1]

        pred = ensemble.predict_single(X_hmm_single, X_tfm_single)
        assert pred.regime in {0, 1, 2, 3}
        assert 0.0 <= pred.confidence <= 1.0
        assert len(pred.ensemble_prob) == 4
        assert abs(sum(pred.ensemble_prob) - 1.0) < 1e-4
