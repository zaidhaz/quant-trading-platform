from dataclasses import dataclass, field

from core.enums import SignalDirection


@dataclass(frozen=True, slots=True)
class Setup:
    """A strategy noticing a potential trade — direction only, not yet sized or
    validated. `check_entry` decides whether it becomes a `Signal`."""

    direction: SignalDirection
    reference_price: float
    reasoning: str
    metadata: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Signal:
    """A validated, sized trade intent, ready for the risk engine."""

    direction: SignalDirection
    entry_price: float
    confidence: float  # 0-100
    reasoning: str
    size: float
    stop_loss: float | None = None
    take_profit: float | None = None
    features_snapshot: dict[str, float] = field(default_factory=dict)
    regime_snapshot: dict[str, str] = field(default_factory=dict)
