from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.enums import ExitReason, PositionSide
from core.types import Position, Symbol
from portfolio.pnl_calculator import unrealized_pnl


@dataclass(slots=True)
class OpenPosition:
    symbol: Symbol
    side: PositionSide
    entry_price: float
    quantity: float
    opened_at: datetime
    stop_loss: float | None = None
    take_profit: float | None = None
    entry_fee: float = 0.0
    funding_paid: float = 0.0

    def to_position(self) -> Position:
        return Position(
            symbol=self.symbol,
            side=self.side,
            entry_price=self.entry_price,
            quantity=self.quantity,
            opened_at=self.opened_at,
            stop_loss=self.stop_loss,
            take_profit=self.take_profit,
        )


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    symbol: Symbol
    side: PositionSide
    entry_price: float
    exit_price: float
    quantity: float
    entry_ts: datetime
    exit_ts: datetime
    fees: float
    funding: float
    exit_reason: ExitReason
    gross_pnl: float
    net_pnl: float  # gross_pnl - fees - funding
    stop_loss: float | None = None  # carried from the open position, for R-multiple

    @property
    def r_multiple(self) -> float | None:
        """net_pnl expressed as a multiple of the capital risked (entry-to-stop
        distance times quantity) — None when the trade had no stop-loss."""
        if self.stop_loss is None:
            return None
        risk_amount = abs(self.entry_price - self.stop_loss) * self.quantity
        if risk_amount <= 0:
            return None
        return self.net_pnl / risk_amount

    @property
    def holding_time(self):  # -> timedelta
        return self.exit_ts - self.entry_ts


class PositionTracker:
    """Long/short positions, one open position per symbol (a strategy instance
    doesn't stack multiple concurrent positions on the same symbol)."""

    def __init__(self) -> None:
        self._open: dict[str, OpenPosition] = {}

    def get(self, symbol: Symbol) -> OpenPosition | None:
        return self._open.get(symbol.canonical)

    def is_open(self, symbol: Symbol) -> bool:
        return symbol.canonical in self._open

    def all_open(self) -> list[OpenPosition]:
        return list(self._open.values())

    def open_position(
        self,
        symbol: Symbol,
        side: PositionSide,
        entry_price: float,
        quantity: float,
        opened_at: datetime,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        entry_fee: float = 0.0,
    ) -> OpenPosition:
        if self.is_open(symbol):
            raise ValueError(f"Position already open for {symbol}")
        position = OpenPosition(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            opened_at=opened_at,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_fee=entry_fee,
        )
        self._open[symbol.canonical] = position
        return position

    def apply_funding(self, symbol: Symbol, cost: float) -> None:
        position = self.get(symbol)
        if position is not None:
            position.funding_paid += cost

    def close_position(
        self,
        symbol: Symbol,
        exit_price: float,
        exit_ts: datetime,
        exit_fee: float,
        exit_reason: ExitReason,
    ) -> ClosedTrade:
        position = self._open.pop(symbol.canonical)
        gross = unrealized_pnl(position.side, position.entry_price, exit_price, position.quantity)
        total_fees = position.entry_fee + exit_fee
        net = gross - total_fees - position.funding_paid
        return ClosedTrade(
            symbol=symbol,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            entry_ts=position.opened_at,
            exit_ts=exit_ts,
            fees=total_fees,
            funding=position.funding_paid,
            exit_reason=exit_reason,
            gross_pnl=gross,
            net_pnl=net,
            stop_loss=position.stop_loss,
        )
