"""Integration test for `scripts/sync_historical_data.py`'s incremental sync.

Mocks only `BinanceFuturesClient._get` (the lowest level) so real pagination,
gap-detection, dedup-on-write, and resumability all actually run — mocking a
higher-level convenience method here would hide bugs in exactly the mechanism
this test exists to verify. The fake backend serves data up to the *real*
wall-clock "now" (matching what `HistoricalDataset.sync_full_history()`
itself uses as its default `end`), not a simulated one, so gap detection
sees a consistent picture on both sides.

The client's real page-size constants (`KLINES_LIMIT` etc.) are monkeypatched
down to a small number so a ~5 day history still requires multiple requests
per dataset — the fake backend always returns up to exactly the requested
`limit`, preserving the real pagination invariant ("a page shorter than the
requested limit means no more data") rather than truncating independently of
it, which would violate that invariant and make the client stop early for
the wrong reason.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.constants import TIMEFRAME_TO_MINUTES
from market_data.historical.binance_client import BinanceFuturesClient
from market_data.historical.parquet_store import ParquetStore
from scripts.sync_historical_data import sync_symbol

LISTING = datetime.now(UTC) - timedelta(days=5)


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class FakeBackend:
    """Deterministic stand-in for the real Binance HTTP surface, keyed by path.
    Always serves up to the real current time, exactly like the real API would."""

    def __init__(self) -> None:
        self.call_log: list[tuple[str, int, int]] = []  # (path, startTime, endTime)

    def get(self, path: str, params: dict) -> object:
        self.call_log.append((path, params.get("startTime", 0), params.get("endTime", 0)))
        now_ms = _to_ms(datetime.now(UTC))

        if path == "/fapi/v1/exchangeInfo":
            return {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "contractType": "PERPETUAL",
                        "onboardDate": _to_ms(LISTING),
                        "pricePrecision": 2,
                        "quantityPrecision": 3,
                    }
                ]
            }

        if path in ("/fapi/v1/klines", "/fapi/v1/markPriceKlines", "/fapi/v1/premiumIndexKlines"):
            interval = params["interval"]
            step_ms = TIMEFRAME_TO_MINUTES[interval] * 60_000
            start_ms = max(int(params["startTime"]), _to_ms(LISTING))
            end_ms = min(int(params["endTime"]), now_ms)
            limit = int(params["limit"])
            rows = []
            t = start_ms
            while t <= end_ms and len(rows) < limit:
                rows.append(
                    [t, "100", "101", "99", "100.5", "10", t + step_ms - 1, "0", 1, "0", "0", "0"]
                )
                t += step_ms
            return rows

        if path == "/fapi/v1/fundingRate":
            step_ms = 8 * 60 * 60_000
            start_ms = max(int(params["startTime"]), _to_ms(LISTING))
            end_ms = min(int(params["endTime"]), now_ms)
            limit = int(params["limit"])
            rows = []
            t = start_ms
            while t <= end_ms and len(rows) < limit:
                rows.append({"symbol": "BTCUSDT", "fundingTime": t, "fundingRate": "0.0001"})
                t += step_ms
            return rows

        if path == "/futures/data/openInterestHist":
            step_ms = 5 * 60_000
            retention_floor_ms = now_ms - 30 * 24 * 60 * 60_000
            start_ms = max(int(params["startTime"]), retention_floor_ms)
            end_ms = min(int(params["endTime"]), now_ms)
            limit = int(params["limit"])
            rows = []
            t = start_ms
            while t <= end_ms and len(rows) < limit:
                rows.append(
                    {
                        "symbol": "BTCUSDT",
                        "timestamp": t,
                        "sumOpenInterest": "1000",
                        "sumOpenInterestValue": "50000000",
                    }
                )
                t += step_ms
            return rows

        raise AssertionError(f"unexpected path {path}")


def _make_client(monkeypatch) -> tuple[BinanceFuturesClient, FakeBackend]:
    # Shrink the real page-size constants so ~5 days of history still spans
    # multiple requests per dataset, genuinely exercising pagination.
    monkeypatch.setattr("market_data.historical.binance_client.KLINES_LIMIT", 20)
    monkeypatch.setattr("market_data.historical.binance_client.FUNDING_RATE_LIMIT", 5)
    monkeypatch.setattr("market_data.historical.binance_client.OPEN_INTEREST_LIMIT", 50)
    client = BinanceFuturesClient()
    backend = FakeBackend()
    monkeypatch.setattr(client, "_get", backend.get)
    return client, backend


def test_first_sync_is_a_full_paginated_download(tmp_path, monkeypatch) -> None:
    client, backend = _make_client(monkeypatch)
    store = ParquetStore(tmp_path)

    outcomes = sync_symbol(
        "BTCUSDT",
        store,
        client,
        candle_timeframes=("1h",),
        mark_premium_timeframes=("1h",),
    )

    assert all(o.ok for o in outcomes), [o.error for o in outcomes if not o.ok]
    candles_outcome = next(o for o in outcomes if o.dataset == "candles")
    assert candles_outcome.rows >= 5 * 24  # ~5 days of 1h bars
    funding_outcome = next(o for o in outcomes if o.dataset == "funding_rate")
    assert funding_outcome.rows >= 5 * 3  # ~5 days of 8h funding
    oi_outcome = next(o for o in outcomes if o.dataset == "open_interest")
    assert oi_outcome.rows > 0
    assert len(backend.call_log) > 5  # multiple datasets, each involving >=1 request


def test_second_sync_only_fetches_the_incremental_gap(tmp_path, monkeypatch) -> None:
    client, backend = _make_client(monkeypatch)
    store = ParquetStore(tmp_path)

    first_outcomes = sync_symbol(
        "BTCUSDT", store, client, candle_timeframes=("1h",), mark_premium_timeframes=("1h",)
    )
    first_run_call_count = len(backend.call_log)
    first_candles_rows = next(o for o in first_outcomes if o.dataset == "candles").rows

    # A second run against the same store should find nearly everything
    # already covered (only the few seconds/minutes elapsed since the first
    # run are new) and make far fewer requests -- the resumability/
    # never-redownload contract.
    client2, backend2 = _make_client(monkeypatch)
    outcomes = sync_symbol(
        "BTCUSDT", store, client2, candle_timeframes=("1h",), mark_premium_timeframes=("1h",)
    )

    assert all(o.ok for o in outcomes), [o.error for o in outcomes if not o.ok]
    assert len(backend2.call_log) < first_run_call_count
    candles_outcome = next(o for o in outcomes if o.dataset == "candles")
    assert candles_outcome.rows >= first_candles_rows  # never loses rows, may gain at most 1 bar


def test_second_sync_produces_no_duplicate_timestamps(tmp_path, monkeypatch) -> None:
    client, backend = _make_client(monkeypatch)
    store = ParquetStore(tmp_path)

    sync_symbol("BTCUSDT", store, client, candle_timeframes=("1h",), mark_premium_timeframes=())
    client2, _ = _make_client(monkeypatch)
    sync_symbol("BTCUSDT", store, client2, candle_timeframes=("1h",), mark_premium_timeframes=())

    from core.types import Symbol

    stored = store.read("candles", Symbol(base="BTC", quote="USDT"), "1h")
    assert stored is not None
    assert not stored.index.duplicated().any()
    assert stored.index.is_monotonic_increasing
