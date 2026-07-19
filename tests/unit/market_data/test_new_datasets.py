"""Unit tests for the mark price, premium index, open interest, and
exchange-info datasets added alongside the historical data layer expansion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from core.types import Symbol
from market_data.historical.exchange_info import SymbolInfo, get_symbol_info
from market_data.historical.mark_price_dataset import MarkPriceDataset
from market_data.historical.open_interest_dataset import (
    OPEN_INTEREST_MAX_LOOKBACK_DAYS,
    OpenInterestDataset,
    open_interest_rows_to_dataframe,
)
from market_data.historical.parquet_store import ParquetStore
from market_data.historical.premium_index_dataset import PremiumIndexDataset

SYMBOL = Symbol(base="BTC", quote="USDT")

SAMPLE_KLINE = [
    1704067200000,
    "42000.10",
    "42500.00",
    "41900.50",
    "42300.75",
    "0",  # placeholder volume field for mark/premium-index klines
    1704070799999,
    "0",
    0,
    "0",
    "0",
    "0",
]


class TestMarkPriceDataset:
    def test_download_calls_client_and_shapes_dataframe(self, tmp_path) -> None:
        client = MagicMock()
        client.get_mark_price_klines.return_value = [SAMPLE_KLINE]
        dataset = MarkPriceDataset(ParquetStore(tmp_path), client)

        df = dataset.download(SYMBOL, datetime(2024, 1, 1), datetime(2024, 1, 2), "1h")

        client.get_mark_price_klines.assert_called_once()
        assert df.iloc[0]["close"] == 42300.75

    def test_download_requires_timeframe(self, tmp_path) -> None:
        dataset = MarkPriceDataset(ParquetStore(tmp_path), MagicMock())
        with pytest.raises(ValueError):
            dataset.download(SYMBOL, datetime(2024, 1, 1), datetime(2024, 1, 2), None)

    def test_find_earliest_available_delegates_to_client(self, tmp_path) -> None:
        client = MagicMock()
        client.find_earliest_mark_price_time.return_value = datetime(2020, 1, 1, tzinfo=UTC)
        dataset = MarkPriceDataset(ParquetStore(tmp_path), client)

        result = dataset.find_earliest_available(SYMBOL, "1h")

        client.find_earliest_mark_price_time.assert_called_once_with("BTCUSDT", "1h")
        assert result == datetime(2020, 1, 1, tzinfo=UTC)


class TestPremiumIndexDataset:
    def test_download_calls_client_and_shapes_dataframe(self, tmp_path) -> None:
        client = MagicMock()
        client.get_premium_index_klines.return_value = [SAMPLE_KLINE]
        dataset = PremiumIndexDataset(ParquetStore(tmp_path), client)

        df = dataset.download(SYMBOL, datetime(2024, 1, 1), datetime(2024, 1, 2), "1h")

        client.get_premium_index_klines.assert_called_once()
        assert df.iloc[0]["close"] == 42300.75

    def test_find_earliest_available_delegates_to_client(self, tmp_path) -> None:
        client = MagicMock()
        client.find_earliest_premium_index_time.return_value = datetime(2020, 1, 1, tzinfo=UTC)
        dataset = PremiumIndexDataset(ParquetStore(tmp_path), client)

        result = dataset.find_earliest_available(SYMBOL, "1h")

        client.find_earliest_premium_index_time.assert_called_once_with("BTCUSDT", "1h")
        assert result == datetime(2020, 1, 1, tzinfo=UTC)


class TestOpenInterestRowsToDataFrame:
    def test_parses_rows(self) -> None:
        rows = [
            {
                "symbol": "BTCUSDT",
                "timestamp": 1704067200000,
                "sumOpenInterest": "12345.6",
                "sumOpenInterestValue": "500000000.0",
            }
        ]
        df = open_interest_rows_to_dataframe(rows)
        assert df.iloc[0]["sum_open_interest"] == 12345.6
        assert df.iloc[0]["sum_open_interest_value"] == 500000000.0

    def test_empty_input(self) -> None:
        df = open_interest_rows_to_dataframe([])
        assert df.empty
        assert list(df.columns) == ["sum_open_interest", "sum_open_interest_value"]


class TestOpenInterestDataset:
    def test_download_clamps_start_to_retention_floor(self, tmp_path) -> None:
        client = MagicMock()
        client.get_open_interest_hist.return_value = []
        dataset = OpenInterestDataset(ParquetStore(tmp_path), client)

        far_past = datetime.now(UTC) - timedelta(days=365)
        now = datetime.now(UTC)
        dataset.download(SYMBOL, far_past, now)

        called_start = client.get_open_interest_hist.call_args.args[2]
        retention_floor = now - timedelta(days=OPEN_INTEREST_MAX_LOOKBACK_DAYS)
        assert abs((pd.Timestamp(called_start) - pd.Timestamp(retention_floor)).total_seconds()) < 5

    def test_download_returns_empty_when_start_after_end(self, tmp_path) -> None:
        client = MagicMock()
        dataset = OpenInterestDataset(ParquetStore(tmp_path), client)

        now = datetime.now(UTC)
        result = dataset.download(SYMBOL, now, now - timedelta(days=60))

        assert result.empty
        client.get_open_interest_hist.assert_not_called()

    def test_find_earliest_available_is_fixed_retention_floor_not_a_probe(self, tmp_path) -> None:
        client = MagicMock()
        dataset = OpenInterestDataset(ParquetStore(tmp_path), client)

        earliest = dataset.find_earliest_available(SYMBOL)

        client.assert_not_called()
        expected = datetime.now(UTC) - timedelta(days=OPEN_INTEREST_MAX_LOOKBACK_DAYS)
        assert abs((earliest - expected).total_seconds()) < 5

    def test_rejects_unsupported_period(self, tmp_path) -> None:
        with pytest.raises(ValueError):
            OpenInterestDataset(ParquetStore(tmp_path), MagicMock(), period="3m")


class TestGetSymbolInfo:
    def test_returns_symbol_info_when_present(self) -> None:
        client = MagicMock()
        client.get_exchange_info.return_value = {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "contractType": "PERPETUAL",
                    "onboardDate": 1569888000000,
                    "pricePrecision": 2,
                    "quantityPrecision": 3,
                }
            ]
        }

        info = get_symbol_info(client, "BTCUSDT")

        assert info == SymbolInfo(
            symbol="BTCUSDT",
            status="TRADING",
            contract_type="PERPETUAL",
            onboard_date=datetime.fromtimestamp(1569888000, tz=UTC),
            price_precision=2,
            quantity_precision=3,
        )

    def test_returns_none_when_symbol_not_listed(self) -> None:
        client = MagicMock()
        client.get_exchange_info.return_value = {"symbols": []}

        assert get_symbol_info(client, "NOSUCHSYMBOL") is None

    def test_missing_onboard_date_becomes_none(self) -> None:
        client = MagicMock()
        client.get_exchange_info.return_value = {
            "symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL"}]
        }

        info = get_symbol_info(client, "BTCUSDT")

        assert info is not None
        assert info.onboard_date is None
