"""Premium index history — `/fapi/v1/premiumIndexKlines`. The premium/discount
of mark price over the spot index, expressed as OHLC "candles" — this is what
funding rate is actually derived from over each 8h window, so having its own
history (rather than only the realized 8-hourly funding rate) lets research
instrumentation see intra-period funding pressure, not just the settled rate.

Same schema caveat as `mark_price_dataset.py`: the "volume" column is a
Binance-side placeholder, not real trade volume.
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


class PremiumIndexDataset(HistoricalDataset):
    name = "premium_index"

    def __init__(self, store: ParquetStore, client: BinanceFuturesClient | None = None) -> None:
        super().__init__(store)
        self._client = client or BinanceFuturesClient()

    def download(
        self, symbol: Symbol, start: datetime, end: datetime, timeframe: str | None = None
    ) -> pd.DataFrame:
        if timeframe is None:
            raise ValueError("PremiumIndexDataset requires a timeframe")
        rows = self._client.get_premium_index_klines(symbol.native(), timeframe, start, end)
        return klines_to_dataframe(rows)

    def expected_frequency(self, timeframe: str | None) -> pd.Timedelta:
        if timeframe is None:
            raise ValueError("PremiumIndexDataset requires a timeframe")
        return pd.Timedelta(minutes=TIMEFRAME_TO_MINUTES[timeframe])

    def find_earliest_available(
        self, symbol: Symbol, timeframe: str | None = None
    ) -> datetime | None:
        if timeframe is None:
            raise ValueError("PremiumIndexDataset requires a timeframe")
        return self._client.find_earliest_premium_index_time(symbol.native(), timeframe)
