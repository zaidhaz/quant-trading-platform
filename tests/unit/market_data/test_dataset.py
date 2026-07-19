from datetime import datetime

import pandas as pd
import pytest

from core.exceptions import DataGapError
from core.types import Symbol
from market_data.historical.dataset import HistoricalDataset, find_gaps
from market_data.historical.parquet_store import ParquetStore

SYMBOL = Symbol(base="BTC", quote="USDT")
HOUR = pd.Timedelta(hours=1)


def make_df(start: str, periods: int, freq: str = "1h") -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame({"close": range(periods)}, index=index)


class FakeDataset(HistoricalDataset):
    name = "fake"

    def __init__(self, store: ParquetStore) -> None:
        super().__init__(store)
        self.download_calls: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    def download(self, symbol, start, end, timeframe=None) -> pd.DataFrame:  # noqa: D401
        self.download_calls.append((pd.Timestamp(start), pd.Timestamp(end)))
        index = pd.date_range(start.ceil("h"), end.floor("h"), freq="1h", tz="UTC")
        return pd.DataFrame({"close": range(len(index))}, index=index)

    def expected_frequency(self, timeframe: str | None) -> pd.Timedelta:
        return HOUR


class SourceHasNoDataDataset(HistoricalDataset):
    """A dataset whose upstream source genuinely has nothing for the requested
    range (e.g. a symbol not yet listed, or a permanent gap) — download() always
    returns empty, simulating an unfillable gap."""

    name = "empty"

    def download(self, symbol, start, end, timeframe=None) -> pd.DataFrame:
        return pd.DataFrame(columns=["close"])

    def expected_frequency(self, timeframe: str | None) -> pd.Timedelta:
        return HOUR


class TestFindGaps:
    def test_empty_dataframe_is_one_big_gap(self) -> None:
        start, end = pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-01-02", tz="UTC")
        assert find_gaps(pd.DataFrame(), start, end, HOUR) == [(start, end)]

    def test_fully_covered_range_has_no_gaps(self) -> None:
        start, end = pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp(
            "2024-01-01 04:00", tz="UTC"
        )
        df = make_df("2024-01-01", 5)
        assert find_gaps(df, start, end, HOUR) == []

    def test_missing_prefix_and_suffix_detected(self) -> None:
        df = make_df("2024-01-01 02:00", 3)  # covers 02:00..04:00
        start, end = pd.Timestamp("2024-01-01 00:00", tz="UTC"), pd.Timestamp(
            "2024-01-01 06:00", tz="UTC"
        )

        gaps = find_gaps(df, start, end, HOUR)

        assert gaps == [
            (
                pd.Timestamp("2024-01-01 00:00", tz="UTC"),
                pd.Timestamp("2024-01-01 01:00", tz="UTC"),
            ),
            (
                pd.Timestamp("2024-01-01 05:00", tz="UTC"),
                pd.Timestamp("2024-01-01 06:00", tz="UTC"),
            ),
        ]

    def test_interior_gap_detected(self) -> None:
        early = make_df("2024-01-01 00:00", 2)  # 00:00, 01:00
        late = make_df("2024-01-01 05:00", 2)  # 05:00, 06:00
        df = pd.concat([early, late])
        start, end = pd.Timestamp("2024-01-01 00:00", tz="UTC"), pd.Timestamp(
            "2024-01-01 06:00", tz="UTC"
        )

        gaps = find_gaps(df, start, end, HOUR)

        assert gaps == [
            (pd.Timestamp("2024-01-01 02:00", tz="UTC"), pd.Timestamp("2024-01-01 04:00", tz="UTC"))
        ]


class TestHistoricalDatasetLoad:
    def test_load_raises_data_gap_error_when_nothing_stored(self, tmp_path) -> None:
        dataset = FakeDataset(ParquetStore(tmp_path))
        with pytest.raises(DataGapError):
            dataset.load(SYMBOL, datetime(2024, 1, 1), datetime(2024, 1, 2), "1h")

    def test_load_allow_gaps_returns_partial_data(self, tmp_path) -> None:
        dataset = FakeDataset(ParquetStore(tmp_path))
        dataset.store_data(SYMBOL, make_df("2024-01-01", 3), "1h")

        result = dataset.load(
            SYMBOL, datetime(2024, 1, 1), datetime(2024, 1, 1, 10), "1h", allow_gaps=True
        )

        assert len(result) == 3

    def test_ensure_range_downloads_only_the_missing_gap(self, tmp_path) -> None:
        dataset = FakeDataset(ParquetStore(tmp_path))
        dataset.store_data(SYMBOL, make_df("2024-01-01 00:00", 3), "1h")  # 00:00..02:00

        result = dataset.ensure_range(
            SYMBOL, datetime(2024, 1, 1, 0), datetime(2024, 1, 1, 5), "1h"
        )

        assert len(dataset.download_calls) == 1
        gap_start, gap_end = dataset.download_calls[0]
        assert gap_start == pd.Timestamp("2024-01-01 03:00", tz="UTC")
        assert not result.empty
        assert result.index.min() == pd.Timestamp("2024-01-01 00:00", tz="UTC")

    def test_ensure_range_no_download_when_fully_cached(self, tmp_path) -> None:
        dataset = FakeDataset(ParquetStore(tmp_path))
        dataset.store_data(SYMBOL, make_df("2024-01-01", 5), "1h")

        dataset.ensure_range(SYMBOL, datetime(2024, 1, 1, 0), datetime(2024, 1, 1, 4), "1h")

        assert dataset.download_calls == []

    def test_ensure_range_raises_when_source_has_no_data_for_the_gap(self, tmp_path) -> None:
        # This is the strict-by-default contract: ensure_range() must not silently
        # return a partial range just because the upstream source has nothing for
        # part of it — the caller needs to know the range is incomplete.
        dataset = SourceHasNoDataDataset(ParquetStore(tmp_path))

        with pytest.raises(DataGapError):
            dataset.ensure_range(SYMBOL, datetime(2024, 1, 1, 0), datetime(2024, 1, 1, 5), "1h")

    def test_ensure_range_allow_gaps_returns_partial_data_instead_of_raising(
        self, tmp_path
    ) -> None:
        dataset = SourceHasNoDataDataset(ParquetStore(tmp_path))

        result = dataset.ensure_range(
            SYMBOL, datetime(2024, 1, 1, 0), datetime(2024, 1, 1, 5), "1h", allow_gaps=True
        )

        assert result.empty
