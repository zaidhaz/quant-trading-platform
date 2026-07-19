"""Extension point for historical dataset types.

Adding a new dataset (open interest, liquidations, CVD, ...) later means writing one
`HistoricalDataset` subclass — implementing `download()` and `expected_frequency()` —
without touching `ParquetStore`, `backtesting/data_feed.py`, or anything downstream.
`candles_dataset.py` and `funding_rate_dataset.py` are the first two implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime

import pandas as pd

from core.exceptions import DataGapError
from core.types import Symbol
from market_data.historical.parquet_store import ParquetStore


def to_utc_timestamp(ts: datetime | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def find_gaps(
    df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, expected_freq: pd.Timedelta
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return [start, end] sub-ranges of [start, end] not covered by `df`'s index."""
    if df.empty:
        return [(start, end)]

    gaps: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    idx = df.index.sort_values()

    if idx.min() - start > expected_freq:
        gaps.append((start, idx.min() - expected_freq))

    diffs = idx.to_series().diff()
    for loc in diffs[diffs > expected_freq * 1.5].index:
        pos = idx.get_loc(loc)
        prev_ts = idx[pos - 1]
        gaps.append((prev_ts + expected_freq, loc - expected_freq))

    if end - idx.max() > expected_freq:
        gaps.append((idx.max() + expected_freq, end))

    return gaps


class HistoricalDataset(ABC):
    name: str

    def __init__(self, store: ParquetStore) -> None:
        self.store = store

    @abstractmethod
    def download(
        self, symbol: Symbol, start: datetime, end: datetime, timeframe: str | None = None
    ) -> pd.DataFrame:
        """Fetch raw data from the source for [start, end], indexed by UTC timestamp.
        `timeframe` is ignored by datasets that don't have one (e.g. funding rate)."""

    @abstractmethod
    def expected_frequency(self, timeframe: str | None) -> pd.Timedelta:
        """Nominal spacing between consecutive rows, used for gap detection."""

    def find_earliest_available(
        self, symbol: Symbol, timeframe: str | None = None
    ) -> datetime | None:
        """The real earliest timestamp this source has data for `symbol`
        (listing date, effectively) — never a hardcoded assumption. Returns
        None if the source has no data at all for this symbol. Not every
        dataset overrides this (the default raises rather than silently
        returning something wrong); see `candles_dataset.py` /
        `funding_rate_dataset.py` / `mark_price_dataset.py` /
        `premium_index_dataset.py` for real implementations, and
        `open_interest_dataset.py` for why open interest's version is
        deliberately not a "true earliest" but a documented retention floor."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement find_earliest_available() "
            "— override it or pass an explicit start date to ensure_range()."
        )

    def sync_full_history(
        self, symbol: Symbol, timeframe: str | None = None, end: datetime | None = None
    ) -> pd.DataFrame:
        """The "never hardcode a date range" entry point: auto-detects the
        earliest available start via `find_earliest_available()`, then syncs
        through `end` (default: now) via the existing incremental, gap-only,
        resumable `ensure_range()`. Raises `DataGapError` if the source has no
        data for this symbol at all (distinct from a partial-history gap)."""
        earliest = self.find_earliest_available(symbol, timeframe)
        if earliest is None:
            raise DataGapError(
                f"{self.name} has no data available at all for {symbol} [{timeframe}] "
                "— nothing to sync (not a gap, an absence)"
            )
        end_dt = end or datetime.now(UTC)
        return self.ensure_range(symbol, earliest, end_dt, timeframe)

    def store_data(self, symbol: Symbol, df: pd.DataFrame, timeframe: str | None = None) -> None:
        self.store.write(self.name, symbol, df, timeframe)

    def load(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        timeframe: str | None = None,
        allow_gaps: bool = False,
    ) -> pd.DataFrame:
        """Read cached data for [start, end]. Raises DataGapError if the range isn't
        fully covered, unless `allow_gaps=True` — never silently returns a partial range."""
        start_ts, end_ts = to_utc_timestamp(start), to_utc_timestamp(end)
        df = self.store.read(self.name, symbol, timeframe)
        window = (
            df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
            if df is not None
            else pd.DataFrame()
        )

        if not allow_gaps:
            gaps = find_gaps(window, start_ts, end_ts, self.expected_frequency(timeframe))
            if gaps:
                raise DataGapError(
                    f"{self.name} for {symbol} [{timeframe}] has gaps in "
                    f"[{start_ts}, {end_ts}]: {gaps}. Call ensure_range() to backfill."
                )
        return window

    def ensure_range(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        timeframe: str | None = None,
        allow_gaps: bool = False,
    ) -> pd.DataFrame:
        """Download+store anything missing in [start, end], then return the full
        range. Strict by default: if the source genuinely has no data for part of
        the range (a symbol not yet listed, an exchange outage, ...), this raises
        DataGapError rather than silently handing back an incomplete range — a
        caller who explicitly wants to tolerate that must pass `allow_gaps=True`."""
        start_ts, end_ts = to_utc_timestamp(start), to_utc_timestamp(end)
        existing = self.load(symbol, start_ts, end_ts, timeframe, allow_gaps=True)
        gaps = find_gaps(existing, start_ts, end_ts, self.expected_frequency(timeframe))
        for gap_start, gap_end in gaps:
            fresh = self.download(symbol, gap_start, gap_end, timeframe)
            if not fresh.empty:
                self.store_data(symbol, fresh, timeframe)
        return self.load(symbol, start_ts, end_ts, timeframe, allow_gaps=allow_gaps)
