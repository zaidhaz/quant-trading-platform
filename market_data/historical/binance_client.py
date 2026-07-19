"""Thin REST client for Binance USDⓈ-M Futures historical endpoints.

Deliberately not CCXT here: this is a narrow, high-volume pagination loop against
a handful of specific endpoints, and a hand-rolled client keeps the retry/pagination
logic visible and easy to reason about. Live trading (Part B) uses CCXT/CCXT Pro per
docs/ARCHITECTURE.md — that's a different access pattern (single requests, WS
streams) where CCXT's broader normalization earns its keep.

Endpoint coverage (see docs/DATA_LAYER.md for the full picture, including what
each one does and does not give us historically):
- `/fapi/v1/klines` — OHLCV candles (any timeframe)
- `/fapi/v1/fundingRate` — funding rate history
- `/fapi/v1/markPriceKlines` — mark price, OHLC-shaped
- `/fapi/v1/premiumIndexKlines` — premium/discount index, OHLC-shaped
- `/futures/data/openInterestHist` — open interest history, capped by Binance to
  roughly the trailing 30 days regardless of the requested start (see
  `OPEN_INTEREST_MAX_LOOKBACK_DAYS` in `open_interest_dataset.py`)
- `/fapi/v1/exchangeInfo` — symbol metadata, including `onboardDate` (listing date)

**Not independently verified against the live API in this environment** —
outbound access to `fapi.binance.com` is blocked by this sandbox's network
policy (confirmed directly: a `CONNECT` to the host is rejected with a 403
policy denial, not a timeout). Every endpoint shape and documented limitation
here is implemented from Binance's published API documentation and tested
against a mocked client (`tests/unit/market_data/test_binance_client.py`), not
against a real response. This client needs no changes to work once network
access exists — only that live verification does.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx

KLINES_LIMIT = 1500
FUNDING_RATE_LIMIT = 1000
OPEN_INTEREST_LIMIT = 500
MAX_RETRIES = 5

# Predates Binance Futures' own launch (2019-09) by a wide margin — used as the
# "before any possible history" probe point for earliest-available-data
# detection (see find_earliest_*). Never used as a claim about when data
# actually starts, only as a safe lower bound to search from.
PROBE_FLOOR = datetime(2015, 1, 1, tzinfo=UTC)


def _to_ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


def _now_ms() -> int:
    return _to_ms(datetime.now(UTC))


class BinanceFuturesClient:
    def __init__(self, base_url: str = "https://fapi.binance.com", timeout: float = 10.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BinanceFuturesClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def ping(self, timeout: float = 5.0) -> bool:
        """One lightweight, no-retry connectivity check against
        `/fapi/v1/ping` (Binance's documented no-op health-check endpoint).
        Deliberately bypasses `_get`'s 5-retry/exponential-backoff loop (up to
        ~60s) — this exists specifically so a caller (e.g.
        `research/data_loader.py`'s real-data-first attempt) can fail fast and
        fall back to a different data source in a couple of seconds instead of
        paying that full retry cost per dataset/timeframe/symbol when the
        network is simply unreachable, as it is in this sandbox today."""
        try:
            response = self._client.get("/fapi/v1/ping", timeout=timeout)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def _get(self, path: str, params: dict[str, str | int]) -> Any:
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._client.get(path, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    time.sleep(min(2**attempt, 30))
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as exc:
                last_exc = exc
                time.sleep(min(2**attempt, 30))
        raise ConnectionError(
            f"Binance request to {path} failed after {MAX_RETRIES} retries"
        ) from last_exc

    # -- OHLCV candles -----------------------------------------------------

    def get_klines(
        self, symbol_native: str, interval: str, start: datetime, end: datetime
    ) -> list[list[Any]]:
        """Paginate /fapi/v1/klines across [start, end]. Returns raw Binance rows."""
        return self._paginate_klines("/fapi/v1/klines", symbol_native, interval, start, end)

    def find_earliest_kline_open_time(self, symbol_native: str, interval: str) -> datetime | None:
        """Earliest available candle for `interval`, via a single `limit=1` request
        spanning [PROBE_FLOOR, now] — Binance returns the first candle that
        actually exists in the requested range, so this needs no pagination or
        binary search. Returns None if the symbol/interval has no data at all
        (e.g. an unlisted or misspelled symbol)."""
        return self._find_earliest(
            "/fapi/v1/klines", {"symbol": symbol_native, "interval": interval}
        )

    # -- Funding rate history -----------------------------------------------

    def get_funding_rate_history(
        self, symbol_native: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """Paginate /fapi/v1/fundingRate across [start, end]."""
        rows: list[dict[str, Any]] = []
        cursor_ms = _to_ms(start)
        end_ms = _to_ms(end)
        while cursor_ms <= end_ms:
            batch = self._get(
                "/fapi/v1/fundingRate",
                {
                    "symbol": symbol_native,
                    "startTime": cursor_ms,
                    "endTime": end_ms,
                    "limit": FUNDING_RATE_LIMIT,
                },
            )
            if not batch:
                break
            rows.extend(batch)
            last_time = int(batch[-1]["fundingTime"])
            if len(batch) < FUNDING_RATE_LIMIT or last_time <= cursor_ms:
                break
            cursor_ms = last_time + 1
        return rows

    def find_earliest_funding_time(self, symbol_native: str) -> datetime | None:
        batch = self._get(
            "/fapi/v1/fundingRate",
            {
                "symbol": symbol_native,
                "startTime": _to_ms(PROBE_FLOOR),
                "endTime": _now_ms(),
                "limit": 1,
            },
        )
        if not batch:
            return None
        return datetime.fromtimestamp(int(batch[0]["fundingTime"]) / 1000, tz=UTC)

    # -- Mark price / premium index (both OHLC-shaped, like klines) --------

    def get_mark_price_klines(
        self, symbol_native: str, interval: str, start: datetime, end: datetime
    ) -> list[list[Any]]:
        """Paginate /fapi/v1/markPriceKlines. Same row shape as regular klines,
        except the "volume"-position field is a Binance-side placeholder (mark
        price has no real trade volume) — callers must not treat it as real
        volume; see `mark_price_dataset.py`."""
        return self._paginate_klines(
            "/fapi/v1/markPriceKlines", symbol_native, interval, start, end
        )

    def find_earliest_mark_price_time(self, symbol_native: str, interval: str) -> datetime | None:
        return self._find_earliest(
            "/fapi/v1/markPriceKlines", {"symbol": symbol_native, "interval": interval}
        )

    def get_premium_index_klines(
        self, symbol_native: str, interval: str, start: datetime, end: datetime
    ) -> list[list[Any]]:
        """Paginate /fapi/v1/premiumIndexKlines — same row shape/caveat as
        `get_mark_price_klines`."""
        return self._paginate_klines(
            "/fapi/v1/premiumIndexKlines", symbol_native, interval, start, end
        )

    def find_earliest_premium_index_time(
        self, symbol_native: str, interval: str
    ) -> datetime | None:
        return self._find_earliest(
            "/fapi/v1/premiumIndexKlines", {"symbol": symbol_native, "interval": interval}
        )

    # -- Open interest history (Binance-side ~30-day retention cap) --------

    def get_open_interest_hist(
        self, symbol_native: str, period: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """Paginate /futures/data/openInterestHist across [start, end]. Binance
        does not retain data older than roughly 30 days for this endpoint
        regardless of `start` — see `open_interest_dataset.py`'s
        `OPEN_INTEREST_MAX_LOOKBACK_DAYS`, which clamps the effective start
        before this method is ever called with an out-of-range one."""
        rows: list[dict[str, Any]] = []
        cursor_ms = _to_ms(start)
        end_ms = _to_ms(end)
        while cursor_ms <= end_ms:
            batch = self._get(
                "/futures/data/openInterestHist",
                {
                    "symbol": symbol_native,
                    "period": period,
                    "startTime": cursor_ms,
                    "endTime": end_ms,
                    "limit": OPEN_INTEREST_LIMIT,
                },
            )
            if not batch:
                break
            rows.extend(batch)
            last_time = int(batch[-1]["timestamp"])
            if len(batch) < OPEN_INTEREST_LIMIT or last_time <= cursor_ms:
                break
            cursor_ms = last_time + 1
        return rows

    # -- Exchange info (symbol metadata, incl. listing date) ----------------

    def get_exchange_info(self) -> dict[str, Any]:
        """GET /fapi/v1/exchangeInfo — no params, returns metadata for every
        symbol Binance Futures currently lists (status, contract type,
        precision/filters, and `onboardDate`). See `exchange_info.py` for a
        typed, single-symbol view of this (`get_symbol_info()`), including
        `onboardDate` parsed into a `datetime`."""
        return self._get("/fapi/v1/exchangeInfo", {})

    # -- shared helpers -------------------------------------------------

    def _paginate_klines(
        self, path: str, symbol_native: str, interval: str, start: datetime, end: datetime
    ) -> list[list[Any]]:
        rows: list[list[Any]] = []
        cursor_ms = _to_ms(start)
        end_ms = _to_ms(end)
        while cursor_ms <= end_ms:
            batch = self._get(
                path,
                {
                    "symbol": symbol_native,
                    "interval": interval,
                    "startTime": cursor_ms,
                    "endTime": end_ms,
                    "limit": KLINES_LIMIT,
                },
            )
            if not batch:
                break
            rows.extend(batch)
            last_open_time = int(batch[-1][0])
            if len(batch) < KLINES_LIMIT or last_open_time <= cursor_ms:
                break
            cursor_ms = last_open_time + 1
        return rows

    def _find_earliest(self, path: str, base_params: dict[str, str]) -> datetime | None:
        batch = self._get(
            path,
            {**base_params, "startTime": _to_ms(PROBE_FLOOR), "endTime": _now_ms(), "limit": 1},
        )
        if not batch:
            return None
        return datetime.fromtimestamp(int(batch[0][0]) / 1000, tz=UTC)
