"""Integration / backtest-sanity tests for the Liquidity Exhaustion Reversal
System (Phase 8 of docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md): runs the
strategy through the real `BacktestEngine` end-to-end (not a hand-built
context), verifying it produces trades, that every signal carries the full
Phase 5/6 explainability + instrumentation payload, that it survives edge
cases without crashing, and a full example-trade walkthrough."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from backtesting.data_feed import DataFeed
from backtesting.engine import BacktestConfig, BacktestEngine
from core.types import Symbol
from journal.journal_recorder import JournalRecorder
from risk.limits import RiskLimits
from strategies.examples.liquidity_exhaustion_reversal import LiquidityExhaustionReversalStrategy

SYMBOL = Symbol(base="BTC", quote="USDT")

_REQUIRED_FEATURE_KEYS = {
    "sweep_extreme",
    "sweep_size",
    "sweep_duration_bars",
    "pool_level",
    "pool_touches",
    "retracement_pct",
    "atr",
    "ema_20",
    "ema_50",
    "ema_200",
    "rsi_14",
    "macd_line",
    "macd_hist",
    "adx",
    "volume",
    "vwap",
    "poc",
    "vah",
    "val",
    "distance_to_poc",
    "distance_to_vah",
    "distance_to_val",
    "funding_rate",
    "open_interest_change",
    "liquidations",
    "delta_proxy",
    "cvd_proxy",
    "absorption_score",
    "fvg_confirmed",
    "order_block_confirmed",
    "oi_flush_confirmed",
    "structure_direction",
    "trend_strength_adx",
    "volatility_regime_atr_percentile",
    "liquidity_regime_volume_percentile",
    "session",
    "day_of_week",
    "market_regime_trending",
    "market_regime_high_volatility",
}


def _engineered_df(
    seed: int = 42, n: int = 900, sweep_bars: tuple[int, ...] = (300, 500, 700)
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.3, n))
    open_ = close + rng.normal(0, 0.05, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.3, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.3, n))
    volume = np.abs(rng.normal(0, 1, n)) * 50 + 20

    for k in (150, 170, 190):
        if k >= n:
            continue
        low[k] = 95.0
        close[k] = 95.5
        open_[k] = 96.0
        high[k] = 96.2

    for i in sweep_bars:
        if i + 1 >= n:
            continue
        low[i] = 95.0 - 0.8
        close[i] = 95.0 + 0.5
        open_[i] = 95.0 - 0.3
        high[i] = max(high[i], close[i] + 0.1)
        open_[i + 1] = close[i]
        close[i + 1] = close[i] + 3.0
        high[i + 1] = close[i + 1] + 0.1
        low[i + 1] = open_[i + 1] - 0.1
        volume[i + 1] *= 5

    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index
    )
    df["high"] = df[["open", "high", "close", "low"]].max(axis=1)
    df["low"] = df[["open", "low", "close", "high"]].min(axis=1)
    return df


def _run(df: pd.DataFrame, **strategy_params: object):
    feed = DataFeed.from_candles(SYMBOL, "1h", df)
    strategy = LiquidityExhaustionReversalStrategy(**strategy_params)
    config = BacktestConfig(initial_capital=100_000.0, risk_limits=RiskLimits())
    engine = BacktestEngine(strategy, feed, config, strategy_id="liquidity_exhaustion_reversal")
    journal = JournalRecorder(engine.bus)
    result = engine.run()
    return result, journal


def test_backtest_runs_and_produces_trades_on_engineered_data() -> None:
    df = _engineered_df()

    result, _journal = _run(df)

    assert len(result.signals) >= 1
    assert len(result.closed_trades) >= 1
    assert len(result.equity_curve) == len(df)
    assert result.final_equity > 0
    assert not result.ruined


def test_signal_features_snapshot_has_full_phase6_instrumentation() -> None:
    df = _engineered_df()

    result, _journal = _run(df)

    assert result.signals
    snapshot = result.signals[0].features_snapshot
    missing = _REQUIRED_FEATURE_KEYS - snapshot.keys()
    assert not missing, f"missing instrumentation features: {sorted(missing)}"


def test_signal_stop_loss_and_take_profit_are_directionally_sane() -> None:
    df = _engineered_df()

    result, _journal = _run(df)

    for signal in result.signals:
        if signal.direction.value == "long":
            if signal.stop_loss is not None:
                assert signal.stop_loss < signal.entry_price
            if signal.take_profit is not None:
                assert signal.take_profit > signal.entry_price
        else:
            if signal.stop_loss is not None:
                assert signal.stop_loss > signal.entry_price
            if signal.take_profit is not None:
                assert signal.take_profit < signal.entry_price
        assert 0.0 <= signal.confidence <= 100.0


def test_journal_entry_captures_les_reasoning_and_metadata() -> None:
    df = _engineered_df()

    _result, journal = _run(df)

    assert journal.entries
    entry = journal.entries[0]
    assert "LIQUIDITY EXHAUSTION REVERSAL" in entry.entry_reason
    assert "sweep_extreme" in entry.features_snapshot
    assert set(entry.market_regime.keys()) == {"trend", "volatility", "bias"}
    assert entry.risk_pct is not None
    assert entry.implied_leverage is not None


def test_full_example_trade_walkthrough() -> None:
    """Phase 8's "example trade walkthrough": take one real, closed,
    engine-produced trade and verify every explainability/instrumentation
    field promised in docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md §5-6
    is actually present and internally consistent."""
    df = _engineered_df()

    _result, journal = _run(df)
    closed = [e for e in journal.entries if e.is_closed]
    assert closed
    entry = closed[0]

    # Phase 5: trade explainability.
    assert entry.symbol == str(SYMBOL)
    assert entry.side is not None
    for required in (
        "Market regime:",
        "Primary hypothesis:",
        "Entry reason:",
        "Evidence supporting trade:",
        "Evidence against trade:",
        "Triggered rules:",
        "Rejected/absent rules:",
        "Invalidation condition:",
        "Expected holding time:",
    ):
        assert required in entry.entry_reason
    assert 0.0 <= entry.confidence_score <= 100.0
    assert entry.risk_pct is not None and entry.risk_pct >= 0.0
    assert entry.position_size > 0.0

    # Phase 6: research instrumentation.
    missing = _REQUIRED_FEATURE_KEYS - entry.features_snapshot.keys()
    assert not missing
    assert math.isnan(entry.features_snapshot["liquidations"])  # honestly unavailable, not faked
    assert math.isnan(entry.features_snapshot["open_interest_change"])

    # The trade actually closed with a computed P&L and holding time.
    assert entry.exit_price is not None
    assert entry.pnl is not None
    assert entry.holding_time_seconds is not None and entry.holding_time_seconds >= 0.0


def test_no_liquidity_pool_ever_forms_yields_zero_trades_no_crash() -> None:
    df = _engineered_df()

    result, _journal = _run(df, tolerance_atr_mult=1e-9, min_touches=50)

    assert result.closed_trades == []
    assert not result.ruined


def test_requiring_fvg_and_order_block_is_a_strict_subset_of_baseline() -> None:
    df = _engineered_df()

    baseline_result, _ = _run(df)
    strict_result, _ = _run(df, require_fvg=True, require_order_block=True)

    baseline_ts = {s.ts for s in baseline_result.signals}
    strict_ts = {s.ts for s in strict_result.signals}
    assert strict_ts.issubset(baseline_ts)


def test_short_backtest_shorter_than_warmup_completes_without_error() -> None:
    df = _engineered_df(n=20)

    result, _journal = _run(df)

    assert result.closed_trades == []
    assert not result.ruined
    assert len(result.equity_curve) == len(df)


def test_sweep_with_no_reclaim_does_not_itself_signal() -> None:
    """A wick through a pool that does not close back above/below it within the
    same bar is, by definition, not a same-bar sweep-and-reclaim -- construct
    one and confirm that specific bar does not trigger a signal. (A later bar
    may legitimately signal once price genuinely reclaims -- this only asserts
    the deep-wick bar itself, which never recovers intrabar, stays quiet.)"""
    df = _engineered_df()
    unreclaimed_bar = 400
    df.iloc[unreclaimed_bar, df.columns.get_loc("low")] = 60.0  # deep wick
    df.iloc[unreclaimed_bar, df.columns.get_loc("close")] = 65.0  # closes well below any pool
    df.iloc[unreclaimed_bar, df.columns.get_loc("open")] = 68.0
    df.iloc[unreclaimed_bar, df.columns.get_loc("high")] = 69.0

    result, _journal = _run(df)

    signal_bars = {int((s.ts - df.index[0]) / pd.Timedelta(hours=1)) for s in result.signals}
    assert unreclaimed_bar not in signal_bars
