from market_data.historical.candles_dataset import klines_to_dataframe
from market_data.historical.funding_rate_dataset import funding_rows_to_dataframe

SAMPLE_KLINE = [
    1704067200000,  # open time
    "42000.10",
    "42500.00",
    "41900.50",
    "42300.75",
    "1234.56",
    1704070799999,  # close time
    "52000000.00",
    1500,
    "600.0",
    "25000000.0",
    "0",
]


def test_klines_to_dataframe_parses_ohlcv() -> None:
    df = klines_to_dataframe([SAMPLE_KLINE])

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.iloc[0]["open"] == 42000.10
    assert df.iloc[0]["close"] == 42300.75
    assert df.index[0].tzinfo is not None


def test_klines_to_dataframe_empty_input() -> None:
    df = klines_to_dataframe([])
    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


SAMPLE_FUNDING_ROW = {
    "symbol": "BTCUSDT",
    "fundingTime": 1704067200000,
    "fundingRate": "0.00010000",
    "markPrice": "42250.30",
}


def test_funding_rows_to_dataframe_parses_rate_and_price() -> None:
    df = funding_rows_to_dataframe([SAMPLE_FUNDING_ROW])

    assert df.iloc[0]["funding_rate"] == 0.0001
    assert df.iloc[0]["mark_price"] == 42250.30


def test_funding_rows_to_dataframe_handles_missing_mark_price() -> None:
    row = {k: v for k, v in SAMPLE_FUNDING_ROW.items() if k != "markPrice"}
    df = funding_rows_to_dataframe([row])
    assert df.iloc[0]["mark_price"] is None


def test_funding_rows_to_dataframe_empty_input() -> None:
    df = funding_rows_to_dataframe([])
    assert df.empty
