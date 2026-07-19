from core.enums import PositionSide, SignalDirection
from core.exceptions import InsufficientDataError
from core.types import Position
from risk.position_sizing import fixed_fractional
from strategies.base_strategy import Strategy
from strategies.context import StrategyContext
from strategies.registry import register_strategy
from strategies.signal import Setup


@register_strategy("ma_crossover")
class MACrossoverStrategy(Strategy):
    """Long/short trend-following: enter on a fast/slow EMA crossover, exit on the
    opposite crossover or a stop/take-profit. Default params can be overridden via
    `params=` at construction (and are what Grid/Walk-Forward optimization vary)."""

    def __init__(
        self,
        fast_period: int = 10,
        slow_period: int = 30,
        atr_period: int = 14,
        stop_loss_atr_mult: float = 2.0,
        take_profit_atr_mult: float = 3.0,
        risk_per_trade: float = 0.01,
        **params: object,
    ) -> None:
        super().__init__(
            fast_period=fast_period,
            slow_period=slow_period,
            atr_period=atr_period,
            stop_loss_atr_mult=stop_loss_atr_mult,
            take_profit_atr_mult=take_profit_atr_mult,
            risk_per_trade=risk_per_trade,
            **params,
        )
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.atr_period = atr_period
        self.stop_loss_atr_mult = stop_loss_atr_mult
        self.take_profit_atr_mult = take_profit_atr_mult
        self.risk_per_trade = risk_per_trade

    def detect_setup(self, context: StrategyContext) -> Setup | None:
        try:
            fast_now = context.features.get("ema", period=self.fast_period)
            slow_now = context.features.get("ema", period=self.slow_period)
            fast_prev = context.features.get("ema", offset=1, period=self.fast_period)
            slow_prev = context.features.get("ema", offset=1, period=self.slow_period)
        except InsufficientDataError:
            return None

        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        crossed_down = fast_prev >= slow_prev and fast_now < slow_now

        if crossed_up:
            return Setup(
                direction=SignalDirection.LONG,
                reference_price=context.price,
                reasoning=f"EMA{self.fast_period} crossed above EMA{self.slow_period}",
            )
        if crossed_down:
            return Setup(
                direction=SignalDirection.SHORT,
                reference_price=context.price,
                reasoning=f"EMA{self.fast_period} crossed below EMA{self.slow_period}",
            )
        return None

    def check_entry(self, context: StrategyContext, setup: Setup) -> bool:
        return True  # the crossover itself is the trigger; no extra confirmation

    def check_exit(self, context: StrategyContext, position: Position) -> bool:
        try:
            fast_now = context.features.get("ema", period=self.fast_period)
            slow_now = context.features.get("ema", period=self.slow_period)
        except InsufficientDataError:
            return False
        if position.side == PositionSide.LONG:
            return fast_now < slow_now
        return fast_now > slow_now

    def _atr(self, context: StrategyContext) -> float:
        return context.features.get("atr", period=self.atr_period)

    def stop_loss(self, context: StrategyContext, setup: Setup) -> float | None:
        atr = self._atr(context)
        offset = self.stop_loss_atr_mult * atr
        if setup.direction == SignalDirection.LONG:
            return setup.reference_price - offset
        return setup.reference_price + offset

    def take_profit(self, context: StrategyContext, setup: Setup) -> float | None:
        atr = self._atr(context)
        offset = self.take_profit_atr_mult * atr
        if setup.direction == SignalDirection.LONG:
            return setup.reference_price + offset
        return setup.reference_price - offset

    def position_size(self, context: StrategyContext, setup: Setup) -> float:
        stop = self.stop_loss(context, setup)
        if stop is None:
            return 0.0
        return fixed_fractional(context.equity, setup.reference_price, stop, self.risk_per_trade)
