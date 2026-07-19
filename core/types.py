"""Domain value types.

Note: prices/quantities/PnL use `float` throughout the research engine (Part A),
matching the vectorized pandas/numpy pipeline used by the backtester. `Decimal`
precision matters where exchange tick/lot sizes and real order placement are
involved — that's a Part B (execution platform) concern, not a backtesting one.
"""

from dataclasses import dataclass
from datetime import datetime

from core.enums import PositionSide


@dataclass(frozen=True, slots=True)
class Symbol:
    """Canonical, exchange-agnostic symbol identity.

    `base`/`quote` are normalized to uppercase on construction — including when
    built directly (not via `.parse()`) — so `Symbol(base="btc", quote="usdt")` and
    `Symbol(base="BTC", quote="USDT")` are the same identity. Without this, case
    differences would silently fragment the Parquet store's file paths, the feature
    cache's keys, and position-tracking dict keys, since all of those key off
    `canonical`/`native()`.
    """

    base: str
    quote: str
    exchange: str = "binance_futures"

    def __post_init__(self) -> None:
        object.__setattr__(self, "base", self.base.upper())
        object.__setattr__(self, "quote", self.quote.upper())

    @property
    def canonical(self) -> str:
        return f"{self.base}/{self.quote}"

    def __str__(self) -> str:
        return self.canonical

    @classmethod
    def parse(cls, value: str, exchange: str = "binance_futures") -> "Symbol":
        """Parse "BTC/USDT" or Binance-native "BTCUSDT" (assumes USDT/USDC/BUSD quote)."""
        if "/" in value:
            base, quote = value.split("/", 1)
            return cls(base=base.upper(), quote=quote.upper(), exchange=exchange)
        for quote in ("USDT", "USDC", "BUSD", "BTC"):
            if value.upper().endswith(quote) and len(value) > len(quote):
                return cls(base=value.upper()[: -len(quote)], quote=quote, exchange=exchange)
        raise ValueError(f"Cannot parse symbol: {value!r}")

    def native(self) -> str:
        """Binance-native symbol string, e.g. BTCUSDT."""
        return f"{self.base}{self.quote}"


@dataclass(frozen=True, slots=True)
class Position:
    """Read-only snapshot of an open position, as seen by a strategy's context."""

    symbol: Symbol
    side: PositionSide
    entry_price: float
    quantity: float
    opened_at: datetime
    stop_loss: float | None = None
    take_profit: float | None = None
