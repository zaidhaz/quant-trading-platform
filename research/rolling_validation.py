"""Phase 5 — rolling out-of-sample validation.

**No parameter optimization happens anywhere in this module** — every window
runs the exact same fixed production `LiquidityExhaustionReversalStrategy()`
config via `research/backtest_runner.py`. "Training period" here means only
a warmup lookback so indicators/liquidity pools have history by the start of
the test window — nothing is fit to it. This is walk-forward *validation*
(does the fixed hypothesis hold up window after window?), not walk-forward
*optimization* (which `optimization/walk_forward.py` implements and which
this exercise was explicitly told not to use).

No look-ahead / no future leakage: each window's test-period trades and
equity are computed from a slice of history that ends at `test_end` — the
engine never sees a bar beyond that when producing that window's numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from analytics import performance_metrics as pm
from core.types import Symbol
from research.backtest_runner import run
from research.trade_records import TradeRecord, build_trade_records


@dataclass(frozen=True, slots=True)
class Window:
    warmup_start: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass(slots=True)
class WindowReport:
    window: Window
    trade_count: int
    win_rate: float
    profit_factor: float
    avg_r_multiple: float
    net_return: float
    sharpe_ratio: float
    max_drawdown: float
    total_pnl: float


def build_windows(
    start: pd.Timestamp, end: pd.Timestamp, warmup_days: int, test_days: int, step_days: int
) -> list[Window]:
    windows = []
    test_start = start + pd.Timedelta(days=warmup_days)
    while test_start + pd.Timedelta(days=test_days) <= end:
        warmup_start = test_start - pd.Timedelta(days=warmup_days)
        test_end = test_start + pd.Timedelta(days=test_days)
        windows.append(Window(warmup_start, test_start, test_end))
        test_start = test_start + pd.Timedelta(days=step_days)
    return windows


def _renormalized_equity_curve(
    equity_curve: list[tuple], test_start: pd.Timestamp, initial_capital: float
) -> list[tuple]:
    """Equity curve restricted to the test period, rescaled so the first
    in-window point equals `initial_capital` — otherwise Sharpe/CAGR for the
    test window would be contaminated by whatever P&L accrued during the
    warmup portion of the run, which isn't part of what's being measured."""
    sliced = [(ts, eq) for ts, eq in equity_curve if pd.Timestamp(ts) >= test_start]
    if not sliced:
        return []
    base = sliced[0][1]
    if base <= 0:
        return sliced
    scale = initial_capital / base
    return [(ts, eq * scale) for ts, eq in sliced]


def _stats(records: list[TradeRecord]) -> tuple[float, float, float]:
    if not records:
        return 0.0, 0.0, 0.0
    wins = [r for r in records if r.pnl > 0]
    losses = [r for r in records if r.pnl < 0]
    gross_profit = sum(r.pnl for r in wins)
    gross_loss = -sum(r.pnl for r in losses)
    pf = (
        (gross_profit / gross_loss)
        if gross_loss > 0
        else (float("inf") if gross_profit > 0 else 0.0)
    )
    r_values = [r.r_multiple for r in records if r.r_multiple is not None]
    avg_r = sum(r_values) / len(r_values) if r_values else 0.0
    return len(wins) / len(records), pf, avg_r


def run_rolling_validation(
    symbol: Symbol,
    timeframe: str,
    candles: pd.DataFrame,
    funding: pd.DataFrame,
    warmup_days: int = 180,
    test_days: int = 90,
    step_days: int = 90,
    initial_capital: float = 100_000.0,
) -> list[WindowReport]:
    start, end = candles.index.min(), candles.index.max()
    windows = build_windows(start, end, warmup_days, test_days, step_days)
    reports = []
    for window in windows:
        sliced_candles = candles.loc[window.warmup_start : window.test_end]
        sliced_funding = (
            funding.loc[window.warmup_start : window.test_end] if not funding.empty else funding
        )
        out = run(
            symbol, timeframe, sliced_candles, sliced_funding, initial_capital=initial_capital
        )
        records = [
            r for r in build_trade_records(out) if pd.Timestamp(r.entry_ts) >= window.test_start
        ]
        oos_equity = _renormalized_equity_curve(
            out.result.equity_curve, window.test_start, initial_capital
        )
        win_rate, profit_factor, avg_r = _stats(records)
        reports.append(
            WindowReport(
                window=window,
                trade_count=len(records),
                win_rate=win_rate,
                profit_factor=profit_factor,
                avg_r_multiple=avg_r,
                net_return=pm.net_return(oos_equity) if oos_equity else 0.0,
                sharpe_ratio=pm.sharpe_ratio(oos_equity, timeframe) if oos_equity else 0.0,
                max_drawdown=pm.max_drawdown(oos_equity) if oos_equity else 0.0,
                total_pnl=float(sum(r.pnl for r in records)),
            )
        )
    return reports


def format_rolling_report(reports: list[WindowReport]) -> str:
    lines = [
        "| Test Window | Trades | Win Rate | Profit Factor | Avg R | Net Return | Sharpe "
        "| Max DD |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        pf = "inf" if r.profit_factor == float("inf") else f"{r.profit_factor:.2f}"
        lines.append(
            f"| {r.window.test_start.date()} to {r.window.test_end.date()} | {r.trade_count} | "
            f"{r.win_rate:.1%} | {pf} | {r.avg_r_multiple:.3f} | {r.net_return:.2%} | "
            f"{r.sharpe_ratio:.2f} | {r.max_drawdown:.2%} |"
        )
    return "\n".join(lines)
