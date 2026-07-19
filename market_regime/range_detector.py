import pandas as pd

from core.types import Symbol
from features.feature_engine import FeatureEngine


def is_compressed(
    df: pd.DataFrame,
    features: FeatureEngine,
    symbol: Symbol,
    timeframe: str,
    period: int = 20,
    lookback: int = 100,
    compression_percentile: float = 30.0,
) -> pd.Series:
    """Donchian-channel-width, normalized by price and ranked against its own trailing
    distribution — a channel narrower than most of the recent history signals a
    compressed/ranging market. This is a different signal than "ADX isn't trending":
    a symbol can be in-between (neither cleanly trending nor cleanly compressed)
    during a regime transition, which is exactly the case this is meant to catch."""
    upper = features.compute_series(symbol, timeframe, "donchian_upper", df, period=period)
    lower = features.compute_series(symbol, timeframe, "donchian_lower", df, period=period)
    width_pct_of_price = (upper - lower) / df["close"]
    width_rank = width_pct_of_price.rolling(lookback).rank(pct=True) * 100
    return width_rank <= compression_percentile
