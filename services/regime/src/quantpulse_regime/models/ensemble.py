"""
EnsemblePredictor — combines HMM and Transformer predictions via weighted soft voting.

Output per sample:
  regime:        int (0-3) — argmax of blended probability vector
  confidence:    float (0-1) — max probability of winning class
  hmm_prob:      list[float] — HMM posterior over 4 states
  transformer_prob: list[float] — Transformer softmax over 4 classes
  ensemble_prob: list[float] — blended probability vector
"""
from dataclasses import dataclass

import numpy as np
import structlog

from quantpulse_regime.config import settings
from quantpulse_regime.models.hmm_model import HMMRegimeModel, HMM_FEATURES
from quantpulse_regime.models.transformer_model import TransformerRegimeModel

logger = structlog.get_logger(__name__)


@dataclass
class RegimePrediction:
    regime: int
    confidence: float
    regime_name: str
    hmm_prob: list[float]
    transformer_prob: list[float]
    ensemble_prob: list[float]


class EnsemblePredictor:
    def __init__(
        self,
        hmm: HMMRegimeModel,
        transformer: TransformerRegimeModel,
        hmm_weight: float | None = None,
        transformer_weight: float | None = None,
    ) -> None:
        self.hmm = hmm
        self.transformer = transformer
        self.hmm_w = hmm_weight or settings.hmm_weight
        self.tfm_w = transformer_weight or settings.transformer_weight
        # Normalise weights
        total = self.hmm_w + self.tfm_w
        self.hmm_w /= total
        self.tfm_w /= total
        self.log = structlog.get_logger(self.__class__.__name__)

    def predict_single(
        self,
        X_hmm: np.ndarray,
        X_tfm: np.ndarray,
    ) -> RegimePrediction:
        """
        Predict regime for a single sample.
        X_hmm: (n_features_hmm,) or (1, n_features_hmm)
        X_tfm: (lookback, n_features_tfm) or (1, lookback, n_features_tfm)
        """
        if X_hmm.ndim == 1:
            X_hmm = X_hmm.reshape(1, -1)
        if X_tfm.ndim == 2:
            X_tfm = X_tfm.reshape(1, *X_tfm.shape)

        _, hmm_prob = self.hmm.predict(X_hmm)
        tfm_prob = self.transformer.predict_proba(X_tfm)

        ensemble = self.hmm_w * hmm_prob[0] + self.tfm_w * tfm_prob[0]
        regime = int(np.argmax(ensemble))
        confidence = float(ensemble[regime])

        return RegimePrediction(
            regime=regime,
            confidence=round(confidence, 4),
            regime_name=settings.regime_names[regime],
            hmm_prob=[round(float(p), 4) for p in hmm_prob[0]],
            transformer_prob=[round(float(p), 4) for p in tfm_prob[0]],
            ensemble_prob=[round(float(p), 4) for p in ensemble],
        )

    def predict_batch(
        self,
        X_hmm: np.ndarray,
        X_tfm: np.ndarray,
    ) -> list[RegimePrediction]:
        """Batch prediction — returns one RegimePrediction per sample."""
        _, hmm_probs = self.hmm.predict(X_hmm)
        tfm_probs = self.transformer.predict_proba(X_tfm)

        results = []
        for i in range(len(X_hmm)):
            ensemble = self.hmm_w * hmm_probs[i] + self.tfm_w * tfm_probs[i]
            regime = int(np.argmax(ensemble))
            results.append(RegimePrediction(
                regime=regime,
                confidence=round(float(ensemble[regime]), 4),
                regime_name=settings.regime_names[regime],
                hmm_prob=[round(float(p), 4) for p in hmm_probs[i]],
                transformer_prob=[round(float(p), 4) for p in tfm_probs[i]],
                ensemble_prob=[round(float(p), 4) for p in ensemble],
            ))
        return results
