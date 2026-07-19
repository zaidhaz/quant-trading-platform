"""Unit tests for the research pipeline's analysis modules
(backtest_runner, trade_records, regime_analysis, rolling_validation,
monte_carlo, robustness) — all run on small synthetic slices so they're fast,
not on the full multi-year history the actual pipeline script uses."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.types import Symbol
from research import monte_carlo as mc
from research import regime_analysis as ra
from research import robustness as rb
from research import rolling_validation as rv
from research import synthetic_history as sh
from research.backtest_runner import run
from research.trade_records import TradeRecord, build_trade_records

SYMBOL = Symbol(base="BTC", quote="USDT")
START = datetime(2022, 1, 1, tzinfo=UTC)
END = datetime(2022, 7, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def run_output():
    candles = sh.generate_ohlcv("BTCUSDT", "1h", START, END)
    funding = sh.generate_funding("BTCUSDT", START, END)
    return run(SYMBOL, "1h", candles, funding)


@pytest.fixture(scope="module")
def records(run_output):
    return build_trade_records(run_output)


def test_run_produces_a_backtest_result_and_matching_journal(run_output) -> None:
    assert run_output.result is not None
    closed_entries = [e for e in run_output.entries if e.is_closed]
    assert len(closed_entries) == len(run_output.result.closed_trades)


def test_build_trade_records_joins_closed_trades_and_journal(records) -> None:
    assert records  # the 6-month window is engineered enough to produce trades
    for record in records:
        assert isinstance(record, TradeRecord)
        assert record.entry_ts <= record.exit_ts
        assert set(record.market_regime.keys()) == {"trend", "volatility", "bias"}


def test_build_trade_records_raises_on_count_mismatch() -> None:
    from dataclasses import dataclass

    from research.backtest_runner import RunOutput

    @dataclass
    class FakeResult:
        closed_trades: list

    fake = RunOutput(result=FakeResult(closed_trades=[1, 2]), entries=[])
    with pytest.raises(ValueError, match="mismatch"):
        build_trade_records(fake)


def test_regime_segmentation_covers_every_trade_at_least_once(records) -> None:
    strategy_segments = ra.by_strategy_observed_regime(records)
    # every trade contributes to a "trend: ..." bucket
    trend_total = sum(
        s.count for label, s in strategy_segments.items() if label.startswith("trend:")
    )
    assert trend_total == len(records)


def test_true_market_condition_segmentation_uses_known_generator_labels(records) -> None:
    segments = ra.by_true_market_condition("BTCUSDT", records)
    assert segments
    for label in segments:
        kind = label.split(" / ")[0]
        assert kind in ("bull", "bear", "range")


def test_rolling_validation_windows_never_look_beyond_their_own_test_end() -> None:
    import pandas as pd

    windows = rv.build_windows(
        pd.Timestamp(START), pd.Timestamp(END), warmup_days=30, test_days=30, step_days=30
    )
    assert windows
    for w in windows:
        assert w.warmup_start < w.test_start < w.test_end
        assert (w.test_start - w.warmup_start).days == 30


def test_rolling_validation_reports_are_bounded_and_consistent() -> None:
    candles = sh.generate_ohlcv("BTCUSDT", "1h", START, END)
    funding = sh.generate_funding("BTCUSDT", START, END)

    reports = rv.run_rolling_validation(
        SYMBOL, "1h", candles, funding, warmup_days=30, test_days=30, step_days=30
    )

    import pandas as pd

    assert reports
    for r in reports:
        assert 0.0 <= r.win_rate <= 1.0
        assert r.window.test_start >= candles.index.min()
        assert r.window.test_end <= candles.index.max() + pd.Timedelta(hours=1)


def test_monte_carlo_is_none_when_no_trades() -> None:
    assert mc.run_monte_carlo([]) is None


def test_monte_carlo_probability_of_ruin_is_a_fraction(records) -> None:
    result = mc.run_monte_carlo(records, n_simulations=200)

    assert result is not None
    assert 0.0 <= result.probability_of_ruin <= 1.0
    assert result.n_trades_per_path == len(records)


def test_monte_carlo_all_losing_trades_has_high_ruin_probability() -> None:
    losing_records = [
        TradeRecord(
            entry_ts=START,
            exit_ts=START,
            side="long",
            pnl=-5000.0,
            r_multiple=-1.0,
            market_regime={"trend": "ranging", "volatility": "low", "bias": "neutral"},
            funding_rate=0.0,
            adx=10.0,
            session=0.0,
        )
        for _ in range(20)
    ]

    result = mc.run_monte_carlo(losing_records, initial_capital=100_000.0, n_simulations=200)

    assert result is not None
    assert result.probability_of_ruin > 0.5


def test_robustness_sweep_perturbs_every_declared_parameter() -> None:
    candles = sh.generate_ohlcv("BTCUSDT", "1h", START, END)
    funding = sh.generate_funding("BTCUSDT", START, END)

    results = rb.run_robustness_sweep(SYMBOL, "1h", candles, funding)

    assert {r.parameter for r in results} == set(rb._PERTURBED_PARAMS)
    for r in results:
        assert r.low_value < r.base_value < r.high_value


def test_structural_filter_comparison_covers_fvg_and_order_block() -> None:
    candles = sh.generate_ohlcv("BTCUSDT", "1h", START, END)
    funding = sh.generate_funding("BTCUSDT", START, END)

    comparisons = rb.run_structural_filter_comparison(SYMBOL, "1h", candles, funding)

    assert {c.filter_name for c in comparisons} == {"require_fvg", "require_order_block"}
    for c in comparisons:
        # "on" (required) can only ever produce a subset of "off" (baseline) trades
        assert c.on.trade_count <= c.off.trade_count
