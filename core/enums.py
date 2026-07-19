from enum import StrEnum


class PositionSide(StrEnum):
    LONG = "long"
    SHORT = "short"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class SignalDirection(StrEnum):
    LONG = "long"
    SHORT = "short"
    HOLD = "hold"


class TrendState(StrEnum):
    TRENDING = "trending"
    RANGING = "ranging"


class VolatilityState(StrEnum):
    HIGH = "high"
    LOW = "low"


class MarketBias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class ExitReason(StrEnum):
    STRATEGY_EXIT = "strategy_exit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    END_OF_BACKTEST = "end_of_backtest"
