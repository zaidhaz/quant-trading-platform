"""Mark price history — `/fapi/v1/markPriceKlines`. Same OHLC row shape as
regular candles (full history back to listing, same as OHLCV), used by the
Liquidity Exhaustion Reversal System's research instrumentation to distinguish
last-traded price from the price funding/liquidations actually reference.

The "volume" column is a Binance-side placeholder for this endpoint (mark
price has no real trade volume) — carried through as-is for schema
consistency with `klines_to_dataframe`, never treated as real volume
downstream.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from core.constants import TIMEFRAME_TO_MINUTES
from core.types import Symbol
from market_data.historical.binance_client import BinanceFuturesClient
from market_data.historical.candles_dataset import klines_to_dataframe
from market_data.historical.dataset import HistoricalDataset
from market_data.historical.parquet_store import ParquetStore


class MarkPriceDataset(HistoricalDataset):
    name = "mark_price"

    def __init__(self, store: ParquetStore, client: BinanceFuturesClient | None = None) -> None:
        super().__init__(store)
        self._client = client or BinanceFuturesClient()

    def download(
        self, symbol: Symbol, start: datetime, end: datetime, timeframe: str | None = None
    ) -> pd.DataFrame:
        if timeframe is None:
            raise ValueError("MarkPriceDataset requires a timeframe")
        rows = self._client.get_mark_price_klines(symbol.native(), timeframe, start, end)
        return klines_to_dataframe(rows)

    def expected_frequency(self, timeframe: str | None) -> pd.Timedelta:
        if timeframe is None:
            raise ValueError("MarkPriceDataset requires a timeframe")
        return pd.Timedelta(minutes=TIMEFRAME_TO_MINUTES[timeframe])

    def find_earliest_available(
        self, symbol: Symbol, timeframe: str | None = None
    ) -> datetime | None:
        if timeframe is None:
            raise ValueError("MarkPriceDataset requires a timeframe")
        return self._client.find_earliest_mark_price_time(symbol.native(), timeframe)
