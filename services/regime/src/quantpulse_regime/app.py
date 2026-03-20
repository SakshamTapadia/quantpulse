"""Regime service — FastAPI app with Kafka consumer and inference endpoints."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

import orjson
import polars as pl
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import BackgroundTasks, FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from starlette.responses import Response

from quantpulse_regime.config import settings
from quantpulse_regime.inference.engine import InferenceEngine
from quantpulse_regime.training.trainer import RegimeTrainer

logger = structlog.get_logger(__name__)

_engine = InferenceEngine()
_consumer: AIOKafkaConsumer | None = None
_producer: AIOKafkaProducer | None = None
_consumer_task: asyncio.Task | None = None

inferences_total = Counter("regime_inferences_total", "Regime predictions made", ["ticker"])


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _consumer, _producer, _consumer_task
    await _engine.connect()
    _engine.load_models()

    _consumer = AIOKafkaConsumer(
        settings.kafka_topic_features,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        value_deserializer=lambda b: orjson.loads(b),
        auto_offset_reset="latest",
    )
    _producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        value_serializer=lambda v: orjson.dumps(v, default=str),
    )
    await _consumer.start()
    await _producer.start()
    _consumer_task = asyncio.create_task(_consume_loop())
    logger.info("regime_service_started")
    yield
    if _consumer_task:
        _consumer_task.cancel()
    await _consumer.stop()
    await _producer.stop()
    await _engine.close()


app = FastAPI(title="QuantPulse Regime Service", version="0.1.0", lifespan=lifespan)


async def _consume_loop() -> None:
    """Consume feature batches and run inference per ticker."""
    from pathlib import Path
    import asyncio

    async for msg in _consumer:
        envelope = msg.value
        records = envelope.get("records", [])
        if not records:
            continue
        df = pl.DataFrame(records).with_columns(
            pl.col("time").str.to_datetime(time_unit="us").dt.replace_time_zone("UTC")
        )
        for ticker in df["ticker"].unique().to_list():
            ticker_df = df.filter(pl.col("ticker") == ticker).sort("time")
            # Load lookback history from feature store so the Transformer has enough context
            lb = settings.transformer_lookback
            feature_path = Path(settings.feature_store_path) / "features"
            if feature_path.exists():
                try:
                    ticker_part = feature_path / f"ticker={ticker}"
                    if ticker_part.exists():
                        hist = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda p=str(ticker_part): pl.read_parquet(p, use_pyarrow=True)
                        )
                        if "ticker" not in hist.columns:
                            hist = hist.with_columns(pl.lit(ticker).alias("ticker"))
                        ticker_df = pl.concat([hist.sort("time").tail(lb + 10), ticker_df]).unique(
                            subset=["time", "ticker"], keep="last"
                        ).sort("time")
                except Exception:
                    pass
            pred = await _engine.predict_ticker(ticker, ticker_df)
            if pred:
                inferences_total.labels(ticker=ticker).inc()
                await _publish_signal(ticker, pred)


async def _publish_signal(ticker: str, pred) -> None:
    if not _producer:
        return
    payload = {
        "time": datetime.now(tz=timezone.utc).isoformat(),
        "ticker": ticker,
        "regime": pred.regime,
        "regime_name": pred.regime_name,
        "confidence": pred.confidence,
        "ensemble_prob": pred.ensemble_prob,
    }
    await _producer.send_and_wait(settings.kafka_topic_regime, value=payload, key=ticker.encode())


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "regime", "models_loaded": _engine.ensemble is not None}


@app.get("/ready")
async def ready() -> dict:
    if not _engine.ensemble:
        raise HTTPException(status_code=503, detail="Models not loaded")
    return {"status": "ready"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/regime/{ticker}")
async def get_regime(ticker: str) -> dict:
    cached = await _engine.get_cached_regime(ticker.upper())
    if not cached:
        raise HTTPException(status_code=404, detail=f"No regime signal for {ticker}")
    return {"ticker": ticker.upper(), **cached}


@app.get("/regime")
async def get_all_regimes() -> dict:
    regimes = await _engine.get_all_regimes()
    return {"regimes": regimes, "count": len(regimes)}


@app.post("/train")
async def trigger_training(background_tasks: BackgroundTasks) -> dict:
    """Trigger a full model retraining. Runs in background."""
    async def _train() -> None:
        from pathlib import Path
        import polars as pl
        store_path = Path(settings.feature_store_path) / "features"
        if not store_path.exists():
            logger.warning("training_skipped_no_features", path=str(store_path))
            return
        df = pl.read_parquet(str(store_path), use_pyarrow=True)
        if df.is_empty():
            logger.warning("training_skipped_no_data")
            return
        trainer = RegimeTrainer()
        ensemble = trainer.train(df)
        _engine.ensemble = ensemble
        logger.info("retraining_complete")

    background_tasks.add_task(_train)
    return {"status": "triggered", "job": "regime_training"}


@app.post("/infer")
async def trigger_inference() -> dict:
    """Run inference for all tickers from the current feature store."""
    from pathlib import Path
    import polars as pl

    if not _engine.ensemble:
        raise HTTPException(status_code=503, detail="Models not loaded")

    store_path = Path(settings.feature_store_path) / "features"
    if not store_path.exists():
        raise HTTPException(status_code=404, detail="Feature store not found")

    results = {}
    lb = settings.transformer_lookback
    for ticker_dir in store_path.iterdir():
        if not ticker_dir.is_dir() or not ticker_dir.name.startswith("ticker="):
            continue
        ticker = ticker_dir.name.replace("ticker=", "")
        try:
            hist = pl.read_parquet(str(ticker_dir), use_pyarrow=True)
            if "ticker" not in hist.columns:
                hist = hist.with_columns(pl.lit(ticker).alias("ticker"))
            hist = hist.sort("time").tail(lb + 10)
            pred = await _engine.predict_ticker(ticker, hist)
            if pred:
                inferences_total.labels(ticker=ticker).inc()
                if _producer:
                    await _publish_signal(ticker, pred)
                results[ticker] = {"regime": pred.regime, "regime_name": pred.regime_name,
                                   "confidence": pred.confidence}
        except Exception as exc:
            logger.warning("infer_ticker_failed", ticker=ticker, error=str(exc))

    return {"status": "ok", "inferred": len(results), "results": results}
