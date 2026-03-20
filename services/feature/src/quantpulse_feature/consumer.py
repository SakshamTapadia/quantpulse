"""
FeatureConsumer - consumes raw data from Kafka, runs the feature pipeline,
writes results to the feature store, and publishes to computed-features topic.

Consumption model:
  - Subscribes to: raw-ohlcv, macro-data, options-flow
  - Batches messages by ticker within a time window (30s)
  - Runs FeaturePipeline on accumulated batch
  - Writes Parquet to FeatureStore
  - Publishes feature rows to computed-features topic
"""
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone

import orjson
import polars as pl
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from prometheus_client import Counter, Histogram

from quantpulse_feature.config import settings
from quantpulse_feature.pipeline.feature_pipeline import FeaturePipeline
from quantpulse_feature.store import FeatureStore

logger = structlog.get_logger(__name__)

messages_consumed = Counter(
    "feature_messages_consumed_total", "Kafka messages consumed", ["topic"]
)
pipeline_runs = Counter(
    "feature_pipeline_runs_total", "Pipeline executions", ["status"]
)
pipeline_duration = Histogram(
    "feature_pipeline_duration_seconds", "Pipeline run duration",
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0],
)


class FeatureConsumer:
    def __init__(self) -> None:
        self.pipeline = FeaturePipeline()
        self.store = FeatureStore()
        self._consumer: AIOKafkaConsumer | None = None
        self._producer: AIOKafkaProducer | None = None
        self._ohlcv_buffer: list[dict] = []
        self._macro_buffer: list[dict] = []
        self._macro_cache: list[dict] = []   # persists across flushes
        self._options_buffer: dict[str, dict[str, float]] = {}
        self.log = structlog.get_logger(self.__class__.__name__)

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            settings.kafka_topic_raw_ohlcv,
            settings.kafka_topic_macro,
            settings.kafka_topic_options,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_consumer_group,
            value_deserializer=lambda b: orjson.loads(b),
            auto_offset_reset="earliest",
            enable_auto_commit=True,
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: orjson.dumps(v, default=str),
        )
        await self._consumer.start()
        await self._producer.start()
        self.log.info("feature_consumer_started")

    async def stop(self) -> None:
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()

    async def run(self) -> None:
        """Main consume loop - batches messages and triggers pipeline every 30s."""
        if not self._consumer:
            raise RuntimeError("Consumer not started")

        # Background task flushes every 30s regardless of message flow
        flush_task = asyncio.create_task(self._flush_loop())

        try:
            async for msg in self._consumer:
                topic = msg.topic
                envelope = msg.value
                messages_consumed.labels(topic=topic).inc()

                records = envelope.get("records", [])

                if topic == settings.kafka_topic_raw_ohlcv:
                    self._ohlcv_buffer.extend(records)
                elif topic == settings.kafka_topic_macro:
                    self._macro_buffer.extend(records)
                elif topic == settings.kafka_topic_options:
                    # Options arrive as derived metrics per ticker
                    for rec in records:
                        ticker = rec.get("ticker", "")
                        if ticker:
                            self._options_buffer[ticker] = {
                                k: v for k, v in rec.items()
                                if k in {"iv_skew_proxy", "put_call_ratio", "gex_proxy"}
                            }
        finally:
            flush_task.cancel()

    async def _flush_loop(self) -> None:
        """Periodically flush buffers even when no new messages arrive."""
        while True:
            await asyncio.sleep(30)
            if self._ohlcv_buffer:
                await self._flush()

    async def _flush(self) -> None:
        """Convert buffers → DataFrames → run pipeline → store + publish."""
        import time
        ohlcv_rows = self._ohlcv_buffer.copy()
        macro_rows = self._macro_buffer.copy()
        options = self._options_buffer.copy()

        self._ohlcv_buffer.clear()
        self._macro_buffer.clear()

        # Update persistent macro cache with any new records
        if macro_rows:
            self._macro_cache.extend(macro_rows)

        if not ohlcv_rows:
            return

        # Use current batch macro + cached macro (dedup by series_id+time)
        effective_macro = macro_rows or self._macro_cache
        self.log.info("flush_start", ohlcv_rows=len(ohlcv_rows), macro_rows=len(effective_macro))
        start = time.perf_counter()

        try:
            ohlcv_df = self._records_to_ohlcv_df(ohlcv_rows)
            macro_df = self._records_to_macro_df(effective_macro) if effective_macro else None

            feature_df = self.pipeline.run(
                ohlcv_df=ohlcv_df,
                macro_df=macro_df,
                options_metrics=options if options else None,
            )

            self.store.write(feature_df)
            await self._publish_features(feature_df)

            elapsed = time.perf_counter() - start
            pipeline_runs.labels(status="success").inc()
            pipeline_duration.observe(elapsed)
            self.log.info("flush_complete", rows=len(feature_df), elapsed=round(elapsed, 3))

        except Exception as exc:
            pipeline_runs.labels(status="error").inc()
            self.log.error("flush_failed", error=str(exc))

    def _records_to_ohlcv_df(self, records: list[dict]) -> pl.DataFrame:
        return pl.DataFrame(records).with_columns(
            pl.col("time").str.to_datetime(time_unit="us", time_zone="UTC")
        ).cast({"open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
                "close": pl.Float64, "volume": pl.Int64})

    def _records_to_macro_df(self, records: list[dict]) -> pl.DataFrame:
        return pl.DataFrame(records).with_columns(
            pl.col("time").str.to_datetime(time_unit="us", time_zone="UTC")
        )

    async def _publish_features(self, df: pl.DataFrame) -> None:
        if not self._producer or df.is_empty():
            return
        # Publish feature summary per ticker (latest row only)
        latest = df.group_by("ticker").tail(1)
        envelope = {
            "published_at": datetime.now(tz=timezone.utc).isoformat(),
            "record_count": len(latest),
            "records": latest.to_dicts(),
        }
        await self._producer.send_and_wait(
            topic=settings.kafka_topic_features,
            value=envelope,
        )
