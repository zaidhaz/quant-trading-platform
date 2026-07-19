"""Phase 6 — Monte Carlo analysis via bootstrap resampling of the *actual*
realized trade P&L distribution. No parametric return assumption (not
normal/lognormal), no new trades invented — every simulated path is a
with-replacement resample of the trade outcomes the backtest actually
produced, reordered, to see the *range* of drawdown/ruin/return outcomes a
single historical path can't show.

Known, stated simplification: resampling trade P&Ls independently ignores
serial correlation (e.g. losing streaks clustering in a specific regime) and
doesn't resample market conditions themselves — a standard limitation of
trade-level bootstrap Monte Carlo, not specific to this strategy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from research.trade_records import TradeRecord

DEFAULT_RUIN_DRAWDOWN = 0.50  # equity falling to 50% of its starting value


@dataclass(slots=True)
class MonteCarloResult:
    n_simulations: int
    n_trades_per_path: int
    years_spanned: float
    expected_max_drawdown: float
    worst_max_drawdown: float
    drawdown_95th_percentile: float
    probability_of_ruin: float
    ruin_drawdown_threshold: float
    expected_annual_return: float
    annual_return_5th_percentile: float
    annual_return_95th_percentile: float


def run_monte_carlo(
    records: list[TradeRecord],
    initial_capital: float = 100_000.0,
    n_simulations: int = 2000,
    ruin_drawdown: float = DEFAULT_RUIN_DRAWDOWN,
    seed: int = 42,
) -> MonteCarloResult | None:
    if not records:
        return None

    pnls = np.array([r.pnl for r in records])
    n_trades = len(pnls)
    years = max(
        (max(r.exit_ts for r in records) - min(r.entry_ts for r in records)).total_seconds()
        / (365.0 * 24 * 3600),
        1e-6,
    )

    rng = np.random.default_rng(seed)
    max_drawdowns = np.empty(n_simulations)
    final_equities = np.empty(n_simulations)
    ruin_count = 0
    ruin_floor = initial_capital * (1.0 - ruin_drawdown)

    for i in range(n_simulations):
        sample = rng.choice(pnls, size=n_trades, replace=True)
        equity_path = initial_capital + np.cumsum(sample)
        running_max = np.maximum.accumulate(np.concatenate(([initial_capital], equity_path)))[1:]
        drawdown = (running_max - equity_path) / running_max
        max_drawdowns[i] = drawdown.max() if len(drawdown) else 0.0
        final_equities[i] = equity_path[-1] if len(equity_path) else initial_capital
        if (equity_path <= ruin_floor).any():
            ruin_count += 1

    total_return = final_equities / initial_capital - 1.0
    # Annualize each path's total return over the same horizon the trade sample
    # spans -- guards the base against a total_return <= -1 (bankrupt path).
    growth = np.maximum(1.0 + total_return, 1e-9)
    annual_return = growth ** (1.0 / years) - 1.0

    return MonteCarloResult(
        n_simulations=n_simulations,
        n_trades_per_path=n_trades,
        years_spanned=years,
        expected_max_drawdown=float(max_drawdowns.mean()),
        worst_max_drawdown=float(max_drawdowns.max()),
        drawdown_95th_percentile=float(np.percentile(max_drawdowns, 95)),
        probability_of_ruin=ruin_count / n_simulations,
        ruin_drawdown_threshold=ruin_drawdown,
        expected_annual_return=float(annual_return.mean()),
        annual_return_5th_percentile=float(np.percentile(annual_return, 5)),
        annual_return_95th_percentile=float(np.percentile(annual_return, 95)),
    )


def format_monte_carlo(result: MonteCarloResult | None) -> str:
    if result is None:
        return "Monte Carlo: no trades to resample."
    return "\n".join(
        [
            f"- Simulations: {result.n_simulations:,} paths, "
            f"{result.n_trades_per_path} trades/path, spanning ~{result.years_spanned:.2f} years",
            f"- Expected max drawdown: {result.expected_max_drawdown:.2%}",
            f"- Worst simulated max drawdown: {result.worst_max_drawdown:.2%}",
            f"- 95th-percentile max drawdown: {result.drawdown_95th_percentile:.2%}",
            f"- Probability of ruin (equity falling to "
            f"{100 * (1 - result.ruin_drawdown_threshold):.0f}% of start): "
            f"{result.probability_of_ruin:.2%}",
            f"- Expected annualized return: {result.expected_annual_return:.2%} "
            f"(5th pct {result.annual_return_5th_percentile:.2%}, "
            f"95th pct {result.annual_return_95th_percentile:.2%})",
        ]
    )
