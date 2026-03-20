"""
Feature service FastAPI app.

Endpoints:
  GET  /health
  GET  /ready
  GET  /metrics               Prometheus
  GET  /features/{ticker}     Latest feature row for a ticker
  GET  /features/tickers      All available tickers in the store
  POST /trigger/compute       Manually trigger pipeline on stored OHLCV
"""
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from quantpulse_feature.consumer import FeatureConsumer
from quantpulse_feature.store import FeatureStore

logger = structlog.get_logger(__name__)

_consumer = FeatureConsumer()
_store = FeatureStore()
_consumer_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _consumer_task
    await _consumer.start()
    _consumer_task = asyncio.create_task(_consumer.run())
    logger.info("feature_service_started")
    yield
    _consumer_task.cancel()
    await _consumer.stop()
    logger.info("feature_service_stopped")


app = FastAPI(title="QuantPulse Feature Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "feature"}


@app.get("/ready")
async def ready() -> dict:
    tickers = _store.get_available_tickers()
    return {"status": "ready", "tickers_in_store": len(tickers)}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/features/tickers")
async def list_tickers() -> dict:
    return {"tickers": _store.get_available_tickers()}


@app.get("/features/{ticker}")
async def get_features(ticker: str, n: int = 1) -> dict:
    df = _store.read_latest(tickers=[ticker.upper()], n=n)
    if df.is_empty():
        raise HTTPException(status_code=404, detail=f"No features found for {ticker}")
    return {"ticker": ticker.upper(), "rows": n, "data": df.to_dicts()}


@app.get("/features/{ticker}/date-range")
async def get_date_range(ticker: str) -> dict:
    result = _store.get_date_range(ticker.upper())
    if not result:
        raise HTTPException(status_code=404, detail=f"No data for {ticker}")
    return {"ticker": ticker.upper(), "start": result[0], "end": result[1]}


@app.post("/trigger/compute")
async def trigger_compute() -> dict:
    asyncio.create_task(_consumer._flush())
    return {"status": "triggered", "job": "feature_computation"}
