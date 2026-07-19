"""Runs the Liquidity Exhaustion Reversal strategy exactly as configured in
production (`strategies/examples/liquidity_exhaustion_reversal.py`'s own
defaults — no parameter overrides unless a caller explicitly passes
`strategy_params`, which only `research/robustness.py`'s perturbation sweep
does, and never for the headline long-horizon run), through the real
`BacktestEngine`, with real fees/funding/slippage/next-bar-execution/risk
exactly as the engine already implements them. This module adds no new
execution logic — it is a thin, reusable entry point so every phase of the
research pipeline runs the strategy the same way.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtesting.data_feed import DataFeed
from backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from core.types import Symbol
from journal.journal_recorder import JournalEntry, JournalRecorder
from risk.limits import RiskLimits
from strategies.examples.liquidity_exhaustion_reversal import LiquidityExhaustionReversalStrategy

STRATEGY_ID = "liquidity_exhaustion_reversal"


@dataclass(slots=True)
class RunOutput:
    result: BacktestResult
    entries: list[JournalEntry]


def run(
    symbol: Symbol,
    timeframe: str,
    candles: pd.DataFrame,
    funding: pd.DataFrame | None = None,
    initial_capital: float = 100_000.0,
    strategy_params: dict[str, object] | None = None,
) -> RunOutput:
    feed = DataFeed.from_candles(symbol, timeframe, candles, funding)
    strategy = LiquidityExhaustionReversalStrategy(**(strategy_params or {}))
    config = BacktestConfig(initial_capital=initial_capital, risk_limits=RiskLimits())
    engine = BacktestEngine(strategy, feed, config, strategy_id=STRATEGY_ID)
    journal = JournalRecorder(engine.bus)
    result = engine.run()
    return RunOutput(result=result, entries=list(journal.entries))
