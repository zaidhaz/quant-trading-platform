import pandas as pd

from core.enums import MarketBias, TrendState, VolatilityState
from core.types import Symbol
from features.feature_engine import FeatureEngine
from market_regime import market_state
from tests.fixtures.synthetic import make_ohlcv

SYMBOL = Symbol(base="BTC", quote="USDT")


def classify_tail(df, label_from: int = -50):
    engine = FeatureEngine()
    regime = market_state.compute(df, engine, SYMBOL, "1h")
    return regime.iloc[label_from:]


def test_strong_uptrend_period_mostly_classified_trending_and_bullish() -> None:
    df = make_ohlcv(300, drift=0.008, volatility=0.001, seed=7)
    tail = classify_tail(df)

    trending_share = (tail["trend"] == TrendState.TRENDING.value).mean()
    bullish_share = (tail["bias"] == MarketBias.BULLISH.value).mean()

    assert trending_share > 0.6
    assert bullish_share > 0.6


def test_strong_downtrend_period_mostly_bearish() -> None:
    df = make_ohlcv(300, drift=-0.008, volatility=0.001, seed=7)
    tail = classify_tail(df)

    bearish_share = (tail["bias"] == MarketBias.BEARISH.value).mean()
    assert bearish_share > 0.6


def test_choppy_zero_drift_period_mostly_ranging() -> None:
    df = make_ohlcv(300, drift=0.0, volatility=0.003, seed=11)
    tail = classify_tail(df)

    ranging_share = (tail["trend"] == TrendState.RANGING.value).mean()
    assert ranging_share > 0.5


def test_volatility_spike_within_a_series_classified_high_relative_to_its_own_calm_history() -> (
    None
):
    # atr_percentile ranks current ATR against *its own* trailing history, so the
    # meaningful test is a regime change within one series, not two unrelated series
    # (which each hover near the 50th percentile of themselves by construction).
    calm = make_ohlcv(200, volatility=0.001, seed=3, start="2024-01-01")
    spike = make_ohlcv(
        100, volatility=0.05, seed=3, start_price=calm["close"].iloc[-1], start="2024-01-09"
    )
    combined = pd.concat([calm, spike])

    engine = FeatureEngine()
    regime = market_state.compute(combined, engine, SYMBOL, "1h")

    calm_high_share = (regime["volatility"].iloc[150:200] == VolatilityState.HIGH.value).mean()
    spike_high_share = (regime["volatility"].iloc[250:300] == VolatilityState.HIGH.value).mean()

    assert spike_high_share > calm_high_share


def test_market_state_at_returns_typed_value_object() -> None:
    df = make_ohlcv(300, drift=0.008, volatility=0.001, seed=7)
    engine = FeatureEngine()
    regime = market_state.compute(df, engine, SYMBOL, "1h")

    state = market_state.at(regime, -1)

    assert isinstance(state.trend, TrendState)
    assert isinstance(state.volatility, VolatilityState)
    assert isinstance(state.bias, MarketBias)
    assert state.as_dict() == {
        "trend": state.trend.value,
        "volatility": state.volatility.value,
        "bias": state.bias.value,
    }
