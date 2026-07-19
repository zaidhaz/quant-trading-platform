import pandas as pd
import pytest

from core.exceptions import ValidationError
from market_data.historical.validation import validate_candles


def make_df(**overrides) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    data = {
        "open": [100.0, 101.0, 102.0],
        "high": [101.0, 102.0, 103.0],
        "low": [99.0, 100.0, 101.0],
        "close": [100.5, 101.5, 102.5],
        "volume": [10.0, 10.0, 10.0],
    }
    df = pd.DataFrame(data, index=index)
    for col, values in overrides.items():
        df[col] = values
    return df


def test_valid_data_passes() -> None:
    validate_candles(make_df())  # no exception


def test_empty_dataframe_is_a_noop() -> None:
    validate_candles(pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))


def test_missing_required_column_rejected() -> None:
    df = make_df().drop(columns=["volume"])
    with pytest.raises(ValidationError, match="missing required column"):
        validate_candles(df)


def test_duplicate_timestamp_rejected() -> None:
    df = make_df()
    df.index = pd.DatetimeIndex([df.index[0], df.index[0], df.index[2]])
    with pytest.raises(ValidationError, match="duplicate timestamp"):
        validate_candles(df)


def test_out_of_order_timestamp_rejected() -> None:
    df = make_df()
    df.index = pd.DatetimeIndex([df.index[0], df.index[2], df.index[1]])
    with pytest.raises(ValidationError, match="not in increasing order"):
        validate_candles(df)


def test_nan_price_rejected() -> None:
    df = make_df(close=[100.5, float("nan"), 102.5])
    with pytest.raises(ValidationError, match="NaN price"):
        validate_candles(df)


def test_nan_volume_rejected() -> None:
    df = make_df(volume=[10.0, float("nan"), 10.0])
    with pytest.raises(ValidationError, match="NaN volume"):
        validate_candles(df)


def test_negative_price_rejected() -> None:
    df = make_df(low=[99.0, -100.0, 101.0])
    with pytest.raises(ValidationError, match="non-positive price"):
        validate_candles(df)


def test_zero_price_rejected() -> None:
    df = make_df(open=[100.0, 0.0, 102.0])
    with pytest.raises(ValidationError, match="non-positive price"):
        validate_candles(df)


def test_negative_volume_rejected() -> None:
    df = make_df(volume=[10.0, -5.0, 10.0])
    with pytest.raises(ValidationError, match="negative volume"):
        validate_candles(df)


def test_zero_volume_is_valid() -> None:
    validate_candles(make_df(volume=[10.0, 0.0, 10.0]))  # legitimate illiquid bar


def test_high_below_low_rejected() -> None:
    df = make_df(high=[101.0, 95.0, 103.0], low=[99.0, 100.0, 101.0])
    with pytest.raises(ValidationError, match="high < low"):
        validate_candles(df)


def test_open_outside_range_rejected() -> None:
    df = make_df(open=[100.0, 999.0, 102.0])
    with pytest.raises(ValidationError, match="open price outside"):
        validate_candles(df)


def test_close_outside_range_rejected() -> None:
    df = make_df(close=[100.5, 500.0, 102.5])
    with pytest.raises(ValidationError, match="close price outside"):
        validate_candles(df)


def test_open_equal_to_high_is_valid_boundary() -> None:
    df = make_df(open=[101.0, 101.0, 103.0], high=[101.0, 102.0, 103.0])
    validate_candles(df)  # open == high is a valid boundary, not "outside"
