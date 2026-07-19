from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from core.constants import TIMEFRAME_TO_MINUTES
from core.types import Symbol
from market_data.historical.binance_client import BinanceFuturesClient
from market_data.historical.dataset import HistoricalDataset
from market_data.historical.parquet_store import ParquetStore

_KLINE_COLUMNS = ["open", "high", "low", "close", "volume"]


def klines_to_dataframe(rows: list[list[Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=_KLINE_COLUMNS)
    index = pd.to_datetime([int(r[0]) for r in rows], unit="ms", utc=True)
    data = {
        "open": [float(r[1]) for r in rows],
        "high": [float(r[2]) for r in rows],
        "low": [float(r[3]) for r in rows],
        "close": [float(r[4]) for r in rows],
        "volume": [float(r[5]) for r in rows],
    }
    df = pd.DataFrame(data, index=index)
    df.index.name = "ts"
    return df


class CandlesDataset(HistoricalDataset):
    name = "candles"

    def __init__(self, store: ParquetStore, client: BinanceFuturesClient | None = None) -> None:
        super().__init__(store)
        self._client = client or BinanceFuturesClient()

    def download(
        self, symbol: Symbol, start: datetime, end: datetime, timeframe: str | None = None
    ) -> pd.DataFrame:
        if timeframe is None:
            raise ValueError("CandlesDataset requires a timeframe")
        rows = self._client.get_klines(symbol.native(), timeframe, start, end)
        return klines_to_dataframe(rows)

    def expected_frequency(self, timeframe: str | None) -> pd.Timedelta:
        if timeframe is None:
            raise ValueError("CandlesDataset requires a timeframe")
        return pd.Timedelta(minutes=TIMEFRAME_TO_MINUTES[timeframe])
