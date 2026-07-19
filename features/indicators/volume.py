import numpy as np
import pandas as pd


def vwap(df: pd.DataFrame, period: int | None = None) -> pd.Series:
    """Volume-weighted average price. `period=None` is a cumulative (anchored) VWAP
    over the whole series; an int gives a rolling VWAP over that many bars."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical_price * df["volume"]
    if period is None:
        return pv.cumsum() / df["volume"].cumsum()
    return pv.rolling(period).sum() / df["volume"].rolling(period).sum()


def volume_profile_poc(df: pd.DataFrame, period: int = 50, bins: int = 10) -> pd.Series:
    """Rolling "point of control": the price bucket with the most traded volume over
    the trailing `period` bars, one value per bar (NaN during warmup)."""
    closes = df["close"].to_numpy()
    volumes = df["volume"].to_numpy()
    result = np.full(len(df), np.nan)

    for i in range(period - 1, len(df)):
        window_close = closes[i - period + 1 : i + 1]
        window_vol = volumes[i - period + 1 : i + 1]
        lo, hi = window_close.min(), window_close.max()
        if hi == lo:
            result[i] = lo
            continue
        bucket_edges = np.linspace(lo, hi, bins + 1)
        bucket_idx = np.clip(np.digitize(window_close, bucket_edges) - 1, 0, bins - 1)
        bucket_volume = np.zeros(bins)
        np.add.at(bucket_volume, bucket_idx, window_vol)
        poc_bucket = int(bucket_volume.argmax())
        result[i] = (bucket_edges[poc_bucket] + bucket_edges[poc_bucket + 1]) / 2

    return pd.Series(result, index=df.index)
