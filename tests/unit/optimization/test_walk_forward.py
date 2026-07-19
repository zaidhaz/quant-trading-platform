from datetime import timedelta

import pandas as pd
import pytest

from backtesting.engine import BacktestConfig
from core.exceptions import InsufficientDataError
from core.types import Symbol
from features.feature_engine import FeatureEngine
from optimization.objective_functions import net_return_objective
from optimization.param_search import GridSearch
from optimization.walk_forward import _slice_with_warmup_buffer, generate_windows, run_walk_forward
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


class TestWarmupBuffer:
    def test_slice_extends_backward_by_requested_bars(self) -> None:
        df = make_ohlcv(200, start="2024-01-01")
        target_start = df.index[100]
        target_end = df.index[150]

        sliced, actual_warmup = _slice_with_warmup_buffer(df, target_start, target_end, 30, "1h")

        assert actual_warmup == 30
        assert sliced.index[0] == df.index[70]
        assert sliced.index[-1] == target_end

    def test_slice_clips_buffer_at_start_of_available_data(self) -> None:
        df = make_ohlcv(200, start="2024-01-01")
        target_start = df.index[10]  # not enough history for a full 30-bar buffer
        target_end = df.index[50]

        sliced, actual_warmup = _slice_with_warmup_buffer(df, target_start, target_end, 30, "1h")

        assert actual_warmup == 10  # clipped, not an error
        assert sliced.index[0] == df.index[0]

    def test_out_of_sample_window_has_valid_indicators_from_its_very_first_bar(self) -> None:
        # This is the regression this fix targets: without a warmup buffer, the
        # first ~30 bars of the OOS window would raise InsufficientDataError for a
        # 30-period indicator. With the buffer, bar 0 of the *evaluation* period
        # (i.e. right at test_start) already has valid values.
        df = make_ohlcv(300, drift=0.002, volatility=0.003, seed=9, start="2024-01-01")
        target_start = df.index[150]
        target_end = df.index[200]

        sliced, actual_warmup = _slice_with_warmup_buffer(df, target_start, target_end, 30, "1h")

        engine = FeatureEngine()
        symbol = SYMBOL
        # actual_warmup is exactly the bar index (within `sliced`) of target_start.
        value = engine.get(symbol, "1h", "ema", sliced, at_index=actual_warmup, period=30)
        assert isinstance(value, float)

        # Prove the *lack* of a buffer would have failed at that same point.
        cold = sliced.iloc[actual_warmup:].reset_index(drop=True)
        cold.index = sliced.index[actual_warmup:]
        with pytest.raises(InsufficientDataError):
            FeatureEngine().get(symbol, "1h", "ema", cold, at_index=0, period=30)

    def test_run_walk_forward_accepts_custom_warmup_bars(self) -> None:
        df = make_ohlcv(24 * 21, drift=0.0015, volatility=0.004, seed=17, start="2024-01-01")
        windows = generate_windows(
            df.index[0], df.index[-1], train_period=timedelta(days=8), test_period=timedelta(days=4)
        )

        results = run_walk_forward(
            strategy_cls=MACrossoverStrategy,
            symbol=SYMBOL,
            timeframe="1h",
            candles=df,
            param_space={"fast_period": [5], "slow_period": [20]},
            search=GridSearch(),
            objective=net_return_objective,
            windows=windows,
            warmup_bars=10,
        )

        assert len(results) == len(windows)
