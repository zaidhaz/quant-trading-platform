import pytest

from core.exceptions import InsufficientDataError
from core.types import Symbol
from features.feature_engine import FeatureEngine
from tests.fixtures.synthetic import make_ohlcv

SYMBOL = Symbol(base="BTC", quote="USDT")


def test_get_returns_expected_value_at_index() -> None:
    df = make_ohlcv(100)
    engine = FeatureEngine()
    value = engine.get(SYMBOL, "1h", "ema", df, at_index=50, period=10)
    assert isinstance(value, float)


def test_get_raises_insufficient_data_during_warmup() -> None:
    df = make_ohlcv(50)
    engine = FeatureEngine()
    with pytest.raises(InsufficientDataError):
        engine.get(SYMBOL, "1h", "ema", df, at_index=5, period=20)


def test_unknown_indicator_raises_value_error() -> None:
    df = make_ohlcv(50)
    engine = FeatureEngine()
    with pytest.raises(ValueError):
        engine.get(SYMBOL, "1h", "not_a_real_indicator", df, at_index=10)


def test_repeated_request_hits_cache_not_recompute() -> None:
    df = make_ohlcv(200)
    engine = FeatureEngine()

    engine.get(SYMBOL, "1h", "rsi", df, at_index=100, period=14)
    engine.get(SYMBOL, "1h", "rsi", df, at_index=150, period=14)

    assert engine.miss_count == 1
    assert engine.hit_count == 1


def test_different_params_are_cached_separately() -> None:
    df = make_ohlcv(200)
    engine = FeatureEngine()

    engine.get(SYMBOL, "1h", "ema", df, at_index=100, period=10)
    engine.get(SYMBOL, "1h", "ema", df, at_index=100, period=20)

    assert engine.miss_count == 2
    assert engine.hit_count == 0


def test_different_symbols_are_cached_separately() -> None:
    df = make_ohlcv(200)
    engine = FeatureEngine()
    other = Symbol(base="ETH", quote="USDT")

    engine.get(SYMBOL, "1h", "ema", df, at_index=100, period=10)
    engine.get(other, "1h", "ema", df, at_index=100, period=10)

    assert engine.miss_count == 2
