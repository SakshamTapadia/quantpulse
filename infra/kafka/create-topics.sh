#!/bin/bash
# Run inside the Kafka container to create all required topics.
# Called automatically by `make kafka-topics`.

set -e
BOOTSTRAP="localhost:9092"

topics=(
  "raw-ohlcv:4"
  "macro-data:2"
  "options-flow:2"
  "computed-features:4"
  "regime-signals:2"
  "alerts:2"
)

for entry in "${topics[@]}"; do
  topic="${entry%%:*}"
  partitions="${entry##*:}"
  kafka-topics --bootstrap-server "$BOOTSTRAP" \
    --create --if-not-exists \
    --topic "$topic" \
    --partitions "$partitions" \
    --replication-factor 1
  echo "Topic ready: $topic ($partitions partitions)"
done

echo ""
echo "All topics created:"
kafka-topics --bootstrap-server "$BOOTSTRAP" --list
