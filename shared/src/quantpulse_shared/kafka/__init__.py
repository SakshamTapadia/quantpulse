"""Shared Kafka topic names and message envelope helpers."""
from datetime import datetime, timezone
import uuid

TOPIC_RAW_OHLCV = "raw-ohlcv"
TOPIC_MACRO     = "macro-data"
TOPIC_OPTIONS   = "options-flow"
TOPIC_FEATURES  = "computed-features"
TOPIC_REGIME    = "regime-signals"
TOPIC_ALERTS    = "alerts"

def make_envelope(data_type: str, records: list[dict]) -> dict:
    return {
        "batch_id":     str(uuid.uuid4()),
        "ingested_at":  datetime.now(tz=timezone.utc).isoformat(),
        "data_type":    data_type,
        "record_count": len(records),
        "records":      records,
    }
