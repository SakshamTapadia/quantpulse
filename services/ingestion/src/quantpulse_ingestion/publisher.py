"""
KafkaPublisher — wraps aiokafka AIOKafkaProducer.

Each record type has its own topic and partition key strategy:
  - OHLCV   → topic: raw-ohlcv,    key: ticker
  - Macro   → topic: macro-data,   key: series_id
  - Options → topic: options-flow, key: ticker
"""
import uuid
from datetime import datetime, timezone
from typing import Any

import orjson
import structlog
from aiokafka import AIOKafkaProducer
from prometheus_client import Counter

from quantpulse_ingestion.config import settings
from quantpulse_ingestion.schemas import MacroRecord, OHLCVRecord, OptionsRecord

logger = structlog.get_logger(__name__)

kafka_published = Counter(
    "ingestion_kafka_published_total",
    "Records published to Kafka",
    ["topic", "status"],
)


def _json_serialiser(obj: Any) -> bytes:
    return orjson.dumps(obj, default=str)


class KafkaPublisher:
    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None
        self.log = structlog.get_logger(self.__class__.__name__)

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=_json_serialiser,
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            compression_type="gzip",
            acks="all",                 # wait for all in-sync replicas
            max_batch_size=1_000_000,
            linger_ms=50,               # small batching window for throughput
        )
        await self._producer.start()
        self.log.info("kafka_producer_started", servers=settings.kafka_bootstrap_servers)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()

    async def publish_ohlcv(self, records: list[OHLCVRecord]) -> None:
        await self._publish_batch(
            topic=settings.kafka_topic_raw_ohlcv,
            records=[r.model_dump(mode="json") for r in records],
            keys=[r.ticker for r in records],
            data_type="ohlcv",
        )

    async def publish_macro(self, records: list[MacroRecord]) -> None:
        await self._publish_batch(
            topic=settings.kafka_topic_macro,
            records=[r.model_dump(mode="json") for r in records],
            keys=[r.series_id for r in records],
            data_type="macro",
        )

    async def publish_options(self, records: list[OptionsRecord]) -> None:
        await self._publish_batch(
            topic=settings.kafka_topic_options,
            records=[r.model_dump(mode="json") for r in records],
            keys=[r.ticker for r in records],
            data_type="options",
        )

    async def _publish_batch(
        self,
        topic: str,
        records: list[dict],
        keys: list[str],
        data_type: str,
    ) -> None:
        if not self._producer:
            raise RuntimeError("Producer not started. Call start() first.")

        # Wrap records in an envelope with metadata
        batch_id = str(uuid.uuid4())
        envelope = {
            "batch_id": batch_id,
            "ingested_at": datetime.now(tz=timezone.utc).isoformat(),
            "source": "ingestion-service",
            "data_type": data_type,
            "record_count": len(records),
            "records": records,
        }

        try:
            await self._producer.send_and_wait(
                topic=topic,
                value=envelope,
                key=keys[0] if keys else None,   # partition by first ticker/series
            )
            kafka_published.labels(topic=topic, status="success").inc(len(records))
            self.log.info(
                "batch_published",
                topic=topic,
                batch_id=batch_id,
                records=len(records),
            )
        except Exception as exc:
            kafka_published.labels(topic=topic, status="error").inc(len(records))
            self.log.error("publish_failed", topic=topic, error=str(exc))
            raise
