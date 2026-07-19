from datetime import timedelta

import pandas as pd

from backtesting.engine import BacktestConfig
from core.types import Symbol
from optimization.objective_functions import net_return_objective
from optimization.param_search import GridSearch
from optimization.walk_forward import generate_windows, run_walk_forward
from strategies.examples.ma_crossover import MACrossoverStrategy
from tests.fixtures.synthetic import make_ohlcv

SYMBOL = Symbol(base="BTC", quote="USDT")


def test_generate_windows_produces_non_overlapping_rolling_windows() -> None:
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2024-01-21", tz="UTC")
    windows = generate_windows(
        start, end, train_period=timedelta(days=8), test_period=timedelta(days=4)
    )

    assert len(windows) >= 2
    first = windows[0]
    assert first.train_end == first.test_start
    assert first.train_end - first.train_start == timedelta(days=8)
    assert first.test_end - first.test_start == timedelta(days=4)
    # windows slide forward by the test period (default step)
    assert windows[1].train_start == first.train_start + timedelta(days=4)


def test_generate_windows_stops_before_exceeding_end() -> None:
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2024-01-13", tz="UTC")
    windows = generate_windows(
        start, end, train_period=timedelta(days=8), test_period=timedelta(days=4)
    )
    for w in windows:
        assert w.test_end <= end


def test_walk_forward_runs_grid_search_per_window_and_scores_out_of_sample() -> None:
    df = make_ohlcv(
        24 * 21, drift=0.0015, volatility=0.004, seed=17, start="2024-01-01"
    )  # ~21 days hourly
    windows = generate_windows(
        df.index[0], df.index[-1], train_period=timedelta(days=8), test_period=timedelta(days=4)
    )
    param_space = {"fast_period": [5, 10], "slow_period": [20, 30]}
    config = BacktestConfig(initial_capital=100_000.0)

    results = run_walk_forward(
        strategy_cls=MACrossoverStrategy,
        symbol=SYMBOL,
        timeframe="1h",
        candles=df,
        param_space=param_space,
        search=GridSearch(),
        objective=net_return_objective,
        windows=windows,
        config=config,
    )

    assert len(results) == len(windows)
    for r in results:
        assert set(r.best_params) == {"fast_period", "slow_period"}
        assert isinstance(r.in_sample_score, float)
        assert isinstance(r.out_of_sample_score, float)
        assert r.out_of_sample_result.final_equity > 0
