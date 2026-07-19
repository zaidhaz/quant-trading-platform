"""Cheap guards against promoting an overfit parameter set. Deliberately minimal for
the research engine's first pass — a statistically rigorous deflated Sharpe ratio
is a natural next addition once walk-forward is in real use, not before."""

from backtesting.engine import BacktestResult


def has_minimum_sample_size(result: BacktestResult, min_trades: int = 30) -> bool:
    """A parameter set that only traded a handful of times shouldn't be trusted,
    regardless of how good its score looks — 30 is the conventional rule-of-thumb
    minimum for a t-test-style significance claim."""
    return len(result.closed_trades) >= min_trades


def out_of_sample_confirms_in_sample(
    in_sample_score: float, out_of_sample_score: float, max_degradation_pct: float = 0.5
) -> bool:
    """Flags a parameter set whose out-of-sample score collapsed relative to its
    in-sample score — the classic overfitting signature in walk-forward validation."""
    if in_sample_score <= 0:
        return out_of_sample_score >= in_sample_score
    return out_of_sample_score >= in_sample_score * (1 - max_degradation_pct)
