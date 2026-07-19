import pandas as pd
import pytest

from core.types import Symbol
from market_data.historical.parquet_store import ParquetStore

SYMBOL = Symbol(base="BTC", quote="USDT")


def make_df(start: str, periods: int, freq: str = "1h") -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame({"close": range(periods)}, index=index)


@pytest.fixture
def store(tmp_path) -> ParquetStore:
    return ParquetStore(tmp_path)


def test_read_missing_returns_none(store: ParquetStore) -> None:
    assert store.read("candles", SYMBOL, "1h") is None


def test_write_then_read_round_trips(store: ParquetStore) -> None:
    df = make_df("2024-01-01", 5)
    store.write("candles", SYMBOL, df, "1h")

    result = store.read("candles", SYMBOL, "1h")

    assert result is not None
    assert len(result) == 5
    assert result["close"].tolist() == [0, 1, 2, 3, 4]


def test_write_merges_and_dedups_overlapping_ranges(store: ParquetStore) -> None:
    first = make_df("2024-01-01", 5)  # 00:00..04:00
    second = make_df("2024-01-01 03:00", 5)  # 03:00..07:00, overlaps 3 rows
    store.write("candles", SYMBOL, first, "1h")
    store.write("candles", SYMBOL, second, "1h")

    result = store.read("candles", SYMBOL, "1h")

    assert result is not None
    assert len(result) == 8  # 00:00..07:00, no duplicates
    assert result.index.is_monotonic_increasing
    # overlapping rows should keep the second write's values ("keep=last")
    assert result.loc["2024-01-01 03:00:00+00:00", "close"] == 0


def test_date_range_reflects_stored_data(store: ParquetStore) -> None:
    store.write("candles", SYMBOL, make_df("2024-01-01", 5), "1h")

    lo, hi = store.date_range("candles", SYMBOL, "1h")

    assert lo == pd.Timestamp("2024-01-01", tz="UTC")
    assert hi == pd.Timestamp("2024-01-01 04:00", tz="UTC")


def test_date_range_none_when_nothing_stored(store: ParquetStore) -> None:
    assert store.date_range("candles", SYMBOL, "1h") is None


def test_different_symbols_are_isolated(store: ParquetStore) -> None:
    other = Symbol(base="ETH", quote="USDT")
    store.write("candles", SYMBOL, make_df("2024-01-01", 3), "1h")

    assert store.read("candles", other, "1h") is None
