"""
InferenceEngine — loads trained models and runs real-time regime inference.

Flow:
  1. On startup: load HMM + Transformer from artifact store
  2. On each feature batch received from Kafka:
     a. Build HMM feature vector (latest bar)
     b. Build Transformer sequence (last 60 bars from feature store)
     c. Run EnsemblePredictor
     d. Write result to TimescaleDB + Redis cache
     e. Publish to regime-signals Kafka topic
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import numpy as np
import polars as pl
import redis.asyncio as aioredis
import structlog

from quantpulse_regime.config import settings
from quantpulse_regime.models.ensemble import EnsemblePredictor, RegimePrediction
from quantpulse_regime.models.hmm_model import HMMRegimeModel, HMM_FEATURES
from quantpulse_regime.models.transformer_model import TransformerRegimeModel
from quantpulse_regime.training.trainer import TFM_FEATURES

logger = structlog.get_logger(__name__)


class InferenceEngine:
    def __init__(self) -> None:
        self.ensemble: EnsemblePredictor | None = None
        self._pool: asyncpg.Pool | None = None
        self._redis: aioredis.Redis | None = None
        self.log = structlog.get_logger(self.__class__.__name__)

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=2, max_size=5)
        self._redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
        self.log.info("inference_engine_connected")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
        if self._redis:
            await self._redis.close()

    def load_models(self, model_dir: str | None = None) -> bool:
        """Load HMM + Transformer from artifact directory. Returns True if successful."""
        base = Path(model_dir or settings.model_store_path)
        hmm_path = base / "hmm_model.joblib"
        tfm_path = base / "transformer_model.pt"

        if not hmm_path.exists() or not tfm_path.exists():
            self.log.warning("models_not_found", path=str(base))
            return False

        hmm = HMMRegimeModel().load(str(hmm_path))
        # Need to know n_features to init transformer — read from saved file
        import torch
        tfm_data = torch.load(str(tfm_path), map_location="cpu")
        n_features = tfm_data.get("n_features", len(TFM_FEATURES))
        tfm = TransformerRegimeModel(n_features=n_features).load(str(tfm_path))

        self.ensemble = EnsemblePredictor(hmm, tfm)
        self.log.info("models_loaded", hmm_path=str(hmm_path), tfm_path=str(tfm_path))
        return True

    async def predict_ticker(
        self,
        ticker: str,
        feature_history: pl.DataFrame,
    ) -> RegimePrediction | None:
        """
        Run inference for a single ticker given its feature history.
        feature_history: recent rows from the feature store, sorted by time.
        """
        if not self.ensemble:
            self.log.warning("no_ensemble_loaded")
            return None

        lb = settings.transformer_lookback
        if len(feature_history) < lb:
            self.log.warning("insufficient_history", ticker=ticker, rows=len(feature_history))
            return None

        # HMM: use latest single bar
        hmm_avail = [f for f in HMM_FEATURES if f in feature_history.columns]
        X_hmm = feature_history.tail(1).select(hmm_avail).to_numpy().astype(np.float32)

        # Transformer: use last `lb` bars as sequence
        tfm_avail = [f for f in TFM_FEATURES if f in feature_history.columns]
        X_tfm = (
            feature_history.tail(lb)
            .select(tfm_avail)
            .to_numpy()
            .astype(np.float32)
            .reshape(1, lb, len(tfm_avail))
        )

        pred = self.ensemble.predict_single(X_hmm, X_tfm)

        # Persist
        await self._write_db(ticker, pred)
        await self._write_redis(ticker, pred)

        return pred

    async def _write_db(self, ticker: str, pred: RegimePrediction) -> None:
        if not self._pool:
            return
        import json as _json
        now = datetime.now(tz=timezone.utc)
        sql = """
            INSERT INTO regime_signals
              (time, ticker, regime, confidence, hmm_prob, transformer_prob, ensemble_prob, model_version)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                sql, now, ticker, pred.regime, pred.confidence,
                _json.dumps(pred.hmm_prob),
                _json.dumps(pred.transformer_prob),
                _json.dumps(pred.ensemble_prob),
                "latest",
            )

    async def _write_redis(self, ticker: str, pred: RegimePrediction) -> None:
        if not self._redis:
            return
        key = f"regime:{ticker}"
        value = json.dumps({
            "regime": pred.regime,
            "regime_name": pred.regime_name,
            "confidence": pred.confidence,
            "ensemble_prob": pred.ensemble_prob,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        })
        await self._redis.setex(key, 3600, value)  # TTL 1 hour

    async def get_cached_regime(self, ticker: str) -> dict | None:
        if not self._redis:
            return None
        raw = await self._redis.get(f"regime:{ticker}")
        return json.loads(raw) if raw else None

    async def get_all_regimes(self) -> dict[str, dict]:
        if not self._redis:
            return {}
        keys = await self._redis.keys("regime:*")
        result = {}
        for key in keys:
            ticker = key.split(":", 1)[1]
            raw = await self._redis.get(key)
            if raw:
                result[ticker] = json.loads(raw)
        return result
