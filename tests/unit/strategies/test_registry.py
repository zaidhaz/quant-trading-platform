import pytest

import strategies.examples.ma_crossover  # noqa: F401  (registers "ma_crossover")
import strategies.examples.mean_reversion  # noqa: F401  (registers "mean_reversion")
from strategies.examples.ma_crossover import MACrossoverStrategy
from strategies.registry import create_strategy, get_strategy_class, registered_strategies


def test_both_example_strategies_are_registered() -> None:
    names = registered_strategies()
    assert "ma_crossover" in names
    assert "mean_reversion" in names


def test_create_strategy_returns_configured_instance() -> None:
    strategy = create_strategy("ma_crossover", fast_period=5, slow_period=15)
    assert isinstance(strategy, MACrossoverStrategy)
    assert strategy.fast_period == 5
    assert strategy.slow_period == 15


def test_unknown_strategy_raises_value_error() -> None:
    with pytest.raises(ValueError):
        get_strategy_class("does_not_exist")


def test_strategies_are_interchangeable_through_same_interface() -> None:
    for name in registered_strategies():
        strategy = create_strategy(name)
        for hook in (
            "detect_setup",
            "check_entry",
            "check_exit",
            "stop_loss",
            "take_profit",
            "position_size",
        ):
            assert callable(getattr(strategy, hook))
