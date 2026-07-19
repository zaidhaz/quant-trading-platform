"""Displacement, absorption, delta proxy / divergence, Fair Value Gap, Order
Block, and Close-Location-Value ("strong close"). All OHLCV-only proxies for
concepts that would properly need trade-level/order-book data -- see
docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md §1.4-1.6, §1.8-1.10, §2.4-2.6,
§2.8-2.10 for what each one measures, what it approximates, and why.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from features.indicators._shared import true_range


def clv(df: pd.DataFrame) -> pd.Series:
    """Close-Location-Value: where close sits within the bar's [low, high]
    range, rescaled to [-1, 1]. NaN on a zero-range bar (no location to
    measure). See docs §2.8."""
    rng = df["high"] - df["low"]
    value = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng
    return value.where(rng > 0)


def strong_close_up(df: pd.DataFrame, threshold: float = 0.5) -> pd.Series:
    return (clv(df) >= threshold).fillna(False)


def strong_close_down(df: pd.DataFrame, threshold: float = 0.5) -> pd.Series:
    return (clv(df) <= -threshold).fillna(False)


def displacement(
    df: pd.DataFrame,
    atr: pd.Series,
    displacement_atr_mult: float = 1.5,
    strong_close_threshold: float = 0.5,
) -> pd.DataFrame:
    """An abnormally large, directionally-conclusive bar -- see docs §1.4,
    §2.4. `up`/`down` are 0.0/1.0 series: true range >= `displacement_atr_mult`
    * ATR *and* a strong close in that direction (a big bar that closes
    mid-range is not conviction)."""
    tr = true_range(df)
    large = tr >= displacement_atr_mult * atr
    up = (large & strong_close_up(df, strong_close_threshold)).astype(float)
    down = (large & strong_close_down(df, strong_close_threshold)).astype(float)
    return pd.DataFrame({"up": up, "down": down}, index=df.index)


def absorption_score(df: pd.DataFrame, lookback: int = 100) -> pd.Series:
    """OHLCV proxy for absorption -- see docs §1.5, §2.5. Rolling percentile
    rank (0-100) of volume-per-unit-of-range; a high value means this bar
    traded unusually heavy volume for how little price range it covered.
    This measures the *outcome* absorption would produce, not the order-flow
    *cause* -- it cannot distinguish real absorption from e.g. a
    low-volatility chop with average volume."""
    tr = true_range(df).replace(0, np.nan)
    volume_per_range = df["volume"] / tr
    return volume_per_range.rolling(lookback).rank(pct=True) * 100


def delta_proxy(df: pd.DataFrame) -> pd.Series:
    """OHLCV proxy for buy-minus-sell volume -- see docs §1.6, §2.6. Assumes
    volume within a bar is distributed in proportion to where the close sits
    in the bar's range (Close-Location-Value x Volume, the same construction
    as Chaikin Money Flow's numerator). This is a real, standard proxy, and a
    real, known-crude one: it says nothing about the *intrabar path*, only
    the bar's start/end/extremes. It is NOT trade-side-classified order flow;
    replace with a real implementation the moment trade-level data exists
    (see `order_flow_provider` on the strategy)."""
    rng = df["high"] - df["low"]
    value = df["volume"] * ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng
    return value.where(rng > 0, 0.0)


def cvd_proxy(df: pd.DataFrame) -> pd.Series:
    return delta_proxy(df).cumsum()


def bullish_delta_divergence(
    df: pd.DataFrame, cvd: pd.Series, lookback_bars: int = 20
) -> pd.Series:
    """Price prints a new local low over `lookback_bars` while cumulative
    delta (proxy or real, via `cvd`) does not confirm it -- see docs §2.6."""
    low = df["low"]
    rolling_min_low = low.rolling(lookback_bars + 1).min()
    rolling_min_cvd = cvd.rolling(lookback_bars + 1).min()
    return ((low == rolling_min_low) & (cvd > rolling_min_cvd)).fillna(False)


def bearish_delta_divergence(
    df: pd.DataFrame, cvd: pd.Series, lookback_bars: int = 20
) -> pd.Series:
    high = df["high"]
    rolling_max_high = high.rolling(lookback_bars + 1).max()
    rolling_max_cvd = cvd.rolling(lookback_bars + 1).max()
    return ((high == rolling_max_high) & (cvd < rolling_max_cvd)).fillna(False)


def bullish_fvg(df: pd.DataFrame, atr: pd.Series, min_size_atr_mult: float = 0.1) -> pd.DataFrame:
    """Three-candle imbalance: bar[i-2].high < bar[i].low -- see docs §1.8,
    §2.9. Pure price geometry, no interpretation. `active` 0.0/1.0, `size`
    the gap width (NaN where inactive)."""
    gap = df["low"] - df["high"].shift(2)
    qualifies = gap >= min_size_atr_mult * atr
    active = (gap > 0) & qualifies.fillna(False)
    size = gap.where(active)
    return pd.DataFrame({"active": active.astype(float), "size": size}, index=df.index)


def bearish_fvg(df: pd.DataFrame, atr: pd.Series, min_size_atr_mult: float = 0.1) -> pd.DataFrame:
    gap = df["low"].shift(2) - df["high"]
    qualifies = gap >= min_size_atr_mult * atr
    active = (gap > 0) & qualifies.fillna(False)
    size = gap.where(active)
    return pd.DataFrame({"active": active.astype(float), "size": size}, index=df.index)


def order_block_for_direction(
    df: pd.DataFrame,
    displacement_mask: pd.Series,
    direction: str,
    max_lookback_bars: int = 20,
) -> pd.DataFrame:
    """Order block zone for a qualifying displacement bar -- see docs §1.9,
    §2.10. Exactly one definition, deliberately narrow (this is the
    weakest-evidence concept in the system, see docs §1.9): scanning backward
    from the displacement bar, the *single nearest* opposite-body candle
    (bearish body before an "up" displacement, bullish body before a "down"
    displacement). `low`/`high` are that candle's range; NaN where no
    displacement fires at a bar, or none is found within
    `max_lookback_bars`."""
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")

    open_ = df["open"].to_numpy()
    close = df["close"].to_numpy()
    low = df["low"].to_numpy()
    high = df["high"].to_numpy()
    disp = displacement_mask.to_numpy()
    n = len(df)

    ob_low = np.full(n, np.nan)
    ob_high = np.full(n, np.nan)

    for d in range(n):
        if not disp[d]:
            continue
        earliest = max(d - max_lookback_bars, 0)
        for b in range(d - 1, earliest - 1, -1):
            body_up = close[b] > open_[b]
            wants_bearish_body = direction == "up"
            if body_up != wants_bearish_body:
                ob_low[d] = low[b]
                ob_high[d] = high[b]
                break

    return pd.DataFrame({"low": ob_low, "high": ob_high}, index=df.index)
