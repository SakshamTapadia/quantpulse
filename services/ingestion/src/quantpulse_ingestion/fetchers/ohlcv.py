"""
OHLCVFetcher - pulls price data from yfinance, normalises to Polars,
validates with Pydantic, and returns clean OHLCVRecord lists.

yfinance is synchronous; we run it in a thread pool to keep the
event loop unblocked.
"""
import asyncio
from datetime import date, datetime, timezone
from typing import Any

import polars as pl
import yfinance as yf
from pydantic import ValidationError

from quantpulse_ingestion.config import settings
from quantpulse_ingestion.fetchers.base import BaseFetcher, records_ingested
from quantpulse_ingestion.schemas import OHLCVRecord


class OHLCVFetcher(BaseFetcher):
    source = "yfinance"

    # Polars schema we enforce after fetching
    _EXPECTED_COLS = {"Open", "High", "Low", "Close", "Volume"}

    async def fetch_ticker(
        self,
        ticker: str,
        start: date,
        end: date,
        interval: str = "1d",
    ) -> list[OHLCVRecord]:
        """Fetch OHLCV for a single ticker between start and end dates."""
        return await self.fetch_with_retry(ticker, start, end, interval)

    async def fetch_universe(
        self,
        tickers: list[str],
        start: date,
        end: date,
        interval: str = "1d",
    ) -> dict[str, list[OHLCVRecord]]:
        """
        Fetch all tickers with a polite delay between each call.
        Returns a dict of ticker -> records (empty list on failure).
        """
        results: dict[str, list[OHLCVRecord]] = {}
        for ticker in tickers:
            try:
                records = await self.fetch_ticker(ticker, start, end, interval)
                results[ticker] = records
                self.log.info("ticker_fetched", ticker=ticker, rows=len(records))
            except Exception as exc:
                self.log.warning("ticker_skipped", ticker=ticker, error=str(exc))
                results[ticker] = []
            await self._sleep(settings.yfinance_delay_seconds)
        return results

    async def _fetch(
        self,
        ticker: str,
        start: date,
        end: date,
        interval: str,
    ) -> list[OHLCVRecord]:
        loop = asyncio.get_running_loop()
        # Run blocking yfinance call in thread pool
        raw = await loop.run_in_executor(
            None,
            lambda: self._yf_download(ticker, str(start), str(end), interval),
        )
        if raw is None or raw.is_empty():
            self.log.warning("empty_response", ticker=ticker)
            return []

        records = self._to_records(raw, ticker)
        records_ingested.labels(source=self.source, data_type="ohlcv").inc(len(records))
        return records

    @staticmethod
    def _yf_download(ticker: str, start: str, end: str, interval: str) -> pl.DataFrame | None:
        """Synchronous yfinance download → Polars DataFrame."""
        yf_ticker = yf.Ticker(ticker)
        hist = yf_ticker.history(start=start, end=end, interval=interval, auto_adjust=True)
        if hist.empty:
            return None

        # Convert pandas → polars
        df = pl.from_pandas(hist.reset_index())

        # Normalise column names (yfinance sometimes returns multiindex)
        df = df.rename({c: c.strip().title() for c in df.columns})

        # Keep only what we need
        available = set(df.columns)
        needed = OHLCVFetcher._EXPECTED_COLS | {"Date", "Datetime"}
        df = df.select([c for c in df.columns if c in needed])

        # Rename date column
        if "Datetime" in df.columns:
            df = df.rename({"Datetime": "Date"})

        return df

    def _to_records(self, df: pl.DataFrame, ticker: str) -> list[OHLCVRecord]:
        """Convert a normalised Polars DataFrame to validated OHLCVRecord list."""
        records: list[OHLCVRecord] = []

        # Ensure correct types
        df = (
            df
            .with_columns([
                pl.col("Date").cast(pl.Datetime("us", "UTC")),
                pl.col("Open").cast(pl.Float64),
                pl.col("High").cast(pl.Float64),
                pl.col("Low").cast(pl.Float64),
                pl.col("Close").cast(pl.Float64),
                pl.col("Volume").cast(pl.Int64),
            ])
            .sort("Date")
            .unique(subset=["Date"], keep="last")
            .drop_nulls(subset=["Open", "High", "Low", "Close"])
        )

        for row in df.iter_rows(named=True):
            try:
                dt = row["Date"]
                if not isinstance(dt, datetime):
                    dt = datetime.combine(dt, datetime.min.time(), tzinfo=timezone.utc)

                record = OHLCVRecord(
                    time=dt,
                    ticker=ticker,
                    open=row["Open"],
                    high=row["High"],
                    low=row["Low"],
                    close=row["Close"],
                    volume=int(row["Volume"]),
                    vwap=row.get("Vwap"),
                    source="yfinance",
                )
                records.append(record)
            except (ValidationError, KeyError, TypeError) as exc:
                self.log.warning("record_validation_failed", ticker=ticker, error=str(exc))

        return records

    async def fetch_options_snapshot(self, ticker: str) -> dict[str, Any]:
        """
        Fetch the latest options chain for IV and put/call ratio computation.
        Returns raw options data; OptionsFetcher processes it further.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._yf_options(ticker),
        )

    @staticmethod
    def _yf_options(ticker: str) -> dict[str, Any]:
        yf_ticker = yf.Ticker(ticker)
        expirations = yf_ticker.options
        if not expirations:
            return {"ticker": ticker, "calls": None, "puts": None}

        # Take the nearest expiry (most liquid)
        nearest = expirations[0]
        chain = yf_ticker.option_chain(nearest)
        return {
            "ticker": ticker,
            "expiry": nearest,
            "calls": pl.from_pandas(chain.calls) if not chain.calls.empty else None,
            "puts": pl.from_pandas(chain.puts) if not chain.puts.empty else None,
        }
