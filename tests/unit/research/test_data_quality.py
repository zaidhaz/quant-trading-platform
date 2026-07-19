import pandas as pd

from research import data_quality as dq


def _clean_hourly_df(n: int = 100) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10.0},
        index=index,
    )


def test_clean_data_reports_clean() -> None:
    df = _clean_hourly_df()

    fixed, report = dq.repair_and_check_candles("BTCUSDT", "1h", df)

    assert report.clean
    assert report.duplicates_removed == 0
    assert not report.was_unsorted
    assert len(fixed) == len(df)


def test_duplicate_timestamps_are_repaired_not_flagged() -> None:
    df = _clean_hourly_df()
    corrupted = pd.concat([df, df.iloc[[5]]])

    fixed, report = dq.repair_and_check_candles("BTCUSDT", "1h", corrupted)

    assert report.duplicates_removed == 1
    assert len(fixed) == len(df)
    assert not fixed.index.duplicated().any()


def test_unsorted_data_is_repaired() -> None:
    df = _clean_hourly_df()
    shuffled = df.sample(frac=1.0, random_state=1)

    fixed, report = dq.repair_and_check_candles("BTCUSDT", "1h", shuffled)

    assert report.was_unsorted
    assert fixed.index.is_monotonic_increasing


def test_gap_is_flagged_never_fabricated() -> None:
    df = _clean_hourly_df(n=50)
    with_gap = df.drop(df.index[20:25])

    fixed, report = dq.repair_and_check_candles("BTCUSDT", "1h", with_gap)

    assert len(report.gaps) == 1
    assert report.gaps[0].missing_bars == 5
    assert len(fixed) == len(with_gap)  # nothing invented


def test_invalid_ohlc_and_nan_are_flagged_not_silently_dropped() -> None:
    df = _clean_hourly_df()
    corrupted = df.copy()
    corrupted.iloc[10, corrupted.columns.get_loc("high")] = 50.0  # high < low now
    corrupted.iloc[20, corrupted.columns.get_loc("close")] = float("nan")

    fixed, report = dq.repair_and_check_candles("BTCUSDT", "1h", corrupted)

    assert report.invalid_ohlc_rows == 1
    assert report.nan_price_rows == 1
    assert not report.clean
    assert len(fixed) == len(corrupted)  # flagged in place, not removed


def test_volume_outlier_detected() -> None:
    df = _clean_hourly_df(n=300)
    corrupted = df.copy()
    corrupted.iloc[250, corrupted.columns.get_loc("volume")] = 10_000.0

    _, report = dq.repair_and_check_candles("BTCUSDT", "1h", corrupted)

    assert report.volume_outlier_rows >= 1


def test_candles_report_notes_open_interest_is_checked_separately() -> None:
    df = _clean_hourly_df()

    _, report = dq.repair_and_check_candles("BTCUSDT", "1h", df)

    assert "N/A" in report.open_interest_status
    assert "repair_and_check_open_interest" in report.open_interest_status


def test_funding_out_of_range_is_flagged() -> None:
    index = pd.date_range("2024-01-01", periods=10, freq="8h", tz="UTC")
    df = pd.DataFrame({"funding_rate": 0.0001, "mark_price": 100.0}, index=index)
    df.iloc[3, df.columns.get_loc("funding_rate")] = 0.02  # way outside +/-0.75%

    _, report = dq.repair_and_check_funding("BTCUSDT", df)

    assert report.funding_out_of_range_rows == 1
    assert not report.clean


def test_open_interest_clean_data_reports_clean_and_sets_own_status() -> None:
    index = pd.date_range("2024-01-01", periods=20, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {"sum_open_interest": 1000.0, "sum_open_interest_value": 50_000_000.0}, index=index
    )

    _, report = dq.repair_and_check_open_interest("BTCUSDT", df)

    assert report.clean
    assert "20 rows" in report.open_interest_status
    assert "N/A" not in report.open_interest_status


def test_open_interest_negative_value_is_flagged_not_repaired() -> None:
    index = pd.date_range("2024-01-01", periods=5, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {"sum_open_interest": 1000.0, "sum_open_interest_value": 50_000_000.0}, index=index
    )
    df.iloc[2, df.columns.get_loc("sum_open_interest")] = -1.0

    working, report = dq.repair_and_check_open_interest("BTCUSDT", df)

    assert report.negative_volume_rows == 1
    assert not report.clean
    assert working.iloc[2]["sum_open_interest"] == -1.0  # flagged, never silently fixed


def test_format_report_is_human_readable() -> None:
    df = _clean_hourly_df()
    _, report = dq.repair_and_check_candles("BTCUSDT", "1h", df)

    text = dq.format_report(report)

    assert "BTCUSDT" in text
    assert "CLEAN" in text
