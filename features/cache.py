"""Pluggable feature cache. In-memory is the default for the research engine —
running a backtest shouldn't require a Redis instance. A Redis-backed implementation
for live multi-process sharing is a Part B concern (see docs/ARCHITECTURE.md)."""

from abc import ABC, abstractmethod
from collections.abc import Hashable

import pandas as pd


class FeatureCache(ABC):
    @abstractmethod
    def get(self, key: Hashable) -> pd.Series | None: ...

    @abstractmethod
    def set(self, key: Hashable, series: pd.Series) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...


class InMemoryFeatureCache(FeatureCache):
    def __init__(self) -> None:
        self._store: dict[Hashable, pd.Series] = {}

    def get(self, key: Hashable) -> pd.Series | None:
        return self._store.get(key)

    def set(self, key: Hashable, series: pd.Series) -> None:
        self._store[key] = series

    def clear(self) -> None:
        self._store.clear()
