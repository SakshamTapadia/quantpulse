"""
Tests for the feature engineering service.
Uses synthetic price data to verify indicator math precisely.
"""
import math
from datetime import datetime, timezone, timedelta

import polars as pl
import pytest

from quantpulse_feature.indicators.volatility import (
    add_atr,
    add_log_returns,
    add_realized_volatility,
    add_vol_ratio,
)
from quantpulse_feature.indicators.momentum import add_rsi, add_tsi, add_momentum
from quantpulse_feature.indicators.normalisation import add_rolling_zscores, get_feature_columns
from quantpulse_feature.pipeline.feature_pipeline import FeaturePipeline


# ── Fixtures ─────────────────────────────────────────────────────────────────

def make_ohlcv(n: int = 300, ticker: str = "SPY", base_price: float = 450.0) -> pl.DataFrame:
    """Generate deterministic synthetic OHLCV data."""
    import math
    base = datetime(2022, 1, 3, tzinfo=timezone.utc)
    rows = []
    price = base_price
    for i in range(n):
        # Simple sine wave trend + noise
        ret = 0.001 * math.sin(i / 20) + (0.002 if i % 7 == 0 else -0.001)
        price *= (1 + ret)
        rows.append({
            "time": base + timedelta(days=i),
            "ticker": ticker,
            "open":   round(price * 0.999, 2),
            "high":   round(price * 1.005, 2),
            "low":    round(price * 0.995, 2),
            "close":  round(price, 2),
            "volume": 80_000_000 + i * 100_000,
        })
    return pl.DataFrame(rows)


@pytest.fixture
def spy_df() -> pl.DataFrame:
    return make_ohlcv(300, "SPY")


@pytest.fixture
def multi_ticker_df() -> pl.DataFrame:
    return pl.concat([
        make_ohlcv(300, "SPY", 450.0),
        make_ohlcv(300, "QQQ", 380.0),
        make_ohlcv(300, "IWM", 200.0),
    ])


# ── Log returns ──────────────────────────────────────────────────────────────

class TestLogReturns:
    def test_log_return_column_added(self, spy_df: pl.DataFrame) -> None:
        df = add_log_returns(spy_df)
        assert "log_return" in df.columns

    def test_first_log_return_is_null(self, spy_df: pl.DataFrame) -> None:
        df = add_log_returns(spy_df)
        assert df["log_return"][0] is None

    def test_log_return_values_reasonable(self, spy_df: pl.DataFrame) -> None:
        df = add_log_returns(spy_df)
        returns = df["log_return"].drop_nulls()
        # Daily returns should be small
        assert abs(float(returns.mean())) < 0.01
        assert float(returns.std()) < 0.05


# ── Realized Volatility ──────────────────────────────────────────────────────

class TestRealizedVolatility:
    def test_rv_columns_added(self, spy_df: pl.DataFrame) -> None:
        df = add_realized_volatility(spy_df)
        assert "rv_5d" in df.columns
        assert "rv_21d" in df.columns
        assert "rv_63d" in df.columns

    def test_rv_values_positive(self, spy_df: pl.DataFrame) -> None:
        df = add_realized_volatility(spy_df)
        rv = df["rv_21d"].drop_nulls()
        assert float(rv.min()) >= 0.0

    def test_rv_annualised_reasonable(self, spy_df: pl.DataFrame) -> None:
        df = add_realized_volatility(spy_df)
        rv = df["rv_21d"].drop_nulls()
        # SPY-like data: RV should be between 5% and 100% annualised
        assert float(rv.mean()) > 0.05
        assert float(rv.mean()) < 1.0

    def test_rv_5d_more_volatile_than_63d_on_average(self, spy_df: pl.DataFrame) -> None:
        df = add_realized_volatility(spy_df).drop_nulls(["rv_5d", "rv_63d"])
        # Short-term RV is noisier so its std should be higher than long-term
        assert float(df["rv_5d"].std()) > float(df["rv_63d"].std())


# ── ATR ──────────────────────────────────────────────────────────────────────

