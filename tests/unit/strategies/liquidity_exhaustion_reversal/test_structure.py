import numpy as np
import pandas as pd

from strategies.liquidity_exhaustion_reversal import structure


def _flat_df(n: int, price: float = 100.0, volume: float = 10.0) -> pd.DataFrame:
    """A "flat" baseline with a negligible, strictly monotonic per-bar slope, so
    every bar has a distinct price and the interior has no local extrema at all --
    an *exactly* flat/repeated price would make every interior bar of a plateau tie
    for the rolling max/min and register as a spurious swing point; *random* jitter
    would instead scatter spurious swing points throughout by chance. A tiny
    monotonic ramp avoids both (this is a synthetic-fixture concern only: real OHLCV
    data essentially never repeats a price to full float precision across many
    consecutive bars)."""
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    values = price + np.arange(n) * 1e-9
    return pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": volume,
        },
        index=index,
    )


def _bump(df: pd.DataFrame, i: int, *, high: float | None = None, low: float | None = None) -> None:
    if high is not None:
        df.iloc[i, df.columns.get_loc("high")] = high
        df.iloc[i, df.columns.get_loc("close")] = high
        df.iloc[i, df.columns.get_loc("open")] = high
    if low is not None:
        df.iloc[i, df.columns.get_loc("low")] = low
        df.iloc[i, df.columns.get_loc("close")] = low
        df.iloc[i, df.columns.get_loc("open")] = low


def test_swing_highs_detects_isolated_local_maximum() -> None:
    df = _flat_df(21)
    _bump(df, 10, high=110.0)

    swings = structure.swing_highs(df, fractal_width=2)

    assert bool(swings.iloc[10]) is True
    assert not swings.iloc[[8, 9, 11, 12]].any()


def test_swing_highs_never_true_within_fractal_width_of_either_edge() -> None:
    df = _flat_df(21)
    _bump(df, 0, high=200.0)
    _bump(df, 20, high=200.0)

    swings = structure.swing_highs(df, fractal_width=2)

    assert not swings.iloc[:2].any()
    assert not swings.iloc[-2:].any()


def test_swing_lows_detects_isolated_local_minimum() -> None:
    df = _flat_df(21)
    _bump(df, 10, low=90.0)

    swings = structure.swing_lows(df, fractal_width=2)

    assert bool(swings.iloc[10]) is True
    assert not swings.iloc[[8, 9, 11, 12]].any()


def test_cluster_prices_merges_nearby_and_separates_far_prices() -> None:
    clusters = structure._cluster_prices([100.0, 100.1, 100.05, 110.0, 110.15], tolerance=0.2)

    levels = {round(level, 2): count for level, count in clusters}
    assert any(count == 3 for count in levels.values())
    assert any(count == 2 for count in levels.values())


def test_compute_liquidity_pools_requires_min_touches() -> None:
    df = _flat_df(120)
    # Three touches of a support level near 95, each a proper isolated swing low.
    for i in (20, 50, 80):
        _bump(df, i, low=95.0)
    atr = pd.Series(1.0, index=df.index)  # constant, generous ATR so tolerance is easy to satisfy

    pools_min2 = structure.compute_liquidity_pools(
        df, atr, fractal_width=2, tolerance_atr_mult=1.0, min_touches=2, pool_lookback_bars=100
    )
    pools_min5 = structure.compute_liquidity_pools(
        df, atr, fractal_width=2, tolerance_atr_mult=1.0, min_touches=5, pool_lookback_bars=100
    )

    # After the 2nd touch (bar 50 confirmed at 52), a 2-touch pool should exist.
    assert pools_min2["support_level"].iloc[90:].notna().all()
    assert (pools_min2["support_touches"].iloc[90:] >= 2).all()
    # A 5-touch requirement can never be satisfied by only 3 touches.
    assert pools_min5["support_level"].isna().all()


def test_compute_liquidity_pools_nearest_pool_is_on_the_correct_side() -> None:
    df = _flat_df(120, price=100.0)
    for i in (20, 50, 80):
        _bump(df, i, low=95.0)  # support pool below 100
    for i in (25, 55, 85):
        _bump(df, i, high=105.0)  # resistance pool above 100
    atr = pd.Series(1.0, index=df.index)

    pools = structure.compute_liquidity_pools(
        df, atr, fractal_width=2, tolerance_atr_mult=1.0, min_touches=2, pool_lookback_bars=100
    )

    row = pools.iloc[100]
    assert row["support_level"] < 100.0
    assert row["resistance_level"] > 100.0


