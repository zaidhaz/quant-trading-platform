"""Scalar scores a search strategy tries to maximize, computed from a
`BacktestResult`."""

from collections.abc import Callable

from analytics import performance_metrics as pm
from backtesting.engine import BacktestResult

ObjectiveFunction = Callable[[BacktestResult], float]


def sharpe_objective(result: BacktestResult) -> float:
    return pm.sharpe_ratio(result.equity_curve, result.timeframe)


def sortino_objective(result: BacktestResult) -> float:
    return pm.sortino_ratio(result.equity_curve, result.timeframe)


def calmar_objective(result: BacktestResult) -> float:
    cagr = pm.cagr(result.equity_curve)
    mdd = pm.max_drawdown(result.equity_curve)
    if mdd == 0:
        return cagr if cagr > 0 else 0.0
    return cagr / mdd


def net_return_objective(result: BacktestResult) -> float:
    return pm.net_return(result.equity_curve)


OBJECTIVE_REGISTRY: dict[str, ObjectiveFunction] = {
    "sharpe": sharpe_objective,
    "sortino": sortino_objective,
    "calmar": calmar_objective,
    "net_return": net_return_objective,
}
