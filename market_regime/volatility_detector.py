import pandas as pd

from core.types import Symbol
from features.feature_engine import FeatureEngine


def is_high_volatility(
    df: pd.DataFrame,
    features: FeatureEngine,
    symbol: Symbol,
    timeframe: str,
    period: int = 14,
    lookback: int = 100,
    threshold_percentile: float = 50.0,
) -> pd.Series:
    """Current ATR ranked against its own trailing distribution; above the median
    (by default) counts as the high-volatility regime."""
    pct = features.compute_series(
        symbol, timeframe, "atr_percentile", df, period=period, lookback=lookback
    )
    return pct >= threshold_percentile
