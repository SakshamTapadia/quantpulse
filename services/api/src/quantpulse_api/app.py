"""
API Gateway — single entry point for the Next.js frontend.

REST endpoints:
  GET  /api/v1/regime/{ticker}       Latest regime for a ticker
  GET  /api/v1/regime                All ticker regimes
  GET  /api/v1/ohlcv/{ticker}        OHLCV bars (paginated)
  GET  /api/v1/features/{ticker}     Latest feature row
  GET  /api/v1/alerts                Recent alerts
  GET  /api/v1/tickers               Available tickers

WebSocket:
  WS   /ws/regime                    Real-time regime updates stream

Auth:
  POST /auth/token                   Get JWT (demo: any username/password)
"""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import asyncpg
import httpx
import orjson
import redis.asyncio as aioredis
import structlog
from aiokafka import AIOKafkaConsumer
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.responses import Response

logger = structlog.get_logger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "quantpulse"
    postgres_password: str = "changeme"
    postgres_db: str = "quantpulse"
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = "changeme"
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_regime: str = "regime-signals"
    jwt_secret: str = "change_this_in_production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    cors_origins: str = "http://localhost:3000"
    service_host: str = "0.0.0.0"
    service_port: int = 8000

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def redis_url(self) -> str:
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}"

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()

# ── Shared state ──────────────────────────────────────────────────────────────
_pool: asyncpg.Pool | None = None
_redis: aioredis.Redis | None = None
_ws_clients: set[WebSocket] = set()
_consumer_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _pool, _redis, _consumer_task
    _pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=2, max_size=10)
    _redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
    _consumer_task = asyncio.create_task(_regime_broadcast_loop())
    logger.info("api_gateway_started")
    yield
    if _consumer_task:
        _consumer_task.cancel()
    await _pool.close()
    await _redis.close()


async def _regime_broadcast_loop() -> None:
    """Consume regime-signals and broadcast to all connected WebSocket clients."""
    consumer = AIOKafkaConsumer(
        settings.kafka_topic_regime,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="api-gateway-ws",
        value_deserializer=lambda b: orjson.loads(b),
        auto_offset_reset="latest",
    )
    await consumer.start()
    try:
        async for msg in consumer:
            if _ws_clients:
                payload = json.dumps(msg.value, default=str)
                dead = set()
                for ws in _ws_clients.copy():
                    try:
                        await ws.send_text(payload)
                    except Exception:
                        dead.add(ws)
                _ws_clients -= dead
    finally:
        await consumer.stop()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="QuantPulse API Gateway", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


# ── Auth ──────────────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str


