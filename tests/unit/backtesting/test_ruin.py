import pandas as pd

from backtesting.data_feed import DataFeed
from backtesting.engine import BacktestConfig, BacktestEngine
from core.enums import ExitReason
from risk.limits import RiskLimits
from tests.unit.backtesting.conftest import SYMBOL, OneShotStrategy

ZERO_COST_CONFIG = BacktestConfig(
    initial_capital=10_000.0,
    taker_fee_rate=0.0,
    slippage_bps=0.0,
    # No stop_loss on the position (see the test) means the risk-per-trade cap
    # never engages, and RiskLimits() defaults to no leverage/notional cap either
    # — deliberately, to exercise the "nothing stops an oversized position from
    # ruining the account" scenario this fix addresses.
    risk_limits=RiskLimits(),
)


def make_feed(df: pd.DataFrame) -> DataFeed:
    return DataFeed.from_candles(SYMBOL, "1h", df)


def test_equity_crash_triggers_ruin_and_force_close(crash_df) -> None:
    strategy = OneShotStrategy(stop_loss=None, take_profit=None, size=1000.0)
    engine = BacktestEngine(strategy, make_feed(crash_df), ZERO_COST_CONFIG)

    result = engine.run()

    assert result.ruined is True
    assert result.closed_trades[-1].exit_reason == ExitReason.RUIN
    assert result.final_equity <= 0


def test_no_further_bars_processed_after_ruin(crash_df) -> None:
    strategy = OneShotStrategy(stop_loss=None, take_profit=None, size=1000.0)
    engine = BacktestEngine(strategy, make_feed(crash_df), ZERO_COST_CONFIG)

    result = engine.run()

    # Ruin happens at bar 3 (index 3); equity curve should not extend past that
    # bar even though the feed has bars 4 and 5.
    assert len(result.equity_curve) <= 4
    assert engine.portfolio.tracker.all_open() == []


def test_non_ruinous_run_is_unaffected(deterministic_long_df) -> None:
    strategy = OneShotStrategy(stop_loss=95.0, take_profit=110.0)
    engine = BacktestEngine(strategy, make_feed(deterministic_long_df), ZERO_COST_CONFIG)

    result = engine.run()

    assert result.ruined is False
    assert len(result.equity_curve) == len(deterministic_long_df)
