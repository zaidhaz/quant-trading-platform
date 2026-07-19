"""Engine stress-test suite: missing data, duplicate timestamps, out-of-order
events, flash crashes, extreme gaps, zero-volume bars, and corrupted inputs.

The standard this holds the engine to is **fail safely**: either reject bad input
loudly and immediately (before any simulation work happens), or — for conditions
that are extreme but legitimate market behavior, not corrupted data — complete the
run without crashing and without producing NaN/inf/nonsensical output.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backtesting.data_feed import DataFeed
from backtesting.engine import BacktestConfig, BacktestEngine
from core.enums import ExitReason, SignalDirection
from core.exceptions import InsufficientDataError, ValidationError
from core.types import Position
from strategies.base_strategy import Strategy
from strategies.context import StrategyContext
from strategies.signal import Setup
from tests.fixtures.synthetic import make_ohlcv
from tests.unit.backtesting.conftest import SYMBOL, OneShotStrategy

CONFIG = BacktestConfig(initial_capital=10_000.0, taker_fee_rate=0.0004, slippage_bps=2.0)


def make_feed(df: pd.DataFrame, funding_df: pd.DataFrame | None = None) -> DataFeed:
    return DataFeed.from_candles(SYMBOL, "1h", df, funding_df)


def assert_finite(*values: float) -> None:
    for v in values:
        assert math.isfinite(v), f"expected a finite number, got {v}"


# ---------------------------------------------------------------------------
# Missing data (gaps) — legitimate, not corrupted: monotonic index, just sparse.
# ---------------------------------------------------------------------------


class TestMissingData:
    def test_sparse_but_valid_data_runs_without_crashing(self) -> None:
        df = make_ohlcv(300, drift=0.001, volatility=0.005, seed=11)
        # Drop a chunk of bars in the middle -- a real gap, but the remaining
        # index is still strictly increasing and unique, so it's not "corrupted."
        sparse = pd.concat([df.iloc[:100], df.iloc[150:]])

        result = BacktestEngine(
            OneShotStrategy(stop_loss=None, take_profit=None, entry_bar_index=5),
            make_feed(sparse),
            CONFIG,
        ).run()

        assert_finite(result.final_equity)
        assert len(result.equity_curve) == len(sparse)

    def test_empty_feed_produces_empty_result_not_a_crash(self) -> None:
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        result = BacktestEngine(OneShotStrategy(), make_feed(empty), CONFIG).run()

        assert result.closed_trades == []
        assert result.final_equity == CONFIG.initial_capital


# ---------------------------------------------------------------------------
# Duplicate timestamps / out-of-order events — rejected at the data-feed gate,
# before any simulation work happens.
# ---------------------------------------------------------------------------


class TestTimestampIntegrity:
    def test_duplicate_timestamps_rejected_before_engine_construction(self) -> None:
        df = make_ohlcv(50, seed=1)
        corrupted = df.copy()
        corrupted.index = pd.DatetimeIndex(
            [df.index[0], *df.index[1:-1], df.index[-2]]
        )  # last two timestamps collide

        with pytest.raises(ValidationError, match="duplicate timestamp"):
            make_feed(corrupted)

    def test_out_of_order_timestamps_rejected_before_engine_construction(self) -> None:
        df = make_ohlcv(50, seed=1)
        shuffled = df.copy()
        idx = list(df.index)
        idx[10], idx[11] = idx[11], idx[10]  # swap two adjacent timestamps
        shuffled.index = pd.DatetimeIndex(idx)

        with pytest.raises(ValidationError, match="not in increasing order"):
            make_feed(shuffled)


# ---------------------------------------------------------------------------
# Flash crash — extreme but legitimate single-bar move.
# ---------------------------------------------------------------------------


class TestFlashCrash:
    def test_flash_crash_triggers_stop_loss_cleanly(self) -> None:
        index = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
        df = pd.DataFrame(
            {
                "open": [100, 100, 100, 40, 41],
                "high": [101, 101, 101, 100, 42],  # bar 3's high still shows the pre-crash level
                "low": [99, 99, 99, 35, 40],  # bar 3 crashes to 35 intrabar
                "close": [100, 100, 100, 41, 41],
                "volume": [10.0] * 5,
            },
            index=index,
        )
        strategy = OneShotStrategy(entry_bar_index=1, stop_loss=90.0, take_profit=None)

        result = BacktestEngine(strategy, make_feed(df), CONFIG).run()

        assert len(result.closed_trades) == 1
        trade = result.closed_trades[0]
        assert trade.exit_reason == ExitReason.STOP_LOSS
        assert_finite(trade.net_pnl, trade.exit_price)
        assert_finite(result.final_equity)

    def test_flash_crash_with_full_recovery_same_bar_does_not_confuse_the_engine(self) -> None:
        # A bar that crashes and recovers within the same bar (low far below open
        # and close, high/close back near the open) -- the stop must still trigger
        # off the bar's low, since that's when the loss actually occurred.
        index = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
        df = pd.DataFrame(
            {
                "open": [100, 100, 100, 100, 100],
                "high": [101, 101, 101, 101, 101],
                "low": [99, 99, 99, 20, 99],  # bar 3: crash to 20, then recover
                "close": [100, 100, 100, 99, 100],
                "volume": [10.0] * 5,
            },
            index=index,
        )
        strategy = OneShotStrategy(entry_bar_index=1, stop_loss=50.0, take_profit=None)

        result = BacktestEngine(strategy, make_feed(df), CONFIG).run()

        assert len(result.closed_trades) == 1
        assert result.closed_trades[0].exit_reason == ExitReason.STOP_LOSS
        assert_finite(result.final_equity)

    def test_flash_crash_beyond_leverage_triggers_ruin_not_a_crash(self) -> None:
        index = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
        df = pd.DataFrame(
            {
                "open": [100, 100, 100, 1, 1],
                "high": [101, 101, 101, 1, 1],
                "low": [99, 99, 99, 1, 1],
                "close": [100, 100, 100, 1, 1],
                "volume": [10.0] * 5,
            },
            index=index,
        )
        # Oversized, unhedged position with no stop -- the crash should ruin the
        # account cleanly (see docs/VALIDATION_REPORT.md), not raise or hang.
        strategy = OneShotStrategy(entry_bar_index=1, stop_loss=None, take_profit=None, size=1000.0)

        result = BacktestEngine(strategy, make_feed(df), CONFIG).run()

        assert result.ruined is True
        assert_finite(result.final_equity)


# ---------------------------------------------------------------------------
# Extreme gaps — a huge time jump between two consecutive (still valid) bars.
# ---------------------------------------------------------------------------


class TestExtremeGaps:
    def test_multi_month_gap_between_bars_does_not_crash(self) -> None:
        early = make_ohlcv(50, seed=3, start="2024-01-01", freq="1h")
        late = make_ohlcv(
            50, seed=3, start_price=early["close"].iloc[-1], start="2024-06-01", freq="1h"
        )
        df = pd.concat([early, late])  # ~5 month gap between bar 49 and bar 50

        strategy = OneShotStrategy(entry_bar_index=5, stop_loss=None, take_profit=None)
        result = BacktestEngine(strategy, make_feed(df), CONFIG).run()

        assert_finite(result.final_equity)
        assert len(result.equity_curve) == len(df)

    def test_funding_still_applies_correctly_across_a_large_gap(self) -> None:
        early = make_ohlcv(30, seed=4, start="2024-01-01", freq="1h")
        late = make_ohlcv(
            30, seed=4, start_price=early["close"].iloc[-1], start="2024-03-01", freq="1h"
        )
        df = pd.concat([early, late])
        funding_ts = late.index[5]
        funding_df = pd.DataFrame({"funding_rate": [0.001]}, index=[funding_ts])

        strategy = OneShotStrategy(entry_bar_index=2, stop_loss=None, take_profit=None)
        result = BacktestEngine(strategy, make_feed(df, funding_df), CONFIG).run()

        assert_finite(result.final_equity)
        # No exception, no NaN funding silently corrupting a trade's accounting.
        for trade in result.closed_trades:
            assert_finite(trade.funding, trade.net_pnl)


# ---------------------------------------------------------------------------
# Zero-volume bars.
# ---------------------------------------------------------------------------


class _VwapStrategy(Strategy):
    """Minimal strategy that exercises the VWAP indicator specifically, since
    that's the one most exposed to a zero-volume divide-by-zero. VWAP over an
    all-zero-volume window is a real 0/0 -> NaN (not an exception, not inf) —
    the safety net is that `FeatureEngine.get()` already treats any NaN value as
    `InsufficientDataError` (see `features/feature_engine.py`), so this strategy
    never actually *sees* a NaN to act on. This test is what confirms that
    guard actually holds end to end through a full backtest, not just in
    isolation."""

    def detect_setup(self, context: StrategyContext) -> Setup | None:
        try:
            vwap = context.features.get("vwap", period=5)
        except InsufficientDataError:
            return None
        # If this ever fires, the NaN guard above has a hole in it.
        if not math.isfinite(vwap):
            raise AssertionError(f"vwap leaked a non-finite value into the strategy: {vwap}")
        if context.index == 20:
            return Setup(
                direction=SignalDirection.LONG, reference_price=context.price, reasoning="test"
            )
        return None

    def check_entry(self, context: StrategyContext, setup: Setup) -> bool:
        return True

    def check_exit(self, context: StrategyContext, position: Position) -> bool:
        return False

    def stop_loss(self, context: StrategyContext, setup: Setup) -> float | None:
        return None

    def take_profit(self, context: StrategyContext, setup: Setup) -> float | None:
        return None

    def position_size(self, context: StrategyContext, setup: Setup) -> float:
        return 1.0


class TestZeroVolumeBars:
    def test_vwap_over_all_zero_volume_window_is_nan_not_an_exception(self) -> None:
        # Ground truth of the underlying math, isolated from the engine: 0/0 in
        # the VWAP formula produces NaN, cleanly, rather than raising or
        # producing inf.
        from features.indicators.volume import vwap

        df = make_ohlcv(20, seed=6)
        df = df.copy()
        df["volume"] = 0.0

        result = vwap(df, period=5)

        assert result.isna().all()
        assert not result.isin([float("inf"), float("-inf")]).any()

    def test_nan_vwap_never_reaches_the_strategy_as_a_tradeable_value(self) -> None:
        df = make_ohlcv(50, seed=6)
        df = df.copy()
        df.loc[df.index[10:30], "volume"] = 0.0  # a long zero-volume stretch

        result = BacktestEngine(_VwapStrategy(), make_feed(df), CONFIG).run()

        assert_finite(result.final_equity)

    def test_all_zero_volume_series_runs_without_crashing(self) -> None:
        df = make_ohlcv(50, seed=6)
        df = df.copy()
        df["volume"] = 0.0

        result = BacktestEngine(
            OneShotStrategy(entry_bar_index=5, stop_loss=None, take_profit=None),
            make_feed(df),
            CONFIG,
        ).run()

        assert_finite(result.final_equity)

    def test_volume_participation_slippage_handles_zero_volume_bar(self) -> None:
        from backtesting.slippage_models import VolumeParticipationSlippage

        config = BacktestConfig(
            initial_capital=10_000.0,
            taker_fee_rate=0.0004,
            slippage_model=VolumeParticipationSlippage(base_bps=2.0, impact_coefficient=0.1),
        )
        df = make_ohlcv(50, seed=6)
        df = df.copy()
        df["volume"] = 0.0

        result = BacktestEngine(
            OneShotStrategy(entry_bar_index=5, stop_loss=None, take_profit=None),
            make_feed(df),
            config,
        ).run()

        assert_finite(result.final_equity)


# ---------------------------------------------------------------------------
# Corrupted inputs — must be rejected before the engine ever starts simulating.
# ---------------------------------------------------------------------------


class TestCorruptedInputsRejectedUpfront:
    def _base_df(self) -> pd.DataFrame:
        return make_ohlcv(20, seed=8)

    def test_nan_close_rejected(self) -> None:
        df = self._base_df().copy()
        df.iloc[5, df.columns.get_loc("close")] = float("nan")
        with pytest.raises(ValidationError):
            make_feed(df)

    def test_negative_price_rejected(self) -> None:
        df = self._base_df().copy()
        df.iloc[5, df.columns.get_loc("low")] = -1.0
        with pytest.raises(ValidationError):
            make_feed(df)

    def test_high_below_low_rejected(self) -> None:
        df = self._base_df().copy()
        df.iloc[5, df.columns.get_loc("high")] = df.iloc[5]["low"] - 10.0
        with pytest.raises(ValidationError):
            make_feed(df)

    def test_negative_volume_rejected(self) -> None:
        df = self._base_df().copy()
        df.iloc[5, df.columns.get_loc("volume")] = -100.0
        with pytest.raises(ValidationError):
            make_feed(df)

    def test_close_far_outside_bar_range_rejected(self) -> None:
        df = self._base_df().copy()
        df.iloc[5, df.columns.get_loc("close")] = df["high"].max() * 10
        with pytest.raises(ValidationError):
            make_feed(df)

    def test_infinite_price_rejected(self) -> None:
        df = self._base_df().copy()
        df.iloc[5, df.columns.get_loc("close")] = float("inf")
        # inf is not NaN and not <= 0, so it slips past those checks, but it is
        # (almost always) outside the bar's own [low, high] -- confirm it's still
        # caught, one way or another, rather than propagating into the engine.
        with pytest.raises(ValidationError):
            make_feed(df)
