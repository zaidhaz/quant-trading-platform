from core.enums import PositionSide, SignalDirection
from core.exceptions import InsufficientDataError
from core.types import Position
from risk.position_sizing import fixed_fractional
from strategies.base_strategy import Strategy
from strategies.context import StrategyContext
from strategies.registry import register_strategy
from strategies.signal import Setup


@register_strategy("mean_reversion")
class MeanReversionStrategy(Strategy):
    """Long/short fade of Bollinger-band extremes confirmed by RSI, targeting a
    reversion to the band midline."""

    def __init__(
        self,
        bb_period: int = 20,
        bb_num_std: float = 2.0,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        exit_rsi: float = 50.0,
        atr_period: int = 14,
        stop_loss_atr_mult: float = 1.5,
        risk_per_trade: float = 0.01,
        **params: object,
    ) -> None:
        super().__init__(
            bb_period=bb_period,
            bb_num_std=bb_num_std,
            rsi_period=rsi_period,
            oversold=oversold,
            overbought=overbought,
            exit_rsi=exit_rsi,
            atr_period=atr_period,
            stop_loss_atr_mult=stop_loss_atr_mult,
            risk_per_trade=risk_per_trade,
            **params,
        )
        self.bb_period = bb_period
        self.bb_num_std = bb_num_std
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.exit_rsi = exit_rsi
        self.atr_period = atr_period
        self.stop_loss_atr_mult = stop_loss_atr_mult
        self.risk_per_trade = risk_per_trade

    def detect_setup(self, context: StrategyContext) -> Setup | None:
        try:
            rsi = context.features.get("rsi", period=self.rsi_period)
            bb_lower = context.features.get(
                "bb_lower", period=self.bb_period, num_std=self.bb_num_std
            )
            bb_upper = context.features.get(
                "bb_upper", period=self.bb_period, num_std=self.bb_num_std
            )
        except InsufficientDataError:
            return None

        if rsi <= self.oversold and context.price <= bb_lower:
            return Setup(
                direction=SignalDirection.LONG,
                reference_price=context.price,
                reasoning=f"RSI {rsi:.1f} <= {self.oversold} and price at/below lower BB",
                metadata={"rsi": rsi},
            )
        if rsi >= self.overbought and context.price >= bb_upper:
            return Setup(
                direction=SignalDirection.SHORT,
                reference_price=context.price,
                reasoning=f"RSI {rsi:.1f} >= {self.overbought} and price at/above upper BB",
                metadata={"rsi": rsi},
            )
        return None

    def check_entry(self, context: StrategyContext, setup: Setup) -> bool:
        return True

    def check_exit(self, context: StrategyContext, position: Position) -> bool:
        try:
            rsi = context.features.get("rsi", period=self.rsi_period)
        except InsufficientDataError:
            return False
        if position.side == PositionSide.LONG:
            return rsi >= self.exit_rsi
        return rsi <= self.exit_rsi

    def stop_loss(self, context: StrategyContext, setup: Setup) -> float | None:
        atr = context.features.get("atr", period=self.atr_period)
        offset = self.stop_loss_atr_mult * atr
        if setup.direction == SignalDirection.LONG:
            return setup.reference_price - offset
        return setup.reference_price + offset

    def take_profit(self, context: StrategyContext, setup: Setup) -> float | None:
        return context.features.get("bb_mid", period=self.bb_period, num_std=self.bb_num_std)

    def position_size(self, context: StrategyContext, setup: Setup) -> float:
        stop = self.stop_loss(context, setup)
        if stop is None:
            return 0.0
        return fixed_fractional(context.equity, setup.reference_price, stop, self.risk_per_trade)
