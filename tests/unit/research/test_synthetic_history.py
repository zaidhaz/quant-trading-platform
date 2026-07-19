from datetime import UTC, datetime

from research import synthetic_history as sh

START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 3, 1, tzinfo=UTC)


def test_generate_ohlcv_is_deterministic() -> None:
    a = sh.generate_ohlcv("BTCUSDT", "1h", START, END)
    b = sh.generate_ohlcv("BTCUSDT", "1h", START, END)

    assert a.equals(b)


def test_generate_ohlcv_different_symbols_differ() -> None:
    btc = sh.generate_ohlcv("BTCUSDT", "1h", START, END)
    eth = sh.generate_ohlcv("ETHUSDT", "1h", START, END)

    assert not btc["close"].equals(eth["close"])


def test_generate_ohlcv_respects_ohlc_invariants() -> None:
    df = sh.generate_ohlcv("BTCUSDT", "1h", START, END)

    assert (df["high"] >= df[["open", "close", "low"]].max(axis=1)).all()
    assert (df["low"] <= df[["open", "close", "high"]].min(axis=1)).all()
    assert (df["volume"] > 0).all()
    assert (df["open"] > 0).all() and (df["close"] > 0).all()


def test_generate_ohlcv_row_count_matches_timeframe() -> None:
    hourly = sh.generate_ohlcv("BTCUSDT", "1h", START, END)
    minute = sh.generate_ohlcv("BTCUSDT", "1m", START, END)

    assert len(minute) == len(hourly) * 60


def test_generate_funding_is_deterministic_and_bounded() -> None:
    a = sh.generate_funding("ETHUSDT", START, END)
    b = sh.generate_funding("ETHUSDT", START, END)

    assert a.equals(b)
    assert (a["funding_rate"].abs() <= 0.0075).all()


def test_regime_schedule_covers_the_full_range_with_no_overlap() -> None:
    import pandas as pd

    schedule = sh.build_regime_schedule("BTCUSDT", pd.Timestamp(START), pd.Timestamp(END))

    assert schedule[0].start == pd.Timestamp(START)
    assert schedule[-1].end == pd.Timestamp(END)
    for prev, nxt in zip(schedule, schedule[1:], strict=False):
        assert prev.end == nxt.start


def test_dataset_summary_reports_synthetic_provenance() -> None:
    df = sh.generate_ohlcv("BTCUSDT", "1h", START, END)

    summary = sh.dataset_summary("BTCUSDT", "1h", df)

    assert "SYNTHETIC" in str(summary["source"])
    assert summary["rows"] == len(df)
