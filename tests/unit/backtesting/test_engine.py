import pandas as pd

from backtesting.data_feed import DataFeed
from backtesting.engine import BacktestConfig, BacktestEngine
from core.enums import ExitReason, PositionSide, SignalDirection
from risk.limits import RiskLimits
from strategies.examples.ma_crossover import MACrossoverStrategy
from tests.fixtures.synthetic import make_ohlcv
from tests.unit.backtesting.conftest import SYMBOL, OneShotStrategy

ZERO_COST_CONFIG = BacktestConfig(initial_capital=10_000.0, taker_fee_rate=0.0, slippage_bps=0.0)


def make_feed(df: pd.DataFrame, funding_df: pd.DataFrame | None = None) -> DataFeed:
    return DataFeed.from_candles(SYMBOL, "1h", df, funding_df)


def test_stop_loss_triggers_at_exact_price_with_zero_costs(deterministic_long_df) -> None:
    strategy = OneShotStrategy(stop_loss=95.0, take_profit=110.0)
    engine = BacktestEngine(strategy, make_feed(deterministic_long_df), ZERO_COST_CONFIG)

    result = engine.run()

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.exit_reason == ExitReason.STOP_LOSS
    assert trade.exit_price == 95.0
    assert trade.side == PositionSide.LONG


def test_take_profit_triggers_when_stop_not_reached(deterministic_long_df) -> None:
    # stop far away, take-profit reachable — bar 4 has low=89 but take_profit=95.5,
    # so raise the target so only take-profit is in reach: high reaches 101 max, so
    # set take_profit=100.5 to trigger at bar 0 already open... instead use a stop
    # far below anything in the series and a reachable take-profit.
    strategy = OneShotStrategy(stop_loss=1.0, take_profit=100.5)
    engine = BacktestEngine(strategy, make_feed(deterministic_long_df), ZERO_COST_CONFIG)

    result = engine.run()

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.exit_reason == ExitReason.TAKE_PROFIT
    assert trade.exit_price == 100.5


def test_short_stop_loss_triggers_when_price_rises(deterministic_short_df) -> None:
    strategy = OneShotStrategy(direction=SignalDirection.SHORT, stop_loss=106.0, take_profit=50.0)
    engine = BacktestEngine(strategy, make_feed(deterministic_short_df), ZERO_COST_CONFIG)

    result = engine.run()

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.side == PositionSide.SHORT
    assert trade.exit_reason == ExitReason.STOP_LOSS
    assert trade.exit_price == 106.0


def test_force_closes_open_position_at_end_of_backtest(deterministic_long_df) -> None:
    strategy = OneShotStrategy(stop_loss=1.0, take_profit=1000.0)  # never hit
    engine = BacktestEngine(strategy, make_feed(deterministic_long_df), ZERO_COST_CONFIG)

    result = engine.run()

    assert len(result.closed_trades) == 1
    assert result.closed_trades[0].exit_reason == ExitReason.END_OF_BACKTEST
    assert engine.portfolio.tracker.all_open() == []


def test_fees_reduce_net_pnl_but_not_gross_pnl(deterministic_long_df) -> None:
    no_fee_config = BacktestConfig(initial_capital=10_000.0, taker_fee_rate=0.0, slippage_bps=0.0)
    with_fee_config = BacktestConfig(
        initial_capital=10_000.0, taker_fee_rate=0.001, slippage_bps=0.0
    )

    no_fee_trade = (
        BacktestEngine(
            OneShotStrategy(stop_loss=1.0, take_profit=100.5),
            make_feed(deterministic_long_df),
            no_fee_config,
        )
        .run()
        .closed_trades[0]
    )
    with_fee_trade = (
        BacktestEngine(
            OneShotStrategy(stop_loss=1.0, take_profit=100.5),
            make_feed(deterministic_long_df),
            with_fee_config,
        )
        .run()
        .closed_trades[0]
    )

    assert no_fee_trade.gross_pnl == with_fee_trade.gross_pnl
    assert with_fee_trade.net_pnl < no_fee_trade.net_pnl
    assert with_fee_trade.fees > 0


def test_slippage_reduces_net_pnl_for_long_entry(deterministic_long_df) -> None:
    no_slip_config = BacktestConfig(initial_capital=10_000.0, taker_fee_rate=0.0, slippage_bps=0.0)
    slip_config = BacktestConfig(initial_capital=10_000.0, taker_fee_rate=0.0, slippage_bps=50.0)

    no_slip_trade = (
        BacktestEngine(
            OneShotStrategy(stop_loss=1.0, take_profit=100.5),
            make_feed(deterministic_long_df),
            no_slip_config,
        )
        .run()
        .closed_trades[0]
    )
    slip_trade = (
        BacktestEngine(
            OneShotStrategy(stop_loss=1.0, take_profit=100.5),
            make_feed(deterministic_long_df),
            slip_config,
        )
        .run()
        .closed_trades[0]
    )

    assert slip_trade.net_pnl < no_slip_trade.net_pnl


def test_funding_cost_charged_on_open_position_at_funding_timestamp(deterministic_long_df) -> None:
    funding_ts = deterministic_long_df.index[2]  # while the OneShotStrategy's position is open
    funding_df = pd.DataFrame({"funding_rate": [0.001]}, index=[funding_ts])

    feed = make_feed(deterministic_long_df, funding_df)
    engine = BacktestEngine(
        OneShotStrategy(stop_loss=1.0, take_profit=100.5), feed, ZERO_COST_CONFIG
    )
    result = engine.run()

    trade = result.closed_trades[0]
    assert trade.funding != 0.0
    assert trade.net_pnl == trade.gross_pnl - trade.fees - trade.funding


def test_signal_persisted_even_when_risk_engine_rejects_trade(deterministic_long_df) -> None:
    tiny_notional_config = BacktestConfig(
        initial_capital=10_000.0, risk_limits=RiskLimits(max_position_notional=0.01)
    )
    engine = BacktestEngine(
        OneShotStrategy(stop_loss=95.0, take_profit=110.0),
        make_feed(deterministic_long_df),
        tiny_notional_config,
    )

    result = engine.run()

    assert len(result.signals) == 1
    assert result.closed_trades == []


def test_full_run_with_real_strategy_produces_equity_curve_covering_every_bar() -> None:
    df = make_ohlcv(200, drift=0.003, volatility=0.005, seed=42)
    strategy = MACrossoverStrategy(fast_period=5, slow_period=20)
    engine = BacktestEngine(strategy, make_feed(df), BacktestConfig(initial_capital=100_000.0))

    result = engine.run()

    assert len(result.equity_curve) == len(df)
    assert result.final_equity == result.equity_curve[-1][1]
    assert engine.portfolio.tracker.all_open() == []  # force-closed if anything was open


def test_zero_leftover_open_positions_after_run_for_choppy_market() -> None:
    df = make_ohlcv(200, drift=0.0, volatility=0.01, seed=5)
    strategy = MACrossoverStrategy(fast_period=5, slow_period=20)
    engine = BacktestEngine(strategy, make_feed(df), BacktestConfig(initial_capital=100_000.0))

    engine.run()

    assert engine.portfolio.tracker.all_open() == []
