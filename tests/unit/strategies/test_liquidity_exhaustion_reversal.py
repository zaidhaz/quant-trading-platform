import numpy as np
import pandas as pd
import pytest

from core.enums import SignalDirection
from strategies.examples.liquidity_exhaustion_reversal import LiquidityExhaustionReversalStrategy
from strategies.liquidity_exhaustion_reversal.config import LiquidityExhaustionReversalConfig
from strategies.registry import create_strategy
from strategies.signal import Setup
from tests.unit.strategies.conftest import make_context


@pytest.fixture
def sweep_df() -> pd.DataFrame:
    """Random-walk OHLCV with a deliberately engineered support-pool sweep,
    reclaim, and displacement around bar 300 -- the same construction verified
    end-to-end in the strategy's manual smoke test."""
    rng = np.random.default_rng(42)
    n = 500
    close = 100 + np.cumsum(rng.normal(0, 0.3, n))
    open_ = close + rng.normal(0, 0.05, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.3, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.3, n))
    volume = np.abs(rng.normal(0, 1, n)) * 50 + 20

    for k in (150, 170, 190):
        low[k] = 95.0
        close[k] = 95.5
        open_[k] = 96.0
        high[k] = 96.2

    i = 300
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


def test_registered_under_its_name() -> None:
    strategy = create_strategy("liquidity_exhaustion_reversal")
    assert isinstance(strategy, LiquidityExhaustionReversalStrategy)


def test_config_rejects_invalid_take_profit_mode() -> None:
    with pytest.raises(ValueError, match="take_profit_mode"):
        LiquidityExhaustionReversalConfig(take_profit_mode="banana")


def test_config_rejects_invalid_value_anchor() -> None:
    with pytest.raises(ValueError, match="value_anchor"):
        LiquidityExhaustionReversalConfig(value_anchor="banana")


def test_detect_setup_returns_none_during_warmup(sweep_df, engine) -> None:
    strategy = LiquidityExhaustionReversalStrategy()
    context = make_context(sweep_df, engine, 5)

    assert strategy.detect_setup(context) is None


def test_detect_setup_finds_engineered_long_setup(sweep_df, engine) -> None:
    strategy = LiquidityExhaustionReversalStrategy()

    long_setup = None
    for i in range(200, 320):
        context = make_context(sweep_df, engine, i)
        setup = strategy.detect_setup(context)
        if setup is not None and setup.direction == SignalDirection.LONG:
            long_setup = setup
            break

    assert long_setup is not None
    assert long_setup.metadata["sweep_extreme"] < long_setup.metadata["pool_level"]
    assert long_setup.metadata["pool_touches"] >= 2


def test_stop_loss_is_sweep_extreme_minus_buffer_for_long(sweep_df, engine) -> None:
    strategy = LiquidityExhaustionReversalStrategy(stop_buffer_atr_mult=0.2)
    context = make_context(sweep_df, engine, 301)
    atr = context.features.get("atr", period=strategy.config.atr_period)
    setup = Setup(
        direction=SignalDirection.LONG,
        reference_price=context.price,
        reasoning="test",
        metadata={"sweep_extreme": 90.0},
    )

    stop = strategy.stop_loss(context, setup)

    assert stop == pytest.approx(90.0 - 0.2 * atr)


def test_stop_loss_is_sweep_extreme_plus_buffer_for_short(sweep_df, engine) -> None:
    strategy = LiquidityExhaustionReversalStrategy(stop_buffer_atr_mult=0.2)
    context = make_context(sweep_df, engine, 301)
    atr = context.features.get("atr", period=strategy.config.atr_period)
    setup = Setup(
        direction=SignalDirection.SHORT,
        reference_price=context.price,
        reasoning="test",
        metadata={"sweep_extreme": 120.0},
    )

    stop = strategy.stop_loss(context, setup)

    assert stop == pytest.approx(120.0 + 0.2 * atr)


def test_check_entry_vetoes_when_stop_is_on_the_wrong_side(sweep_df, engine) -> None:
    strategy = LiquidityExhaustionReversalStrategy()
    context = make_context(sweep_df, engine, 301)
    # A LONG setup whose "sweep extreme" is *above* current price would put the
    # stop-loss above entry -- nonsensical, must be vetoed.
    bad_setup = Setup(
        direction=SignalDirection.LONG,
        reference_price=context.price,
        reasoning="test",
        metadata={"sweep_extreme": context.price + 1000.0},
    )

    assert strategy.check_entry(context, bad_setup) is False


def test_position_size_zero_when_no_stop_distance(sweep_df, engine) -> None:
    strategy = LiquidityExhaustionReversalStrategy(stop_buffer_atr_mult=0.0)
    context = make_context(sweep_df, engine, 301)
    setup = Setup(
        direction=SignalDirection.LONG,
        reference_price=context.price,
        reasoning="test",
        metadata={"sweep_extreme": context.price},  # zero stop distance (no buffer)
    )

    assert strategy.position_size(context, setup) == 0.0


def test_confidence_is_bounded_0_to_100(sweep_df, engine) -> None:
    strategy = LiquidityExhaustionReversalStrategy()
    setups_and_contexts = []
    for i in range(200, 320):
        context = make_context(sweep_df, engine, i)
        setup = strategy.detect_setup(context)
        if setup is not None:
            setups_and_contexts.append((context, setup))

    assert setups_and_contexts  # the fixture is engineered to produce at least one
    for context, setup in setups_and_contexts:
        confidence = strategy.confidence(context, setup)
        assert 0.0 <= confidence <= 100.0


def test_reasoning_contains_every_explainability_field(sweep_df, engine) -> None:
    strategy = LiquidityExhaustionReversalStrategy()
    setup = None
    context = None
    for i in range(200, 320):
        context = make_context(sweep_df, engine, i)
        setup = strategy.detect_setup(context)
        if setup is not None:
            break

    assert setup is not None
    reasoning = strategy.reasoning(context, setup)
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
        assert required in reasoning


def test_baseline_setup_works_with_all_optional_filters_disabled(sweep_df, engine) -> None:
    strategy = LiquidityExhaustionReversalStrategy(
        require_absorption=False,
        require_delta_divergence=False,
        require_fvg=False,
        require_order_block=False,
        require_oi_flush=False,
    )
    found = False
    for i in range(200, 320):
        context = make_context(sweep_df, engine, i)
        if strategy.detect_setup(context) is not None:
            found = True
            break

    assert found


def test_requiring_an_optional_filter_can_only_shrink_the_setup_set(sweep_df, engine) -> None:
    """A/B test of Phase 4's independence requirement: turning a filter ON must
    never produce a setup the baseline (all filters off) wouldn't also find --
    optional filters can only narrow, never expand, the baseline hypothesis."""
    baseline = LiquidityExhaustionReversalStrategy()
    strict = LiquidityExhaustionReversalStrategy(require_fvg=True, require_order_block=True)

    baseline_hits = set()
    strict_hits = set()
    for i in range(200, 320):
        context = make_context(sweep_df, engine, i)
        if baseline.detect_setup(context) is not None:
            baseline_hits.add(i)
        if strict.detect_setup(context) is not None:
            strict_hits.add(i)

    assert strict_hits.issubset(baseline_hits)
