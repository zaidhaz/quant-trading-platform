from datetime import UTC, datetime

from core.enums import ExitReason, PositionSide
from core.types import Symbol
from portfolio.portfolio_manager import PortfolioManager

SYMBOL = Symbol(base="BTC", quote="USDT")
TS = datetime(2024, 1, 1, tzinfo=UTC)


def test_cash_reduced_by_entry_fee_on_open() -> None:
    pm = PortfolioManager(initial_capital=10_000.0)
    pm.open_position(SYMBOL, PositionSide.LONG, 100.0, 1.0, TS, None, None, entry_fee=4.0)
    assert pm.cash == 10_000.0 - 4.0


def test_equity_includes_unrealized_pnl_of_open_position() -> None:
    pm = PortfolioManager(initial_capital=10_000.0)
    pm.open_position(SYMBOL, PositionSide.LONG, 100.0, 2.0, TS, None, None, entry_fee=0.0)

    equity = pm.equity({SYMBOL.canonical: 110.0})

    assert equity == 10_000.0 + 20.0  # (110-100)*2 unrealized


def test_full_round_trip_cash_equals_initial_plus_net_pnl() -> None:
    pm = PortfolioManager(initial_capital=10_000.0)
    pm.open_position(SYMBOL, PositionSide.LONG, 100.0, 1.0, TS, None, None, entry_fee=1.0)
    pm.apply_funding(SYMBOL, mark_price=105.0, funding_rate=0.0001)  # small cost
    trade = pm.close_position(SYMBOL, 110.0, TS, exit_fee=1.1, exit_reason=ExitReason.STRATEGY_EXIT)

    assert pm.cash == 10_000.0 + trade.net_pnl
    assert pm.tracker.all_open() == []
    assert pm.closed_trades == [trade]


def test_record_equity_appends_to_curve() -> None:
    pm = PortfolioManager(initial_capital=10_000.0)
    pm.record_equity(TS, {})
    assert pm.equity_curve == [(TS, 10_000.0)]


def test_get_position_returns_none_when_flat() -> None:
    pm = PortfolioManager(initial_capital=10_000.0)
    assert pm.get_position(SYMBOL) is None


def test_get_position_returns_snapshot_when_open() -> None:
    pm = PortfolioManager(initial_capital=10_000.0)
    pm.open_position(SYMBOL, PositionSide.SHORT, 100.0, 1.0, TS, 105.0, 90.0, entry_fee=0.0)

    position = pm.get_position(SYMBOL)

    assert position is not None
    assert position.side == PositionSide.SHORT
