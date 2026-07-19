"""Phases 1-9 long-horizon research pipeline for the Liquidity Exhaustion
Reversal System, run on SYNTHETIC data (see `research/__init__.py` for why:
`fapi.binance.com` is unreachable from this sandbox — verified, not assumed).

Writes `docs/research/LIQUIDITY_EXHAUSTION_REVERSAL_LONG_HORIZON_REPORT.md`.

Usage:
    python scripts/run_research_pipeline.py
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from analytics import performance_metrics as pm
from core.types import Symbol
from research import data_quality as dq
from research import monte_carlo as mc
from research import regime_analysis as ra
from research import robustness as rb
from research import rolling_validation as rv
from research import synthetic_history as sh
from research.backtest_runner import run as run_backtest
from research.trade_records import build_trade_records

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
ALL_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]
DEEP_ANALYSIS_TIMEFRAME = "1h"
SECONDARY_TIMEFRAME = "4h"
ROBUSTNESS_WINDOW_YEARS = 2  # scoped down from full history for compute cost, stated in report
NOW = datetime(2026, 7, 19, tzinfo=UTC)

REPORT_PATH = Path("docs/research/LIQUIDITY_EXHAUSTION_REVERSAL_LONG_HORIZON_REPORT.md")

_start_time = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - _start_time:8.1f}s] {msg}", flush=True)


def main() -> None:
    # ------------------------------------------------------------------
    # Phase 0/1: dataset generation + provenance
    # ------------------------------------------------------------------
    log("Phase 1: generating synthetic history for every symbol x timeframe")
    dataset_summaries = []
    quality_reports = []
    for sym_str in SYMBOLS:
        listing = sh.ASSUMED_LISTING_DATE[sym_str]
        for tf in ALL_TIMEFRAMES:
            candles = sh.generate_ohlcv(sym_str, tf, listing, NOW)
            dataset_summaries.append(sh.dataset_summary(sym_str, tf, candles))
            _, report = dq.repair_and_check_candles(sym_str, tf, candles)
            quality_reports.append(report)
            log(
                f"  {sym_str} [{tf}]: {len(candles):,} rows, "
                f"{'CLEAN' if report.clean else 'ISSUES'}"
            )
        funding = sh.generate_funding(sym_str, listing, NOW)
        _, freport = dq.repair_and_check_funding(sym_str, funding)
        quality_reports.append(freport)
        log(
            f"  {sym_str} funding: {len(funding):,} rows, "
            f"{'CLEAN' if freport.clean else 'ISSUES'}"
        )

    # ------------------------------------------------------------------
    # Phase 3/4/5/6: deep analysis at the primary + secondary timeframe
    # ------------------------------------------------------------------
    deep_results: dict[str, dict] = {}
    for sym_str in SYMBOLS:
        symbol = Symbol.parse(sym_str)
        listing = sh.ASSUMED_LISTING_DATE[sym_str]
        deep_results[sym_str] = {}

        for tf in (DEEP_ANALYSIS_TIMEFRAME, SECONDARY_TIMEFRAME):
            log(f"Phase 3: full-history backtest {sym_str} [{tf}]")
            candles = sh.generate_ohlcv(sym_str, tf, listing, NOW)
            funding = sh.generate_funding(sym_str, listing, NOW)
            out = run_backtest(symbol, tf, candles, funding)
            records = build_trade_records(out)
            summary = pm.summarize(out.result.equity_curve, out.result.closed_trades, tf)
            log(
                f"  {len(records)} trades, net_return={summary['net_return']:.2%}, "
                f"sharpe={summary['sharpe_ratio']:.2f}, max_dd={summary['max_drawdown']:.2%}"
            )

            deep_results[sym_str][tf] = {
                "out": out,
                "records": records,
                "summary": summary,
                "candles": candles,
                "funding": funding,
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
    # Phase 7: robustness (scoped to a recent window for compute cost)
    # ------------------------------------------------------------------
    robustness_results: dict[str, dict] = {}
    robustness_start = NOW.replace(year=NOW.year - ROBUSTNESS_WINDOW_YEARS)
    for sym_str in SYMBOLS:
        symbol = Symbol.parse(sym_str)
        log(
            f"Phase 7: robustness sweep {sym_str} [{DEEP_ANALYSIS_TIMEFRAME}] "
            f"(last {ROBUSTNESS_WINDOW_YEARS}y, scoped for compute cost)"
        )
        candles = sh.generate_ohlcv(sym_str, DEEP_ANALYSIS_TIMEFRAME, robustness_start, NOW)
        funding = sh.generate_funding(sym_str, robustness_start, NOW)
        perturbations = rb.run_robustness_sweep(symbol, DEEP_ANALYSIS_TIMEFRAME, candles, funding)
        structural = rb.run_structural_filter_comparison(
            symbol, DEEP_ANALYSIS_TIMEFRAME, candles, funding
        )
        robustness_results[sym_str] = {"perturbations": perturbations, "structural": structural}
        fragile_count = sum(1 for p in perturbations if p.fragile)
        log(f"  {fragile_count}/{len(perturbations)} parameters flagged fragile")

    log("Phase 8/9: assembling report")
    _write_report(dataset_summaries, quality_reports, deep_results, robustness_results)
    log(f"Report written to {REPORT_PATH}")


def _write_report(dataset_summaries, quality_reports, deep_results, robustness_results) -> None:
    from scripts._research_report_body import build_report  # local import, see that module

    text = build_report(
        now=NOW,
        dataset_summaries=dataset_summaries,
        quality_reports=quality_reports,
        deep_results=deep_results,
        robustness_results=robustness_results,
        robustness_window_years=ROBUSTNESS_WINDOW_YEARS,
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(text)


if __name__ == "__main__":
    main()
