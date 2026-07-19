from risk import pre_trade_checks
from risk.limits import RiskLimits
from risk.position_sizing import confidence_scaled
from risk.pre_trade_checks import RiskDecision


class RiskEngine:
    """Sits between a strategy's proposed `Signal` and the (simulated or live)
    broker: applies optional confidence-based rescaling, then the pre-trade check
    pipeline. A strategy's `position_size()` is a suggestion; this is what actually
    decides the traded quantity."""

    def __init__(
        self,
        limits: RiskLimits,
        use_confidence_scaling: bool = False,
        confidence_floor: float = 0.25,
    ) -> None:
        self.limits = limits
        self.use_confidence_scaling = use_confidence_scaling
        self.confidence_floor = confidence_floor

    def evaluate(
        self,
        suggested_quantity: float,
        entry_price: float,
        stop_loss: float | None,
        confidence: float,
        equity: float,
    ) -> RiskDecision:
        quantity = suggested_quantity
        if self.use_confidence_scaling:
            quantity = confidence_scaled(quantity, confidence, self.confidence_floor)
        return pre_trade_checks.evaluate(quantity, entry_price, stop_loss, equity, self.limits)
