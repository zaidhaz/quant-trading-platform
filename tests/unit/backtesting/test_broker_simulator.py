from backtesting.broker_simulator import BacktestCosts, BrokerSimulator
from backtesting.slippage_models import FixedBpsSlippage
from core.enums import OrderSide


def test_fill_clamps_to_bar_range_when_slippage_would_exceed_it() -> None:
    # 50 bps slippage on a tight-range bar would push the fill above the bar's own
    # high — found by cross-validating against Backtrader, which clamps by
    # default (see docs/BACKTRADER_COMPARISON.md §3.2).
    broker = BrokerSimulator(BacktestCosts(taker_fee_rate=0.0, slippage=FixedBpsSlippage(bps=50.0)))

    fill_price, _ = broker.fill(
        OrderSide.BUY, quantity=1.0, reference_price=100.0, bar_low=99.0, bar_high=100.2
    )

    assert fill_price == 100.2  # clamped to the bar's high, not 100.5


def test_fill_clamps_sell_to_bar_low() -> None:
    broker = BrokerSimulator(BacktestCosts(taker_fee_rate=0.0, slippage=FixedBpsSlippage(bps=50.0)))

    fill_price, _ = broker.fill(
        OrderSide.SELL, quantity=1.0, reference_price=100.0, bar_low=99.8, bar_high=101.0
    )

    assert fill_price == 99.8  # clamped to the bar's low, not 99.5


def test_fill_unclamped_when_within_range() -> None:
    broker = BrokerSimulator(BacktestCosts(taker_fee_rate=0.0, slippage=FixedBpsSlippage(bps=5.0)))

    fill_price, _ = broker.fill(
        OrderSide.BUY, quantity=1.0, reference_price=100.0, bar_low=95.0, bar_high=105.0
    )

    assert fill_price == 100.05  # well within range, no clamping needed


def test_fill_not_clamped_when_bar_range_omitted() -> None:
    # Backward-compatible: no bar_low/bar_high means no clamping (used by any
    # caller that doesn't have bar OHLC context available).
    broker = BrokerSimulator(BacktestCosts(taker_fee_rate=0.0, slippage=FixedBpsSlippage(bps=50.0)))

    fill_price, _ = broker.fill(OrderSide.BUY, quantity=1.0, reference_price=100.0)

    assert fill_price == 100.5
