"""Unit tests for BinanceFuturesClient. Mocks only the lowest-level `_get`
(and, for `ping`, the underlying httpx client's `.get`) so real pagination
and earliest-timestamp logic is actually exercised rather than bypassed —
mocking a higher-level convenience method here would hide bugs in exactly
the code this test suite exists to cover.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from market_data.historical.binance_client import (
    KLINES_LIMIT,
    OPEN_INTEREST_LIMIT,
    BinanceFuturesClient,
)


@pytest.fixture
def client() -> BinanceFuturesClient:
    return BinanceFuturesClient()


def _kline_row(open_time_ms: int) -> list:
    return [open_time_ms, "1", "2", "0.5", "1.5", "10", open_time_ms + 59999, "0", 1, "0", "0", "0"]


class TestPing:
    def test_ping_true_on_200(self, client: BinanceFuturesClient, monkeypatch) -> None:
        monkeypatch.setattr(
            client._client,
            "get",
            lambda *a, **k: httpx.Response(200, request=httpx.Request("GET", "x")),
        )
        assert client.ping() is True

    def test_ping_false_on_non_200(self, client: BinanceFuturesClient, monkeypatch) -> None:
        monkeypatch.setattr(
            client._client,
            "get",
            lambda *a, **k: httpx.Response(500, request=httpx.Request("GET", "x")),
        )
        assert client.ping() is False

    def test_ping_false_on_connection_error(
        self, client: BinanceFuturesClient, monkeypatch
    ) -> None:
        def raise_connect_error(*a, **k):
            raise httpx.ConnectError("blocked")

        monkeypatch.setattr(client._client, "get", raise_connect_error)
        assert client.ping() is False


class TestPaginateKlines:
    def test_single_page(self, client: BinanceFuturesClient, monkeypatch) -> None:
        rows = [_kline_row(1_700_000_000_000 + i * 60_000) for i in range(3)]
        monkeypatch.setattr(client, "_get", lambda path, params: rows)

        result = client.get_klines(
            "BTCUSDT", "1m", datetime(2023, 11, 14, tzinfo=UTC), datetime(2023, 11, 15, tzinfo=UTC)
        )

        assert result == rows

    def test_pagination_stops_on_short_final_page(
        self, client: BinanceFuturesClient, monkeypatch
    ) -> None:
        base_ms = 1_700_000_000_000
        page1 = [_kline_row(base_ms + i * 60_000) for i in range(KLINES_LIMIT)]
        page2 = [_kline_row(base_ms + (KLINES_LIMIT + i) * 60_000) for i in range(5)]
        calls = {"n": 0}

        def fake_get(path, params):
            calls["n"] += 1
            return page1 if calls["n"] == 1 else page2

        monkeypatch.setattr(client, "_get", fake_get)

        result = client.get_klines(
            "BTCUSDT", "1m", datetime(2023, 11, 14, tzinfo=UTC), datetime(2023, 11, 20, tzinfo=UTC)
        )

        assert calls["n"] == 2
        assert len(result) == KLINES_LIMIT + 5

    def test_empty_response_returns_empty_list(
        self, client: BinanceFuturesClient, monkeypatch
    ) -> None:
        monkeypatch.setattr(client, "_get", lambda path, params: [])

        result = client.get_klines(
            "BTCUSDT", "1m", datetime(2023, 11, 14, tzinfo=UTC), datetime(2023, 11, 15, tzinfo=UTC)
        )

        assert result == []


class TestFindEarliest:
    def test_find_earliest_kline_open_time(self, client: BinanceFuturesClient, monkeypatch) -> None:
        first_row = _kline_row(1_600_000_000_000)
        seen_params = {}

        def fake_get(path, params):
            seen_params.update(params)
            assert params["limit"] == 1
            return [first_row]

        monkeypatch.setattr(client, "_get", fake_get)

        earliest = client.find_earliest_kline_open_time("BTCUSDT", "1h")

        assert earliest == datetime.fromtimestamp(1_600_000_000, tz=UTC)
        assert seen_params["symbol"] == "BTCUSDT"
        assert seen_params["interval"] == "1h"

    def test_find_earliest_returns_none_when_no_data(
        self, client: BinanceFuturesClient, monkeypatch
    ) -> None:
        monkeypatch.setattr(client, "_get", lambda path, params: [])

        assert client.find_earliest_kline_open_time("NOSUCHSYMBOL", "1h") is None

    def test_find_earliest_mark_price_and_premium_index(
        self, client: BinanceFuturesClient, monkeypatch
    ) -> None:
        first_row = _kline_row(1_610_000_000_000)
        monkeypatch.setattr(client, "_get", lambda path, params: [first_row])

        assert client.find_earliest_mark_price_time("BTCUSDT", "1h") == datetime.fromtimestamp(
            1_610_000_000, tz=UTC
        )
        assert client.find_earliest_premium_index_time("BTCUSDT", "1h") == datetime.fromtimestamp(
            1_610_000_000, tz=UTC
        )

    def test_find_earliest_funding_time(self, client: BinanceFuturesClient, monkeypatch) -> None:
        row = {"symbol": "BTCUSDT", "fundingTime": 1_620_000_000_000, "fundingRate": "0.0001"}
        monkeypatch.setattr(client, "_get", lambda path, params: [row])

        assert client.find_earliest_funding_time("BTCUSDT") == datetime.fromtimestamp(
            1_620_000_000, tz=UTC
        )

    def test_find_earliest_funding_time_none_when_empty(
        self, client: BinanceFuturesClient, monkeypatch
    ) -> None:
        monkeypatch.setattr(client, "_get", lambda path, params: [])
        assert client.find_earliest_funding_time("BTCUSDT") is None


class TestFundingRateHistory:
    def test_pagination_advances_cursor_past_last_funding_time(
        self, client: BinanceFuturesClient, monkeypatch
    ) -> None:
        from market_data.historical.binance_client import FUNDING_RATE_LIMIT

        base_ms = 1_700_000_000_000
        page1 = [
            {"symbol": "BTCUSDT", "fundingTime": base_ms + i * 28_800_000, "fundingRate": "0.0001"}
            for i in range(FUNDING_RATE_LIMIT)
        ]
        page2 = [
            {
                "symbol": "BTCUSDT",
                "fundingTime": base_ms + (FUNDING_RATE_LIMIT + i) * 28_800_000,
                "fundingRate": "0.0001",
            }
            for i in range(3)
        ]
        calls = {"n": 0}

        def fake_get(path, params):
            calls["n"] += 1
            return page1 if calls["n"] == 1 else page2

        monkeypatch.setattr(client, "_get", fake_get)

        result = client.get_funding_rate_history(
            "BTCUSDT", datetime(2023, 11, 14, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)
        )

        assert calls["n"] == 2
        assert len(result) == FUNDING_RATE_LIMIT + 3


class TestOpenInterestHist:
    def test_pagination(self, client: BinanceFuturesClient, monkeypatch) -> None:
        base_ms = 1_700_000_000_000
        page1 = [
            {
                "symbol": "BTCUSDT",
                "timestamp": base_ms + i * 300_000,
                "sumOpenInterest": "1000",
                "sumOpenInterestValue": "50000000",
            }
            for i in range(OPEN_INTEREST_LIMIT)
        ]
        calls = {"n": 0}

        def fake_get(path, params):
            calls["n"] += 1
            return page1 if calls["n"] == 1 else []

        monkeypatch.setattr(client, "_get", fake_get)

        result = client.get_open_interest_hist(
            "BTCUSDT", "5m", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 3, tzinfo=UTC)
        )

        assert len(result) == OPEN_INTEREST_LIMIT


class TestExchangeInfo:
    def test_get_exchange_info_passes_through(
        self, client: BinanceFuturesClient, monkeypatch
    ) -> None:
        payload = {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING"}]}
        monkeypatch.setattr(client, "_get", lambda path, params: payload)

        assert client.get_exchange_info() == payload
