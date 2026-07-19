import pandas as pd
import pytest


@pytest.fixture
def deterministic_long_df() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=6, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100, 100, 100, 100, 90, 90],
            "high": [101, 101, 101, 101, 91, 91],
            "low": [99, 99, 99, 94, 89, 89],
            "close": [100, 100, 100, 95, 90, 90],
            "volume": [10.0] * 6,
        },
        index=index,
    )


@pytest.fixture
def deterministic_short_df() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=6, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100, 100, 100, 100, 106, 106],
            "high": [101, 101, 101, 106, 107, 107],
            "low": [99, 99, 99, 99, 105, 105],
            "close": [100, 100, 100, 105, 106, 106],
            "volume": [10.0] * 6,
        },
        index=index,
    )
