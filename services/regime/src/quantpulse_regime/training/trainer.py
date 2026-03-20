"""
Trainer — orchestrates HMM + Transformer training pipeline.

Pseudo-labelling strategy (no ground-truth labels available):
  1. Fit HMM on full feature history → get state sequence
  2. Use HMM state sequence as pseudo-labels for Transformer training
  3. Retrain Transformer on pseudo-labels with confidence filtering
     (only use samples where HMM confidence > 0.6)
  4. Evaluate ensemble on held-out validation period

This approach is unsupervised at the HMM level and semi-supervised at
the Transformer level — we bootstrap labels from the statistical model
and use the neural network to learn a richer, non-Markovian representation.
"""
from pathlib import Path

import mlflow
import numpy as np
import polars as pl
import structlog

from quantpulse_regime.config import settings
from quantpulse_regime.models.hmm_model import HMMRegimeModel, HMM_FEATURES
from quantpulse_regime.models.transformer_model import TransformerRegimeModel
from quantpulse_regime.models.ensemble import EnsemblePredictor

logger = structlog.get_logger(__name__)

# All features used by the Transformer (superset of HMM_FEATURES)
TFM_FEATURES = [
    "rv_5d_z", "rv_21d_z", "rv_63d_z", "rv_ratio",
    "atr_pct_z", "rv_21d_zscore",
    "rsi_norm", "tsi", "trend_r",
    "mom_5d_z", "mom_21d_z", "mom_63d_z",
    "vix_zscore", "hy_spread_zscore", "yc_inverted",
    "iv_skew_proxy", "put_call_ratio", "gex_proxy",
]


