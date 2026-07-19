import pandas as pd

from strategies.liquidity_exhaustion_reversal import microstructure


def _df(rows: list[dict]) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=len(rows), freq="1h", tz="UTC")
    return pd.DataFrame(rows, index=index)


def test_clv_close_at_high_is_one_and_close_at_low_is_negative_one() -> None:
    df = _df(
        [
            {"open": 100, "high": 110, "low": 100, "close": 110, "volume": 10},
            {"open": 100, "high": 110, "low": 100, "close": 100, "volume": 10},
            {"open": 105, "high": 105, "low": 105, "close": 105, "volume": 10},  # zero range
        ]
    )

    result = microstructure.clv(df)

    assert result.iloc[0] == 1.0
    assert result.iloc[1] == -1.0
    assert pd.isna(result.iloc[2])


def test_displacement_requires_strong_close_not_just_large_range() -> None:
    df = _df(
        [
            {"open": 100, "high": 100.1, "low": 99.9, "close": 100, "volume": 10},
            # Big range but close is dead-center -- not a displacement bar.
            {"open": 100, "high": 110, "low": 90, "close": 100, "volume": 10},
            # Gap-free continuation, strong close near the high -- is displacement.
            {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 10},
            # Small range, no gap from prior close -- never a displacement bar.
            {"open": 109, "high": 109.5, "low": 108.9, "close": 109.4, "volume": 10},
        ]
    )
    atr = pd.Series(5.0, index=df.index)  # constant ATR, so 1.5x ATR = 7.5

    result = microstructure.displacement(
        df, atr, displacement_atr_mult=1.5, strong_close_threshold=0.5
    )

    assert result["up"].iloc[1] == 0.0
    assert result["up"].iloc[2] == 1.0
    assert result["up"].iloc[3] == 0.0


def test_absorption_score_ranks_a_volume_spike_over_a_normal_bar() -> None:
    rows = [{"open": 100, "high": 101, "low": 100, "close": 100.5, "volume": 10} for _ in range(20)]
    rows.append({"open": 100, "high": 100.2, "low": 100, "close": 100.1, "volume": 500})  # spike
    rows += [{"open": 100, "high": 101, "low": 100, "close": 100.5, "volume": 10} for _ in range(5)]
    df = _df(rows)

    score = microstructure.absorption_score(df, lookback=10)

    assert score.iloc[20] == 100.0  # the spike bar ranks at the top of its own window
    assert score.iloc[10] < score.iloc[20]  # an ordinary bar does not


def test_delta_proxy_sign_follows_close_location_and_scales_with_volume() -> None:
    df = _df(
        [
            {"open": 100, "high": 110, "low": 100, "close": 110, "volume": 100},  # close at high
            {"open": 100, "high": 110, "low": 100, "close": 100, "volume": 100},  # close at low
            {"open": 105, "high": 105, "low": 105, "close": 105, "volume": 100},  # zero range
        ]
    )

    delta = microstructure.delta_proxy(df)

    assert delta.iloc[0] > 0
    assert delta.iloc[1] < 0
    assert delta.iloc[2] == 0.0  # zero-range bars contribute no delta, not NaN/crash


def test_cvd_proxy_is_cumulative_sum_of_delta_proxy() -> None:
    df = _df(
        [
            {"open": 100, "high": 110, "low": 100, "close": 110, "volume": 10},
            {"open": 100, "high": 110, "low": 100, "close": 100, "volume": 10},
        ]
    )

    cvd = microstructure.cvd_proxy(df)
    delta = microstructure.delta_proxy(df)

    assert cvd.iloc[0] == delta.iloc[0]
    assert cvd.iloc[1] == delta.iloc[0] + delta.iloc[1]


def test_bullish_delta_divergence_flags_new_low_with_non_confirming_cvd() -> None:
    df = _df(
        [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 10}] * 10
        + [{"open": 100, "high": 101, "low": 90, "close": 100, "volume": 10}]  # new local low
    )
    # Hand-craft a CVD series that does NOT make a new low on the last bar.
    cvd = pd.Series([0.0] * 10 + [5.0], index=df.index)
    cvd.iloc[5] = -10.0  # the rolling-window minimum happened earlier, not on the last bar

    result = microstructure.bullish_delta_divergence(df, cvd, lookback_bars=10)

    assert bool(result.iloc[-1]) is True


def test_bullish_fvg_pure_geometry_no_gap_no_active() -> None:
    df = _df(
        [
            {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 10},
            {"open": 101, "high": 103, "low": 100, "close": 102, "volume": 10},
            {"open": 102, "high": 104, "low": 101, "close": 103, "volume": 10},  # overlaps bar 0
        ]
    )
    atr = pd.Series(1.0, index=df.index)

    result = microstructure.bullish_fvg(df, atr, min_size_atr_mult=0.1)

    assert result["active"].iloc[2] == 0.0  # bar0.high=102 >= bar2.low=101, no gap


def test_bullish_fvg_detects_true_gap_and_reports_size() -> None:
    df = _df(
        [
            {"open": 100, "high": 100.5, "low": 99, "close": 100, "volume": 10},
            {"open": 100, "high": 110, "low": 100, "close": 109, "volume": 10},  # displacement
            {
                "open": 109,
                "high": 112,
                "low": 102,
                "close": 111,
                "volume": 10,
            },  # low=102 > bar0.high=100.5
        ]
    )
    atr = pd.Series(1.0, index=df.index)

    result = microstructure.bullish_fvg(df, atr, min_size_atr_mult=0.1)

    assert result["active"].iloc[2] == 1.0
    assert result["size"].iloc[2] == 102 - 100.5


def test_order_block_for_direction_finds_last_opposite_body_before_displacement() -> None:
    df = _df(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 10},  # bullish
            {
                "open": 100.5,
                "high": 101,
                "low": 98,
                "close": 98.5,
                "volume": 10,
            },  # bearish (the OB)
            {
                "open": 98.5,
                "high": 99,
                "low": 98,
                "close": 98.7,
                "volume": 10,
            },  # bullish, irrelevant
            {"open": 98.7, "high": 115, "low": 98.6, "close": 114, "volume": 50},  # displacement up
        ]
    )
    displacement_up = pd.Series([False, False, False, True], index=df.index)

    result = microstructure.order_block_for_direction(
        df, displacement_up, "up", max_lookback_bars=5
    )

    assert result["low"].iloc[3] == 98.0
    assert result["high"].iloc[3] == 101.0
    assert pd.isna(result["low"].iloc[0])  # no displacement at bar 0 -> no order block


def test_order_block_for_direction_none_found_within_lookback() -> None:
    rows = [
        {"open": 100, "high": 101, "low": 99.5, "close": 100.5, "volume": 10}
    ] * 5  # all bullish
    rows.append({"open": 100.5, "high": 115, "low": 100.4, "close": 114, "volume": 50})
    df = _df(rows)
    displacement_up = pd.Series([False] * 5 + [True], index=df.index)

    result = microstructure.order_block_for_direction(
        df, displacement_up, "up", max_lookback_bars=5
    )

    assert pd.isna(result["low"].iloc[-1])
