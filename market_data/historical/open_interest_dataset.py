"""Open interest history — `/futures/data/openInterestHist`.

**Documented limitation, not a code gap**: Binance does not retain data older
than roughly 30 days for this endpoint, regardless of what `start` is
requested — this is stated in Binance's own API documentation, not something
discovered by fabricating a shorter range ourselves. `OPEN_INTEREST_MAX_LOOKBACK_DAYS`
encodes that limit; `download()` clamps its effective start to it so a caller
asking for full history gets exactly what Binance can actually provide (the
trailing window), not a doomed repeated attempt at unavailable history, and
not a silently-shortened response the caller has no way to notice.

**Not independently re-verified live** in this session — network to
`fapi.binance.com` is blocked here (see `binance_client.py`'s module
docstring) — this is Binance's documented behavior, implemented and tested
against a mock, ready to confirm against the real endpoint the moment access
exists.

This is why `docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md` §0/§1.7 treats
`oi_flush_confirmed` as inert by default rather than assuming full-history OI
would ever be available: even once this dataset is wired up for real, it can
only ever cover the last ~30 days of any backtest, never a multi-year run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from core.types import Symbol
from market_data.historical.binance_client import BinanceFuturesClient
from market_data.historical.dataset import HistoricalDataset, to_utc_timestamp
from market_data.historical.parquet_store import ParquetStore

OPEN_INTEREST_MAX_LOOKBACK_DAYS = 30

_PERIOD_TO_TIMEDELTA = {
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "2h": pd.Timedelta(hours=2),
    "4h": pd.Timedelta(hours=4),
    "6h": pd.Timedelta(hours=6),
    "12h": pd.Timedelta(hours=12),
    "1d": pd.Timedelta(days=1),
}

_COLUMNS = ["sum_open_interest", "sum_open_interest_value"]


def open_interest_rows_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=_COLUMNS)
    index = pd.to_datetime([int(r["timestamp"]) for r in rows], unit="ms", utc=True)
    df = pd.DataFrame(
        {
            "sum_open_interest": [float(r["sumOpenInterest"]) for r in rows],
            "sum_open_interest_value": [float(r["sumOpenInterestValue"]) for r in rows],
        },
        index=index,
    )
    df.index.name = "ts"
    return df


class OpenInterestDataset(HistoricalDataset):
    name = "open_interest"

    def __init__(
        self,
        store: ParquetStore,
        client: BinanceFuturesClient | None = None,
        period: str = "5m",
    ) -> None:
        super().__init__(store)
        if period not in _PERIOD_TO_TIMEDELTA:
            raise ValueError(f"Unsupported open interest period: {period!r}")
        self._client = client or BinanceFuturesClient()
        self.period = period

    def download(
        self, symbol: Symbol, start: datetime, end: datetime, timeframe: str | None = None
    ) -> pd.DataFrame:
        now = datetime.now(UTC)
        retention_floor = now - timedelta(days=OPEN_INTEREST_MAX_LOOKBACK_DAYS)
        effective_start = max(to_utc_timestamp(start), to_utc_timestamp(retention_floor))
        effective_end = to_utc_timestamp(end)
        if effective_start > effective_end:
            return pd.DataFrame(columns=_COLUMNS)
        rows = self._client.get_open_interest_hist(
            symbol.native(), self.period, effective_start, effective_end
        )
        return open_interest_rows_to_dataframe(rows)

    def expected_frequency(self, timeframe: str | None) -> pd.Timedelta:
        return _PERIOD_TO_TIMEDELTA[self.period]

    def find_earliest_available(
        self, symbol: Symbol, timeframe: str | None = None
    ) -> datetime | None:
        """Deliberately **not** an empirical "true earliest" probe like the other
        datasets — Binance's retention cap means the true earliest available
        point for this endpoint is always `now - OPEN_INTEREST_MAX_LOOKBACK_DAYS`,
        a fixed, documented floor rather than something to detect per symbol."""
        return datetime.now(UTC) - timedelta(days=OPEN_INTEREST_MAX_LOOKBACK_DAYS)
