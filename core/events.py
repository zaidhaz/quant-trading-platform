"""Event dataclasses that flow across `core.event_bus`.

Every event carries `ts` (event time) and `correlation_id` so a chain from a candle
through to a resulting fill/journal entry can be traced. `correlation_id` defaults to
the event's own id when nothing upstream is being chained from.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from core.enums import ExitReason, OrderSide, SignalDirection
from core.types import Symbol


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    event_id: str = field(default_factory=_new_id)
    ts: datetime
    correlation_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.correlation_id:
            object.__setattr__(self, "correlation_id", self.event_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class CandleEvent(Event):
    symbol: Symbol
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_index: int


@dataclass(frozen=True, slots=True, kw_only=True)
class FundingRateEvent(Event):
    symbol: Symbol
    funding_rate: float
    mark_price: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketRegimeChangedEvent(Event):
    symbol: Symbol
    trend: str
    volatility: str
    bias: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalEvent(Event):
    symbol: Symbol
    strategy_id: str
    direction: SignalDirection
    confidence: float  # 0-100
    reasoning: str
    entry_price: float
    equity_at_signal: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    suggested_size: float | None = None
    features_snapshot: dict[str, float] = field(default_factory=dict)
    regime_snapshot: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskRejectedEvent(Event):
    symbol: Symbol
    strategy_id: str
    signal_id: str
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderIntentEvent(Event):
    symbol: Symbol
    strategy_id: str
    signal_id: str
    side: OrderSide
    quantity: float
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class FillEvent(Event):
    symbol: Symbol
    strategy_id: str
    order_id: str
    side: OrderSide
    quantity: float
    price: float
    fee: float
    funding_cost: float = 0.0
    is_position_open: bool = False
    is_position_close: bool = False
    exit_reason: ExitReason | None = None
