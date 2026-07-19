from core.enums import SignalDirection
from strategies.examples.ma_crossover import MACrossoverStrategy
from strategies.signal import Setup
from tests.fixtures.synthetic import make_ohlcv
from tests.unit.strategies.conftest import make_context


def test_confidence_higher_when_direction_agrees_with_regime_bias(engine) -> None:
    up = make_ohlcv(200, drift=0.008, volatility=0.001, seed=9)
    strategy = MACrossoverStrategy()
    context = make_context(up, engine, 150)

    long_setup = Setup(direction=SignalDirection.LONG, reference_price=context.price, reasoning="t")
    short_setup = Setup(
        direction=SignalDirection.SHORT, reference_price=context.price, reasoning="t"
    )

    long_confidence = strategy.confidence(context, long_setup)
    short_confidence = strategy.confidence(context, short_setup)

    assert long_confidence > short_confidence


def test_confidence_is_bounded_0_to_100(engine) -> None:
    df = make_ohlcv(200, drift=0.01, volatility=0.001, seed=2)
    strategy = MACrossoverStrategy()
    context = make_context(df, engine, 150)
    setup = Setup(direction=SignalDirection.LONG, reference_price=context.price, reasoning="t")

    confidence = strategy.confidence(context, setup)

    assert 0.0 <= confidence <= 100.0


def test_reasoning_defaults_to_setup_reasoning(engine) -> None:
    df = make_ohlcv(100)
    strategy = MACrossoverStrategy()
    context = make_context(df, engine, 50)
    setup = Setup(direction=SignalDirection.LONG, reference_price=100.0, reasoning="because X")

    assert strategy.reasoning(context, setup) == "because X"
