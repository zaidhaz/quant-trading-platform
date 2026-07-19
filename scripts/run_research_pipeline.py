"""Phases 1-9 long-horizon research pipeline for the Liquidity Exhaustion
Reversal System.

Data source is resolved per symbol/timeframe by `research/data_loader.py`:
`--data-source auto` (default) tries real Binance data first and falls back
to clearly-labeled synthetic data only when real data is genuinely
unavailable (as it is in this sandbox today — `fapi.binance.com` is
network-blocked, verified directly, not assumed). `--data-source real` fails
loudly instead of silently falling back. `--data-source synthetic` always
uses synthetic data (continued methodology testing). This -- one script, one
flag, real-data-first by default -- is what makes "the moment real data
exists, this platform performs the definitive study" literally true: nothing
in this file needs to change when that day comes.

Writes `docs/research/LIQUIDITY_EXHAUSTION_REVERSAL_LONG_HORIZON_REPORT.md`.

Usage:
    python -m scripts.run_research_pipeline
    python -m scripts.run_research_pipeline --data-source real
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from analytics import performance_metrics as pm
from core.types import Symbol
from research import data_quality as dq
from research import monte_carlo as mc
from research import regime_analysis as ra
from research import robustness as rb
from research import rolling_validation as rv
from research.backtest_runner import run as run_backtest
from research.data_loader import LoadedHistory, load_history
from research.trade_records import build_trade_records

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
ALL_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]
DEEP_ANALYSIS_TIMEFRAME = "1h"
SECONDARY_TIMEFRAME = "4h"
ROBUSTNESS_WINDOW_YEARS = 2  # scoped down from full history for compute cost, stated in report

REPORT_PATH = Path("docs/research/LIQUIDITY_EXHAUSTION_REVERSAL_LONG_HORIZON_REPORT.md")

_start_time = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - _start_time:8.1f}s] {msg}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--data-source",
        choices=["auto", "real", "synthetic"],
        default="auto",
        help="auto (default): real Binance data, synthetic fallback if unreachable. "
        "real: real data or fail loudly. synthetic: always synthetic.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    log(f"data source mode: {args.data_source!r}")

    # ------------------------------------------------------------------
    # Phase 1/2: dataset loading + data quality
    # ------------------------------------------------------------------
    log("Phase 1: loading history for every symbol x timeframe")
    dataset_summaries = []
    quality_reports = []
    last_loaded_by_symbol: dict[str, LoadedHistory] = {}
    for sym_str in SYMBOLS:
        for tf in ALL_TIMEFRAMES:
            loaded = load_history(sym_str, tf, mode=args.data_source)
            last_loaded_by_symbol[sym_str] = loaded
            dataset_summaries.append(
                {
                    "symbol": sym_str,
                    "timeframe": tf,
                    "rows": len(loaded.candles),
                    "start": str(loaded.candles.index.min()) if not loaded.candles.empty else None,
                    "end": str(loaded.candles.index.max()) if not loaded.candles.empty else None,
                    "source": loaded.source,
                }
            )
            _, report = dq.repair_and_check_candles(sym_str, tf, loaded.candles)
            quality_reports.append(report)
            log(
                f"  {sym_str} [{tf}] ({loaded.source}): {len(loaded.candles):,} rows, "
                f"{'CLEAN' if report.clean else 'ISSUES'}"
            )
        # Funding is timeframe-independent -- one check per symbol, reusing
        # whichever per-timeframe load happened last (same underlying series).
        funding_df = last_loaded_by_symbol[sym_str].funding
        _, freport = dq.repair_and_check_funding(sym_str, funding_df)
        quality_reports.append(freport)
        log(
            f"  {sym_str} funding: {len(funding_df):,} rows, "
            f"{'CLEAN' if freport.clean else 'ISSUES'}"
        )

    # ------------------------------------------------------------------
    # Phase 3/4/5/6: deep analysis at the primary + secondary timeframe
    # ------------------------------------------------------------------
    deep_results: dict[str, dict] = {}
    for sym_str in SYMBOLS:
        symbol = Symbol.parse(sym_str)
        deep_results[sym_str] = {}

        for tf in (DEEP_ANALYSIS_TIMEFRAME, SECONDARY_TIMEFRAME):
            log(f"Phase 3: full-history backtest {sym_str} [{tf}]")
            loaded = load_history(sym_str, tf, mode=args.data_source)
            out = run_backtest(symbol, tf, loaded.candles, loaded.funding)
            records = build_trade_records(out)
            summary = pm.summarize(out.result.equity_curve, out.result.closed_trades, tf)
            log(
                f"  ({loaded.source}) {len(records)} trades, "
                f"net_return={summary['net_return']:.2%}, sharpe={summary['sharpe_ratio']:.2f}, "
                f"max_dd={summary['max_drawdown']:.2%}"
            )

            deep_results[sym_str][tf] = {
                "out": out,
                "records": records,
                "summary": summary,
                "candles": loaded.candles,
                "funding": loaded.funding,
                "source": loaded.source,
            }

        # Phase 4: regime segmentation (primary timeframe only)
        log(f"Phase 4: regime segmentation {sym_str} [{DEEP_ANALYSIS_TIMEFRAME}]")
        primary_records = deep_results[sym_str][DEEP_ANALYSIS_TIMEFRAME]["records"]
        deep_results[sym_str]["true_regime_segments"] = ra.by_true_market_condition(
            sym_str, primary_records
        )
        deep_results[sym_str]["strategy_regime_segments"] = ra.by_strategy_observed_regime(
            primary_records
        )

        # Phase 5: rolling out-of-sample validation (primary timeframe only)
        log(f"Phase 5: rolling out-of-sample validation {sym_str} [{DEEP_ANALYSIS_TIMEFRAME}]")
        primary_candles = deep_results[sym_str][DEEP_ANALYSIS_TIMEFRAME]["candles"]
        primary_funding = deep_results[sym_str][DEEP_ANALYSIS_TIMEFRAME]["funding"]
        deep_results[sym_str]["rolling"] = rv.run_rolling_validation(
            symbol,
            DEEP_ANALYSIS_TIMEFRAME,
            primary_candles,
            primary_funding,
            warmup_days=180,
            test_days=180,
            step_days=180,
        )

        # Phase 6: Monte Carlo (primary timeframe only)
        log(f"Phase 6: Monte Carlo {sym_str} [{DEEP_ANALYSIS_TIMEFRAME}]")
        deep_results[sym_str]["monte_carlo"] = mc.run_monte_carlo(primary_records)

    # ------------------------------------------------------------------
    # Phase 7: robustness — sliced from the already-loaded full history down
    # to the most recent ROBUSTNESS_WINDOW_YEARS (no second fetch/generation
    # needed, works identically whether the source was real or synthetic)
    # ------------------------------------------------------------------
    robustness_results: dict[str, dict] = {}
    for sym_str in SYMBOLS:
        symbol = Symbol.parse(sym_str)
        log(
            f"Phase 7: robustness sweep {sym_str} [{DEEP_ANALYSIS_TIMEFRAME}] "
            f"(last {ROBUSTNESS_WINDOW_YEARS}y, scoped for compute cost)"
        )
        full_candles = deep_results[sym_str][DEEP_ANALYSIS_TIMEFRAME]["candles"]
        full_funding = deep_results[sym_str][DEEP_ANALYSIS_TIMEFRAME]["funding"]
        if full_candles.empty:
            robustness_results[sym_str] = {"perturbations": [], "structural": []}
            log("  no candles available, skipping")
            continue
        window_start = full_candles.index.max() - pd.Timedelta(days=365 * ROBUSTNESS_WINDOW_YEARS)
        candles = full_candles.loc[window_start:]
        funding = full_funding.loc[window_start:] if not full_funding.empty else full_funding

        perturbations = rb.run_robustness_sweep(symbol, DEEP_ANALYSIS_TIMEFRAME, candles, funding)
        structural = rb.run_structural_filter_comparison(
            symbol, DEEP_ANALYSIS_TIMEFRAME, candles, funding
        )
        robustness_results[sym_str] = {"perturbations": perturbations, "structural": structural}
        fragile_count = sum(1 for p in perturbations if p.fragile)
        log(f"  {fragile_count}/{len(perturbations)} parameters flagged fragile")

    log("Phase 8/9: assembling report")
    _write_report(dataset_summaries, quality_reports, deep_results, robustness_results, args)
    log(f"Report written to {REPORT_PATH}")


def _write_report(
    dataset_summaries, quality_reports, deep_results, robustness_results, args
) -> None:
    from scripts._research_report_body import build_report  # local import, see that module

    text = build_report(
        now=datetime.now(UTC),
        dataset_summaries=dataset_summaries,
        quality_reports=quality_reports,
        deep_results=deep_results,
        robustness_results=robustness_results,
        robustness_window_years=ROBUSTNESS_WINDOW_YEARS,
        data_source_mode=args.data_source,
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(text)


if __name__ == "__main__":
    main()
