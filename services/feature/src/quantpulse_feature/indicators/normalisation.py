"""
Normalisation - rolling z-score for all numeric feature columns.

Why rolling z-score (not global)?
  Financial data is non-stationary. A z-score computed on a fixed
  historical window will drift as market regimes change. Rolling z-score
  with a 252-day window captures the local distribution of each feature,
  making features comparable across different market eras.

Strategy:
  For each feature column F and each ticker:
    z_F = (F - rolling_mean(F, W)) / rolling_std(F, W)
  Clipped to [-4, 4] to limit outlier influence on the ML model.

Columns explicitly excluded from z-scoring:
  - time, ticker (identifiers)
  - boolean / flag columns (yc_inverted)
  - already-normalised columns (rsi_norm, tsi - already scaled)
  - ratio columns that have natural scale (rv_ratio, put_call_ratio)
"""
import polars as pl

from quantpulse_feature.config import settings

# Columns that should NOT be z-scored
_SKIP_NORMALISE = frozenset({
    "time", "ticker",
    "rsi_norm",          # already in [-1, 1]
    "tsi",               # already oscillator
    "tsi_signal",
    "rv_ratio",          # already a ratio
    "put_call_ratio",    # already a ratio
    "yc_inverted",       # boolean flag
    "trend_r",           # already in [-1, 1]
    "vix_zscore",        # already z-scored
    "hy_spread_zscore",  # already z-scored
    "rv_21d_zscore",     # already z-scored
})


def add_rolling_zscores(
    df: pl.DataFrame,
    window: int | None = None,
    clip: float = 4.0,
) -> pl.DataFrame:
    """
    Add z-scored versions of all eligible numeric feature columns.
    New columns are named: {original}_z  (e.g. rv_5d_z, vix_z).

    Args:
        df:     Feature DataFrame with ticker column for grouping.
        window: Rolling window in bars. Defaults to settings.normalisation_window.
        clip:   Clip z-scores to [-clip, clip].
    """
    w = window or settings.normalisation_window

    numeric_cols = [
        c for c in df.columns
        if df[c].dtype in (pl.Float32, pl.Float64, pl.Int32, pl.Int64)
        and c not in _SKIP_NORMALISE
    ]

    zscore_exprs = []
    for col in numeric_cols:
        mean_col = f"_mean_{col}"
        std_col  = f"_std_{col}"
        zscore_exprs += [
            pl.col(col).rolling_mean(window_size=w).over("ticker").alias(mean_col),
            pl.col(col).rolling_std(window_size=w).over("ticker").alias(std_col),
        ]

    df = df.with_columns(zscore_exprs)

    final_exprs = []
    drop_cols = []
    for col in numeric_cols:
        mean_col = f"_mean_{col}"
        std_col  = f"_std_{col}"
        final_exprs.append(
            (
                (pl.col(col) - pl.col(mean_col))
                / pl.col(std_col).clip(lower_bound=1e-8)
            )
            .clip(lower_bound=-clip, upper_bound=clip)
            .alias(f"{col}_z")
        )
        drop_cols += [mean_col, std_col]

    df = df.with_columns(final_exprs).drop(drop_cols)
    return df


def get_feature_columns(df: pl.DataFrame, normalised_only: bool = False) -> list[str]:
    """
    Return the list of feature column names (excluding identifiers and temps).
    If normalised_only=True, returns only the _z suffixed columns.
    """
    exclude = {"time", "ticker", "open", "high", "low", "close", "volume",
               "log_return", "vwap", "source"}
    cols = [c for c in df.columns if c not in exclude and not c.startswith("_")]
    if normalised_only:
        cols = [c for c in cols if c.endswith("_z")]
    return cols
