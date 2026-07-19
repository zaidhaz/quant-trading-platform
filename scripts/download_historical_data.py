"""CLI: download Binance Futures historical data into the local Parquet store.

Usage:
    python scripts/download_historical_data.py --symbol BTC/USDT --timeframe 1h \\
        --start 2023-01-01 --end 2024-01-01 --dataset candles

    python scripts/download_historical_data.py --symbol BTC/USDT \\
        --start 2023-01-01 --end 2024-01-01 --dataset funding_rate
"""

from __future__ import annotations

import argparse
from datetime import datetime

from config.logging import configure_logging
from config.settings import get_settings
from core.types import Symbol
from market_data.historical.candles_dataset import CandlesDataset
from market_data.historical.funding_rate_dataset import FundingRateDataset
from market_data.historical.parquet_store import ParquetStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True, help="e.g. BTC/USDT")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--dataset", choices=["candles", "funding_rate"], default="candles")
    parser.add_argument("--timeframe", default="1h", help="Required for --dataset candles")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging()
    settings = get_settings()

    symbol = Symbol.parse(args.symbol)
    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    store = ParquetStore(settings.historical_data_dir)

    if args.dataset == "candles":
        dataset = CandlesDataset(store)
        df = dataset.ensure_range(symbol, start, end, timeframe=args.timeframe)
    else:
        dataset = FundingRateDataset(store)
        df = dataset.ensure_range(symbol, start, end)

    print(
        f"{args.dataset} for {symbol} [{args.timeframe if args.dataset == 'candles' else '-'}]: "
        f"{len(df)} rows, {df.index.min() if not df.empty else '-'} to "
        f"{df.index.max() if not df.empty else '-'}"
    )


if __name__ == "__main__":
    main()
