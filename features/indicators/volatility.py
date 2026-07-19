import pandas as pd

from features.indicators._shared import true_range, wilder_smooth


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return wilder_smooth(true_range(df), period)


def atr_percentile(df: pd.DataFrame, period: int = 14, lookback: int = 100) -> pd.Series:
    """Where the current ATR sits within its own trailing distribution — used by
    market_regime for high/low volatility classification."""
    atr_series = atr(df, period)
    return atr_series.rolling(lookback).rank(pct=True) * 100


def bollinger_bands(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return pd.DataFrame({"upper": mid + num_std * std, "mid": mid, "lower": mid - num_std * std})
