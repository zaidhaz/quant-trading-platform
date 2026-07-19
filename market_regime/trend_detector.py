import pandas as pd

from core.types import Symbol
from features.feature_engine import FeatureEngine


def is_trending(
    df: pd.DataFrame,
    features: FeatureEngine,
    symbol: Symbol,
    timeframe: str,
    period: int = 14,
    threshold: float = 25.0,
) -> pd.Series:
    """ADX >= threshold is the conventional "market is trending" reading."""
    adx = features.compute_series(symbol, timeframe, "adx", df, period=period)
    return adx >= threshold
