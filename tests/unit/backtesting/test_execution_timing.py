"""Regression tests for the execution-timing audit finding: entries and
strategy-driven exits must fill at the *next* bar's open, not the bar that
generated the signal; stop-loss/take-profit must account for gap-through."""

import pandas as pd

from backtesting.data_feed import DataFeed
from backtesting.engine import BacktestConfig, BacktestEngine
from core.enums import ExitReason, PositionSide, SignalDirection
from tests.unit.backtesting.conftest import SYMBOL, OneShotStrategy

ZERO_COST_CONFIG = BacktestConfig(initial_capital=10_000.0, taker_fee_rate=0.0, slippage_bps=0.0)


def make_feed(df: pd.DataFrame) -> DataFeed:
    return DataFeed.from_candles(SYMBOL, "1h", df)


def test_entry_fills_at_next_bar_open_not_decision_bar_close(gapped_entry_df) -> None:
    # Decision bar (index 2) closes at 95; if the engine incorrectly filled at the
    # decision price, entry_price would be 95. The correct fill is bar 3's open, 110.
    strategy = OneShotStrategy(entry_bar_index=2, stop_loss=1.0, take_profit=1000.0)
    engine = BacktestEngine(strategy, make_feed(gapped_entry_df), ZERO_COST_CONFIG)

    result = engine.run()

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.entry_price == 110.0
    assert trade.entry_price != 95.0  # would be the (wrong) same-bar-fill price


def test_no_pending_order_left_over_at_end_of_data(gapped_entry_df) -> None:
    # A decision made on the very last bar has no "next bar" to execute at and
    # must simply never become a trade.
    df = gapped_entry_df.iloc[:3]  # ends exactly on the decision bar
    strategy = OneShotStrategy(entry_bar_index=2, stop_loss=1.0, take_profit=1000.0)
    engine = BacktestEngine(strategy, make_feed(df), ZERO_COST_CONFIG)

    result = engine.run()

    assert result.closed_trades == []
    assert result.signals[0].direction == SignalDirection.LONG  # the signal still fired


def test_stop_loss_gap_through_fills_at_open_not_stop_level(gap_through_stop_long_df) -> None:
    strategy = OneShotStrategy(entry_bar_index=1, stop_loss=95.0, take_profit=1000.0)
    engine = BacktestEngine(strategy, make_feed(gap_through_stop_long_df), ZERO_COST_CONFIG)

    result = engine.run()

    trade = result.closed_trades[0]
    assert trade.exit_reason == ExitReason.STOP_LOSS
    assert trade.exit_price == 90.0  # the gapped-through open, not the 95 stop level


def test_take_profit_gap_through_fills_at_open_not_target_level(
    gap_through_take_profit_long_df,
) -> None:
    strategy = OneShotStrategy(entry_bar_index=1, stop_loss=1.0, take_profit=105.0)
    engine = BacktestEngine(strategy, make_feed(gap_through_take_profit_long_df), ZERO_COST_CONFIG)

    result = engine.run()

    trade = result.closed_trades[0]
    assert trade.exit_reason == ExitReason.TAKE_PROFIT
    assert trade.exit_price == 110.0  # the gapped-through open, better than the 105 target


def test_short_stop_loss_gap_through(gap_through_stop_short_df) -> None:
    strategy = OneShotStrategy(
        direction=SignalDirection.SHORT, entry_bar_index=1, stop_loss=106.0, take_profit=1.0
    )
    engine = BacktestEngine(strategy, make_feed(gap_through_stop_short_df), ZERO_COST_CONFIG)

    result = engine.run()

    trade = result.closed_trades[0]
    assert trade.side == PositionSide.SHORT
    assert trade.exit_reason == ExitReason.STOP_LOSS
    assert trade.exit_price == 110.0  # gapped open, worse than the 106 stop level


def test_short_take_profit_gap_through(gap_through_take_profit_short_df) -> None:
    strategy = OneShotStrategy(
        direction=SignalDirection.SHORT, entry_bar_index=1, stop_loss=1000.0, take_profit=95.0
    )
    engine = BacktestEngine(strategy, make_feed(gap_through_take_profit_short_df), ZERO_COST_CONFIG)

    result = engine.run()

    trade = result.closed_trades[0]
    assert trade.exit_reason == ExitReason.TAKE_PROFIT
    assert trade.exit_price == 90.0  # gapped open, better than the 95 target for a short


def test_stop_hit_without_gap_still_fills_at_stop_level(deterministic_long_df) -> None:
    # No-gap regression: when the bar opens on the "safe" side of the stop and
    # only the low crosses it, the fill should still be the exact stop level.
    strategy = OneShotStrategy(stop_loss=95.0, take_profit=110.0)
    engine = BacktestEngine(strategy, make_feed(deterministic_long_df), ZERO_COST_CONFIG)

    result = engine.run()

    assert result.closed_trades[0].exit_price == 95.0
