"""Phase 7 — parameter-sensitivity / robustness check.

**Not optimization.** Every parameter is perturbed one at a time, ~±10% off
its current production default (`LiquidityExhaustionReversalConfig`'s own
defaults — see `docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md` §9), the
backtest is rerun, and the resulting metrics are compared to the unperturbed
baseline. No search, no picking the best perturbation, no keeping a "better"
value — the only output is *how much a small nudge moves the numbers*. Two
of the requested checks (Fair Value Gap filter, Order Block filter) are
boolean, not continuous, so they're reported as an on/off structural
comparison instead of a ±10% numeric one — noted explicitly rather than
forcing a percentage onto a switch.

If a metric swings sharply (sign flips, or a large relative move) for a tiny
input change, that specific case is the fragility signature described in the
task: "if performance collapses after tiny changes, report that the strategy
is likely overfit."
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from analytics import performance_metrics as pm
from core.types import Symbol
from research.backtest_runner import run
from research.trade_records import build_trade_records

PERTURBATION_PCT = 0.10

# name -> production default; only float/continuous config fields are perturbed
# by a clean +/-10%. Integer fields where 10% would round to zero change (e.g.
# min_touches=2, fractal_width=2) are excluded for that reason, stated here
# rather than silently skipped.
_PERTURBED_PARAMS: dict[str, float] = {
    "displacement_atr_mult": 1.5,
    "sweep_margin_atr_mult": 0.1,
    "tolerance_atr_mult": 0.15,
    "strong_close_threshold": 0.5,
    "absorption_percentile": 80.0,
    "stop_buffer_atr_mult": 0.1,
    "take_profit_r_multiple": 2.0,
    "risk_per_trade": 0.01,
    "pool_lookback_bars": 100.0,
}

_STRUCTURAL_FILTERS = ("require_fvg", "require_order_block")


@dataclass(slots=True)
class RunMetrics:
    trade_count: int
    net_return: float
    cagr: float
    sharpe_ratio: float
    profit_factor: float
    max_drawdown: float


@dataclass(slots=True)
class PerturbationResult:
    parameter: str
    base_value: float
    low_value: float
    high_value: float
    base: RunMetrics
    low: RunMetrics
    high: RunMetrics
    fragile: bool
    fragility_reason: str


def _metrics(symbol: Symbol, timeframe: str, candles, funding, params: dict) -> RunMetrics:
    out = run(symbol, timeframe, candles, funding, strategy_params=params)
    records = build_trade_records(out)
    trades = out.result.closed_trades
    return RunMetrics(
        trade_count=len(records),
        net_return=pm.net_return(out.result.equity_curve),
        cagr=pm.cagr(out.result.equity_curve),
        sharpe_ratio=pm.sharpe_ratio(out.result.equity_curve, timeframe),
        profit_factor=pm.profit_factor(trades),
        max_drawdown=pm.max_drawdown(out.result.equity_curve),
    )


def _is_fragile(base: RunMetrics, low: RunMetrics, high: RunMetrics) -> tuple[bool, str]:
    for variant, label in ((low, "-10%"), (high, "+10%")):
        if (base.sharpe_ratio > 0) != (variant.sharpe_ratio > 0) and abs(
            base.sharpe_ratio - variant.sharpe_ratio
        ) > 0.1:
            return True, f"Sharpe sign flips at {label}"
        base_pf = min(base.profit_factor, 10.0)  # cap so inf/huge PF doesn't dominate the ratio
        variant_pf = min(variant.profit_factor, 10.0)
        if base_pf > 0 and abs(variant_pf - base_pf) / base_pf > 0.75:
            return True, f"profit factor moves >75% at {label} ({base_pf:.2f} -> {variant_pf:.2f})"
    return False, ""


def run_robustness_sweep(
    symbol: Symbol, timeframe: str, candles: pd.DataFrame, funding: pd.DataFrame
) -> list[PerturbationResult]:
    base_metrics = _metrics(symbol, timeframe, candles, funding, {})
    results = []
    for name, default in _PERTURBED_PARAMS.items():
        delta = default * PERTURBATION_PCT
        low_value = default - delta
        high_value = default + delta
        low_metrics = _metrics(symbol, timeframe, candles, funding, {name: low_value})
        high_metrics = _metrics(symbol, timeframe, candles, funding, {name: high_value})
        fragile, reason = _is_fragile(base_metrics, low_metrics, high_metrics)
        results.append(
            PerturbationResult(
                parameter=name,
                base_value=default,
                low_value=low_value,
                high_value=high_value,
                base=base_metrics,
                low=low_metrics,
                high=high_metrics,
                fragile=fragile,
                fragility_reason=reason,
            )
        )
    return results


@dataclass(slots=True)
class StructuralComparison:
    filter_name: str
    off: RunMetrics
    on: RunMetrics


def run_structural_filter_comparison(
    symbol: Symbol, timeframe: str, candles: pd.DataFrame, funding: pd.DataFrame
) -> list[StructuralComparison]:
    comparisons = []
    for name in _STRUCTURAL_FILTERS:
        off_metrics = _metrics(symbol, timeframe, candles, funding, {name: False})
        on_metrics = _metrics(symbol, timeframe, candles, funding, {name: True})
        comparisons.append(StructuralComparison(name, off_metrics, on_metrics))
    return comparisons


def format_robustness(results: list[PerturbationResult]) -> str:
    lines = [
        "| Parameter | -10% | Base | +10% | Sharpe (-10% / base / +10%) | Fragile? |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.parameter} | {r.low_value:.4g} | {r.base_value:.4g} | {r.high_value:.4g} | "
            f"{r.low.sharpe_ratio:.2f} / {r.base.sharpe_ratio:.2f} / {r.high.sharpe_ratio:.2f} | "
            f"{'**YES** — ' + r.fragility_reason if r.fragile else 'no'} |"
        )
    return "\n".join(lines)


def format_structural(comparisons: list[StructuralComparison]) -> str:
    lines = [
        "| Filter | Off (baseline) trades/Sharpe/PF | On (required) trades/Sharpe/PF |",
        "|---|---|---|",
    ]
    for c in comparisons:
        off_pf = "inf" if c.off.profit_factor == float("inf") else f"{c.off.profit_factor:.2f}"
        on_pf = "inf" if c.on.profit_factor == float("inf") else f"{c.on.profit_factor:.2f}"
        lines.append(
            f"| {c.filter_name} | {c.off.trade_count} / {c.off.sharpe_ratio:.2f} / {off_pf} | "
            f"{c.on.trade_count} / {c.on.sharpe_ratio:.2f} / {on_pf} |"
        )
    return "\n".join(lines)
