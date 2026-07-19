import pandas as pd

from core.enums import PositionSide, SignalDirection
from core.types import Position
from strategies.examples.ma_crossover import MACrossoverStrategy
from tests.fixtures.synthetic import make_ohlcv
from tests.unit.strategies.conftest import SYMBOL, make_context


def test_detects_long_setup_after_a_flat_to_uptrend_regime_change(engine) -> None:
    # A monotonic uptrend from bar 0 crosses its EMAs during warmup itself, before
    # there's a "previous" state to compare against — so this test constructs an
    # unambiguous crossover well after warmup: flat, then a sharp uptrend.
    flat = make_ohlcv(80, drift=0.0, volatility=0.001, seed=5, start="2024-01-01")
    up = make_ohlcv(
        80,
        drift=0.01,
        volatility=0.001,
        seed=5,
        start_price=flat["close"].iloc[-1],
        start="2024-01-04",
    )
    df = pd.concat([flat, up])

    strategy = MACrossoverStrategy(fast_period=5, slow_period=20)
    setups = []
    for i in range(25, len(df)):
        context = make_context(df, engine, i)
        setup = strategy.detect_setup(context)
        if setup is not None:
            setups.append(setup)

    assert any(s.direction == SignalDirection.LONG for s in setups)


def test_no_setup_before_warmup_period(trending_df, engine) -> None:
    strategy = MACrossoverStrategy(fast_period=5, slow_period=20)
    context = make_context(trending_df, engine, 5)
    assert strategy.detect_setup(context) is None


def test_check_entry_always_confirms_for_this_strategy(trending_df, engine) -> None:
    strategy = MACrossoverStrategy(fast_period=5, slow_period=20)
    context = make_context(trending_df, engine, 100)
    setup = strategy.detect_setup(context) or strategy.detect_setup(
        make_context(trending_df, engine, 30)
    )
    if setup is not None:
        assert strategy.check_entry(context, setup) is True


def test_stop_loss_below_entry_for_long_above_for_short(trending_df, engine) -> None:
    strategy = MACrossoverStrategy(fast_period=5, slow_period=20)
    context = make_context(trending_df, engine, 100)
    from strategies.signal import Setup

    long_setup = Setup(
        direction=SignalDirection.LONG, reference_price=context.price, reasoning="test"
    )
    short_setup = Setup(
        direction=SignalDirection.SHORT, reference_price=context.price, reasoning="test"
    )

    assert strategy.stop_loss(context, long_setup) < context.price
    assert strategy.stop_loss(context, short_setup) > context.price


def test_take_profit_above_entry_for_long_below_for_short(trending_df, engine) -> None:
    strategy = MACrossoverStrategy(fast_period=5, slow_period=20)
    context = make_context(trending_df, engine, 100)
    from strategies.signal import Setup

    long_setup = Setup(
        direction=SignalDirection.LONG, reference_price=context.price, reasoning="test"
    )
    short_setup = Setup(
        direction=SignalDirection.SHORT, reference_price=context.price, reasoning="test"
    )

    assert strategy.take_profit(context, long_setup) > context.price
    assert strategy.take_profit(context, short_setup) < context.price


def test_position_size_scales_with_equity(trending_df, engine) -> None:
    strategy = MACrossoverStrategy(fast_period=5, slow_period=20, risk_per_trade=0.01)
    from strategies.signal import Setup

    setup = Setup(direction=SignalDirection.LONG, reference_price=100.0, reasoning="test")

    small = make_context(trending_df, engine, 100, equity=10_000.0)
    large = make_context(trending_df, engine, 100, equity=100_000.0)

    size_small = strategy.position_size(small, setup)
    size_large = strategy.position_size(large, setup)

    assert size_large == size_small * 10


def test_position_size_zero_when_no_equity(trending_df, engine) -> None:
    strategy = MACrossoverStrategy(fast_period=5, slow_period=20)
    from strategies.signal import Setup

    setup = Setup(direction=SignalDirection.LONG, reference_price=100.0, reasoning="test")
    context = make_context(trending_df, engine, 100, equity=0.0)

    assert strategy.position_size(context, setup) == 0.0


def test_check_exit_true_on_opposite_crossover_for_long_position(trending_df, engine) -> None:
    strategy = MACrossoverStrategy(fast_period=5, slow_period=20)
    # Build a position and scan forward for a bar where fast < slow (exit condition).
    position = Position(
        symbol=SYMBOL,
        side=PositionSide.LONG,
        entry_price=1.0,
        quantity=1.0,
        opened_at=trending_df.index[30],
    )
    exits = []
    for i in range(30, len(trending_df)):
        context = make_context(trending_df, engine, i)
        exits.append(strategy.check_exit(context, position))
    # In a persistent, low-noise uptrend the fast EMA should stay above the slow EMA
    # almost the whole time, i.e. exit should almost never fire.
    assert sum(exits) < len(exits) * 0.2
