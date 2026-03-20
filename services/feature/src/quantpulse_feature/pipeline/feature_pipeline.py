"""
FeaturePipeline — orchestrates the full indicator computation chain.

Execution order:
  1.  log_returns
  2.  realized_vol  (RV 5/21/63d)
  3.  vol_ratio     (rv_5d / rv_63d)
  4.  atr           (ATR-14, atr_pct)
  5.  normalised_vol (rv_21d z-score)
  6.  rsi           (RSI-14, rsi_norm)
  7.  tsi           (TSI + signal)
  8.  momentum      (ROC 5/21/63d)
  9.  trend_strength (rolling correlation R)
  10. macro join     (VIX, yield curve, HY spread, derived)
  11. options join   (iv_skew_proxy, put_call_ratio, gex_proxy)
  12. z-scores       (rolling normalisation on all eligible columns)
  13. null filter    (drop rows with insufficient history)
"""
import polars as pl
import structlog

from quantpulse_feature.indicators.volatility import (
    add_atr,
    add_log_returns,
    add_normalised_vol,
    add_realized_volatility,
    add_vol_ratio,
)
from quantpulse_feature.indicators.momentum import (
    add_momentum,
    add_rsi,
    add_trend_strength,
    add_tsi,
)
from quantpulse_feature.indicators.macro import (
    add_macro_features,
    build_macro_frame,
    join_macro_to_ticker,
)
from quantpulse_feature.indicators.normalisation import (
    add_rolling_zscores,
    get_feature_columns,
)

logger = structlog.get_logger(__name__)


class FeaturePipeline:
    """Stateless pipeline — call .run() with raw DataFrames, get feature matrix."""

    def run(
        self,
        ohlcv_df: pl.DataFrame,
        macro_df: pl.DataFrame | None = None,
        options_metrics: dict[str, dict[str, float]] | None = None,
        normalise: bool = True,
    ) -> pl.DataFrame:
        log = logger.bind(tickers=ohlcv_df["ticker"].n_unique(), rows=len(ohlcv_df))
        log.info("pipeline_start")

        df = ohlcv_df.sort(["ticker", "time"])

        # ── Price-based indicators ───────────────────────────────────────────
        df = add_log_returns(df)
        df = add_realized_volatility(df)
        df = add_vol_ratio(df)
        df = add_atr(df)
        df = add_normalised_vol(df)
        df = add_rsi(df)
        df = add_tsi(df)
        df = add_momentum(df)
        df = add_trend_strength(df)

        # ── Macro overlay ────────────────────────────────────────────────────
        if macro_df is not None and not macro_df.is_empty():
            macro_wide = build_macro_frame(macro_df)
            macro_wide = add_macro_features(macro_wide)
            df = join_macro_to_ticker(df, macro_wide)
            log.info("macro_joined", macro_rows=len(macro_wide))
        else:
            log.warning("macro_skipped", reason="no macro data provided")

        # ── Options metrics ──────────────────────────────────────────────────
        if options_metrics:
            df = self._join_options_metrics(df, options_metrics)
            log.info("options_joined", tickers=len(options_metrics))

        # ── Z-score normalisation ────────────────────────────────────────────
        if normalise:
            df = add_rolling_zscores(df)

        # ── Drop rows with insufficient history ──────────────────────────────
        feature_cols = get_feature_columns(df)
        min_non_null = int(len(feature_cols) * 0.8)
        df = df.filter(
            pl.sum_horizontal([
                pl.col(c).is_not_null().cast(pl.Int8) for c in feature_cols
            ]) >= min_non_null
        )

        log.info("pipeline_complete", output_rows=len(df), feature_cols=len(feature_cols))
        return df

    def _join_options_metrics(
        self,
        df: pl.DataFrame,
        options_metrics: dict[str, dict[str, float]],
    ) -> pl.DataFrame:
        rows = [
            {
                "ticker":         ticker.upper(),
                "iv_skew_proxy":  metrics.get("iv_skew_proxy"),
                "put_call_ratio": metrics.get("put_call_ratio"),
                "gex_proxy":      metrics.get("gex_proxy"),
            }
            for ticker, metrics in options_metrics.items()
        ]
        if not rows:
            return df
        opts_df = pl.DataFrame(rows, schema={
            "ticker":         pl.Utf8,
            "iv_skew_proxy":  pl.Float64,
            "put_call_ratio": pl.Float64,
            "gex_proxy":      pl.Float64,
        })
        return df.join(opts_df, on="ticker", how="left")

    def get_model_features(self, df: pl.DataFrame) -> list[str]:
        """Return the final feature list for the regime ML model."""
        z_cols = get_feature_columns(df, normalised_only=True)
        passthrough = [
            "rsi_norm", "tsi", "rv_ratio", "put_call_ratio",
            "trend_r", "yc_inverted", "vix_zscore", "hy_spread_zscore",
        ]
        supplement = [c for c in passthrough if c in df.columns]
        return sorted(set(z_cols + supplement))
