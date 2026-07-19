"""CLI: run a backtest against locally stored historical data and print a summary.

Usage:
    python scripts/download_historical_data.py --symbol BTC/USDT \\
        --start 2023-01-01 --end 2024-01-01
    python scripts/download_historical_data.py --symbol BTC/USDT \\
        --start 2023-01-01 --end 2024-01-01 --dataset funding_rate

    python scripts/run_backtest.py --strategy ma_crossover --symbol BTC/USDT \\
        --timeframe 1h --start 2023-01-01 --end 2024-01-01 \\
        --params '{"fast_period": 10, "slow_period": 30}'
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

# Import registers @register_strategy-decorated classes as a side effect.
import strategies.examples.ma_crossover  # noqa: F401,E402
import strategies.examples.mean_reversion  # noqa: F401,E402
from analytics import performance_metrics as pm
from backtesting.data_feed import DataFeed
from backtesting.engine import BacktestConfig, BacktestEngine
from config.logging import configure_logging
from config.settings import get_settings
from core.types import Symbol
from journal.exporters.csv_exporter import export_csv
from journal.journal_recorder import JournalRecorder
from market_data.historical.candles_dataset import CandlesDataset
from market_data.historical.funding_rate_dataset import FundingRateDataset
from market_data.historical.parquet_store import ParquetStore
from risk.limits import RiskLimits
from strategies.registry import create_strategy  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--strategy", required=True, help="registered strategy name, e.g. ma_crossover"
    )
    parser.add_argument("--symbol", required=True, help="e.g. BTC/USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--params", default="{}", help="JSON dict of strategy params")
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument("--fee-rate", type=float, default=0.0004)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument(
        "--journal-csv", default=None, help="optional path to export the trade journal"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging()
    settings = get_settings()

    symbol = Symbol.parse(args.symbol)
    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    params = json.loads(args.params)

    store = ParquetStore(settings.historical_data_dir)
    feed = DataFeed.load(
        symbol, args.timeframe, start, end, CandlesDataset(store), FundingRateDataset(store)
    )

    strategy = create_strategy(args.strategy, **params)
    config = BacktestConfig(
        initial_capital=args.initial_capital,
        taker_fee_rate=args.fee_rate,
        slippage_bps=args.slippage_bps,
        risk_limits=RiskLimits(),
    )
    engine = BacktestEngine(strategy, feed, config, strategy_id=args.strategy)
    journal = JournalRecorder(engine.bus)
    result = engine.run()

    summary = pm.summarize(result.equity_curve, result.closed_trades, args.timeframe)

    print(f"Strategy: {args.strategy}  Symbol: {symbol}  Timeframe: {args.timeframe}")
    print(f"Bars: {len(feed)}  Signals: {len(result.signals)}  Trades: {len(result.closed_trades)}")
    print(
        f"Initial capital: {result.initial_capital:,.2f}  Final equity: {result.final_equity:,.2f}"
    )
    for key in (
        "net_return",
        "cagr",
        "sharpe_ratio",
        "sortino_ratio",
        "profit_factor",
        "win_rate",
        "average_r_multiple",
        "max_drawdown",
    ):
        value = summary[key]
        print(f"  {key}: {value:.4f}" if isinstance(value, float) else f"  {key}: {value}")
    print(
        f"  max_consecutive_wins: {summary['max_consecutive_wins']}  "
        f"max_consecutive_losses: {summary['max_consecutive_losses']}"
    )

    if args.journal_csv:
        export_csv(journal.entries, Path(args.journal_csv))
        print(f"Journal exported to {args.journal_csv}")


if __name__ == "__main__":
    main()
