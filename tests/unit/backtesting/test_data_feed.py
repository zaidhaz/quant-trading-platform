import logging
from datetime import datetime

import pandas as pd
import pytest

from backtesting.data_feed import DataFeed
from core.exceptions import DataGapError
from core.types import Symbol
from market_data.historical.dataset import HistoricalDataset
from market_data.historical.parquet_store import ParquetStore

SYMBOL = Symbol(base="BTC", quote="USDT")
HOUR = pd.Timedelta(hours=1)


class FullCandles(HistoricalDataset):
    name = "candles"

    def download(self, symbol, start, end, timeframe=None) -> pd.DataFrame:
        index = pd.date_range(start.ceil("h"), end.floor("h"), freq="1h", tz="UTC")
        return pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=index
        )

    def expected_frequency(self, timeframe) -> pd.Timedelta:
        return HOUR


class GappyCandles(HistoricalDataset):
    """Source that never has data — simulates an unfillable candle gap."""

    name = "candles"

    def download(self, symbol, start, end, timeframe=None) -> pd.DataFrame:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    def expected_frequency(self, timeframe) -> pd.Timedelta:
        return HOUR


class GappyFunding(HistoricalDataset):
    """Source that never has data — simulates an unfillable funding gap."""

    name = "funding_rate"

    def download(self, symbol, start, end, timeframe=None) -> pd.DataFrame:
        return pd.DataFrame(columns=["funding_rate", "mark_price"])

    def expected_frequency(self, timeframe) -> pd.Timedelta:
        return pd.Timedelta(hours=8)


def test_load_raises_on_unfillable_candle_gap(tmp_path) -> None:
    store = ParquetStore(tmp_path)
    with pytest.raises(DataGapError):
        DataFeed.load(
            SYMBOL, "1h", datetime(2024, 1, 1), datetime(2024, 1, 1, 5), GappyCandles(store)
        )


def test_load_degrades_gracefully_on_unfillable_funding_gap(tmp_path, caplog) -> None:
    store = ParquetStore(tmp_path)
    with caplog.at_level(logging.WARNING):
        feed = DataFeed.load(
            SYMBOL,
            "1h",
            datetime(2024, 1, 1),
            datetime(2024, 1, 1, 5),
            FullCandles(store),
            GappyFunding(store),
        )

    assert len(feed.candles) > 0  # candles still loaded fine
    assert feed.funding_events.isna().all()  # funding just absent, not fatal
    assert any("Funding rate data incomplete" in r.message for r in caplog.records)