def test_compute_sweeps_same_bar_sweep_and_reclaim() -> None:
    df = _flat_df(60, price=100.0)
    for i in (10, 20, 30):
        _bump(df, i, low=95.0)
    atr = pd.Series(1.0, index=df.index)
    pools = structure.compute_liquidity_pools(
        df, atr, fractal_width=2, tolerance_atr_mult=1.0, min_touches=2, pool_lookback_bars=100
    )

    # Bar 40: wick below the pool, close back above it, same bar.
    df.iloc[40, df.columns.get_loc("low")] = 94.5
    df.iloc[40, df.columns.get_loc("close")] = 100.5
    df.iloc[40, df.columns.get_loc("open")] = 96.0
    df.iloc[40, df.columns.get_loc("high")] = 100.6

    sweeps = structure.compute_sweeps(
        df, atr, pools, sweep_margin_atr_mult=0.1, reclaim_window_bars=3
    )

    assert sweeps["sweep_low_active"].iloc[40] == 1.0
    assert sweeps["sweep_low_extreme"].iloc[40] == 94.5
    assert sweeps["sweep_low_bars_ago"].iloc[40] == 0.0
    assert sweeps["sweep_low_pool_touches"].iloc[40] >= 2


def test_compute_sweeps_multi_bar_reclaim() -> None:
    df = _flat_df(60, price=100.0)
    for i in (10, 20, 30):
        _bump(df, i, low=95.0)
    atr = pd.Series(1.0, index=df.index)
    pools = structure.compute_liquidity_pools(
        df, atr, fractal_width=2, tolerance_atr_mult=1.0, min_touches=2, pool_lookback_bars=100
    )

    # Bar 40: breach and close below the pool (no reclaim yet).
    df.iloc[40, df.columns.get_loc("low")] = 94.5
    df.iloc[40, df.columns.get_loc("close")] = 96.0
    df.iloc[40, df.columns.get_loc("open")] = 96.0
    df.iloc[40, df.columns.get_loc("high")] = 96.2
    # Bar 41: still below.
    df.iloc[41, df.columns.get_loc("close")] = 97.0
    df.iloc[41, df.columns.get_loc("open")] = 96.0
    df.iloc[41, df.columns.get_loc("low")] = 95.5
    df.iloc[41, df.columns.get_loc("high")] = 97.1
    # Bar 42: reclaims above the pool.
    df.iloc[42, df.columns.get_loc("close")] = 100.5
    df.iloc[42, df.columns.get_loc("open")] = 97.0
    df.iloc[42, df.columns.get_loc("low")] = 96.9
    df.iloc[42, df.columns.get_loc("high")] = 100.6

    sweeps = structure.compute_sweeps(
        df, atr, pools, sweep_margin_atr_mult=0.1, reclaim_window_bars=3
    )

    assert sweeps["sweep_low_active"].iloc[42] == 1.0
    assert sweeps["sweep_low_extreme"].iloc[42] == 94.5
    assert sweeps["sweep_low_bars_ago"].iloc[42] == 2.0
    # Not re-fired the bar after (already reclaimed).
    df.iloc[43, df.columns.get_loc("close")] = 100.7
    df.iloc[43, df.columns.get_loc("open")] = 100.5
    df.iloc[43, df.columns.get_loc("low")] = 100.4
    df.iloc[43, df.columns.get_loc("high")] = 100.8
    sweeps2 = structure.compute_sweeps(
        df, atr, pools, sweep_margin_atr_mult=0.1, reclaim_window_bars=3
    )
    assert sweeps2["sweep_low_active"].iloc[43] == 0.0


def test_compute_sweeps_no_pool_means_no_sweep() -> None:
    df = _flat_df(60, price=100.0)
    df.iloc[40, df.columns.get_loc("low")] = 80.0  # a lone, unpooled breach
    atr = pd.Series(1.0, index=df.index)
    pools = structure.compute_liquidity_pools(
        df, atr, fractal_width=2, tolerance_atr_mult=1.0, min_touches=2, pool_lookback_bars=100
    )

    sweeps = structure.compute_sweeps(df, atr, pools)

    assert (sweeps["sweep_low_active"] == 0.0).all()
    assert (sweeps["sweep_high_active"] == 0.0).all()


def test_compute_structure_first_break_bootstraps_direction_without_bos_or_choch() -> None:
    df = _flat_df(20, price=100.0)
    _bump(df, 5, high=110.0)  # swing high, confirmed at bar 7
    _bump(df, 8, high=111.0)  # single-bar break above it -- direction bootstraps UP

    result = structure.compute_structure(df, fractal_width=2)

    first_break_idx = result.index[(result["bos_up"] + result["choch_up"]) > 0]
    assert len(first_break_idx) == 0  # the very first break never fires BoS/ChoCH
    assert (result["direction"].iloc[8:] == 1.0).all()


def test_compute_structure_choch_flips_direction() -> None:
    n = 40
    df = _flat_df(n, price=100.0)
    _bump(df, 5, high=110.0)  # swing high
    _bump(df, 8, high=111.0)  # break up -> direction bootstraps UP
    _bump(df, 25, low=90.0)  # swing low, confirmed at 27
    _bump(df, 30, low=85.0)  # break below the swing low -- against prevailing UP -> ChoCH down

    result = structure.compute_structure(df, fractal_width=2)

    assert result["direction"].iloc[15] == 1.0
    assert result["choch_down"].iloc[30] == 1.0
    assert result["choch_down"].sum() == 1.0
    assert result["direction"].iloc[35] == -1.0
