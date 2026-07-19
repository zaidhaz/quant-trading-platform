"""Pluggable position sizing models, shared by strategies (in their `position_size`
hook) and by `risk_engine.py` (which may re-scale whatever a strategy suggests)."""


def fixed_fractional(
    equity: float, entry_price: float, stop_price: float, risk_per_trade: float
) -> float:
    """Size so that a stop-loss hit loses exactly `risk_per_trade` fraction of equity."""
    if equity <= 0:
        return 0.0
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return 0.0
    return (equity * risk_per_trade) / stop_distance


def volatility_target(
    equity: float, atr: float, risk_per_trade: float, atr_mult: float = 2.0
) -> float:
    """Size using ATR as the stop distance proxy instead of a strategy-specific stop."""
    if equity <= 0 or atr <= 0:
        return 0.0
    stop_distance = atr * atr_mult
    return (equity * risk_per_trade) / stop_distance


def confidence_scaled(base_quantity: float, confidence: float, floor: float = 0.25) -> float:
    """Scale a base quantity by signal confidence (0-100), never below `floor` of the
    base size — a low-confidence signal shouldn't round to a zero-size no-op trade,
    and a high-confidence one shouldn't bypass the base risk model entirely."""
    scale = max(confidence / 100.0, floor)
    return base_quantity * scale
