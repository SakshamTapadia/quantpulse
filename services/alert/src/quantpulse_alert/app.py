"""
Alert service - consumes regime-signals and features, evaluates rules,
persists alerts to TimescaleDB, and pushes to the API gateway via Kafka.

Alert types:
  REGIME_SHIFT   - regime changed for a ticker (e.g. trending → high_vol)
  VOL_SPIKE      - rv_ratio > threshold or VIX z-score > threshold
  GEX_FLIP       - GEX proxy crossed zero (dealer positioning flip)
  CONFIDENCE_LOW - ensemble confidence < 0.5 (uncertain regime)

Severity:
  1 = info     (regime shift within low-vol regimes)
  2 = warning  (vol spike, GEX flip)
  3 = critical (high_vol regime entered, confidence collapse)
"""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

import asyncpg
import orjson
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.responses import Response


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_topic_regime: str = Field(default="regime-signals", alias="KAFKA_TOPIC_REGIME")

    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_user: str = Field(default="quantpulse", alias="POSTGRES_USER")
    postgres_password: str = Field(default="changeme", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="quantpulse", alias="POSTGRES_DB")

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


regime_settings = _Settings()

logger = structlog.get_logger(__name__)

alerts_generated = Counter("alert_generated_total", "Alerts generated", ["alert_type", "severity"])

# In-memory cache of last regime per ticker (for detecting changes)
_last_regime: dict[str, int] = {}
_db_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app) -> AsyncIterator[None]:
    global _db_pool
    _db_pool = await asyncpg.create_pool(dsn=regime_settings.postgres_dsn, min_size=2, max_size=5)
    consumer = AIOKafkaConsumer(
        regime_settings.kafka_topic_regime,
        bootstrap_servers=regime_settings.kafka_bootstrap_servers,
        group_id="alert-service",
        value_deserializer=lambda b: orjson.loads(b),
        auto_offset_reset="latest",
    )
    await consumer.start()
    task = asyncio.create_task(_consume(consumer))
    logger.info("alert_service_started")
    yield
    task.cancel()
    await consumer.stop()
    await _db_pool.close()


app = FastAPI(title="QuantPulse Alert Service", version="0.1.0", lifespan=lifespan)


async def _consume(consumer: AIOKafkaConsumer) -> None:
    async for msg in consumer:
        signal = msg.value
        await _evaluate(signal)


async def _evaluate(signal: dict) -> None:
    ticker = signal.get("ticker", "")
    regime = signal.get("regime")
    confidence = signal.get("confidence", 1.0)
    regime_name = signal.get("regime_name", "")
    ensemble_prob = signal.get("ensemble_prob", [])

    alerts = []

    # ── Regime shift ────────────────────────────────────────────────────────
    prev = _last_regime.get(ticker)
    if prev is not None and prev != regime:
        severity = 3 if regime == 3 else (2 if regime in {0, 1} and prev == 2 else 1)
        alerts.append({
            "alert_type": "REGIME_SHIFT",
            "severity": severity,
            "ticker": ticker,
            "payload": {
                "from_regime": prev,
                "to_regime": regime,
                "to_regime_name": regime_name,
                "confidence": confidence,
            },
        })
    _last_regime[ticker] = regime

    # ── High-vol entered ─────────────────────────────────────────────────────
    if regime == 3 and (prev is None or prev != 3):
        alerts.append({
            "alert_type": "HIGH_VOL_ENTERED",
            "severity": 3,
            "ticker": ticker,
            "payload": {"confidence": confidence, "probs": ensemble_prob},
        })

    # ── Low confidence ────────────────────────────────────────────────────────
    if confidence < 0.5:
        alerts.append({
            "alert_type": "CONFIDENCE_LOW",
            "severity": 1,
            "ticker": ticker,
            "payload": {"confidence": confidence, "regime": regime},
        })

    for alert in alerts:
        await _persist_alert(alert)
        alerts_generated.labels(
            alert_type=alert["alert_type"], severity=str(alert["severity"])
        ).inc()


async def _persist_alert(alert: dict) -> None:
    if not _db_pool:
        return
    sql = """
        INSERT INTO alerts (time, ticker, alert_type, severity, payload)
        VALUES ($1, $2, $3, $4, $5)
    """
    async with _db_pool.acquire() as conn:
        await conn.execute(
            sql,
            datetime.now(tz=timezone.utc),
            alert.get("ticker"),
            alert["alert_type"],
            alert["severity"],
            json.dumps(alert["payload"]),
        )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "alert"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/alerts")
async def get_alerts(limit: int = 50) -> dict:
    if not _db_pool:
        return {"alerts": []}
    rows = await _db_pool.fetch(
        "SELECT * FROM alerts ORDER BY time DESC LIMIT $1", limit
    )
    return {"alerts": [dict(r) for r in rows]}
