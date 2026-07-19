from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from backtesting.data_feed import DataFeed
from backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from core.constants import TIMEFRAME_TO_MINUTES
from core.types import Symbol
from optimization.evaluator import make_backtest_evaluator
from optimization.objective_functions import ObjectiveFunction
from optimization.param_search import ParamSet, ParamSpace, SearchStrategy
from strategies.base_strategy import Strategy

DEFAULT_WARMUP_BARS = 50


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


def _slice_with_warmup_buffer(
    candles: pd.DataFrame,
    target_start: pd.Timestamp,
    target_end: pd.Timestamp,
    warmup_bars: int,
    timeframe: str,
) -> tuple[pd.DataFrame, int]:
    """Extend the requested [target_start, target_end] slice backward by up to
    `warmup_bars` bars, so indicators have real history to warm up on instead of
    starting cold exactly at `target_start` — which would otherwise waste the first
    N bars of every window (most importantly, out-of-sample test windows) with no
    signals while indicators fill up, silently shrinking the evaluated sample.

    Returns (sliced_df, actual_warmup_bar_count) — the actual count is measured
    from the slice itself rather than assumed, so it's correct even if the data
    isn't perfectly bar-aligned to `target_start`.
    """
    minutes_per_bar = TIMEFRAME_TO_MINUTES[timeframe]
    buffer = pd.Timedelta(minutes=minutes_per_bar * warmup_bars)
    data_start = candles.index[0] if len(candles) else target_start
    buffer_start = max(data_start, target_start - buffer)
    sliced = candles.loc[buffer_start:target_end]
    actual_warmup = int((sliced.index < target_start).sum())
    return sliced, actual_warmup


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
    warmup_bars: int = DEFAULT_WARMUP_BARS,
) -> list[WalkForwardResult]:
    """For each window: search `param_space` on the train slice (in-sample), then
    run the best-found params once, untouched, on the test slice (out-of-sample).
    Only out-of-sample scores are a trustworthy performance estimate — see
    docs/ARCHITECTURE.md on why in-sample-only optimization overfits.

    Both slices are extended backward by `warmup_bars` (default 50) so indicators
    aren't cold-starting exactly at the window boundary; those buffer bars feed
    indicators only — no signals/trades are evaluated from them
    (`BacktestConfig.warmup_bars` enforces this per-run).
    """
    config = config or BacktestConfig()
    results: list[WalkForwardResult] = []

    for window in windows:
        train_df, train_warmup = _slice_with_warmup_buffer(
            candles,
            pd.Timestamp(window.train_start),
            pd.Timestamp(window.train_end),
            warmup_bars,
            timeframe,
        )
        train_config = dataclasses.replace(config, warmup_bars=train_warmup)
        train_feed = DataFeed.from_candles(symbol, timeframe, train_df, funding_df)
        evaluate = make_backtest_evaluator(strategy_cls, train_feed, train_config, objective)
        search_results = search.search(param_space, evaluate)
        best_params, in_sample_score = search_results[0]

        test_df, test_warmup = _slice_with_warmup_buffer(
            candles,
            pd.Timestamp(window.test_start),
            pd.Timestamp(window.test_end),
            warmup_bars,
            timeframe,
        )
        test_config = dataclasses.replace(config, warmup_bars=test_warmup)
        test_feed = DataFeed.from_candles(symbol, timeframe, test_df, funding_df)
        oos_result = BacktestEngine(strategy_cls(**best_params), test_feed, test_config).run()
        oos_score = objective(oos_result)

        results.append(
            WalkForwardResult(window, best_params, in_sample_score, oos_result, oos_score)
        )

    return results
