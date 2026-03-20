"""
Pydantic v2 schemas for all data coming out of the ingestion layer.
These are the canonical shapes published to Kafka and written to TimescaleDB.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class OHLCVRecord(BaseModel):
    time: datetime
    ticker: str
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: int = Field(ge=0)
    vwap: float | None = None
    source: Literal["yfinance", "polygon"] = "yfinance"

    @field_validator("high")
    @classmethod
    def high_gte_low(cls, v: float, info: object) -> float:
        data = getattr(info, "data", {})
        low = data.get("low")
        if low is not None and v < low:
            raise ValueError(f"high ({v}) must be >= low ({low})")
        return v

    @field_validator("ticker")
    @classmethod
    def ticker_upper(cls, v: str) -> str:
        return v.upper().strip()


class MacroRecord(BaseModel):
    time: datetime
    series_id: str          # e.g. "VIXCLS"
    value: float
    source: Literal["fred", "yfinance"] = "fred"


class OptionsRecord(BaseModel):
    time: datetime
    ticker: str
    expiry: datetime
    strike: float = Field(gt=0)
    option_type: Literal["call", "put"]
    last_price: float | None = None
    implied_volatility: float | None = Field(default=None, ge=0)
    open_interest: int | None = Field(default=None, ge=0)
    volume: int | None = Field(default=None, ge=0)
    delta: float | None = None
    gamma: float | None = None
    source: Literal["yfinance", "polygon"] = "yfinance"

    @field_validator("ticker")
    @classmethod
    def ticker_upper(cls, v: str) -> str:
        return v.upper().strip()


class IngestionBatch(BaseModel):
    """Envelope published to Kafka - carries metadata alongside records."""
    batch_id: str
    ingested_at: datetime
    source: str
    record_count: int
    records: list[OHLCVRecord] | list[MacroRecord] | list[OptionsRecord]
