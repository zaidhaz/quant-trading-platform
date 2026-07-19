from dataclasses import dataclass

from risk.limits import RiskLimits, check_leverage_limit, check_notional_limit


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    reason: str | None
    quantity: float  # final quantity to trade (0.0 if rejected)
    notional: float = 0.0
    implied_leverage: float = 0.0
    """notional / equity at decision time. `RiskLimits.max_leverage` defaults to
    None (unlimited) — there's no universally-correct default to guess, since the
    right cap is strategy- and account-specific. Surfacing the realized number here
    (and on the journal) is how unbounded exposure stays visible/auditable instead
    of silent when no cap is configured. See docs/VALIDATION_REPORT.md."""


def evaluate(
    quantity: float,
    entry_price: float,
    stop_loss: float | None,
    equity: float,
    limits: RiskLimits,
) -> RiskDecision:
    """Composable pre-trade check pipeline. Rejects on a hard notional/leverage
    breach; scales the quantity down (rather than rejecting) when the implied
    per-trade risk exceeds `max_risk_per_trade_pct` — that cap always wins over
    whatever a strategy's own `position_size()` suggested."""
    if quantity <= 0:
        return RiskDecision(False, "non-positive size", 0.0)
    if equity <= 0:
        return RiskDecision(False, "non-positive equity", 0.0)

    notional = quantity * entry_price
    for reason in (
        check_notional_limit(notional, limits),
        check_leverage_limit(notional, equity, limits),
    ):
        if reason is not None:
            return RiskDecision(False, reason, 0.0)

    if stop_loss is not None:
        risk_amount = abs(entry_price - stop_loss) * quantity
        max_risk = equity * limits.max_risk_per_trade_pct
        if risk_amount > max_risk and risk_amount > 0:
            quantity = quantity * (max_risk / risk_amount)

    final_notional = quantity * entry_price
    return RiskDecision(True, None, quantity, final_notional, final_notional / equity)
