"""Thin REST client for Binance Futures historical endpoints.

Deliberately not CCXT here: this is a narrow, high-volume pagination loop against
two specific endpoints (klines, funding rate history), and a hand-rolled client
keeps the retry/pagination logic visible and easy to reason about. Live trading
(Part B) uses CCXT/CCXT Pro per docs/ARCHITECTURE.md — that's a different access
pattern (single requests, WS streams) where CCXT's broader normalization earns its
keep.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

KLINES_LIMIT = 1500
FUNDING_RATE_LIMIT = 1000
MAX_RETRIES = 5


def _to_ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


class BinanceFuturesClient:
    def __init__(self, base_url: str = "https://fapi.binance.com", timeout: float = 10.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BinanceFuturesClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

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

    def get_klines(
        self, symbol_native: str, interval: str, start: datetime, end: datetime
    ) -> list[list[Any]]:
        """Paginate /fapi/v1/klines across [start, end]. Returns raw Binance rows."""
        rows: list[list[Any]] = []
        cursor_ms = _to_ms(start)
        end_ms = _to_ms(end)
        while cursor_ms <= end_ms:
            batch = self._get(
                "/fapi/v1/klines",
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
