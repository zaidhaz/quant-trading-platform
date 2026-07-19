"""Production-grade incremental sync of the full Binance USDⓈ-M Futures data
layer (candles across every supported timeframe, funding rate, mark price,
premium index, open interest) for one or more symbols.

- **Never redownloads existing data**: `HistoricalDataset.ensure_range()`
  only ever fetches the sub-ranges missing from the local Parquet store
  (`market_data/historical/dataset.py::find_gaps`).
- **Never hardcodes a date range**: every dataset auto-detects its own real
  earliest available timestamp (`find_earliest_available()` /
  `sync_full_history()`) instead of assuming a listing date.
- **Resumable**: safe to interrupt and rerun — a partial prior run just
  leaves gaps that the next run fills; nothing needs to track "where it left
  off" separately from what's already on disk.
- **Deduplicated on write**: `ParquetStore.write()` merges, drops duplicate
  timestamps (keep last), and sorts on every write — the per-dataset quality
  report below is a verification/reporting step over that already-repaired
  storage, not a second repair pass.
- **Never fabricates missing history**: Open Interest is clamped to
  Binance's documented ~30-day retention window
  (`open_interest_dataset.py::OPEN_INTEREST_MAX_LOOKBACK_DAYS`); any dataset
  a source genuinely has no data for is reported as such (`DataGapError`
  from `sync_full_history()`), never silently skipped or backfilled with
  invented values.

Usage:
    python -m scripts.sync_historical_data --symbols BTCUSDT ETHUSDT
    python -m scripts.sync_historical_data --symbols BTCUSDT \\
        --candle-timeframes 1h 4h --skip-open-interest
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

import pandas as pd

from config.logging import configure_logging
from config.settings import get_settings
from core.exceptions import DataGapError
from core.types import Symbol
from market_data.historical.binance_client import BinanceFuturesClient
from market_data.historical.candles_dataset import CandlesDataset
from market_data.historical.dataset import HistoricalDataset
from market_data.historical.exchange_info import get_symbol_info
from market_data.historical.funding_rate_dataset import FundingRateDataset
from market_data.historical.mark_price_dataset import MarkPriceDataset
from market_data.historical.open_interest_dataset import OpenInterestDataset
from market_data.historical.parquet_store import ParquetStore
from market_data.historical.premium_index_dataset import PremiumIndexDataset
from research import data_quality as dq

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT")
DEFAULT_CANDLE_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
# Mark price / premium index are synced at a coarser subset of timeframes by
# default -- a scope choice (not a capability limit: the dataset classes
# support any SUPPORTED_TIMEFRAMES value), stated explicitly rather than
# silently applied, to keep a default full sync's request volume reasonable.
DEFAULT_MARK_PREMIUM_TIMEFRAMES = ("1h", "4h")


@dataclass(slots=True)
class SyncOutcome:
    symbol: str
    dataset: str
    timeframe: str | None
    rows: int
    start: str | None
    end: str | None
    clean: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _quality_check(dataset_name: str, symbol_str: str, timeframe: str | None, df: pd.DataFrame):
    if dataset_name in ("candles", "mark_price", "premium_index"):
        return dq.repair_and_check_candles(symbol_str, timeframe or "-", df)[1]
    if dataset_name == "funding_rate":
        return dq.repair_and_check_funding(symbol_str, df)[1]
    if dataset_name == "open_interest":
        return dq.repair_and_check_open_interest(symbol_str, df)[1]
    raise ValueError(f"no quality checker registered for dataset {dataset_name!r}")


def sync_one(
    symbol_str: str,
    symbol: Symbol,
    dataset_name: str,
    timeframe: str | None,
    dataset: HistoricalDataset,
) -> SyncOutcome:
    try:
        df = dataset.sync_full_history(symbol, timeframe)
    except (DataGapError, ConnectionError) as exc:
        logger.error("%s %s [%s]: %s", symbol_str, dataset_name, timeframe, exc)
        return SyncOutcome(symbol_str, dataset_name, timeframe, 0, None, None, False, str(exc))

    report = _quality_check(dataset_name, symbol_str, timeframe, df)
    if not report.clean:
        logger.warning(
            "data quality issues for %s %s [%s]:\n%s",
            symbol_str,
            dataset_name,
            timeframe,
            dq.format_report(report),
        )

    return SyncOutcome(
        symbol=symbol_str,
        dataset=dataset_name,
        timeframe=timeframe,
        rows=len(df),
        start=str(df.index.min()) if not df.empty else None,
        end=str(df.index.max()) if not df.empty else None,
        clean=report.clean,
    )


def sync_symbol(
    symbol_str: str,
    store: ParquetStore,
    client: BinanceFuturesClient,
    candle_timeframes: tuple[str, ...],
    mark_premium_timeframes: tuple[str, ...],
    sync_mark_price: bool = True,
    sync_premium_index: bool = True,
    sync_open_interest: bool = True,
) -> list[SyncOutcome]:
    symbol = Symbol.parse(symbol_str)
    outcomes: list[SyncOutcome] = []

    try:
        info = get_symbol_info(client, symbol.native())
        if info is None:
            logger.warning(
                "%s not present in current exchangeInfo (delisted or never listed on "
                "Binance Futures) -- sync will still be attempted per-dataset below, "
                "each of which will report its own DataGapError if there's truly "
                "nothing to fetch",
                symbol_str,
            )
        else:
            logger.info(
                "%s exchangeInfo: status=%s contract_type=%s onboard_date=%s "
                "(cross-check against each dataset's own empirically-detected start)",
                symbol_str,
                info.status,
                info.contract_type,
                info.onboard_date,
            )
    except (ConnectionError, ValueError) as exc:
        logger.warning("exchangeInfo lookup failed for %s (non-fatal): %s", symbol_str, exc)

    candles_ds = CandlesDataset(store, client)
    for tf in candle_timeframes:
        outcomes.append(sync_one(symbol_str, symbol, "candles", tf, candles_ds))

    outcomes.append(
        sync_one(symbol_str, symbol, "funding_rate", None, FundingRateDataset(store, client))
    )

    if sync_mark_price:
        mark_ds = MarkPriceDataset(store, client)
        for tf in mark_premium_timeframes:
            outcomes.append(sync_one(symbol_str, symbol, "mark_price", tf, mark_ds))

    if sync_premium_index:
        premium_ds = PremiumIndexDataset(store, client)
        for tf in mark_premium_timeframes:
            outcomes.append(sync_one(symbol_str, symbol, "premium_index", tf, premium_ds))

    if sync_open_interest:
        outcomes.append(
            sync_one(symbol_str, symbol, "open_interest", None, OpenInterestDataset(store, client))
        )

    return outcomes


def format_summary(outcomes: list[SyncOutcome]) -> str:
    lines = [
        "| Symbol | Dataset | Timeframe | Rows | Start | End | Clean | Error |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for o in outcomes:
        lines.append(
            f"| {o.symbol} | {o.dataset} | {o.timeframe or '-'} | {o.rows:,} | "
            f"{o.start or '-'} | {o.end or '-'} | {'yes' if o.clean else 'NO'} | "
            f"{o.error or ''} |"
        )
    ok_count = sum(1 for o in outcomes if o.ok)
    lines.append("")
    lines.append(
        f"{ok_count}/{len(outcomes)} dataset x timeframe combinations synced successfully."
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--candle-timeframes", nargs="+", default=list(DEFAULT_CANDLE_TIMEFRAMES))
    parser.add_argument(
        "--mark-premium-timeframes", nargs="+", default=list(DEFAULT_MARK_PREMIUM_TIMEFRAMES)
    )
    parser.add_argument("--skip-mark-price", action="store_true")
    parser.add_argument("--skip-premium-index", action="store_true")
    parser.add_argument("--skip-open-interest", action="store_true")
    parser.add_argument(
        "--summary-out", default=None, help="optional path to write the summary table"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging()
    settings = get_settings()

    store = ParquetStore(settings.historical_data_dir)
    client = BinanceFuturesClient()
    all_outcomes: list[SyncOutcome] = []
    try:
        for symbol_str in args.symbols:
            all_outcomes.extend(
                sync_symbol(
                    symbol_str,
                    store,
                    client,
                    tuple(args.candle_timeframes),
                    tuple(args.mark_premium_timeframes),
                    sync_mark_price=not args.skip_mark_price,
                    sync_premium_index=not args.skip_premium_index,
                    sync_open_interest=not args.skip_open_interest,
                )
            )
    finally:
        client.close()

    summary = format_summary(all_outcomes)
    print(summary)
    if args.summary_out:
        with open(args.summary_out, "w") as f:
            f.write(summary + "\n")


if __name__ == "__main__":
    main()
