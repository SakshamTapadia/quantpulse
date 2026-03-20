"""
OptionsFetcher - processes raw options chain data from yfinance into
structured OptionsRecord objects and computes derived metrics:

  - IV skew proxy  (25-delta put IV - 25-delta call IV, approximated by
                    OTM put IV - OTM call IV from the chain)
  - Put/call ratio  (total OI puts / total OI calls)
  - GEX proxy       (gamma * OI * 100 * spot, summed signed by side)

These metrics feed directly into the feature engineering service.
"""
import asyncio
from datetime import date, datetime, timezone
from typing import Any

import polars as pl
from pydantic import ValidationError

from quantpulse_ingestion.config import settings
from quantpulse_ingestion.fetchers.base import BaseFetcher, records_ingested
from quantpulse_ingestion.fetchers.ohlcv import OHLCVFetcher
from quantpulse_ingestion.schemas import OptionsRecord


class OptionsFetcher(BaseFetcher):
    source = "yfinance_options"

    def __init__(self) -> None:
        super().__init__()
        self._ohlcv = OHLCVFetcher()

    async def fetch_ticker_options(
        self, ticker: str
    ) -> tuple[list[OptionsRecord], dict[str, float]]:
        """
        Returns (option_records, derived_metrics).
        derived_metrics keys: iv_skew_proxy, put_call_ratio, gex_proxy
        """
        raw = await self._ohlcv.fetch_options_snapshot(ticker)
        if raw.get("calls") is None or raw.get("puts") is None:
            return [], {}

        calls_df: pl.DataFrame = raw["calls"]
        puts_df: pl.DataFrame = raw["puts"]
        expiry_str: str = raw["expiry"]

        try:
            expiry_dt = datetime.fromisoformat(expiry_str).replace(tzinfo=timezone.utc)
        except ValueError:
            expiry_dt = datetime.now(tz=timezone.utc)

        now = datetime.now(tz=timezone.utc)

        records: list[OptionsRecord] = []
        records.extend(self._parse_chain(calls_df, ticker, expiry_dt, "call", now))
        records.extend(self._parse_chain(puts_df, ticker, expiry_dt, "put", now))

        derived = self._compute_derived_metrics(calls_df, puts_df)
        records_ingested.labels(source=self.source, data_type="options").inc(len(records))

        return records, derived

    async def fetch_universe_options(
        self, tickers: list[str]
    ) -> dict[str, dict[str, float]]:
        """Fetch derived options metrics for all tickers. Used by feature service."""
        results: dict[str, dict[str, float]] = {}
        for ticker in tickers:
            try:
                _, metrics = await self.fetch_ticker_options(ticker)
                results[ticker] = metrics
                self.log.info("options_fetched", ticker=ticker, metrics=list(metrics.keys()))
            except Exception as exc:
                self.log.warning("options_skipped", ticker=ticker, error=str(exc))
                results[ticker] = {}
            await self._sleep(settings.yfinance_delay_seconds)
        return results

    async def _fetch(self, *args: Any, **kwargs: Any) -> Any:
        # Required by BaseFetcher; direct calls use fetch_ticker_options
        raise NotImplementedError("Use fetch_ticker_options directly")

    def _parse_chain(
        self,
        df: pl.DataFrame,
        ticker: str,
        expiry: datetime,
        option_type: str,
        now: datetime,
    ) -> list[OptionsRecord]:
        records = []
        required = {"strike", "lastPrice", "impliedVolatility", "openInterest", "volume"}
        if not required.issubset(set(df.columns)):
            return records

        df = df.filter(
            pl.col("impliedVolatility").is_not_null()
            & pl.col("impliedVolatility").gt(0)
            & pl.col("strike").gt(0)
        )

        for row in df.iter_rows(named=True):
            try:
                records.append(
                    OptionsRecord(
                        time=now,
                        ticker=ticker,
                        expiry=expiry,
                        strike=float(row["strike"]),
                        option_type=option_type,
                        last_price=row.get("lastPrice"),
                        implied_volatility=row.get("impliedVolatility"),
                        open_interest=int(row.get("openInterest") or 0),
                        volume=int(row.get("volume") or 0),
                        delta=row.get("delta"),
                        gamma=row.get("gamma"),
                        source="yfinance",
                    )
                )
            except (ValidationError, TypeError, ValueError):
                continue
        return records

    def _compute_derived_metrics(
        self,
        calls_df: pl.DataFrame,
        puts_df: pl.DataFrame,
    ) -> dict[str, float]:
        metrics: dict[str, float] = {}

        # ── Put/call OI ratio ──────────────────────────────────────────────
        if "openInterest" in calls_df.columns and "openInterest" in puts_df.columns:
            call_oi = calls_df["openInterest"].drop_nulls().sum()
            put_oi = puts_df["openInterest"].drop_nulls().sum()
            if call_oi > 0:
                metrics["put_call_ratio"] = round(put_oi / call_oi, 4)

        # ── IV skew proxy (OTM put IV - OTM call IV) ──────────────────────
        if "impliedVolatility" in calls_df.columns and "impliedVolatility" in puts_df.columns:
            otm_call_iv = (
                calls_df
                .filter(pl.col("impliedVolatility").gt(0))
                .sort("strike")
                .tail(5)                      # top 5 OTM calls by strike
                ["impliedVolatility"]
                .mean()
            )
            otm_put_iv = (
                puts_df
                .filter(pl.col("impliedVolatility").gt(0))
                .sort("strike")
                .head(5)                      # bottom 5 OTM puts by strike
                ["impliedVolatility"]
                .mean()
            )
            if otm_call_iv and otm_put_iv:
                metrics["iv_skew_proxy"] = round(otm_put_iv - otm_call_iv, 6)

        # ── GEX proxy (simplified) ────────────────────────────────────────
        # GEX = sum(gamma * OI * 100) for calls - sum(gamma * OI * 100) for puts
        if "gamma" in calls_df.columns and "openInterest" in calls_df.columns:
            def gex_sum(df: pl.DataFrame) -> float:
                filtered = df.filter(
                    pl.col("gamma").is_not_null() & pl.col("openInterest").is_not_null()
                )
                if filtered.is_empty():
                    return 0.0
                return float(
                    (filtered["gamma"] * filtered["openInterest"] * 100).sum()
                )

            call_gex = gex_sum(calls_df)
            put_gex = gex_sum(puts_df)
            metrics["gex_proxy"] = round(call_gex - put_gex, 2)

        return metrics
