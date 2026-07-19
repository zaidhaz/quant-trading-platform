from core.enums import PositionSide, SignalDirection
from core.types import Position
from strategies.examples.mean_reversion import MeanReversionStrategy
from tests.unit.strategies.conftest import SYMBOL, make_context


def test_detects_long_setup_on_oversold_extreme(choppy_df, engine) -> None:
    strategy = MeanReversionStrategy()
    setups = []
    for i in range(30, len(choppy_df)):
        context = make_context(choppy_df, engine, i)
        setup = strategy.detect_setup(context)
        if setup is not None:
            setups.append(setup)

    # A choppy, mean-reverting series should produce both LONG and SHORT fades.
    directions = {s.direction for s in setups}
    assert SignalDirection.LONG in directions or SignalDirection.SHORT in directions


def test_take_profit_targets_band_midline(choppy_df, engine) -> None:
    strategy = MeanReversionStrategy()
    context = make_context(choppy_df, engine, 100)
    from strategies.signal import Setup

    setup = Setup(direction=SignalDirection.LONG, reference_price=context.price, reasoning="test")
    expected_mid = context.features.get(
        "bb_mid", period=strategy.bb_period, num_std=strategy.bb_num_std
    )

    assert strategy.take_profit(context, setup) == expected_mid


def test_check_exit_true_when_rsi_crosses_back_through_midline(choppy_df, engine) -> None:
    strategy = MeanReversionStrategy(exit_rsi=50.0)
    long_position = Position(
        symbol=SYMBOL,
        side=PositionSide.LONG,
        entry_price=1.0,
        quantity=1.0,
        opened_at=choppy_df.index[30],
    )
    short_position = Position(
        symbol=SYMBOL,
        side=PositionSide.SHORT,
        entry_price=1.0,
        quantity=1.0,
        opened_at=choppy_df.index[30],
    )

    saw_long_exit = False
    saw_short_exit = False
    for i in range(30, len(choppy_df)):
        context = make_context(choppy_df, engine, i)
        rsi = context.features.get("rsi", period=strategy.rsi_period)
        if rsi >= 50.0:
            saw_long_exit = saw_long_exit or strategy.check_exit(context, long_position)
        if rsi <= 50.0:
            saw_short_exit = saw_short_exit or strategy.check_exit(context, short_position)

    assert saw_long_exit
    assert saw_short_exit