class RegimeTrainer:
    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    def train(self, feature_df: pl.DataFrame) -> EnsemblePredictor:
        """
        Full training pipeline. Returns fitted EnsemblePredictor.
        Logs all metrics and artifacts to MLflow.
        """
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(settings.mlflow_experiment_name)

        with mlflow.start_run() as run:
            self.log.info("training_start", run_id=run.info.run_id)
            mlflow.log_params({
                "hmm_n_states": settings.hmm_n_states,
                "hmm_covariance": settings.hmm_covariance_type,
                "tfm_d_model": settings.transformer_d_model,
                "tfm_layers": settings.transformer_num_layers,
                "tfm_lookback": settings.transformer_lookback,
                "train_start": settings.train_start_date,
            })

            # ── Prepare data ──────────────────────────────────────────────
            df_clean = self._prepare_features(feature_df)
            train_df, val_df = self._train_val_split(df_clean)

            # ── HMM ───────────────────────────────────────────────────────
            hmm = self._train_hmm(train_df)

            # ── Pseudo-labels for Transformer ─────────────────────────────
            train_labels, train_conf = self._get_pseudo_labels(hmm, train_df)
            val_labels, _  = self._get_pseudo_labels(hmm, val_df)

            # Filter low-confidence samples
            mask = train_conf >= 0.6
            self.log.info("pseudo_label_filter", kept=int(mask.sum()), total=len(mask))
            mlflow.log_metric("pseudo_label_kept_pct", float(mask.mean()))

            # ── Transformer ───────────────────────────────────────────────
            n_tfm_features = self._count_tfm_features(train_df)
            tfm = TransformerRegimeModel(n_features=n_tfm_features)

            X_train_tfm, y_train_tfm = self._make_sequences(train_df, train_labels, mask)
            X_val_tfm,   y_val_tfm   = self._make_sequences(val_df, val_labels)
            tfm.fit(X_train_tfm, y_train_tfm, X_val_tfm, y_val_tfm)

            # ── Evaluate ensemble on validation set ───────────────────────
            X_val_hmm = self._get_hmm_features(val_df)
            # X_val_tfm skips the first `lookback` rows per ticker; align HMM to same size
            X_val_hmm_aligned = X_val_hmm[-len(X_val_tfm):]
            ensemble = EnsemblePredictor(hmm, tfm)
            preds = ensemble.predict_batch(X_val_hmm_aligned, X_val_tfm)
            pred_labels = np.array([p.regime for p in preds])
            acc = float((pred_labels == y_val_tfm).mean())
            mlflow.log_metric("val_accuracy_vs_pseudo", acc)
            self.log.info("ensemble_val_accuracy", acc=round(acc, 4))

            # ── Save artifacts ─────────────────────────────────────────────
            artifact_dir = Path(settings.model_store_path)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            hmm_path = str(artifact_dir / "hmm_model.joblib")
            tfm_path = str(artifact_dir / "transformer_model.pt")
            hmm.save(hmm_path)
            tfm.save(tfm_path)
            try:
                mlflow.log_artifact(hmm_path, "models")
                mlflow.log_artifact(tfm_path, "models")
            except Exception as e:
                self.log.warning("mlflow_artifact_skip", error=str(e))
            mlflow.log_param("model_version", run.info.run_id[:8])

            self.log.info("training_complete", run_id=run.info.run_id)
            return ensemble

    def _prepare_features(self, df: pl.DataFrame) -> pl.DataFrame:
        """Drop rows with nulls in any required feature column."""
        from datetime import datetime, timezone
        required = [f for f in HMM_FEATURES + TFM_FEATURES if f in df.columns]
        cutoff = datetime.fromisoformat(settings.train_start_date).replace(tzinfo=timezone.utc)
        return (
            df.filter(pl.col("time") >= cutoff)
            .drop_nulls(subset=required)
            .sort(["ticker", "time"])
        )

    def _train_val_split(self, df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
        times = df["time"].unique().sort()
        split_idx = int(len(times) * settings.train_val_split)
        split_date = times[split_idx]
        return (
            df.filter(pl.col("time") < split_date),
            df.filter(pl.col("time") >= split_date),
        )

    def _train_hmm(self, df: pl.DataFrame) -> HMMRegimeModel:
        X, lengths = self._get_hmm_features_with_lengths(df)
        hmm = HMMRegimeModel()
        hmm.fit(X, lengths=lengths)
        return hmm

    def _get_hmm_features(self, df: pl.DataFrame) -> np.ndarray:
        available = [f for f in HMM_FEATURES if f in df.columns]
        return df.select(available).to_numpy().astype(np.float32)

    def _get_hmm_features_with_lengths(self, df: pl.DataFrame) -> tuple[np.ndarray, list[int]]:
        """Returns concatenated feature array and per-ticker sequence lengths."""
        arrays, lengths = [], []
        for ticker in df["ticker"].unique().sort().to_list():
            sub = df.filter(pl.col("ticker") == ticker)
            available = [f for f in HMM_FEATURES if f in sub.columns]
            arr = sub.select(available).to_numpy().astype(np.float32)
            arrays.append(arr)
            lengths.append(len(arr))
        return np.concatenate(arrays, axis=0), lengths

    def _get_pseudo_labels(
        self, hmm: HMMRegimeModel, df: pl.DataFrame
    ) -> tuple[np.ndarray, np.ndarray]:
        X = self._get_hmm_features(df)
        labels, probs = hmm.predict(X)
        confidence = probs.max(axis=1)
        return labels, confidence

    def _make_sequences(
        self,
        df: pl.DataFrame,
        labels: np.ndarray,
        mask: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Build sliding-window sequences for Transformer input."""
        lb = settings.transformer_lookback
        available = [f for f in TFM_FEATURES if f in df.columns]
        X_raw = df.select(available).to_numpy().astype(np.float32)

        seqs, ys = [], []
        tickers = df["ticker"].to_list()
        for i in range(lb, len(X_raw)):
            if tickers[i] != tickers[i - lb]:
                continue  # don't mix tickers in a window
            if mask is not None and not mask[i]:
                continue
            seqs.append(X_raw[i - lb:i])
            ys.append(labels[i])

        if not seqs:
            return np.empty((0, lb, len(available))), np.empty(0, dtype=np.int64)
        return np.stack(seqs), np.array(ys, dtype=np.int64)

    def _count_tfm_features(self, df: pl.DataFrame) -> int:
        return len([f for f in TFM_FEATURES if f in df.columns])
