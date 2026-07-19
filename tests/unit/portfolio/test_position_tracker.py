from datetime import UTC, datetime

import pytest

from core.enums import ExitReason, PositionSide
from core.types import Symbol
from portfolio.position_tracker import PositionTracker

SYMBOL = Symbol(base="BTC", quote="USDT")
TS = datetime(2024, 1, 1, tzinfo=UTC)


def test_open_then_get_returns_position() -> None:
    tracker = PositionTracker()
    tracker.open_position(SYMBOL, PositionSide.LONG, 100.0, 1.0, TS)
    assert tracker.get(SYMBOL) is not None
    assert tracker.is_open(SYMBOL)


def test_cannot_open_second_position_for_same_symbol() -> None:
    tracker = PositionTracker()
    tracker.open_position(SYMBOL, PositionSide.LONG, 100.0, 1.0, TS)
    with pytest.raises(ValueError):
        tracker.open_position(SYMBOL, PositionSide.LONG, 105.0, 1.0, TS)


def test_close_position_removes_it_and_returns_closed_trade() -> None:
    tracker = PositionTracker()
    tracker.open_position(SYMBOL, PositionSide.LONG, 100.0, 2.0, TS, entry_fee=0.5)

    trade = tracker.close_position(
        SYMBOL, 110.0, TS, exit_fee=0.6, exit_reason=ExitReason.TAKE_PROFIT
    )

    assert not tracker.is_open(SYMBOL)
    assert trade.gross_pnl == 20.0
    assert trade.fees == 1.1  # entry + exit
    assert trade.net_pnl == 20.0 - 1.1


def test_funding_accrues_and_reduces_net_pnl() -> None:
    tracker = PositionTracker()
    tracker.open_position(SYMBOL, PositionSide.LONG, 100.0, 1.0, TS)
    tracker.apply_funding(SYMBOL, 2.0)
    tracker.apply_funding(SYMBOL, 3.0)

    trade = tracker.close_position(
        SYMBOL, 100.0, TS, exit_fee=0.0, exit_reason=ExitReason.STRATEGY_EXIT
    )

    assert trade.funding == 5.0
    assert trade.net_pnl == -5.0


def test_to_position_produces_read_only_snapshot() -> None:
    tracker = PositionTracker()
    open_position = tracker.open_position(
        SYMBOL, PositionSide.SHORT, 100.0, 1.0, TS, stop_loss=105.0, take_profit=90.0
    )

    snapshot = open_position.to_position()

    assert snapshot.side == PositionSide.SHORT
    assert snapshot.stop_loss == 105.0
    assert snapshot.take_profit == 90.0
