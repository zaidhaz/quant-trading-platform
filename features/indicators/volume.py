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


def volume_profile_value_area(
    df: pd.DataFrame, period: int = 50, bins: int = 10, value_area_pct: float = 0.70
) -> pd.DataFrame:
    """Rolling Value Area High/Low: starting from the POC bucket, expand
    outward adding whichever neighboring bucket (above or below the area so
    far) holds more volume, until the accumulated volume covers
    `value_area_pct` of the window's total (70% is the standard Market
    Profile convention). VAH/VAL are the top/bottom edges of the resulting
    bucket range. NaN during warmup, same convention as `volume_profile_poc`,
    which this shares its bucketing with (kept as a separate rolling loop
    rather than refactored to share state, to keep both functions
    independently readable and testable)."""
    closes = df["close"].to_numpy()
    volumes = df["volume"].to_numpy()
    vah = np.full(len(df), np.nan)
    val = np.full(len(df), np.nan)

    for i in range(period - 1, len(df)):
        window_close = closes[i - period + 1 : i + 1]
        window_vol = volumes[i - period + 1 : i + 1]
        lo, hi = window_close.min(), window_close.max()
        if hi == lo:
            vah[i] = val[i] = lo
            continue
        bucket_edges = np.linspace(lo, hi, bins + 1)
        bucket_idx = np.clip(np.digitize(window_close, bucket_edges) - 1, 0, bins - 1)
        bucket_volume = np.zeros(bins)
        np.add.at(bucket_volume, bucket_idx, window_vol)

        total_volume = bucket_volume.sum()
        if total_volume <= 0:
            continue

        poc_bucket = int(bucket_volume.argmax())
        lower, upper = poc_bucket, poc_bucket
        covered = bucket_volume[poc_bucket]
        target = value_area_pct * total_volume
        while covered < target and (lower > 0 or upper < bins - 1):
            vol_below = bucket_volume[lower - 1] if lower > 0 else -1.0
            vol_above = bucket_volume[upper + 1] if upper < bins - 1 else -1.0
            if vol_above >= vol_below:
                upper += 1
                covered += bucket_volume[upper]
            else:
                lower -= 1
                covered += bucket_volume[lower]

        vah[i] = bucket_edges[upper + 1]
        val[i] = bucket_edges[lower]

    return pd.DataFrame({"vah": vah, "val": val}, index=df.index)


def volume_percentile(df: pd.DataFrame, lookback: int = 100) -> pd.Series:
    """Rolling percentile rank (0-100) of volume within its own trailing
    distribution -- a simple proxy for "liquidity regime" (high percentile =
    unusually liquid/active, low = thin)."""
    return df["volume"].rolling(lookback).rank(pct=True) * 100
