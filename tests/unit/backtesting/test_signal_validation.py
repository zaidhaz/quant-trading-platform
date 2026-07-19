import pandas as pd

from backtesting.data_feed import DataFeed
from backtesting.engine import BacktestConfig, BacktestEngine
from core.enums import SignalDirection
from core.event_bus import EventBus
from core.events import RiskRejectedEvent
from tests.unit.backtesting.conftest import SYMBOL, OneShotStrategy

ZERO_COST_CONFIG = BacktestConfig(initial_capital=10_000.0, taker_fee_rate=0.0, slippage_bps=0.0)


def make_feed(df: pd.DataFrame) -> DataFeed:
    return DataFeed.from_candles(SYMBOL, "1h", df)


def test_long_with_stop_above_entry_is_rejected(deterministic_long_df) -> None:
    # Entry ~100, stop=105 is on the wrong side for a LONG (would "protect" against
    # the price going up, nonsensical) — must not open a position.
    strategy = OneShotStrategy(stop_loss=105.0, take_profit=110.0)
    bus = EventBus()
    rejections: list[RiskRejectedEvent] = []
    bus.subscribe(RiskRejectedEvent, rejections.append)
    engine = BacktestEngine(strategy, make_feed(deterministic_long_df), ZERO_COST_CONFIG, bus=bus)

    result = engine.run()

    assert result.closed_trades == []
    assert len(rejections) == 1
    assert "invalid" in rejections[0].reason


def test_long_with_take_profit_below_entry_is_rejected(deterministic_long_df) -> None:
    strategy = OneShotStrategy(stop_loss=95.0, take_profit=99.0)
    engine = BacktestEngine(strategy, make_feed(deterministic_long_df), ZERO_COST_CONFIG)

    result = engine.run()

    assert result.closed_trades == []


def test_short_with_stop_below_entry_is_rejected(deterministic_short_df) -> None:
    strategy = OneShotStrategy(direction=SignalDirection.SHORT, stop_loss=95.0, take_profit=50.0)
    engine = BacktestEngine(strategy, make_feed(deterministic_short_df), ZERO_COST_CONFIG)

    result = engine.run()

    assert result.closed_trades == []


def test_short_with_take_profit_above_entry_is_rejected(deterministic_short_df) -> None:
    strategy = OneShotStrategy(direction=SignalDirection.SHORT, stop_loss=106.0, take_profit=101.0)
    engine = BacktestEngine(strategy, make_feed(deterministic_short_df), ZERO_COST_CONFIG)

    result = engine.run()

    assert result.closed_trades == []


def test_valid_stop_and_take_profit_still_trade_normally(deterministic_long_df) -> None:
    strategy = OneShotStrategy(stop_loss=95.0, take_profit=110.0)
    engine = BacktestEngine(strategy, make_feed(deterministic_long_df), ZERO_COST_CONFIG)

    result = engine.run()

    assert len(result.closed_trades) == 1


def test_signal_still_persisted_when_stop_take_profit_invalid(deterministic_long_df) -> None:
    strategy = OneShotStrategy(stop_loss=105.0, take_profit=110.0)
    engine = BacktestEngine(strategy, make_feed(deterministic_long_df), ZERO_COST_CONFIG)

    result = engine.run()

    assert len(result.signals) == 1
