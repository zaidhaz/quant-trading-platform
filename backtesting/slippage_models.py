from abc import ABC, abstractmethod

from core.enums import OrderSide


class SlippageModel(ABC):
    @abstractmethod
    def apply(
        self,
        reference_price: float,
        side: OrderSide,
        quantity: float = 0.0,
        bar_volume: float = 0.0,
    ) -> float:
        """Return the simulated fill price for an order at `reference_price`.
        `quantity`/`bar_volume` are only used by models whose slippage depends on
        order size relative to the bar's traded volume (e.g. VolumeParticipationSlippage);
        other models ignore them."""


class NoSlippage(SlippageModel):
    def apply(
        self,
        reference_price: float,
        side: OrderSide,
        quantity: float = 0.0,
        bar_volume: float = 0.0,
    ) -> float:
        return reference_price


class FixedBpsSlippage(SlippageModel):
    """Fills always move against the trader by a fixed number of basis points —
    the simplest, most common backtest slippage assumption."""

    def __init__(self, bps: float) -> None:
        self.bps = bps

    def apply(
        self,
        reference_price: float,
        side: OrderSide,
        quantity: float = 0.0,
        bar_volume: float = 0.0,
    ) -> float:
        adjustment = reference_price * (self.bps / 10_000)
        return (
            reference_price + adjustment if side == OrderSide.BUY else reference_price - adjustment
        )


class VolumeParticipationSlippage(SlippageModel):
    """Slippage grows with how large the order is relative to the bar's traded
    volume — a cheap proxy for market impact without needing full order-book depth
    data. `quantity`/`bar_volume` are passed per call (not baked in at construction)
    so one instance is reusable across an entire backtest, where they differ bar to
    bar and order to order."""

    def __init__(self, base_bps: float, impact_coefficient: float) -> None:
        self.base_bps = base_bps
        self.impact_coefficient = impact_coefficient

    def apply(
        self,
        reference_price: float,
        side: OrderSide,
        quantity: float = 0.0,
        bar_volume: float = 0.0,
    ) -> float:
        participation = quantity / bar_volume if bar_volume > 0 else 1.0
        total_bps = self.base_bps + self.impact_coefficient * participation * 10_000
        adjustment = reference_price * (total_bps / 10_000)
        return (
            reference_price + adjustment if side == OrderSide.BUY else reference_price - adjustment
        )
