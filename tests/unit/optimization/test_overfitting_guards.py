from datetime import UTC, datetime

from backtesting.engine import BacktestResult
from optimization.overfitting_guards import (
    has_minimum_sample_size,
    out_of_sample_confirms_in_sample,
)

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def make_result(n_trades: int) -> BacktestResult:
    return BacktestResult(
        strategy_id="t",
        symbol_native="BTCUSDT",
        timeframe="1d",
        equity_curve=[(T0, 100.0)],
        closed_trades=[object()] * n_trades,  # type: ignore[list-item]
        signals=[],
        initial_capital=100.0,
        final_equity=100.0,
    )


def test_rejects_too_few_trades() -> None:
    assert not has_minimum_sample_size(make_result(5), min_trades=30)


def test_accepts_enough_trades() -> None:
    assert has_minimum_sample_size(make_result(30), min_trades=30)


def test_out_of_sample_confirms_when_close_to_in_sample() -> None:
    assert out_of_sample_confirms_in_sample(in_sample_score=1.0, out_of_sample_score=0.9)


def test_out_of_sample_flags_severe_degradation() -> None:
    assert not out_of_sample_confirms_in_sample(
        in_sample_score=1.0, out_of_sample_score=0.1, max_degradation_pct=0.5
    )


def test_out_of_sample_handles_non_positive_in_sample_score() -> None:
    assert out_of_sample_confirms_in_sample(in_sample_score=-1.0, out_of_sample_score=-0.5)
    assert not out_of_sample_confirms_in_sample(in_sample_score=-1.0, out_of_sample_score=-2.0)
