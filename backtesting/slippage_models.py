from abc import ABC, abstractmethod

from core.enums import OrderSide


class SlippageModel(ABC):
    @abstractmethod
    def apply(self, reference_price: float, side: OrderSide) -> float:
        """Return the simulated fill price for an order at `reference_price`."""


class NoSlippage(SlippageModel):
    def apply(self, reference_price: float, side: OrderSide) -> float:
        return reference_price


class FixedBpsSlippage(SlippageModel):
    """Fills always move against the trader by a fixed number of basis points —
    the simplest, most common backtest slippage assumption."""

    def __init__(self, bps: float) -> None:
        self.bps = bps

    def apply(self, reference_price: float, side: OrderSide) -> float:
        adjustment = reference_price * (self.bps / 10_000)
        return (
            reference_price + adjustment if side == OrderSide.BUY else reference_price - adjustment
        )


class VolumeParticipationSlippage(SlippageModel):
    """Slippage grows with how large the order is relative to the bar's volume —
    a cheap proxy for market impact without needing full order-book depth data."""

    def __init__(
        self, base_bps: float, impact_coefficient: float, bar_volume: float, order_quantity: float
    ) -> None:
        self.base_bps = base_bps
        participation = order_quantity / bar_volume if bar_volume > 0 else 1.0
        self.total_bps = base_bps + impact_coefficient * participation * 10_000

    def apply(self, reference_price: float, side: OrderSide) -> float:
        adjustment = reference_price * (self.total_bps / 10_000)
        return (
            reference_price + adjustment if side == OrderSide.BUY else reference_price - adjustment
        )
