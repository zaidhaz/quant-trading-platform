from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from core.types import Symbol
from market_data.historical.binance_client import BinanceFuturesClient
from market_data.historical.dataset import HistoricalDataset
from market_data.historical.parquet_store import ParquetStore

# Binance Futures pays funding every 8 hours for most perpetuals.
DEFAULT_FUNDING_INTERVAL = pd.Timedelta(hours=8)


def funding_rows_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["funding_rate", "mark_price"])
    index = pd.to_datetime([int(r["fundingTime"]) for r in rows], unit="ms", utc=True)
    df = pd.DataFrame(
        {
            "funding_rate": [float(r["fundingRate"]) for r in rows],
            "mark_price": [float(r["markPrice"]) if "markPrice" in r else None for r in rows],
        },
        index=index,
    )
    df.index.name = "ts"
    return df


class FundingRateDataset(HistoricalDataset):
    name = "funding_rate"

    def __init__(self, store: ParquetStore, client: BinanceFuturesClient | None = None) -> None:
        super().__init__(store)
        self._client = client or BinanceFuturesClient()

    def download(
        self, symbol: Symbol, start: datetime, end: datetime, timeframe: str | None = None
    ) -> pd.DataFrame:
        rows = self._client.get_funding_rate_history(symbol.native(), start, end)
        return funding_rows_to_dataframe(rows)

    def expected_frequency(self, timeframe: str | None) -> pd.Timedelta:
        return DEFAULT_FUNDING_INTERVAL

    def find_earliest_available(
        self, symbol: Symbol, timeframe: str | None = None
    ) -> datetime | None:
        return self._client.find_earliest_funding_time(symbol.native())
