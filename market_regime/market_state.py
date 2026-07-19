from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.enums import MarketBias, TrendState, VolatilityState
from core.types import Symbol
from features.feature_engine import FeatureEngine
from market_regime import range_detector, trend_detector, volatility_detector


@dataclass(frozen=True, slots=True)
class MarketState:
    trend: TrendState
    volatility: VolatilityState
    bias: MarketBias

    def as_dict(self) -> dict[str, str]:
        return {
            "trend": self.trend.value,
            "volatility": self.volatility.value,
            "bias": self.bias.value,
        }


def _bias_series(
    df: pd.DataFrame,
    features: FeatureEngine,
    symbol: Symbol,
    timeframe: str,
    fast: int = 20,
    slow: int = 50,
) -> pd.Series:
    ema_fast = features.compute_series(symbol, timeframe, "ema", df, period=fast)
    ema_slow = features.compute_series(symbol, timeframe, "ema", df, period=slow)
    fast_rising = ema_fast.diff() > 0
    bullish = (ema_fast > ema_slow) & fast_rising
    bearish = (ema_fast < ema_slow) & ~fast_rising
    bias = pd.Series(MarketBias.NEUTRAL.value, index=df.index)
    bias[bullish] = MarketBias.BULLISH.value
    bias[bearish] = MarketBias.BEARISH.value
    return bias


def compute(
    df: pd.DataFrame,
    features: FeatureEngine,
    symbol: Symbol,
    timeframe: str,
    trend_period: int = 14,
    trend_threshold: float = 25.0,
    range_period: int = 20,
    range_lookback: int = 100,
    range_compression_percentile: float = 30.0,
    vol_period: int = 14,
    vol_lookback: int = 100,
    vol_threshold_percentile: float = 50.0,
    bias_fast: int = 20,
    bias_slow: int = 50,
) -> pd.DataFrame:
    """One row per bar: trend/volatility/bias classification. TRENDING requires ADX
    above threshold *and* the channel not currently flagged as compressed by
    range_detector — the two checks disagreeing (transitional regime) resolves to
    RANGING, the conservative default for strategies that condition on a clean trend."""
    trending = trend_detector.is_trending(
        df, features, symbol, timeframe, trend_period, trend_threshold
    )
    compressed = range_detector.is_compressed(
        df, features, symbol, timeframe, range_period, range_lookback, range_compression_percentile
    )
    high_vol = volatility_detector.is_high_volatility(
        df, features, symbol, timeframe, vol_period, vol_lookback, vol_threshold_percentile
    )
    bias = _bias_series(df, features, symbol, timeframe, bias_fast, bias_slow)

    trend_state = pd.Series(TrendState.RANGING.value, index=df.index)
    trend_state[trending & ~compressed] = TrendState.TRENDING.value

    volatility_state = pd.Series(VolatilityState.LOW.value, index=df.index)
    volatility_state[high_vol] = VolatilityState.HIGH.value

    return pd.DataFrame({"trend": trend_state, "volatility": volatility_state, "bias": bias})


def at(regime_df: pd.DataFrame, index: int) -> MarketState:
    row = regime_df.iloc[index]
    return MarketState(
        trend=TrendState(row["trend"]),
        volatility=VolatilityState(row["volatility"]),
        bias=MarketBias(row["bias"]),
    )
