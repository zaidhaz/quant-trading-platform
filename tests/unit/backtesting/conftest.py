from core.enums import SignalDirection
from core.types import Position, Symbol
from strategies.base_strategy import Strategy
from strategies.context import StrategyContext
from strategies.signal import Setup

SYMBOL = Symbol(base="BTC", quote="USDT")


class OneShotStrategy(Strategy):
    """Deterministic test double: enters exactly once at `entry_bar_index`, at a
    fixed stop/take-profit/size, and never triggers a strategy-driven exit — so
    stop-loss/take-profit behavior can be tested precisely without depending on
    real indicator warmup or formulas."""

    def __init__(
        self,
        direction: SignalDirection = SignalDirection.LONG,
        entry_bar_index: int = 1,
        stop_loss: float | None = 95.0,
        take_profit: float | None = 110.0,
        size: float = 1.0,
        confidence: float = 80.0,
    ) -> None:
        super().__init__()
        self.direction = direction
        self.entry_bar_index = entry_bar_index
        self._stop = stop_loss
        self._tp = take_profit
        self._size = size
        self._confidence = confidence

    def detect_setup(self, context: StrategyContext) -> Setup | None:
        if context.index == self.entry_bar_index:
            return Setup(
                direction=self.direction, reference_price=context.price, reasoning="test entry"
            )
        return None

    def check_entry(self, context: StrategyContext, setup: Setup) -> bool:
        return True

    def check_exit(self, context: StrategyContext, position: Position) -> bool:
        return False

    def stop_loss(self, context: StrategyContext, setup: Setup) -> float | None:
        return self._stop

    def take_profit(self, context: StrategyContext, setup: Setup) -> float | None:
        return self._tp

    def position_size(self, context: StrategyContext, setup: Setup) -> float:
        return self._size

    def confidence(self, context: StrategyContext, setup: Setup) -> float:
        return self._confidence
