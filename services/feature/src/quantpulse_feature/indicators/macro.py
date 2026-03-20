"""
Macro indicators - joins FRED macro series onto the per-ticker feature frame.

Sources (all from TimescaleDB macro table, originally from FRED):
  VIXCLS        → vix (spot level)
  T10Y2Y        → yield_curve_slope (10Y - 2Y spread, bp)
  BAMLH0A0HYM2  → hy_spread (HY OAS spread, bp)
  DGS10         → rate_10y
  DGS2          → rate_2y

Derived:
  vix_term_slope  = rolling 20d change in VIX (proxy for vol term structure slope)
  vix_zscore      = rolling 252d z-score of VIX

All macro series are daily (business day frequency) and are forward-filled
to align with the per-ticker OHLCV frame.
"""
import polars as pl


# FRED series → output column name mapping
MACRO_SERIES_MAP = {
    "VIXCLS":        "vix",
    "T10Y2Y":        "yield_curve_slope",
    "BAMLH0A0HYM2":  "hy_spread",
    "DGS10":         "rate_10y",
    "DGS2":          "rate_2y",
}


def build_macro_frame(macro_df: pl.DataFrame) -> pl.DataFrame:
    """
    Pivot the long-format macro DataFrame (time, series_id, value)
    into a wide daily frame with one column per series.

    Input schema: time, series_id, value
    Output schema: date | vix | yield_curve_slope | hy_spread | rate_10y | rate_2y
    """
    # Keep only series we care about
    macro_df = macro_df.filter(pl.col("series_id").is_in(list(MACRO_SERIES_MAP.keys())))

    # Rename series_id values to friendly column names
    macro_df = macro_df.with_columns(
        pl.col("series_id").replace(MACRO_SERIES_MAP).alias("series_id")
    )

    # Pivot: one row per date, one column per series
    wide = macro_df.pivot(
        values="value",
        index="time",
        on="series_id",
        aggregate_function="last",
    ).sort("time")

    # Ensure all expected columns exist (fill missing with null)
    for col_name in MACRO_SERIES_MAP.values():
        if col_name not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Float64).alias(col_name))

    return wide


def add_macro_features(macro_wide: pl.DataFrame) -> pl.DataFrame:
    """
    Add derived macro features to the wide macro frame.
    Returns enriched frame ready to join onto per-ticker OHLCV frames.
    """
    # Forward-fill sparse series so rolling windows don't get poisoned by a
    # single null (e.g. VIX is null on US holidays when bond markets trade).
    fill_cols = [c for c in ["vix", "hy_spread", "yield_curve_slope", "rate_10y", "rate_2y"]
                 if c in macro_wide.columns]
    if fill_cols:
        macro_wide = macro_wide.with_columns([pl.col(c).forward_fill() for c in fill_cols])

    macro_wide = macro_wide.with_columns([
        # VIX 20-day rolling change (term slope proxy)
        (pl.col("vix") - pl.col("vix").shift(20)).alias("vix_term_slope"),

        # VIX z-score (252-day rolling)
        (
            (pl.col("vix") - pl.col("vix").rolling_mean(window_size=252))
            / pl.col("vix").rolling_std(window_size=252).clip(lower_bound=1e-8)
        ).clip(lower_bound=-4.0, upper_bound=4.0).alias("vix_zscore"),

        # Yield curve inversion flag
        (pl.col("yield_curve_slope") < 0).cast(pl.Float64).alias("yc_inverted"),

        # HY spread z-score (252-day)
        (
            (pl.col("hy_spread") - pl.col("hy_spread").rolling_mean(window_size=252))
            / pl.col("hy_spread").rolling_std(window_size=252).clip(lower_bound=1e-8)
        ).clip(lower_bound=-4.0, upper_bound=4.0).alias("hy_spread_zscore"),
    ])

    return macro_wide


def join_macro_to_ticker(
    ticker_df: pl.DataFrame,
    macro_wide: pl.DataFrame,
) -> pl.DataFrame:
    """
    Left-join macro features onto a per-ticker OHLCV frame by date.
    Uses as-of join (forward-fill) to handle macro series published
    with a one-day lag (FRED publishes next day).

    ticker_df must have column: time (Datetime UTC)
    macro_wide must have column: time (Datetime UTC)
    """
    macro_cols = [
        "vix", "yield_curve_slope", "hy_spread",
        "vix_term_slope", "vix_zscore", "yc_inverted", "hy_spread_zscore",
    ]
    available = [c for c in macro_cols if c in macro_wide.columns]

    # Truncate both to date for join key
    ticker_keyed = ticker_df.with_columns(
        pl.col("time").dt.date().alias("_date")
    )
    macro_keyed = macro_wide.with_columns(
        pl.col("time").dt.date().alias("_date")
    ).select(["_date"] + available)

    joined = ticker_keyed.join(macro_keyed, on="_date", how="left").drop("_date")

    # Forward-fill macro values (handles weekends, holidays, publication lags)
    joined = joined.with_columns([
        pl.col(c).forward_fill().over("ticker") for c in available if c in joined.columns
    ])

    return joined
