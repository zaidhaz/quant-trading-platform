import pytest

from backtesting.data_feed import DataFeed
from backtesting.engine import BacktestConfig, BacktestEngine
from core.enums import ExitReason, PositionSide, SignalDirection
from journal.journal_recorder import JournalRecorder
from tests.unit.backtesting.conftest import SYMBOL, OneShotStrategy

CONFIG = BacktestConfig(initial_capital=10_000.0, taker_fee_rate=0.0, slippage_bps=0.0)


def run_with_journal(df, strategy):
    feed = DataFeed.from_candles(SYMBOL, "1h", df)
    engine = BacktestEngine(strategy, feed, CONFIG)
    journal = JournalRecorder(engine.bus)
    result = engine.run()
    return result, journal


def test_journal_entry_created_on_open_fill(deterministic_long_df) -> None:
    strategy = OneShotStrategy(stop_loss=95.0, take_profit=110.0, confidence=77.0)
    result, journal = run_with_journal(deterministic_long_df, strategy)

    assert len(journal.entries) == 1
    entry = journal.entries[0]
    assert entry.side == PositionSide.LONG
    assert entry.entry_reason == "test entry"
    assert entry.confidence_score == 77.0
    assert entry.strategy_id == "OneShotStrategy"


def test_journal_entry_closed_with_exit_details(deterministic_long_df) -> None:
    strategy = OneShotStrategy(stop_loss=95.0, take_profit=110.0)
    result, journal = run_with_journal(deterministic_long_df, strategy)

    entry = journal.entries[0]
    assert entry.is_closed
    assert entry.exit_reason == ExitReason.STOP_LOSS.value
    assert entry.exit_price == 95.0
    assert entry.holding_time_seconds is not None
    assert entry.holding_time_seconds > 0


def test_journal_pnl_matches_engine_closed_trade_net_pnl(deterministic_long_df) -> None:
    strategy = OneShotStrategy(stop_loss=1.0, take_profit=100.5)
    result, journal = run_with_journal(deterministic_long_df, strategy)

    trade = result.closed_trades[0]
    entry = journal.entries[0]
    assert entry.pnl == trade.net_pnl


def test_journal_captures_market_regime_and_features_snapshot(deterministic_long_df) -> None:
    strategy = OneShotStrategy(stop_loss=95.0, take_profit=110.0)
    result, journal = run_with_journal(deterministic_long_df, strategy)

    entry = journal.entries[0]
    assert set(entry.market_regime.keys()) == {"trend", "volatility", "bias"}
    assert isinstance(entry.features_snapshot, dict)


def test_journal_risk_pct_computed_from_stop_distance_and_equity(deterministic_long_df) -> None:
    strategy = OneShotStrategy(stop_loss=95.0, take_profit=110.0, size=10.0)
    result, journal = run_with_journal(deterministic_long_df, strategy)

    entry = journal.entries[0]
    # risk = |100-95| * filled_quantity ; equity ~= initial_capital at signal time
    assert entry.risk_pct is not None
    assert entry.risk_pct > 0


def test_journal_implied_leverage_computed_even_without_a_stop(deterministic_long_df) -> None:
    # implied_leverage is visibility into notional exposure, independent of
    # whether a stop-loss exists — RiskLimits() has no default leverage cap, so
    # this is the one place that exposure is guaranteed to show up.
    strategy = OneShotStrategy(stop_loss=None, take_profit=None, size=50.0)
    result, journal = run_with_journal(deterministic_long_df, strategy)

    entry = journal.entries[0]
    assert entry.risk_pct is None  # no stop -> no risk_pct
    assert entry.implied_leverage is not None
    expected = (entry.entry_price * entry.position_size) / 10_000.0
    assert entry.implied_leverage == pytest.approx(expected)


def test_short_position_journaled_correctly(deterministic_short_df) -> None:
    strategy = OneShotStrategy(direction=SignalDirection.SHORT, stop_loss=106.0, take_profit=50.0)
    result, journal = run_with_journal(deterministic_short_df, strategy)

    entry = journal.entries[0]
    assert entry.side == PositionSide.SHORT
    assert entry.is_closed


def test_no_journal_entry_when_signal_rejected_and_no_fill(deterministic_long_df) -> None:
    from risk.limits import RiskLimits

    strategy = OneShotStrategy(stop_loss=95.0, take_profit=110.0)
    feed = DataFeed.from_candles(SYMBOL, "1h", deterministic_long_df)
    engine = BacktestEngine(
        strategy,
        feed,
        BacktestConfig(
            initial_capital=10_000.0, risk_limits=RiskLimits(max_position_notional=0.01)
        ),
    )
    journal = JournalRecorder(engine.bus)
    engine.run()

    assert journal.entries == []
