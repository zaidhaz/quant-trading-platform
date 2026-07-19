from core.enums import PositionSide


def realized_pnl(
    side: PositionSide, entry_price: float, exit_price: float, quantity: float
) -> float:
    direction = 1 if side == PositionSide.LONG else -1
    return direction * (exit_price - entry_price) * quantity


def unrealized_pnl(
    side: PositionSide, entry_price: float, mark_price: float, quantity: float
) -> float:
    return realized_pnl(side, entry_price, mark_price, quantity)


def fee_cost(price: float, quantity: float, fee_rate: float) -> float:
    return price * quantity * fee_rate


def funding_cost(side: PositionSide, notional: float, funding_rate: float) -> float:
    """Perpetual futures funding: when funding_rate > 0, longs pay shorts. Returns
    the amount deducted from the position holder's cash (negative = they receive)."""
    direction = 1 if side == PositionSide.LONG else -1
    return direction * notional * funding_rate
