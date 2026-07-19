import numpy as np
import pandas as pd

from features.indicators import momentum, trend, volatility, volume
from tests.fixtures.synthetic import make_ohlcv


def test_ema_matches_pandas_ewm_reference() -> None:
    close = make_ohlcv(100)["close"]
    result = trend.ema(close, period=10)
    expected = close.ewm(span=10, adjust=False, min_periods=10).mean()
    pd.testing.assert_series_equal(result, expected)


def test_ema_warms_up_with_nan_before_period() -> None:
    close = make_ohlcv(50)["close"]
    result = trend.ema(close, period=20)
    assert result.iloc[:19].isna().all()
    assert result.iloc[19:].notna().all()


def test_rsi_is_bounded_between_0_and_100() -> None:
    close = make_ohlcv(300, volatility=0.02)["close"]
    result = momentum.rsi(close, period=14).dropna()
    assert (result >= 0).all()
    assert (result <= 100).all()


def test_rsi_high_after_persistent_uptrend() -> None:
    close = make_ohlcv(100, drift=0.01, volatility=0.001)["close"]
    result = momentum.rsi(close, period=14).dropna()
    assert result.iloc[-1] > 70


def test_rsi_low_after_persistent_downtrend() -> None:
    close = make_ohlcv(100, drift=-0.01, volatility=0.001)["close"]
    result = momentum.rsi(close, period=14).dropna()
    assert result.iloc[-1] < 30


def test_atr_is_non_negative() -> None:
    df = make_ohlcv(200)
    result = volatility.atr(df, period=14).dropna()
    assert (result >= 0).all()


def test_atr_higher_for_more_volatile_series() -> None:
    calm = make_ohlcv(200, volatility=0.001)
    wild = make_ohlcv(200, volatility=0.05)
    assert volatility.atr(wild, 14).iloc[-1] > volatility.atr(calm, 14).iloc[-1]


def test_bollinger_bands_are_ordered() -> None:
    close = make_ohlcv(100)["close"]
    bands = volatility.bollinger_bands(close, period=20).dropna()
    assert (bands["upper"] >= bands["mid"]).all()
    assert (bands["mid"] >= bands["lower"]).all()


def test_macd_hist_equals_macd_minus_signal() -> None:
    close = make_ohlcv(150)["close"]
    result = trend.macd(close).dropna()
    np.testing.assert_allclose(result["hist"], result["macd"] - result["signal"])


def test_donchian_upper_never_below_lower() -> None:
    df = make_ohlcv(100)
    result = trend.donchian(df, period=20).dropna()
    assert (result["upper"] >= result["lower"]).all()


def test_adx_higher_during_strong_trend_than_chop() -> None:
    trending = make_ohlcv(200, drift=0.01, volatility=0.001, seed=1)
    choppy = make_ohlcv(200, drift=0.0, volatility=0.01, seed=1)
    trend_adx = trend.adx(trending, period=14).dropna().iloc[-1]
    chop_adx = trend.adx(choppy, period=14).dropna().iloc[-1]
    assert trend_adx > chop_adx


def test_vwap_stays_within_price_range() -> None:
    df = make_ohlcv(100)
    result = volume.vwap(df, period=20).dropna()
    assert (result >= df["low"].rolling(20).min().dropna()).all()
    assert (result <= df["high"].rolling(20).max().dropna()).all()


def test_volume_profile_poc_within_window_price_range() -> None:
    df = make_ohlcv(100)
    result = volume.volume_profile_poc(df, period=20, bins=10).dropna()
    window_low = df["close"].rolling(20).min().reindex(result.index)
    window_high = df["close"].rolling(20).max().reindex(result.index)
    assert (result >= window_low - 1e-9).all()
    assert (result <= window_high + 1e-9).all()
