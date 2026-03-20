"""Shared Pydantic models reused across all QuantPulse services."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class OHLCVRecord(BaseModel):
    time: datetime
    ticker: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str = "yfinance"


class MacroRecord(BaseModel):
    time: datetime
    series_id: str
    value: float
    source: str = "fred"


class RegimeSignal(BaseModel):
    time: datetime
    ticker: str
    regime: int = Field(ge=0, le=3)
    regime_name: Literal["trending", "mean_reverting", "choppy", "high_vol"]
    confidence: float = Field(ge=0.0, le=1.0)
    hmm_prob: list[float]
    transformer_prob: list[float]
    ensemble_prob: list[float]
    model_version: str = "latest"


class AlertEvent(BaseModel):
    time: datetime
    ticker: str | None
    alert_type: str
    severity: int = Field(ge=1, le=3)
    payload: dict
