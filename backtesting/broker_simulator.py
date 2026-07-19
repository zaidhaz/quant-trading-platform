from dataclasses import dataclass, field

from backtesting.slippage_models import NoSlippage, SlippageModel
from core.constants import DEFAULT_TAKER_FEE_RATE
from core.enums import OrderSide
from portfolio.pnl_calculator import fee_cost


@dataclass(slots=True)
class BacktestCosts:
    taker_fee_rate: float = DEFAULT_TAKER_FEE_RATE
    slippage: SlippageModel = field(default_factory=NoSlippage)


class BrokerSimulator:
    """Simulates order execution for the backtest engine — everything a live
    `execution/adapters/*` implementation (Part B) would otherwise do, but against
    historical data instead of an exchange."""

    def __init__(self, costs: BacktestCosts) -> None:
        self.costs = costs

    def fill(
        self,
        side: OrderSide,
        quantity: float,
        reference_price: float,
        bar_volume: float = 0.0,
        bar_low: float | None = None,
        bar_high: float | None = None,
    ) -> tuple[float, float]:
        """Returns (fill_price, fee). When `bar_low`/`bar_high` are given, the
        slippage-adjusted price is clamped to that range — a market order cannot
        fill at a price the bar never actually traded at. Without this, an
        aggressive slippage setting on a tight-range bar can push the fill outside
        the bar's own high/low, which is what an external comparison against
        Backtrader (a respected, widely-used backtesting library) surfaced:
        Backtrader clamps slippage to the bar range by default and this engine
        didn't — see docs/BACKTRADER_COMPARISON.md."""
        fill_price = self.costs.slippage.apply(
            reference_price, side, quantity=quantity, bar_volume=bar_volume
        )
        if bar_low is not None and bar_high is not None:
            fill_price = min(max(fill_price, bar_low), bar_high)
        fee = fee_cost(fill_price, quantity, self.costs.taker_fee_rate)
        return fill_price, fee
