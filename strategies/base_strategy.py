"""Strategy interface, decomposed into named hooks rather than one monolithic event
handler — this is what makes strategies interchangeable and independently
unit-testable (see docs/ARCHITECTURE.md Revision 2)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.enums import MarketBias, SignalDirection
from core.exceptions import InsufficientDataError
from core.types import Position
from strategies.context import StrategyContext
from strategies.signal import Setup

_DIRECTION_TO_FAVORABLE_BIAS = {
    SignalDirection.LONG: MarketBias.BULLISH,
    SignalDirection.SHORT: MarketBias.BEARISH,
}


class Strategy(ABC):
    """Subclass and implement all six hooks. `strategies/registry.py` is how a
    subclass becomes selectable by name for backtesting/optimization."""

    def __init__(self, **params: Any) -> None:
        self.params = params

    @abstractmethod
    def detect_setup(self, context: StrategyContext) -> Setup | None:
        """Called every bar when there's no open position. Return a `Setup` if this
        bar looks like a potential trade, else None."""

    @abstractmethod
    def check_entry(self, context: StrategyContext, setup: Setup) -> bool:
        """Confirm (or veto) a detected setup before it becomes a `Signal`."""

    @abstractmethod
    def check_exit(self, context: StrategyContext, position: Position) -> bool:
        """Called every bar there's an open position (before stop/take-profit are
        checked against the bar's high/low). True closes the position now."""

    @abstractmethod
    def stop_loss(self, context: StrategyContext, setup: Setup) -> float | None:
        """Stop-loss price for a setup about to be entered. None means no stop."""

    @abstractmethod
    def take_profit(self, context: StrategyContext, setup: Setup) -> float | None:
        """Take-profit price for a setup about to be entered. None means no target."""

    @abstractmethod
    def position_size(self, context: StrategyContext, setup: Setup) -> float:
        """Suggested quantity for a setup about to be entered. The risk engine may
        still reduce or reject this (see risk/position_sizing.py)."""

    def confidence(self, context: StrategyContext, setup: Setup) -> float:
        """Default confidence formula: trend quality (ADX-based) blended with regime
        fit (does the setup's direction agree with the current market bias?). A
        strategy with a better basis for confidence should override this."""
        try:
            adx = context.features.get("adx", period=14)
        except InsufficientDataError:
            adx = 0.0
        trend_quality = min(adx / 50.0, 1.0) * 100

        regime = context.regime.current()
        favorable_bias = _DIRECTION_TO_FAVORABLE_BIAS.get(setup.direction)
        if regime.bias == favorable_bias:
            regime_fit = 100.0
        elif regime.bias == MarketBias.NEUTRAL:
            regime_fit = 50.0
        else:
            regime_fit = 0.0

        return round(0.6 * trend_quality + 0.4 * regime_fit, 2)

    def reasoning(self, context: StrategyContext, setup: Setup) -> str:
        return setup.reasoning
