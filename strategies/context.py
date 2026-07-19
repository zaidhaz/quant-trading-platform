from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from core.types import Position, Symbol
from features.feature_engine import FeatureEngine
from market_regime import market_state


class FeatureAccessor:
    """`context.features.get("rsi", period=14)` — the only way strategies read
    indicators. `offset` counts bars back from the current one (offset=1 is "the
    previous bar's value"), used for crossover-style detection."""

    def __init__(
        self, engine: FeatureEngine, df: pd.DataFrame, symbol: Symbol, timeframe: str, index: int
    ) -> None:
        self._engine = engine
        self._df = df
        self._symbol = symbol
        self._timeframe = timeframe
        self._index = index

    def get(self, indicator: str, offset: int = 0, **params: object) -> float:
        return self._engine.get(
            self._symbol, self._timeframe, indicator, self._df, self._index - offset, **params
        )


class RegimeAccessor:
    def __init__(self, regime_df: pd.DataFrame, index: int) -> None:
        self._regime_df = regime_df
        self._index = index

    def current(self) -> market_state.MarketState:
        return market_state.at(self._regime_df, self._index)


@dataclass(slots=True)
class StrategyContext:
    index: int
    ts: datetime
    bar: pd.Series  # current OHLCV row
    features: FeatureAccessor
    regime: RegimeAccessor
    equity: float
    position: Position | None = None
    funding_rate: float | None = None
    """This bar's funding rate, when the feed loaded one (see `DataFeed.funding_events`)
    -- current-bar only, no `offset` lookback like `features.get()` has, since it's a
    single passthrough value rather than a cached derived series."""

    @property
    def price(self) -> float:
        return float(self.bar["close"])


def build_context(
    df: pd.DataFrame,
    engine: FeatureEngine,
    symbol: Symbol,
    timeframe: str,
    regime_df: pd.DataFrame,
    index: int,
    equity: float,
    position: Position | None = None,
    funding_rate: float | None = None,
) -> StrategyContext:
    row = df.iloc[index]
    return StrategyContext(
        index=index,
        ts=row.name.to_pydatetime() if hasattr(row.name, "to_pydatetime") else row.name,
        bar=row,
        features=FeatureAccessor(engine, df, symbol, timeframe, index),
        regime=RegimeAccessor(regime_df, index),
        equity=equity,
        position=position,
        funding_rate=funding_rate,
    )
