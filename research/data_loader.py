"""Data-source resolution for the research pipeline.

This is the one place that decides, per symbol/timeframe, whether the
pipeline runs on real Binance history or on synthetic data — and the reason
`scripts/run_research_pipeline.py` needs zero changes to produce a real
study the moment real data is available: `mode="auto"` (the pipeline's
default) tries real data first and only falls back to synthetic when it
genuinely can't get real data, clearly labeling every result with which one
it actually used.

Three modes:
- `"auto"` (default): try real Binance data; if unreachable, fall back to
  synthetic with a logged reason. Right tool for an unattended/CI-style run.
- `"real"`: real Binance data or fail loudly (`ConnectionError`/
  `DataGapError` propagates) — no silent fallback. Right tool for someone
  deliberately running the definitive study who needs to know immediately
  if it can't get real data.
- `"synthetic"`: always synthetic, for continued methodology testing (what
  every prior run in this environment has used, since network access to
  `fapi.binance.com` is blocked here — see `research/__init__.py`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from config.settings import get_settings
from core.exceptions import DataGapError
from core.types import Symbol
from market_data.historical.binance_client import BinanceFuturesClient
from market_data.historical.candles_dataset import CandlesDataset
from market_data.historical.funding_rate_dataset import FundingRateDataset
from market_data.historical.parquet_store import ParquetStore
from research import synthetic_history as sh

logger = logging.getLogger(__name__)

DataSourceMode = str  # "auto" | "real" | "synthetic"


@dataclass(slots=True)
class LoadedHistory:
    candles: pd.DataFrame
    funding: pd.DataFrame
    source: str  # "real" | "synthetic"
    detail: str  # human-readable provenance note, always safe to put in a report


def load_history(
    symbol_str: str,
    timeframe: str,
    mode: DataSourceMode = "auto",
    store: ParquetStore | None = None,
    client: BinanceFuturesClient | None = None,
) -> LoadedHistory:
    if mode not in ("auto", "real", "synthetic"):
        raise ValueError(f"mode must be 'auto', 'real', or 'synthetic', got {mode!r}")

    if mode == "synthetic":
        return _load_synthetic(symbol_str, timeframe)

    client = client or BinanceFuturesClient()
    if not client.ping():
        reason = "fapi.binance.com unreachable (ping failed)"
        if mode == "real":
            raise ConnectionError(reason)
        logger.warning(
            "%s [%s]: %s — falling back to synthetic data (mode='auto')",
            symbol_str,
            timeframe,
            reason,
        )
        return _load_synthetic(symbol_str, timeframe, reason=reason)

    try:
        return _load_real(symbol_str, timeframe, store, client)
    except (DataGapError, ConnectionError) as exc:
        if mode == "real":
            raise
        logger.warning(
            "%s [%s]: real data fetch failed (%s) — falling back to synthetic "
            "data (mode='auto')",
            symbol_str,
            timeframe,
            exc,
        )
        return _load_synthetic(symbol_str, timeframe, reason=str(exc))


def _load_real(
    symbol_str: str, timeframe: str, store: ParquetStore | None, client: BinanceFuturesClient
) -> LoadedHistory:
    settings = get_settings()
    store = store or ParquetStore(settings.historical_data_dir)
    symbol = Symbol.parse(symbol_str)

    candles = CandlesDataset(store, client).sync_full_history(symbol, timeframe)
    funding = FundingRateDataset(store, client).sync_full_history(symbol)

    detail = (
        f"REAL Binance USDⓈ-M Futures data via HistoricalDataset.sync_full_history() "
        f"({len(candles)} candles, {candles.index.min()} to {candles.index.max()})"
        if not candles.empty
        else "REAL data source reached, but returned zero candles"
    )
    return LoadedHistory(candles=candles, funding=funding, source="real", detail=detail)


def _load_synthetic(symbol_str: str, timeframe: str, reason: str | None = None) -> LoadedHistory:
    listing = sh.ASSUMED_LISTING_DATE.get(symbol_str, datetime(2019, 1, 1, tzinfo=UTC))
    now = datetime.now(UTC)
    candles = sh.generate_ohlcv(symbol_str, timeframe, listing, now)
    funding = sh.generate_funding(symbol_str, listing, now)

    detail = "SYNTHETIC data (research/synthetic_history.py) — NOT real market history"
    if reason:
        detail += f"; real data unavailable: {reason}"
    return LoadedHistory(candles=candles, funding=funding, source="synthetic", detail=detail)
