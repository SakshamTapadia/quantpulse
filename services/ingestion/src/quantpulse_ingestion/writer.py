"""
DBWriter — writes validated records to TimescaleDB via asyncpg.
Uses UPSERT (INSERT ... ON CONFLICT DO UPDATE) to safely re-run ingestion.
"""
from typing import Any

import asyncpg
import structlog
from prometheus_client import Counter, Histogram

from quantpulse_ingestion.config import settings
from quantpulse_ingestion.schemas import MacroRecord, OHLCVRecord, OptionsRecord

logger = structlog.get_logger(__name__)

db_writes = Counter(
    "ingestion_db_writes_total",
    "DB rows written",
    ["table", "status"],
)
db_write_duration = Histogram(
    "ingestion_db_write_duration_seconds",
    "Time to complete a DB write batch",
    ["table"],
)


class DBWriter:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self.log = structlog.get_logger(self.__class__.__name__)

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=settings.postgres_dsn,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
        self.log.info("db_pool_created", dsn=settings.postgres_dsn.split("@")[-1])

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    @property
    def pool(self) -> asyncpg.Pool:
        if not self._pool:
            raise RuntimeError("DB pool not initialised. Call connect() first.")
        return self._pool

    # ── OHLCV ────────────────────────────────────────────────────────────────

    async def write_ohlcv(self, records: list[OHLCVRecord]) -> int:
        if not records:
            return 0

        rows = [
            (r.time, r.ticker, r.open, r.high, r.low, r.close, r.volume, r.vwap, r.source)
            for r in records
        ]
        sql = """
            INSERT INTO ohlcv (time, ticker, open, high, low, close, volume, vwap, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (ticker, time) DO UPDATE SET
                open   = EXCLUDED.open,
                high   = EXCLUDED.high,
                low    = EXCLUDED.low,
                close  = EXCLUDED.close,
                volume = EXCLUDED.volume,
                vwap   = EXCLUDED.vwap
        """
        return await self._executemany("ohlcv", sql, rows)

    # ── Macro ────────────────────────────────────────────────────────────────

    async def write_macro(self, records: list[MacroRecord]) -> int:
        if not records:
            return 0

        rows = [(r.time, r.series_id, r.value, r.source) for r in records]
        sql = """
            INSERT INTO macro (time, series_id, value, source)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (series_id, time) DO UPDATE SET
                value  = EXCLUDED.value,
                source = EXCLUDED.source
        """
        return await self._executemany("macro", sql, rows)

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _executemany(
        self,
        table: str,
        sql: str,
        rows: list[tuple[Any, ...]],
    ) -> int:
        import time
        start = time.perf_counter()
        try:
            async with self.pool.acquire() as conn:
                await conn.executemany(sql, rows)
            elapsed = time.perf_counter() - start
            db_writes.labels(table=table, status="success").inc(len(rows))
            db_write_duration.labels(table=table).observe(elapsed)
            self.log.info("db_write_complete", table=table, rows=len(rows), elapsed=round(elapsed, 3))
            return len(rows)
        except asyncpg.PostgresError as exc:
            db_writes.labels(table=table, status="error").inc(len(rows))
            self.log.error("db_write_failed", table=table, error=str(exc))
            raise
