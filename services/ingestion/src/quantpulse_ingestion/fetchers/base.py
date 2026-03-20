"""
Base fetcher — all data fetchers inherit from this.
Provides: structured logging, Prometheus metrics, tenacity retry.
"""
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

import structlog
from prometheus_client import Counter, Histogram
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from quantpulse_ingestion.config import settings

logger = structlog.get_logger(__name__)

# ── Prometheus metrics ───────────────────────────────────────────────────────
fetch_total = Counter(
    "ingestion_fetch_total",
    "Total fetch attempts",
    ["source", "status"],
)
fetch_duration = Histogram(
    "ingestion_fetch_duration_seconds",
    "Fetch duration in seconds",
    ["source"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)
records_ingested = Counter(
    "ingestion_records_total",
    "Total records successfully ingested",
    ["source", "data_type"],
)


class BaseFetcher(ABC):
    source: str = "unknown"

    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    async def fetch_with_retry(self, *args: Any, **kwargs: Any) -> Any:
        """Wraps _fetch() with exponential backoff retry and metrics."""
        start = time.perf_counter()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(settings.max_retries),
                wait=wait_exponential(
                    multiplier=settings.retry_wait_seconds, min=1, max=30
                ),
                retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
                reraise=True,
            ):
                with attempt:
                    result = await self._fetch(*args, **kwargs)

            elapsed = time.perf_counter() - start
            fetch_total.labels(source=self.source, status="success").inc()
            fetch_duration.labels(source=self.source).observe(elapsed)
            self.log.info("fetch_complete", elapsed=round(elapsed, 3))
            return result

        except Exception as exc:
            elapsed = time.perf_counter() - start
            fetch_total.labels(source=self.source, status="error").inc()
            self.log.error("fetch_failed", error=str(exc), elapsed=round(elapsed, 3))
            raise

    @abstractmethod
    async def _fetch(self, *args: Any, **kwargs: Any) -> Any:
        """Implement the actual fetch logic in subclasses."""
        ...

    async def _sleep(self, seconds: float) -> None:
        """Polite delay to avoid hammering free-tier APIs."""
        await asyncio.sleep(seconds)
