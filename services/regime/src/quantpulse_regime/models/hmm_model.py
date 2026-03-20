"""
GaussianHMM regime model — 4 hidden states corresponding to:
  0: Trending       (high momentum, moderate vol, directional)
  1: Mean-reverting (low vol, oscillating, RSI extremes revert)
  2: Choppy         (low momentum, low trend_r, random-walk-like)
  3: High-vol       (elevated RV, wide ATR, crisis-like)

State labelling is post-hoc: after fitting, we assign semantic labels
by inspecting the mean emission vector of each state.
"""
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import structlog
from hmmlearn.hmm import GaussianHMM

from quantpulse_regime.config import settings

logger = structlog.get_logger(__name__)

# Feature columns the HMM uses (subset — HMM works better with fewer, less correlated features)
HMM_FEATURES = [
    "rv_21d_zscore",
    "rv_ratio",
    "rsi_norm",
    "tsi",
    "trend_r",
    "vix_zscore",
    "hy_spread_zscore",
    "mom_21d",
    "atr_pct",
    "yield_curve_slope",
]


class HMMRegimeModel:
    def __init__(self) -> None:
        self.model: GaussianHMM | None = None
        self.state_map: dict[int, int] = {}   # hmm_state → canonical regime label
        self.is_fitted: bool = False
        self.log = structlog.get_logger(self.__class__.__name__)

    def fit(self, X: np.ndarray, lengths: list[int] | None = None) -> "HMMRegimeModel":
        """
        Fit the HMM on a 2D feature matrix X (n_samples, n_features).
        lengths: list of sequence lengths for multi-ticker training.
        """
        self.log.info("hmm_fit_start", samples=len(X), features=X.shape[1])
        self.model = GaussianHMM(
            n_components=settings.hmm_n_states,
            covariance_type=settings.hmm_covariance_type,
            n_iter=settings.hmm_n_iter,
            random_state=42,
            verbose=False,
        )
        self.model.fit(X, lengths=lengths)
        self._assign_state_labels()
        self.is_fitted = True
        self.log.info("hmm_fit_complete", converged=self.model.monitor_.converged)
        return self

    def predict(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        Predict regime labels and posterior probabilities.
        Returns: (labels array, proba matrix shape [n, 4])
        """
        if not self.model or not self.is_fitted:
            raise RuntimeError("Model not fitted")
        raw_states = self.model.predict(X)
        log_proba = self.model.predict_proba(X)
        # Remap raw HMM states to canonical regime labels
        canonical = np.array([self.state_map.get(s, s) for s in raw_states])
        # Reorder columns to match canonical label ordering
        n = settings.hmm_n_states
        reordered = np.zeros_like(log_proba)
        for hmm_state, canon_label in self.state_map.items():
            if hmm_state < log_proba.shape[1] and canon_label < n:
                reordered[:, canon_label] = log_proba[:, hmm_state]
        return canonical, reordered

    def _assign_state_labels(self) -> None:
        """
        Heuristic state labelling based on emission means.
        Uses the feature ordering in HMM_FEATURES:
          rv_21d_zscore[0], rv_ratio[1], rsi_norm[2], tsi[3],
          trend_r[4], vix_zscore[5], hy_spread_zscore[6],
          mom_21d[7], atr_pct[8], yield_curve_slope[9]
        """
        if not self.model:
            return
        means = self.model.means_   # shape: (n_states, n_features)
        scores: dict[int, dict[str, float]] = {}
        for i in range(settings.hmm_n_states):
            m = means[i]
            scores[i] = {
                "vol_score":      float(m[0]) + float(m[5]),   # rv_zscore + vix_zscore
                "momentum_score": float(m[3]) + float(m[7]),   # tsi + mom_21d
                "trend_score":    float(m[4]),                  # trend_r
                "atr_score":      float(m[8]) if len(m) > 8 else 0.0,
            }

        # Sort states by regime characteristics
        by_vol  = sorted(scores.keys(), key=lambda s: scores[s]["vol_score"])
        by_mom  = sorted(scores.keys(), key=lambda s: scores[s]["momentum_score"], reverse=True)
        by_trend = sorted(scores.keys(), key=lambda s: scores[s]["trend_score"], reverse=True)

        assigned: dict[int, int] = {}
        # Highest vol → high_vol (3)
        high_vol = by_vol[-1]
        assigned[high_vol] = 3
        remaining = [s for s in range(settings.hmm_n_states) if s != high_vol]
        # Highest trend_r among remaining → trending (0)
        trending = max(remaining, key=lambda s: scores[s]["trend_score"])
        assigned[trending] = 0
        remaining = [s for s in remaining if s != trending]
        # Highest momentum among remaining → mean_reverting (1) — slight misnomer but captures oscillatory
        mean_rev = max(remaining, key=lambda s: abs(scores[s]["momentum_score"]))
        assigned[mean_rev] = 1
        # Remainder → choppy (2)
        choppy = [s for s in remaining if s != mean_rev][0]
        assigned[choppy] = 2

        self.state_map = assigned
        self.log.info("state_labels_assigned", mapping=assigned)

    def save(self, path: str) -> None:
        joblib.dump({"model": self.model, "state_map": self.state_map}, path)

    def load(self, path: str) -> "HMMRegimeModel":
        data = joblib.load(path)
        self.model = data["model"]
        self.state_map = data["state_map"]
        self.is_fitted = True
        return self
