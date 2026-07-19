from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_risk_per_trade_pct: float = 0.02  # hard cap regardless of what a strategy suggests
    max_position_notional: float | None = None
    max_leverage: float | None = None


def check_notional_limit(notional: float, limits: RiskLimits) -> str | None:
    if limits.max_position_notional is not None and notional > limits.max_position_notional:
        return (
            f"position notional {notional:.2f} exceeds max_position_notional "
            f"{limits.max_position_notional:.2f}"
        )
    return None


def check_leverage_limit(notional: float, equity: float, limits: RiskLimits) -> str | None:
    if limits.max_leverage is not None and equity > 0:
        leverage = notional / equity
        if leverage > limits.max_leverage:
            return (
                f"implied leverage {leverage:.2f}x exceeds max_leverage {limits.max_leverage:.2f}x"
            )
    return None
