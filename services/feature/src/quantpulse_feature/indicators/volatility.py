"""
Volatility indicators — all implemented as pure Polars expressions.

Realized Volatility (RV):
  RV_n = sqrt(252) * std(log_returns, window=n)
  Annualised, based on close-to-close log returns.

ATR (Average True Range):
  TR  = max(high-low, |high-prev_close|, |low-prev_close|)
  ATR = EWM(TR, span=period)

Vol Ratio:
  rv_5d / rv_63d — short-term vs long-term vol compression signal.
  > 1  →  vol expanding (trending / crisis)
  < 1  →  vol compressed (mean-reverting / low-vol regime)

All functions accept a Polars DataFrame with columns:
  [time, ticker, open, high, low, close, volume]
and return the same DataFrame with additional columns appended.
"""
import polars as pl

from quantpulse_feature.config import settings


def add_log_returns(df: pl.DataFrame) -> pl.DataFrame:
    """Add log_return column (close-to-close)."""
    return df.with_columns(
        pl.col("close")
        .log()
        .diff()
        .over("ticker")
        .alias("log_return")
    )


def add_realized_volatility(df: pl.DataFrame) -> pl.DataFrame:
    """
    Add RV columns for each window in settings.rv_windows.
    Output columns: rv_5d, rv_21d, rv_63d (annualised, as decimals).
    """
    if "log_return" not in df.columns:
        df = add_log_returns(df)

    exprs = []
    for window in settings.rv_windows:
        exprs.append(
            (
                pl.col("log_return")
                .rolling_std(window_size=window)
                .over("ticker")
                * (252 ** 0.5)
            ).alias(f"rv_{window}d")
        )
    return df.with_columns(exprs)


def add_vol_ratio(df: pl.DataFrame) -> pl.DataFrame:
    """
    rv_ratio = rv_5d / rv_63d.
    Values > 1.5 signal vol expansion; < 0.5 signal extreme compression.
    Clipped to [0.1, 5.0] to prevent outlier blowups.
    """
    short_col = f"rv_{settings.rv_windows[0]}d"   # rv_5d
    long_col  = f"rv_{settings.rv_windows[-1]}d"  # rv_63d

    for col in [short_col, long_col]:
        if col not in df.columns:
            df = add_realized_volatility(df)
            break

    return df.with_columns(
        (pl.col(short_col) / pl.col(long_col).clip(lower_bound=1e-8))
        .clip(lower_bound=0.1, upper_bound=5.0)
        .alias("rv_ratio")
    )


def add_atr(df: pl.DataFrame) -> pl.DataFrame:
    """
    Average True Range using EWM (exponentially weighted).
    Normalised by close price to make it scale-invariant: atr_pct = ATR / close.
    """
    period = settings.atr_period
    return df.with_columns([
        # True Range components
        (pl.col("high") - pl.col("low")).alias("_tr1"),
        (pl.col("high") - pl.col("close").shift(1).over("ticker")).abs().alias("_tr2"),
        (pl.col("low")  - pl.col("close").shift(1).over("ticker")).abs().alias("_tr3"),
    ]).with_columns(
        pl.max_horizontal("_tr1", "_tr2", "_tr3").alias("_tr")
    ).with_columns(
        pl.col("_tr")
        .ewm_mean(span=period)
        .over("ticker")
        .alias("atr_14")
    ).with_columns(
        (pl.col("atr_14") / pl.col("close"))
        .alias("atr_pct")
    ).drop(["_tr1", "_tr2", "_tr3", "_tr"])


def add_normalised_vol(df: pl.DataFrame, window: int | None = None) -> pl.DataFrame:
    """
    Rolling z-score normalisation of rv_21d.
    z = (rv_21d - rolling_mean) / rolling_std
    Window defaults to settings.normalisation_window (252 trading days).
    Clipped to [-4, 4] to handle outliers gracefully.
    """
    w = window or settings.normalisation_window
    if "rv_21d" not in df.columns:
        df = add_realized_volatility(df)

    return df.with_columns([
        pl.col("rv_21d").rolling_mean(window_size=w).over("ticker").alias("_rv_mean"),
        pl.col("rv_21d").rolling_std(window_size=w).over("ticker").alias("_rv_std"),
    ]).with_columns(
        (
            (pl.col("rv_21d") - pl.col("_rv_mean"))
            / pl.col("_rv_std").clip(lower_bound=1e-8)
        )
        .clip(lower_bound=-4.0, upper_bound=4.0)
        .alias("rv_21d_zscore")
    ).drop(["_rv_mean", "_rv_std"])
