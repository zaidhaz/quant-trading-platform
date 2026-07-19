from datetime import UTC, datetime, timedelta

import pytest

from backtesting.engine import BacktestResult
from optimization import objective_functions as obj

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def make_result(equity_curve) -> BacktestResult:
    return BacktestResult(
        strategy_id="test",
        symbol_native="BTCUSDT",
        timeframe="1d",
        equity_curve=equity_curve,
        closed_trades=[],
        signals=[],
        initial_capital=equity_curve[0][1] if equity_curve else 0.0,
        final_equity=equity_curve[-1][1] if equity_curve else 0.0,
    )


def test_net_return_objective() -> None:
    result = make_result([(T0, 100.0), (T0 + timedelta(days=1), 120.0)])
    assert obj.net_return_objective(result) == pytest.approx(0.2)


def test_sharpe_objective_matches_performance_metrics() -> None:
    curve = [(T0, 100.0), (T0 + timedelta(days=1), 110.0), (T0 + timedelta(days=2), 121.0)]
    result = make_result(curve)
    assert obj.sharpe_objective(result) == 0.0  # zero variance in this constant-return series


def test_calmar_objective_zero_when_flat() -> None:
    result = make_result([(T0, 100.0), (T0 + timedelta(days=1), 100.0)])
    assert obj.calmar_objective(result) == 0.0


def test_objective_registry_contains_all_supported_objectives() -> None:
    assert set(obj.OBJECTIVE_REGISTRY) == {"sharpe", "sortino", "calmar", "net_return"}
