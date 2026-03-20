"""
FeatureStore — persists computed feature matrices as partitioned Parquet files.

Layout:
  {feature_store_path}/
    features/
      ticker=SPY/
        date=2024-01-02/
          part-0.parquet
      ticker=QQQ/
        ...

This is a simple local store compatible with the Hive partitioning scheme.
For production scaling, swap the path for an S3/MinIO URI — Polars handles
both transparently with pyarrow.
"""
import os
from pathlib import Path

import polars as pl
import structlog

from quantpulse_feature.config import settings

logger = structlog.get_logger(__name__)


class FeatureStore:
    def __init__(self, base_path: str | None = None) -> None:
        self.base = Path(base_path or settings.feature_store_path)
        self.features_path = self.base / "features"
        self.features_path.mkdir(parents=True, exist_ok=True)

    def write(self, df: pl.DataFrame, partition_by: list[str] = ["ticker"]) -> None:
        """
        Write a feature DataFrame to Parquet, partitioned by ticker (and optionally date).
        Existing files for the same partition are overwritten.
        """
        if df.is_empty():
            logger.warning("feature_store_write_empty")
            return

        df.write_parquet(
            self.features_path,
            use_pyarrow=True,
            pyarrow_options={
                "partition_cols": partition_by,
                "existing_data_behavior": "delete_matching",
            },
        )
        logger.info(
            "feature_store_written",
            rows=len(df),
            path=str(self.features_path),
            partitions=partition_by,
        )

    def read(
        self,
        tickers: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pl.DataFrame:
        """
        Read features from the store, optionally filtered by ticker and date range.

        Args:
            tickers:    List of tickers to load. None = all tickers.
            start_date: ISO date string e.g. "2023-01-01". None = no lower bound.
            end_date:   ISO date string. None = no upper bound.
        """
        if not self.features_path.exists():
            logger.warning("feature_store_empty", path=str(self.features_path))
            return pl.DataFrame()

        try:
            df = pl.read_parquet(
                self.features_path,
                use_pyarrow=True,
            )
        except Exception as exc:
            logger.error("feature_store_read_failed", error=str(exc))
            return pl.DataFrame()

        # Apply filters
        if tickers:
            upper = [t.upper() for t in tickers]
            df = df.filter(pl.col("ticker").is_in(upper))

        if start_date:
            df = df.filter(pl.col("time") >= pl.lit(start_date).str.to_datetime())

        if end_date:
            df = df.filter(pl.col("time") <= pl.lit(end_date).str.to_datetime())

        return df.sort(["ticker", "time"])

    def read_latest(self, tickers: list[str] | None = None, n: int = 1) -> pl.DataFrame:
        """
        Read the N most recent rows per ticker — used by the regime service
        for inference on the latest data.
        """
        df = self.read(tickers=tickers)
        if df.is_empty():
            return df
        return (
            df.sort(["ticker", "time"])
            .group_by("ticker")
            .tail(n)
        )

    def get_available_tickers(self) -> list[str]:
        """List all tickers currently in the feature store."""
        if not self.features_path.exists():
            return []
        return [
            p.name.replace("ticker=", "")
            for p in self.features_path.iterdir()
            if p.is_dir() and p.name.startswith("ticker=")
        ]

    def get_date_range(self, ticker: str) -> tuple[str, str] | None:
        """Return (min_date, max_date) for a given ticker."""
        df = self.read(tickers=[ticker])
        if df.is_empty():
            return None
        return (
            str(df["time"].min()),
            str(df["time"].max()),
        )
