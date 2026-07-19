"""Symbol metadata — `/fapi/v1/exchangeInfo`. Not a time-series
`HistoricalDataset` (it's a single current snapshot, no start/end range), so
it lives separately rather than being forced into that abstraction.

Primary use in this platform: `onboardDate` is Binance's own record of a
contract's listing date — an authoritative cross-check against the empirical
`find_earliest_available()` probes every `HistoricalDataset` subclass
implements (which read the true first data point directly, and are what the
sync script actually uses to start a download — see
`scripts/sync_historical_data.py`). The two should agree to within a few
minutes; a meaningful disagreement would indicate something worth
investigating (a backfilled/relisted contract, a data gap right at listing),
not something to silently paper over.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from market_data.historical.binance_client import BinanceFuturesClient


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    symbol: str
    status: str
    contract_type: str
    onboard_date: datetime | None
    price_precision: int
    quantity_precision: int


def get_symbol_info(client: BinanceFuturesClient, symbol_native: str) -> SymbolInfo | None:
    """None if `symbol_native` isn't in the current exchangeInfo response at
    all — not currently listed on Binance Futures (never existed, or was
    delisted)."""
    info = client.get_exchange_info()
    for entry in info.get("symbols", []):
        if entry.get("symbol") != symbol_native:
            continue
        onboard_ms = entry.get("onboardDate")
        return SymbolInfo(
            symbol=symbol_native,
            status=str(entry.get("status", "")),
            contract_type=str(entry.get("contractType", "")),
            onboard_date=(
                datetime.fromtimestamp(int(onboard_ms) / 1000, tz=UTC) if onboard_ms else None
            ),
            price_precision=int(entry.get("pricePrecision", 0)),
            quantity_precision=int(entry.get("quantityPrecision", 0)),
        )
    return None
