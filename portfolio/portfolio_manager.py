from __future__ import annotations

from datetime import datetime

from core.enums import ExitReason, PositionSide
from core.types import Position, Symbol
from portfolio.pnl_calculator import funding_cost, unrealized_pnl
from portfolio.position_tracker import ClosedTrade, PositionTracker


class PortfolioManager:
    """Tracks cash + open positions for a single backtest run and accumulates the
    equity curve and closed-trade history that `analytics/` and `journal/` consume.

    `cash` represents realized equity: starting capital plus every realized PnL,
    minus every fee and funding payment as they occur. `equity()` adds unrealized
    PnL of currently open positions on top of that.
    """

    def __init__(self, initial_capital: float) -> None:
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.tracker = PositionTracker()
        self.closed_trades: list[ClosedTrade] = []
        self.equity_curve: list[tuple[datetime, float]] = []

    def open_position(
        self,
        symbol: Symbol,
        side: PositionSide,
        entry_price: float,
        quantity: float,
        opened_at: datetime,
        stop_loss: float | None,
        take_profit: float | None,
        entry_fee: float,
    ) -> None:
        self.cash -= entry_fee
        self.tracker.open_position(
            symbol, side, entry_price, quantity, opened_at, stop_loss, take_profit, entry_fee
        )

    def apply_funding(self, symbol: Symbol, mark_price: float, funding_rate: float) -> float:
        position = self.tracker.get(symbol)
        if position is None:
            return 0.0
        notional = mark_price * position.quantity
        cost = funding_cost(position.side, notional, funding_rate)
        self.cash -= cost
        self.tracker.apply_funding(symbol, cost)
        return cost

    def close_position(
        self,
        symbol: Symbol,
        exit_price: float,
        exit_ts: datetime,
        exit_fee: float,
        exit_reason: ExitReason,
    ) -> ClosedTrade:
        trade = self.tracker.close_position(symbol, exit_price, exit_ts, exit_fee, exit_reason)
        self.cash += trade.gross_pnl - exit_fee
        self.closed_trades.append(trade)
        return trade

    def get_position(self, symbol: Symbol) -> Position | None:
        open_position = self.tracker.get(symbol)
        return open_position.to_position() if open_position is not None else None

    def equity(self, mark_prices: dict[str, float]) -> float:
        total = self.cash
        for position in self.tracker.all_open():
            total += unrealized_pnl(
                position.side,
                position.entry_price,
                mark_prices[position.symbol.canonical],
                position.quantity,
            )
        return total

    def record_equity(self, ts: datetime, mark_prices: dict[str, float]) -> float:
        equity = self.equity(mark_prices)
        self.equity_curve.append((ts, equity))
        return equity
