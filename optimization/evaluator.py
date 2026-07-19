from collections.abc import Callable

from backtesting.data_feed import DataFeed
from backtesting.engine import BacktestConfig, BacktestEngine
from optimization.objective_functions import ObjectiveFunction
from strategies.base_strategy import Strategy


def make_backtest_evaluator(
    strategy_cls: type[Strategy],
    feed: DataFeed,
    config: BacktestConfig,
    objective: ObjectiveFunction,
) -> Callable[[dict[str, object]], float]:
    """A `SearchStrategy` evaluates one param set by calling this: instantiate the
    strategy with those params, run a full backtest over `feed`, score the result."""

    def evaluate(params: dict[str, object]) -> float:
        strategy = strategy_cls(**params)
        result = BacktestEngine(strategy, feed, config).run()
        return objective(result)

    return evaluate
