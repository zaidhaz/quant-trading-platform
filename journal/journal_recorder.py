"""Automatic trade journaling. Subscribes to `SignalEvent`/`FillEvent` on the event
bus — identical code whether the events came from a backtest or (Part B) live/paper
trading, since both publish the same event types onto the same bus shape."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.enums import ExitReason, OrderSide, PositionSide
from core.event_bus import EventBus
from core.events import FillEvent, SignalEvent
from portfolio.pnl_calculator import realized_pnl

_ENTRY_SIDE_TO_POSITION_SIDE = {
    OrderSide.BUY: PositionSide.LONG,
    OrderSide.SELL: PositionSide.SHORT,
}


@dataclass(slots=True)
class JournalEntry:
    symbol: str
    strategy_id: str
    side: PositionSide
    entry_ts: datetime
    entry_price: float
    entry_reason: str
    confidence_score: float
    features_snapshot: dict[str, float]
    market_regime: dict[str, str]
    position_size: float
    risk_pct: float | None
    implied_leverage: float | None = None
    """(entry_price * position_size) / equity_at_signal — surfaced so an unbounded
    RiskLimits() (no max_leverage set) doesn't mean exposure goes unnoticed; see
    docs/VALIDATION_REPORT.md."""
    fees: float = 0.0
    funding: float = 0.0
    exit_ts: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    pnl: float | None = None
    holding_time_seconds: float | None = None
    screenshot_url: str | None = None  # populated later by an operator, not automatically
    notes: str = ""

    @property
    def is_closed(self) -> bool:
        return self.exit_ts is not None


class JournalRecorder:
    def __init__(self, bus: EventBus) -> None:
        self.entries: list[JournalEntry] = []
        self._pending_signal: dict[str, SignalEvent] = {}
        self._open_entry: dict[str, JournalEntry] = {}
        bus.subscribe(SignalEvent, self._on_signal)
        bus.subscribe(FillEvent, self._on_fill)

    def _on_signal(self, event: SignalEvent) -> None:
        # The most recent signal for a symbol is the one whose reasoning/features
        # belong to whatever fill happens next for that symbol.
        self._pending_signal[event.symbol.canonical] = event

    def _on_fill(self, event: FillEvent) -> None:
        if event.is_position_open:
            self._open(event)
        elif event.is_position_close:
            self._close(event)

    def _open(self, event: FillEvent) -> None:
        key = event.symbol.canonical
        signal = self._pending_signal.pop(key, None)

        risk_pct = None
        implied_leverage = None
        if signal is not None and signal.equity_at_signal > 0:
            if signal.stop_loss is not None:
                risk_amount = abs(signal.entry_price - signal.stop_loss) * event.quantity
                risk_pct = risk_amount / signal.equity_at_signal
            implied_leverage = (event.price * event.quantity) / signal.equity_at_signal

        entry = JournalEntry(
            symbol=str(event.symbol),
            strategy_id=event.strategy_id,
            side=_ENTRY_SIDE_TO_POSITION_SIDE[event.side],
            entry_ts=event.ts,
            entry_price=event.price,
            entry_reason=signal.reasoning if signal else "",
            confidence_score=signal.confidence if signal else 0.0,
            features_snapshot=dict(signal.features_snapshot) if signal else {},
            market_regime=dict(signal.regime_snapshot) if signal else {},
            position_size=event.quantity,
            risk_pct=risk_pct,
            implied_leverage=implied_leverage,
            fees=event.fee,
        )
        self._open_entry[key] = entry
        self.entries.append(entry)

    def _close(self, event: FillEvent) -> None:
        entry = self._open_entry.pop(event.symbol.canonical, None)
        if entry is None:
            return

        entry.exit_ts = event.ts
        entry.exit_price = event.price
        entry.exit_reason = (
            event.exit_reason.value if isinstance(event.exit_reason, ExitReason) else None
        )
        entry.fees += event.fee
        entry.funding = event.funding_cost
        entry.holding_time_seconds = (event.ts - entry.entry_ts).total_seconds()

        gross = realized_pnl(entry.side, entry.entry_price, event.price, entry.position_size)
        entry.pnl = gross - entry.fees - entry.funding
