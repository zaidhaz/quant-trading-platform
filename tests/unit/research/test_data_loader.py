"""Unit tests for `research/data_loader.py` — the single place that decides,
per symbol/timeframe, whether a research pipeline run uses real or synthetic
data. Mocks `BinanceFuturesClient.ping()` and the dataset sync methods so no
network access is exercised; the sandbox this suite normally runs in has
`fapi.binance.com` blocked anyway, so these tests must pass regardless of
network state.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core.exceptions import DataGapError
from research.data_loader import load_history

NON_EMPTY_CANDLES = pd.DataFrame(
    {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
    index=pd.DatetimeIndex(["2024-01-01"], tz="UTC"),
)
EMPTY_FUNDING = pd.DataFrame(columns=["funding_rate", "mark_price"])


class TestSyntheticMode:
    def test_always_uses_synthetic_regardless_of_network(self) -> None:
        loaded = load_history("BTCUSDT", "1h", mode="synthetic")

        assert loaded.source == "synthetic"
        assert not loaded.candles.empty
        assert "SYNTHETIC" in loaded.detail

    def test_does_not_touch_the_network_client_at_all(self) -> None:
        client = MagicMock()
        loaded = load_history("BTCUSDT", "1h", mode="synthetic", client=client)

        client.ping.assert_not_called()
        assert loaded.source == "synthetic"


class TestAutoMode:
    def test_falls_back_to_synthetic_when_ping_fails(self) -> None:
        client = MagicMock()
        client.ping.return_value = False

        loaded = load_history("BTCUSDT", "1h", mode="auto", client=client)

        assert loaded.source == "synthetic"
        assert "unreachable" in loaded.detail

    def test_uses_real_data_when_ping_succeeds_and_fetch_works(self, tmp_path) -> None:
        client = MagicMock()
        client.ping.return_value = True
        from market_data.historical.parquet_store import ParquetStore

        store = ParquetStore(tmp_path)
        with (
            patch(
                "research.data_loader.CandlesDataset.sync_full_history",
                return_value=NON_EMPTY_CANDLES,
            ),
            patch(
                "research.data_loader.FundingRateDataset.sync_full_history",
                return_value=EMPTY_FUNDING,
            ),
        ):
            loaded = load_history("BTCUSDT", "1h", mode="auto", store=store, client=client)

        assert loaded.source == "real"
        assert not loaded.candles.empty

    def test_falls_back_to_synthetic_when_real_fetch_raises_data_gap_error(self, tmp_path) -> None:
        client = MagicMock()
        client.ping.return_value = True
        from market_data.historical.parquet_store import ParquetStore

        store = ParquetStore(tmp_path)
        with patch(
            "research.data_loader.CandlesDataset.sync_full_history",
            side_effect=DataGapError("no data for this symbol"),
        ):
            loaded = load_history("BTCUSDT", "1h", mode="auto", store=store, client=client)

        assert loaded.source == "synthetic"
        assert "no data for this symbol" in loaded.detail


class TestRealMode:
    def test_raises_instead_of_falling_back_when_ping_fails(self) -> None:
        client = MagicMock()
        client.ping.return_value = False

        with pytest.raises(ConnectionError):
            load_history("BTCUSDT", "1h", mode="real", client=client)

    def test_raises_instead_of_falling_back_when_fetch_fails(self, tmp_path) -> None:
        client = MagicMock()
        client.ping.return_value = True
        from market_data.historical.parquet_store import ParquetStore

        store = ParquetStore(tmp_path)
        with (
            patch(
                "research.data_loader.CandlesDataset.sync_full_history",
                side_effect=DataGapError("nothing available"),
            ),
            pytest.raises(DataGapError),
        ):
            load_history("BTCUSDT", "1h", mode="real", store=store, client=client)


def test_invalid_mode_raises_value_error() -> None:
    with pytest.raises(ValueError):
        load_history("BTCUSDT", "1h", mode="not-a-real-mode")
