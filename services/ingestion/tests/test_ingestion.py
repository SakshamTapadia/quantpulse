"""
Tests for the ingestion service.
Mocks yfinance and FRED calls - no external network required.
"""
import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import polars as pl
import pytest

from quantpulse_ingestion.fetchers.ohlcv import OHLCVFetcher
from quantpulse_ingestion.fetchers.macro import MacroFetcher
from quantpulse_ingestion.schemas import MacroRecord, OHLCVRecord


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_ohlcv_df() -> pd.DataFrame:
    return pd.DataFrame({
        "Date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"], utc=True),
        "Open":   [470.0, 472.0, 468.0],
        "High":   [475.0, 476.0, 473.0],
        "Low":    [469.0, 471.0, 465.0],
        "Close":  [474.0, 473.0, 471.0],
        "Volume": [80_000_000, 75_000_000, 90_000_000],
    }).set_index("Date")


@pytest.fixture
def sample_fred_response() -> dict:
    return {
        "observations": [
            {"date": "2024-01-02", "value": "13.45"},
            {"date": "2024-01-03", "value": "13.20"},
            {"date": "2024-01-04", "value": "."},    # missing - should be dropped
            {"date": "2024-01-05", "value": "14.00"},
        ]
    }


# ── OHLCVRecord schema ───────────────────────────────────────────────────────

class TestOHLCVRecord:
    def test_valid_record(self) -> None:
        r = OHLCVRecord(
            time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            ticker="spy",
            open=470.0, high=475.0, low=469.0, close=474.0,
            volume=80_000_000,
        )
        assert r.ticker == "SPY"   # ticker_upper validator

    def test_ticker_normalised_to_uppercase(self) -> None:
        r = OHLCVRecord(
            time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            ticker="aapl ",
            open=180.0, high=182.0, low=179.0, close=181.0,
            volume=50_000_000,
        )
        assert r.ticker == "AAPL"

    def test_high_lt_low_raises(self) -> None:
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            OHLCVRecord(
                time=datetime(2024, 1, 2, tzinfo=timezone.utc),
                ticker="SPY",
                open=470.0, high=460.0, low=469.0, close=461.0,
                volume=1_000,
            )

    def test_negative_volume_raises(self) -> None:
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            OHLCVRecord(
                time=datetime(2024, 1, 2, tzinfo=timezone.utc),
                ticker="SPY",
                open=470.0, high=475.0, low=469.0, close=474.0,
                volume=-100,
            )


# ── OHLCVFetcher ─────────────────────────────────────────────────────────────

class TestOHLCVFetcher:
    @pytest.mark.asyncio
    async def test_fetch_ticker_returns_records(self, sample_ohlcv_df: pd.DataFrame) -> None:
        fetcher = OHLCVFetcher()
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = sample_ohlcv_df
            records = await fetcher.fetch_ticker(
                "SPY", start=date(2024, 1, 2), end=date(2024, 1, 5)
            )
        assert len(records) == 3
        assert all(isinstance(r, OHLCVRecord) for r in records)
        assert records[0].ticker == "SPY"
        assert records[0].close == pytest.approx(474.0)

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_list(self) -> None:
        fetcher = OHLCVFetcher()
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = pd.DataFrame()
            records = await fetcher.fetch_ticker(
                "INVALID", start=date(2024, 1, 2), end=date(2024, 1, 5)
            )
        assert records == []

    @pytest.mark.asyncio
    async def test_fetch_universe_skips_failed_tickers(self) -> None:
        fetcher = OHLCVFetcher()
        call_count = 0

        async def fake_fetch(ticker: str, *args, **kwargs) -> list:
            nonlocal call_count
            call_count += 1
            if ticker == "BAD":
                raise ConnectionError("network error")
            return [MagicMock(spec=OHLCVRecord)]

        fetcher.fetch_ticker = fake_fetch  # type: ignore[method-assign]
        results = await fetcher.fetch_universe(
            ["SPY", "BAD", "QQQ"],
            start=date(2024, 1, 2),
            end=date(2024, 1, 5),
        )
        assert "SPY" in results
        assert "BAD" in results
        assert results["BAD"] == []
        assert call_count == 3


# ── MacroFetcher ─────────────────────────────────────────────────────────────

class TestMacroFetcher:
    @pytest.mark.asyncio
    async def test_parse_drops_missing_values(self, sample_fred_response: dict) -> None:
        fetcher = MacroFetcher()
        records = fetcher._parse_observations("VIXCLS", sample_fred_response["observations"])
        # "." value should be dropped
        assert len(records) == 3
        assert all(isinstance(r, MacroRecord) for r in records)
        assert records[0].series_id == "VIXCLS"
        assert records[0].value == pytest.approx(13.45)

    @pytest.mark.asyncio
    async def test_fetch_series_calls_fred(self, sample_fred_response: dict) -> None:
        import httpx
        fetcher = MacroFetcher()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = sample_fred_response

        with patch.object(fetcher._client, "get", new=AsyncMock(return_value=mock_response)):
            records = await fetcher.fetch_series(
                "VIXCLS", start=date(2024, 1, 2), end=date(2024, 1, 5)
            )

        assert len(records) == 3
