from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from backtesting.data_feed import DataFeed
from backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from core.types import Symbol
from optimization.evaluator import make_backtest_evaluator
from optimization.objective_functions import ObjectiveFunction
from optimization.param_search import ParamSet, ParamSpace, SearchStrategy
from strategies.base_strategy import Strategy


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


@dataclass(slots=True)
class WalkForwardResult:
    window: WalkForwardWindow
    best_params: ParamSet
    in_sample_score: float
    out_of_sample_result: BacktestResult
    out_of_sample_score: float


def generate_windows(
    start: datetime,
    end: datetime,
    train_period: timedelta,
    test_period: timedelta,
    step: timedelta | None = None,
) -> list[WalkForwardWindow]:
    """Rolling windows: [start, start+train) trains, [start+train, start+train+test)
    tests out-of-sample, then the whole window slides forward by `step` (default:
    the test period, i.e. non-overlapping test windows)."""
    step = step or test_period
    windows: list[WalkForwardWindow] = []
    train_start = start
    while True:
        train_end = train_start + train_period
        test_end = train_end + test_period
        if test_end > end:
            break
        windows.append(WalkForwardWindow(train_start, train_end, train_end, test_end))
        train_start = train_start + step
    return windows


def run_walk_forward(
    strategy_cls: type[Strategy],
    symbol: Symbol,
    timeframe: str,
    candles: pd.DataFrame,
    param_space: ParamSpace,
    search: SearchStrategy,
    objective: ObjectiveFunction,
    windows: list[WalkForwardWindow],
    config: BacktestConfig | None = None,
    funding_df: pd.DataFrame | None = None,
) -> list[WalkForwardResult]:
    """For each window: search `param_space` on the train slice (in-sample), then
    run the best-found params once, untouched, on the test slice (out-of-sample).
    Only out-of-sample scores are a trustworthy performance estimate — see
    docs/ARCHITECTURE.md on why in-sample-only optimization overfits."""
    config = config or BacktestConfig()
    results: list[WalkForwardResult] = []

    for window in windows:
        train_df = candles.loc[window.train_start : window.train_end]
        test_df = candles.loc[window.test_start : window.test_end]

        train_feed = DataFeed.from_candles(symbol, timeframe, train_df, funding_df)
        evaluate = make_backtest_evaluator(strategy_cls, train_feed, config, objective)
        search_results = search.search(param_space, evaluate)
        best_params, in_sample_score = search_results[0]

        test_feed = DataFeed.from_candles(symbol, timeframe, test_df, funding_df)
        oos_result = BacktestEngine(strategy_cls(**best_params), test_feed, config).run()
        oos_score = objective(oos_result)

        results.append(
            WalkForwardResult(window, best_params, in_sample_score, oos_result, oos_score)
        )

    return results