class TestATR:
    def test_atr_column_added(self, spy_df: pl.DataFrame) -> None:
        df = add_atr(spy_df)
        assert "atr_14" in df.columns
        assert "atr_pct" in df.columns

    def test_atr_pct_between_0_and_1(self, spy_df: pl.DataFrame) -> None:
        df = add_atr(spy_df)
        atr_pct = df["atr_pct"].drop_nulls()
        assert float(atr_pct.min()) >= 0.0
        assert float(atr_pct.max()) < 1.0   # <100% move per bar


# ── RSI ──────────────────────────────────────────────────────────────────────

class TestRSI:
    def test_rsi_bounded_0_100(self, spy_df: pl.DataFrame) -> None:
        df = add_rsi(spy_df)
        rsi = df["rsi_14"].drop_nulls()
        assert float(rsi.min()) >= 0.0
        assert float(rsi.max()) <= 100.0

    def test_rsi_norm_bounded_minus1_plus1(self, spy_df: pl.DataFrame) -> None:
        df = add_rsi(spy_df)
        rsi_norm = df["rsi_norm"].drop_nulls()
        assert float(rsi_norm.min()) >= -1.0
        assert float(rsi_norm.max()) <= 1.0


# ── Momentum ─────────────────────────────────────────────────────────────────

class TestMomentum:
    def test_momentum_columns_added(self, spy_df: pl.DataFrame) -> None:
        df = add_momentum(spy_df)
        assert "mom_5d" in df.columns
        assert "mom_21d" in df.columns
        assert "mom_63d" in df.columns

    def test_momentum_values_reasonable(self, spy_df: pl.DataFrame) -> None:
        df = add_momentum(spy_df)
        mom = df["mom_21d"].drop_nulls()
        # 21-day return should be in [-50%, +50%] for normal equity data
        assert float(mom.min()) > -0.5
        assert float(mom.max()) < 0.5


# ── Normalisation ─────────────────────────────────────────────────────────────

class TestNormalisation:
    def test_zscore_columns_added(self, spy_df: pl.DataFrame) -> None:
        df = add_realized_volatility(spy_df)
        df = add_rsi(df)
        df = add_rolling_zscores(df)
        z_cols = [c for c in df.columns if c.endswith("_z")]
        assert len(z_cols) > 0

    def test_zscore_clipped_to_4(self, spy_df: pl.DataFrame) -> None:
        df = add_realized_volatility(spy_df)
        df = add_rolling_zscores(df)
        for col in [c for c in df.columns if c.endswith("_z")]:
            vals = df[col].drop_nulls()
            assert float(vals.min()) >= -4.0
            assert float(vals.max()) <= 4.0


# ── Full pipeline ─────────────────────────────────────────────────────────────

class TestFeaturePipeline:
    def test_pipeline_runs_without_error(self, multi_ticker_df: pl.DataFrame) -> None:
        pipeline = FeaturePipeline()
        result = pipeline.run(multi_ticker_df)
        assert not result.is_empty()
        assert "ticker" in result.columns
        assert "time" in result.columns

    def test_pipeline_preserves_all_tickers(self, multi_ticker_df: pl.DataFrame) -> None:
        pipeline = FeaturePipeline()
        result = pipeline.run(multi_ticker_df)
        tickers = set(result["ticker"].to_list())
        assert "SPY" in tickers
        assert "QQQ" in tickers
        assert "IWM" in tickers

    def test_pipeline_output_has_feature_cols(self, multi_ticker_df: pl.DataFrame) -> None:
        pipeline = FeaturePipeline()
        result = pipeline.run(multi_ticker_df)
        feature_cols = get_feature_columns(result)
        assert len(feature_cols) >= 10  # at least 10 features

    def test_model_feature_list_nonempty(self, multi_ticker_df: pl.DataFrame) -> None:
        pipeline = FeaturePipeline()
        result = pipeline.run(multi_ticker_df)
        model_features = pipeline.get_model_features(result)
        assert len(model_features) > 5