def _create_token(username: str) -> str:
    expire = datetime.now(tz=timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode({"sub": username, "exp": expire}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        username: str = payload.get("sub", "")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.post("/auth/token", response_model=Token)
async def login(form: OAuth2PasswordRequestForm = Depends()) -> Token:
    # Demo auth — any non-empty credentials work
    if not form.username or not form.password:
        raise HTTPException(status_code=400, detail="Username and password required")
    return Token(access_token=_create_token(form.username), token_type="bearer")


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api-gateway"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v1/tickers")
async def get_tickers(user: str = Depends(get_current_user)) -> dict:
    if not _redis:
        raise HTTPException(status_code=503, detail="Cache unavailable")
    keys = await _redis.keys("regime:*")
    return {"tickers": [k.split(":", 1)[1] for k in keys]}


@app.get("/api/v1/regime")
async def get_all_regimes(user: str = Depends(get_current_user)) -> dict:
    if not _redis:
        raise HTTPException(status_code=503, detail="Cache unavailable")
    keys = await _redis.keys("regime:*")
    result = {}
    for key in keys:
        ticker = key.split(":", 1)[1]
        raw = await _redis.get(key)
        if raw:
            result[ticker] = json.loads(raw)
    return {"regimes": result}


@app.get("/api/v1/regime/{ticker}")
async def get_ticker_regime(ticker: str, user: str = Depends(get_current_user)) -> dict:
    if not _redis:
        raise HTTPException(status_code=503, detail="Cache unavailable")
    raw = await _redis.get(f"regime:{ticker.upper()}")
    if not raw:
        raise HTTPException(status_code=404, detail=f"No regime for {ticker}")
    return {"ticker": ticker.upper(), **json.loads(raw)}


@app.get("/api/v1/ohlcv/{ticker}")
async def get_ohlcv(
    ticker: str,
    limit: int = 252,
    interval: str = "1d",
    user: str = Depends(get_current_user),
) -> dict:
    if not _pool:
        raise HTTPException(status_code=503, detail="DB unavailable")
    rows = await _pool.fetch(
        "SELECT time, open, high, low, close, volume FROM ohlcv WHERE ticker=$1 ORDER BY time DESC LIMIT $2",
        ticker.upper(), limit,
    )
    return {"ticker": ticker.upper(), "bars": [dict(r) for r in reversed(rows)]}


@app.get("/api/v1/regime/{ticker}/history")
async def get_regime_history(
    ticker: str, limit: int = 100, user: str = Depends(get_current_user)
) -> dict:
    if not _pool:
        raise HTTPException(status_code=503, detail="DB unavailable")
    rows = await _pool.fetch(
        "SELECT time, regime, confidence FROM regime_signals WHERE ticker=$1 ORDER BY time DESC LIMIT $2",
        ticker.upper(), limit,
    )
    return {"ticker": ticker.upper(), "history": [dict(r) for r in reversed(rows)]}


@app.get("/api/v1/alerts")
async def get_alerts(
    limit: int = 50,
    unread_only: bool = False,
    user: str = Depends(get_current_user),
) -> dict:
    if not _pool:
        raise HTTPException(status_code=503, detail="DB unavailable")
    sql = "SELECT * FROM alerts"
    sql += " WHERE read=FALSE" if unread_only else ""
    sql += " ORDER BY time DESC LIMIT $1"
    rows = await _pool.fetch(sql, limit)
    return {"alerts": [dict(r) for r in rows]}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/regime")
async def ws_regime(websocket: WebSocket) -> None:
    await websocket.accept()
    _ws_clients.add(websocket)
    logger.info("ws_client_connected", total=len(_ws_clients))
    try:
        # Send current regime snapshot on connect
        if _redis:
            keys = await _redis.keys("regime:*")
            snapshot = {}
            for key in keys:
                raw = await _redis.get(key)
                if raw:
                    snapshot[key.split(":", 1)[1]] = json.loads(raw)
            await websocket.send_text(json.dumps({"type": "snapshot", "data": snapshot}))

        while True:
            await websocket.receive_text()  # keep alive

    except WebSocketDisconnect:
        _ws_clients.discard(websocket)
        logger.info("ws_client_disconnected", total=len(_ws_clients))


# ── Regime service proxy ───────────────────────────────────────────────────────

_REGIME_SERVICE_URL = "http://regime:8003"
_INGESTION_SERVICE_URL = "http://ingestion:8001"


@app.post("/trigger/backfill")
async def proxy_backfill(years: int = 5, user: str = Depends(get_current_user)) -> dict:
    """Proxy historical backfill trigger to the ingestion service."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(f"{_INGESTION_SERVICE_URL}/trigger/backfill?years={years}")
            return r.json()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {exc}")


@app.post("/trigger/eod")
async def proxy_eod(user: str = Depends(get_current_user)) -> dict:
    """Proxy EOD ingestion trigger to the ingestion service."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(f"{_INGESTION_SERVICE_URL}/trigger/eod")
            return r.json()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {exc}")


@app.post("/train")
async def proxy_train(user: str = Depends(get_current_user)) -> dict:
    """Proxy training trigger to the regime service."""
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.post(f"{_REGIME_SERVICE_URL}/train")
            return r.json()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Regime service unavailable: {exc}")


@app.post("/infer")
async def proxy_infer(user: str = Depends(get_current_user)) -> dict:
    """Proxy inference trigger to the regime service."""
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            r = await client.post(f"{_REGIME_SERVICE_URL}/infer")
            return r.json()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Regime service unavailable: {exc}")
