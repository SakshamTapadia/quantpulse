"""
MacroFetcher - pulls macroeconomic time series from the St. Louis FRED API.
All series listed in settings.fred_series are fetched and published to
the macro-data Kafka topic.

FRED's public API does not require a key for many series, but providing
FRED_API_KEY unlocks higher rate limits.
"""
from datetime import date, datetime, timezone

import httpx
import polars as pl

from quantpulse_ingestion.config import settings
from quantpulse_ingestion.fetchers.base import BaseFetcher, records_ingested
from quantpulse_ingestion.schemas import MacroRecord

_FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"


class MacroFetcher(BaseFetcher):
    source = "fred"

    def __init__(self) -> None:
        super().__init__()
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_series(
        self,
        series_id: str,
        start: date,
        end: date,
    ) -> list[MacroRecord]:
        """Fetch a single FRED series."""
        return await self.fetch_with_retry(series_id, start, end)

    async def fetch_all_series(
        self,
        start: date,
        end: date,
    ) -> list[MacroRecord]:
        """Fetch all configured macro series and return combined records."""
        all_records: list[MacroRecord] = []
        for series_id in settings.fred_series:
            try:
                records = await self.fetch_series(series_id, start, end)
                all_records.extend(records)
                self.log.info("macro_series_fetched", series=series_id, rows=len(records))
            except Exception as exc:
                self.log.warning("macro_series_failed", series=series_id, error=str(exc))
            # FRED is generous but let's be polite
            await self._sleep(0.2)
        return all_records

    async def _fetch(
        self,
        series_id: str,
        start: date,
        end: date,
    ) -> list[MacroRecord]:
        params: dict[str, str] = {
            "series_id": series_id,
            "observation_start": str(start),
            "observation_end": str(end),
            "file_type": "json",
            "sort_order": "asc",
        }
        if settings.fred_api_key:
            params["api_key"] = settings.fred_api_key

        resp = await self._client.get(_FRED_OBS_URL, params=params)
        resp.raise_for_status()

        data = resp.json()
        observations = data.get("observations", [])

        records = self._parse_observations(series_id, observations)
        records_ingested.labels(source=self.source, data_type="macro").inc(len(records))
        return records

    def _parse_observations(
        self,
        series_id: str,
        observations: list[dict],
    ) -> list[MacroRecord]:
        """
        Parse FRED observations JSON into MacroRecord list.
        FRED returns '.' for missing values - we drop those.
        """
        rows = []
        for obs in observations:
            val_str = obs.get("value", ".")
            if val_str == ".":
                continue
            try:
                rows.append({
                    "date": obs["date"],
                    "value": float(val_str),
                })
            except (ValueError, KeyError):
                continue

        if not rows:
            return []

        df = (
            pl.DataFrame(rows)
            .with_columns(
                pl.col("date").str.to_datetime("%Y-%m-%d").dt.replace_time_zone("UTC")
            )
            .sort("date")
        )

        records = []
        for row in df.iter_rows(named=True):
            dt = row["date"]
            if not isinstance(dt, datetime):
                dt = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
            records.append(
                MacroRecord(
                    time=dt,
                    series_id=series_id,
                    value=row["value"],
                    source="fred",
                )
            )
        return records

    async def fetch_vix_term_slope(self, as_of: date) -> float | None:
        """
        Convenience: compute VIX term structure slope proxy using
        VIX (30d IV) and available FRED series as a rough estimate.
        Real VIX9D vs VIX requires Cboe data; we approximate using
        the VIXCLS series rolling change as a proxy.
        Returns None if data unavailable.
        """
        try:
            records = await self.fetch_series("VIXCLS", start=date(as_of.year - 1, 1, 1), end=as_of)
            if len(records) < 2:
                return None
            df = pl.DataFrame([{"time": r.time, "vix": r.value} for r in records]).sort("time")
            recent = df.tail(20)
            slope = (recent["vix"][-1] - recent["vix"][0]) / len(recent)
            return round(slope, 4)
        except Exception:
            return None
