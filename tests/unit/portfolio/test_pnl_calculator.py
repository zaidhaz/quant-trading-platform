from core.enums import PositionSide
from portfolio.pnl_calculator import fee_cost, funding_cost, realized_pnl, unrealized_pnl


def test_long_profits_when_price_rises() -> None:
    assert realized_pnl(PositionSide.LONG, entry_price=100, exit_price=110, quantity=2) == 20


def test_long_loses_when_price_falls() -> None:
    assert realized_pnl(PositionSide.LONG, entry_price=100, exit_price=90, quantity=2) == -20


def test_short_profits_when_price_falls() -> None:
    assert realized_pnl(PositionSide.SHORT, entry_price=100, exit_price=90, quantity=2) == 20


def test_short_loses_when_price_rises() -> None:
    assert realized_pnl(PositionSide.SHORT, entry_price=100, exit_price=110, quantity=2) == -20


def test_unrealized_pnl_matches_realized_formula_at_mark_price() -> None:
    assert unrealized_pnl(PositionSide.LONG, 100, 105, 3) == realized_pnl(
        PositionSide.LONG, 100, 105, 3
    )


def test_fee_cost_is_price_times_quantity_times_rate() -> None:
    assert fee_cost(price=100, quantity=2, fee_rate=0.0004) == 0.08


def test_positive_funding_rate_costs_longs_and_pays_shorts() -> None:
    long_cost = funding_cost(PositionSide.LONG, notional=10_000, funding_rate=0.0001)
    short_cost = funding_cost(PositionSide.SHORT, notional=10_000, funding_rate=0.0001)
    assert long_cost == 1.0
    assert short_cost == -1.0


def test_negative_funding_rate_pays_longs_and_costs_shorts() -> None:
    long_cost = funding_cost(PositionSide.LONG, notional=10_000, funding_rate=-0.0001)
    short_cost = funding_cost(PositionSide.SHORT, notional=10_000, funding_rate=-0.0001)
    assert long_cost == -1.0
    assert short_cost == 1.0
