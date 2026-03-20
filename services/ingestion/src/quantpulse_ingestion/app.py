"""
Ingestion service FastAPI app.

Endpoints:
  GET  /health          liveness probe
  GET  /ready           readiness probe (checks DB + Kafka)
  GET  /metrics         Prometheus metrics
  POST /trigger/eod     manually trigger EOD ingestion
  POST /trigger/backfill?years=5   trigger historical backfill
"""
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import BackgroundTasks, FastAPI, HTTPException
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from quantpulse_ingestion.config import settings
from quantpulse_ingestion.publisher import KafkaPublisher
from quantpulse_ingestion.scheduler import IngestionScheduler
from quantpulse_ingestion.writer import DBWriter

logger = structlog.get_logger(__name__)

# ── Shared state ─────────────────────────────────────────────────────────────
publisher = KafkaPublisher()
writer = DBWriter()
scheduler: IngestionScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global scheduler
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
    logger.info("ingestion_service_starting", tickers=len(settings.tickers))

    await publisher.start()
    await writer.connect()

    scheduler = IngestionScheduler(publisher=publisher, writer=writer)
    scheduler.start()

    yield

    logger.info("ingestion_service_stopping")
    scheduler.stop()
    await publisher.stop()
    await writer.close()


app = FastAPI(
    title="QuantPulse Ingestion Service",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "ingestion"}


@app.get("/ready")
async def ready() -> dict:
    checks: dict[str, str] = {}
    # DB check
    try:
        async with writer.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc}"
    # Kafka check
    checks["kafka"] = "ok" if publisher._producer else "not_started"

    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        raise HTTPException(status_code=503, detail=checks)
    return {"status": "ready", "checks": checks}


# ── Metrics ──────────────────────────────────────────────────────────────────

@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ── Manual triggers ──────────────────────────────────────────────────────────

@app.post("/trigger/eod")
async def trigger_eod(background_tasks: BackgroundTasks) -> dict:
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not ready")
    background_tasks.add_task(scheduler.run_eod_ingestion)
    return {"status": "triggered", "job": "eod_ingestion"}


@app.post("/trigger/intraday")
async def trigger_intraday(background_tasks: BackgroundTasks) -> dict:
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not ready")
    background_tasks.add_task(scheduler.run_intraday_ingestion)
    return {"status": "triggered", "job": "intraday_ingestion"}


@app.post("/trigger/backfill")
async def trigger_backfill(
    background_tasks: BackgroundTasks,
    years: int = 5,
) -> dict:
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not ready")
    if not 1 <= years <= 20:
        raise HTTPException(status_code=422, detail="years must be between 1 and 20")
    background_tasks.add_task(scheduler.run_historical_backfill, years)
    return {"status": "triggered", "job": "historical_backfill", "years": years}


@app.get("/status")
async def status() -> dict:
    if not scheduler:
        return {"scheduler": "not_started"}
    jobs = [
        {"id": j.id, "name": j.name, "next_run": str(j.next_run_time)}
        for j in scheduler._scheduler.get_jobs()
    ]
    return {
        "service": "ingestion",
        "tickers": len(settings.tickers),
        "ticker_universe": settings.tickers,
        "scheduler_jobs": jobs,
    }
