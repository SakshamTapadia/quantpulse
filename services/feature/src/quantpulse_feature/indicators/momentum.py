"""
Momentum indicators - pure Polars expressions.

RSI (Relative Strength Index, Wilder smoothing):
  RSI = 100 - 100 / (1 + avg_gain / avg_loss)
  Uses EWM with alpha = 1/period (equivalent to Wilder smoothing).
  Normalised to [-1, 1]: rsi_norm = (RSI - 50) / 50

TSI (True Strength Index):
  TSI = 100 * EWM(EWM(price_change, slow), fast)
            / EWM(EWM(|price_change|, slow), fast)
  Oscillates around zero; positive = bullish momentum.

Price Momentum (ROC - Rate of Change):
  mom_N = (close / close.shift(N)) - 1
  Windows: 5, 21, 63 days.

Trend Strength (linear regression R² proxy):
  A simple rolling correlation between price and time index.
  Values near 1 = strong trend; near 0 = choppy/random.
"""
import polars as pl

from quantpulse_feature.config import settings


def add_rsi(df: pl.DataFrame) -> pl.DataFrame:
    """
    RSI with Wilder smoothing (EWM, alpha=1/period).
    Output: rsi_14 (0-100), rsi_norm (-1 to 1).
    """
    period = settings.rsi_period
    alpha = 1.0 / period

    df = df.with_columns(
        pl.col("close").diff().over("ticker").alias("_delta")
    ).with_columns([
        pl.col("_delta").clip(lower_bound=0).alias("_gain"),
        (-pl.col("_delta")).clip(lower_bound=0).alias("_loss"),
    ]).with_columns([
        pl.col("_gain").ewm_mean(alpha=alpha, adjust=False).over("ticker").alias("_avg_gain"),
        pl.col("_loss").ewm_mean(alpha=alpha, adjust=False).over("ticker").alias("_avg_loss"),
    ]).with_columns(
        (
            100.0 - 100.0 / (
                1.0 + pl.col("_avg_gain") / pl.col("_avg_loss").clip(lower_bound=1e-10)
            )
        ).alias("rsi_14")
    ).with_columns(
        ((pl.col("rsi_14") - 50.0) / 50.0).alias("rsi_norm")
    ).drop(["_delta", "_gain", "_loss", "_avg_gain", "_avg_loss"])

    return df


def add_tsi(df: pl.DataFrame) -> pl.DataFrame:
    """
    True Strength Index.
    Output: tsi (unbounded, typically -100 to 100), tsi_signal (EWM of tsi).
    """
    fast   = settings.tsi_fast    # 13
    slow   = settings.tsi_slow    # 25
    signal = settings.tsi_signal  # 7

    df = df.with_columns(
        pl.col("close").diff().over("ticker").alias("_pc")
    ).with_columns([
        pl.col("_pc").ewm_mean(span=slow, adjust=False).over("ticker").alias("_pc_slow"),
        pl.col("_pc").abs().ewm_mean(span=slow, adjust=False).over("ticker").alias("_apc_slow"),
    ]).with_columns([
        pl.col("_pc_slow").ewm_mean(span=fast, adjust=False).over("ticker").alias("_pc_double"),
        pl.col("_apc_slow").ewm_mean(span=fast, adjust=False).over("ticker").alias("_apc_double"),
    ]).with_columns(
        (
            100.0 * pl.col("_pc_double")
            / pl.col("_apc_double").clip(lower_bound=1e-10)
        ).alias("tsi")
    ).with_columns(
        pl.col("tsi")
        .ewm_mean(span=signal, adjust=False)
        .over("ticker")
        .alias("tsi_signal")
    ).drop(["_pc", "_pc_slow", "_apc_slow", "_pc_double", "_apc_double"])

    return df


def add_momentum(df: pl.DataFrame) -> pl.DataFrame:
    """
    Rate-of-change momentum at 5d, 21d, 63d.
    Values are decimal returns (not percentages).
    """
    windows = [5, 21, 63]
    exprs = []
    for w in windows:
        exprs.append(
            (pl.col("close") / pl.col("close").shift(w).over("ticker") - 1.0)
            .alias(f"mom_{w}d")
        )
    return df.with_columns(exprs)


def add_trend_strength(df: pl.DataFrame, window: int = 21) -> pl.DataFrame:
    """
    Rolling Pearson correlation between close price and a time index
    as a proxy for trend linearity.
    Result: trend_r  ∈ [-1, 1]
      +1 = perfect uptrend, -1 = perfect downtrend, 0 = no trend / choppy.
    """
    # Polars doesn't have rolling_corr natively, so we compute manually
    # using rolling cov / (rolling std_x * rolling std_y).
    # The time index increments by 1 each bar - its rolling std is constant
    # for a fixed window, so we can use a simplified form.
    df = df.with_columns(
        pl.int_range(pl.len()).over("ticker").cast(pl.Float64).alias("_t_idx")
    )

    df = df.with_columns([
        pl.col("close").rolling_mean(window_size=window).over("ticker").alias("_close_mean"),
        pl.col("_t_idx").rolling_mean(window_size=window).over("ticker").alias("_t_mean"),
    ]).with_columns([
        (pl.col("close") - pl.col("_close_mean")).alias("_dc"),
        (pl.col("_t_idx") - pl.col("_t_mean")).alias("_dt"),
    ]).with_columns([
        (pl.col("_dc") * pl.col("_dt")).rolling_mean(window_size=window).over("ticker").alias("_cov"),
        (pl.col("_dc") ** 2).rolling_mean(window_size=window).over("ticker").alias("_var_c"),
        (pl.col("_dt") ** 2).rolling_mean(window_size=window).over("ticker").alias("_var_t"),
    ]).with_columns(
        (
            pl.col("_cov")
            / (
                (pl.col("_var_c") * pl.col("_var_t")).sqrt()
                .clip(lower_bound=1e-10)
            )
        )
        .clip(lower_bound=-1.0, upper_bound=1.0)
        .alias("trend_r")
    ).drop(["_t_idx", "_close_mean", "_t_mean", "_dc", "_dt", "_cov", "_var_c", "_var_t"])

    return df
