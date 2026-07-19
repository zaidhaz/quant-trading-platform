from backtesting.data_feed import DataFeed
from backtesting.engine import BacktestConfig, BacktestEngine
from backtesting.slippage_models import (
    FixedBpsSlippage,
    NoSlippage,
    VolumeParticipationSlippage,
)
from core.enums import OrderSide
from tests.unit.backtesting.conftest import SYMBOL, OneShotStrategy


def test_no_slippage_returns_reference_price_unchanged() -> None:
    model = NoSlippage()
    assert model.apply(100.0, OrderSide.BUY) == 100.0
    assert model.apply(100.0, OrderSide.SELL) == 100.0


def test_fixed_bps_moves_buy_price_up_and_sell_price_down() -> None:
    model = FixedBpsSlippage(bps=10.0)  # 0.10%
    assert model.apply(100.0, OrderSide.BUY) == 100.1
    assert model.apply(100.0, OrderSide.SELL) == 99.9


def test_volume_participation_is_reusable_across_calls_with_different_context() -> None:
    # This is the bug that was fixed: a single instance must work correctly across
    # many bars/orders with different quantity/bar_volume each time, not just once
    # at construction.
    model = VolumeParticipationSlippage(base_bps=1.0, impact_coefficient=0.5)

    small_order_price = model.apply(100.0, OrderSide.BUY, quantity=1.0, bar_volume=1000.0)
    large_order_price = model.apply(100.0, OrderSide.BUY, quantity=500.0, bar_volume=1000.0)

    assert small_order_price < large_order_price  # bigger participation -> more slippage


def test_volume_participation_worse_for_buy_better_direction_for_sell() -> None:
    model = VolumeParticipationSlippage(base_bps=5.0, impact_coefficient=0.1)

    buy_price = model.apply(100.0, OrderSide.BUY, quantity=10.0, bar_volume=1000.0)
    sell_price = model.apply(100.0, OrderSide.SELL, quantity=10.0, bar_volume=1000.0)

    assert buy_price > 100.0
    assert sell_price < 100.0


def test_volume_participation_handles_zero_bar_volume_without_dividing_by_zero() -> None:
    model = VolumeParticipationSlippage(base_bps=1.0, impact_coefficient=0.5)
    price = model.apply(100.0, OrderSide.BUY, quantity=10.0, bar_volume=0.0)
    assert price > 100.0  # falls back to full (worst-case) participation, doesn't crash


def test_volume_participation_model_is_selectable_through_backtest_config(
    deterministic_long_df,
) -> None:
    # Proves the fix end to end: BacktestConfig can select a non-default slippage
    # model, and it's reused correctly across every fill in a real run rather than
    # only working for a single hardcoded bar/quantity.
    config = BacktestConfig(
        initial_capital=10_000.0,
        taker_fee_rate=0.0,
        slippage_model=VolumeParticipationSlippage(base_bps=5.0, impact_coefficient=0.2),
    )
    strategy = OneShotStrategy(stop_loss=95.0, take_profit=110.0)
    feed = DataFeed.from_candles(SYMBOL, "1h", deterministic_long_df)

    result = BacktestEngine(strategy, feed, config).run()

    trade = result.closed_trades[0]
    # Entry (a BUY) should have filled worse than the reference price; exit (a
    # SELL, at the stop) should also have filled worse than the stop level.
    assert trade.entry_price > 100.0
    assert trade.exit_price < 95.0
