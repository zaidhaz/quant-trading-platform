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
        self, side: OrderSide, quantity: float, reference_price: float, bar_volume: float = 0.0
    ) -> tuple[float, float]:
        """Returns (fill_price, fee)."""
        fill_price = self.costs.slippage.apply(
            reference_price, side, quantity=quantity, bar_volume=bar_volume
        )
        fee = fee_cost(fill_price, quantity, self.costs.taker_fee_rate)
        return fill_price, fee
