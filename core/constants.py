SUPPORTED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")

TIMEFRAME_TO_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

DEFAULT_TIMEFRAME = "1h"

# Binance USDT-margined perpetual futures defaults, used when a symbol's own
# fee schedule isn't specified in backtest config.
DEFAULT_TAKER_FEE_RATE = 0.0004  # 4 bps
DEFAULT_MAKER_FEE_RATE = 0.0002  # 2 bps

TRADING_DAYS_PER_YEAR = 365  # crypto trades 24/7
