"""Centralized, cached indicator calculation.

`FeatureEngine.get()` is what `strategies/` and `market_regime/` call instead of
each computing their own indicators. Indicators are computed once per
(symbol, timeframe, indicator, params) over the full loaded price series — every
indicator here is causal (value at bar i depends only on bars <= i), so this is not
look-ahead bias, it's simply computing the whole series in one vectorized pass
instead of re-deriving it bar-by-bar. `backtesting/event_simulator.py` is what
enforces that a strategy can only *read* the value at or before the current
simulated bar.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from core.exceptions import InsufficientDataError
from core.types import Symbol
from features.cache import FeatureCache, InMemoryFeatureCache
from features.indicators import momentum, trend, volatility, volume

IndicatorFn = Callable[..., pd.Series]

INDICATOR_REGISTRY: dict[str, IndicatorFn] = {
    "ema": lambda df, period=20: trend.ema(df["close"], period),
    "adx": lambda df, period=14: trend.adx(df, period),
    "macd_line": lambda df, fast=12, slow=26, signal=9: trend.macd(df["close"], fast, slow, signal)[
        "macd"
    ],
    "macd_signal": lambda df, fast=12, slow=26, signal=9: trend.macd(
        df["close"], fast, slow, signal
    )["signal"],
    "macd_hist": lambda df, fast=12, slow=26, signal=9: trend.macd(df["close"], fast, slow, signal)[
        "hist"
    ],
    "donchian_upper": lambda df, period=20: trend.donchian(df, period)["upper"],
    "donchian_lower": lambda df, period=20: trend.donchian(df, period)["lower"],
    "donchian_mid": lambda df, period=20: trend.donchian(df, period)["mid"],
    "atr": lambda df, period=14: volatility.atr(df, period),
    "atr_percentile": lambda df, period=14, lookback=100: volatility.atr_percentile(
        df, period, lookback
    ),
    "bb_upper": lambda df, period=20, num_std=2.0: volatility.bollinger_bands(
        df["close"], period, num_std
    )["upper"],
    "bb_mid": lambda df, period=20, num_std=2.0: volatility.bollinger_bands(
        df["close"], period, num_std
    )["mid"],
    "bb_lower": lambda df, period=20, num_std=2.0: volatility.bollinger_bands(
        df["close"], period, num_std
    )["lower"],
    "rsi": lambda df, period=14: momentum.rsi(df["close"], period),
    "vwap": lambda df, period=None: volume.vwap(df, period),
    "volume_profile_poc": lambda df, period=50, bins=10: volume.volume_profile_poc(
        df, period, bins
    ),
}


class FeatureEngine:
    def __init__(self, cache: FeatureCache | None = None) -> None:
        self.cache = cache or InMemoryFeatureCache()
        self.hit_count = 0
        self.miss_count = 0

    def _cache_key(
        self, symbol: Symbol, timeframe: str, indicator: str, params: dict[str, object]
    ) -> tuple[object, ...]:
        return (symbol.canonical, timeframe, indicator, tuple(sorted(params.items())))

    def compute_series(
        self, symbol: Symbol, timeframe: str, indicator: str, df: pd.DataFrame, **params: object
    ) -> pd.Series:
        if indicator not in INDICATOR_REGISTRY:
            raise ValueError(f"Unknown indicator: {indicator!r}")

        key = self._cache_key(symbol, timeframe, indicator, params)
        cached = self.cache.get(key)
        if cached is not None:
            self.hit_count += 1
            return cached

        self.miss_count += 1
        series = INDICATOR_REGISTRY[indicator](df, **params)
        self.cache.set(key, series)
        return series

    def get(
        self,
        symbol: Symbol,
        timeframe: str,
        indicator: str,
        df: pd.DataFrame,
        at_index: int,
        **params: object,
    ) -> float:
        """Value of `indicator` at bar `at_index`. Raises InsufficientDataError during
        an indicator's warmup period (e.g. bar 5 of a 20-period EMA) instead of
        silently returning NaN."""
        series = self.compute_series(symbol, timeframe, indicator, df, **params)
        value = series.iloc[at_index]
        if pd.isna(value):
            raise InsufficientDataError(
                f"{indicator} not yet available at bar {at_index} for {symbol} "
                f"[{timeframe}] (warmup period not satisfied)"
            )
        return float(value)
