import pytest

from core.types import Symbol
from features.feature_engine import FeatureEngine
from market_regime import market_state
from strategies.context import build_context
from tests.fixtures.synthetic import make_ohlcv

SYMBOL = Symbol(base="BTC", quote="USDT")


@pytest.fixture
def trending_df():
    return make_ohlcv(300, drift=0.006, volatility=0.001, seed=7)


@pytest.fixture
def choppy_df():
    return make_ohlcv(300, drift=0.0, volatility=0.004, seed=11)


@pytest.fixture
def engine():
    return FeatureEngine()


def make_context(df, engine, index, equity=100_000.0, position=None):
    regime_df = market_state.compute(df, engine, SYMBOL, "1h")
    return build_context(df, engine, SYMBOL, "1h", regime_df, index, equity, position)
