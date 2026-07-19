"""Backtest performance metrics, computed from a `BacktestResult`'s equity curve
and closed-trade history."""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd

from core.constants import TIMEFRAME_TO_MINUTES, TRADING_DAYS_PER_YEAR
from portfolio.position_tracker import ClosedTrade

EquityCurve = list[tuple[datetime, float]]


def periods_per_year(timeframe: str) -> float:
    minutes_per_bar = TIMEFRAME_TO_MINUTES[timeframe]
    return (TRADING_DAYS_PER_YEAR * 24 * 60) / minutes_per_bar


def _equity_series(equity_curve: EquityCurve) -> pd.Series:
    if not equity_curve:
        return pd.Series(dtype=float)
    ts, values = zip(*equity_curve, strict=True)
    return pd.Series(values, index=pd.DatetimeIndex(ts))


def _returns(equity_curve: EquityCurve) -> pd.Series:
    return _equity_series(equity_curve).pct_change().dropna()


def net_return(equity_curve: EquityCurve) -> float:
    series = _equity_series(equity_curve)
    if series.empty or series.iloc[0] == 0:
        return 0.0
    return (series.iloc[-1] - series.iloc[0]) / series.iloc[0]


def cagr(equity_curve: EquityCurve) -> float:
    series = _equity_series(equity_curve)
    if len(series) < 2 or series.iloc[0] <= 0:
        return 0.0
    years = (series.index[-1] - series.index[0]).total_seconds() / (365 * 24 * 3600)
    if years <= 0:
        return 0.0
    growth = series.iloc[-1] / series.iloc[0]
    if growth <= 0:
        return -1.0
    return growth ** (1 / years) - 1


def sharpe_ratio(equity_curve: EquityCurve, timeframe: str, risk_free_rate: float = 0.0) -> float:
    returns = _returns(equity_curve)
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    ppy = periods_per_year(timeframe)
    excess = returns - risk_free_rate / ppy
    return float(excess.mean() / returns.std() * math.sqrt(ppy))


def sortino_ratio(equity_curve: EquityCurve, timeframe: str, risk_free_rate: float = 0.0) -> float:
    returns = _returns(equity_curve)
    if len(returns) < 2:
        return 0.0
    # Downside deviation over the *whole* return series (upside returns treated as
    # 0 contribution) rather than the sample std of just the negative subset —
    # avoids a NaN/undefined std when there are 0 or 1 negative periods.
    downside_deviation = math.sqrt((returns.clip(upper=0) ** 2).mean())
    if not downside_deviation:
        return 0.0
    ppy = periods_per_year(timeframe)
    excess = returns.mean() - risk_free_rate / ppy
    return float(excess / downside_deviation * math.sqrt(ppy))


def max_drawdown(equity_curve: EquityCurve) -> float:
    """Positive fraction, e.g. 0.15 for a 15% peak-to-trough drawdown."""
    series = _equity_series(equity_curve)
    if series.empty:
        return 0.0
    running_max = series.cummax()
    drawdown = (series - running_max) / running_max.replace(0, np.nan)
    return float(abs(drawdown.min())) if not drawdown.empty else 0.0


def profit_factor(trades: list[ClosedTrade]) -> float:
    gross_profit = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    gross_loss = -sum(t.net_pnl for t in trades if t.net_pnl < 0)
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def win_rate(trades: list[ClosedTrade]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.net_pnl > 0)
    return wins / len(trades)


def average_r_multiple(trades: list[ClosedTrade]) -> float:
    r_multiples = [t.r_multiple for t in trades if t.r_multiple is not None]
    if not r_multiples:
        return 0.0
    return float(np.mean(r_multiples))


def consecutive_wins_losses(trades: list[ClosedTrade]) -> dict[str, int]:
    max_wins = max_losses = current_wins = current_losses = 0
    for trade in trades:
        if trade.net_pnl > 0:
            current_wins += 1
            current_losses = 0
        elif trade.net_pnl < 0:
            current_losses += 1
            current_wins = 0
        else:
            current_wins = current_losses = 0
        max_wins = max(max_wins, current_wins)
        max_losses = max(max_losses, current_losses)
    return {"max_consecutive_wins": max_wins, "max_consecutive_losses": max_losses}


def monthly_returns(equity_curve: EquityCurve) -> pd.Series:
    series = _equity_series(equity_curve)
    if series.empty:
        return pd.Series(dtype=float)
    month_end = series.resample("ME").last().ffill()
    return month_end.pct_change().dropna()


def trade_distribution(trades: list[ClosedTrade]) -> dict[str, object]:
    if not trades:
        return {
            "count": 0,
            "by_exit_reason": {},
            "by_side": {},
            "avg_holding_hours": 0.0,
            "median_holding_hours": 0.0,
        }
    holding_hours = [t.holding_time.total_seconds() / 3600 for t in trades]
    by_exit_reason: dict[str, int] = {}
    by_side: dict[str, int] = {}
    for t in trades:
        by_exit_reason[t.exit_reason.value] = by_exit_reason.get(t.exit_reason.value, 0) + 1
        by_side[t.side.value] = by_side.get(t.side.value, 0) + 1
    return {
        "count": len(trades),
        "by_exit_reason": by_exit_reason,
        "by_side": by_side,
        "avg_holding_hours": float(np.mean(holding_hours)),
        "median_holding_hours": float(np.median(holding_hours)),
    }


def summarize(
    equity_curve: EquityCurve, trades: list[ClosedTrade], timeframe: str
) -> dict[str, object]:
    """Everything §4 of the review asked for, in one call — what
    `analytics/tearsheet.py` and the trade journal export build on top of."""
    return {
        "net_return": net_return(equity_curve),
        "cagr": cagr(equity_curve),
        "sharpe_ratio": sharpe_ratio(equity_curve, timeframe),
        "sortino_ratio": sortino_ratio(equity_curve, timeframe),
        "profit_factor": profit_factor(trades),
        "win_rate": win_rate(trades),
        "average_r_multiple": average_r_multiple(trades),
        "max_drawdown": max_drawdown(equity_curve),
        **consecutive_wins_losses(trades),
        "monthly_returns": monthly_returns(equity_curve).to_dict(),
        "trade_distribution": trade_distribution(trades),
    }
