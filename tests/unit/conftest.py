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


def _df(open_, high, low, close, n=None):
    n = n or len(open_)
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": [10.0] * n}, index=index
    )


@pytest.fixture
def gapped_entry_df() -> pd.DataFrame:
    """Decision bar (index 2) closes at 95; the *next* bar opens at 110 — a bar
    later and a materially different price, so a same-bar-fill bug and a
    next-bar-open fill are numerically distinguishable."""
    return _df(
        open_=[100, 100, 100, 110, 110, 110],
        high=[101, 101, 101, 111, 111, 111],
        low=[99, 99, 94, 109, 109, 109],
        close=[100, 100, 95, 110, 110, 110],
    )


@pytest.fixture
def gap_through_stop_long_df() -> pd.DataFrame:
    """Position opens (bar 2, open=100) with a 95 stop; bar 3 gaps to open=90,
    below the stop, before the stop's own level was ever touched intrabar."""
    return _df(
        open_=[100, 100, 100, 90, 90],
        high=[101, 101, 101, 92, 92],
        low=[99, 99, 99, 88, 88],
        close=[100, 100, 100, 91, 91],
    )


@pytest.fixture
def gap_through_take_profit_long_df() -> pd.DataFrame:
    """Position opens (bar 2, open=100) with a 105 target; bar 3 gaps to
    open=110, above the target, before the target's level was ever touched."""
    return _df(
        open_=[100, 100, 100, 110, 110],
        high=[101, 101, 101, 111, 111],
        low=[99, 99, 99, 109, 109],
        close=[100, 100, 100, 110, 110],
    )


@pytest.fixture
def gap_through_stop_short_df() -> pd.DataFrame:
    """Short opens (bar 2, open=100) with a 106 stop; bar 3 gaps to open=110,
    above the stop."""
    return _df(
        open_=[100, 100, 100, 110, 110],
        high=[101, 101, 101, 112, 112],
        low=[99, 99, 99, 108, 108],
        close=[100, 100, 100, 110, 110],
    )


@pytest.fixture
def gap_through_take_profit_short_df() -> pd.DataFrame:
    """Short opens (bar 2, open=100) with a 95 target; bar 3 gaps to open=90,
    below the target."""
    return _df(
        open_=[100, 100, 100, 90, 90],
        high=[101, 101, 101, 92, 92],
        low=[99, 99, 99, 88, 88],
        close=[100, 100, 100, 91, 91],
    )


@pytest.fixture
def crash_df() -> pd.DataFrame:
    """Position opens (bar 2, open=100); bar 3 crashes essentially to zero — used
    to exercise account-ruin handling for an unhedged, oversized position."""
    return _df(
        open_=[100, 100, 100, 1, 1, 1],
        high=[101, 101, 101, 1, 1, 1],
        low=[99, 99, 99, 1, 1, 1],
        close=[100, 100, 100, 1, 1, 1],
    )
