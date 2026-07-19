"""A single, shared, flat trade representation joining `ClosedTrade`
(P&L/R-multiple accounting from `portfolio/`) with the `JournalEntry` that was
recorded for the same fill (regime/funding/ADX context from `journal/`), so
`regime_analysis.py`, `monte_carlo.py`, and `robustness.py` all consume one
consistent list instead of three different partial views of the same trades.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from research.backtest_runner import RunOutput


@dataclass(frozen=True, slots=True)
class TradeRecord:
    entry_ts: datetime
    exit_ts: datetime
    side: str
    pnl: float
    r_multiple: float | None
    market_regime: dict[str, str]
    funding_rate: float
    adx: float
    session: float  # 0=Asia, 1=London, 2=New York, 3=late-US/pre-Asia (UTC hour bucket)


def build_trade_records(run_output: RunOutput) -> list[TradeRecord]:
    closed_trades = run_output.result.closed_trades
    closed_entries = [e for e in run_output.entries if e.is_closed]
    if len(closed_trades) != len(closed_entries):
        raise ValueError(
            f"closed_trades ({len(closed_trades)}) and closed journal entries "
            f"({len(closed_entries)}) count mismatch — the 1:1 chronological "
            "correspondence this module relies on (single symbol, single "
            "position at a time, both driven by the same fill sequence) "
            "does not hold for this run; investigate before trusting the "
            "regime/Monte Carlo/robustness analysis built on top of it"
        )

    records = []
    for trade, entry in zip(closed_trades, closed_entries, strict=True):
        records.append(
            TradeRecord(
                entry_ts=trade.entry_ts,
                exit_ts=trade.exit_ts,
                side=trade.side.value,
                pnl=trade.net_pnl,
                r_multiple=trade.r_multiple,
                market_regime=dict(entry.market_regime),
                funding_rate=float(entry.features_snapshot.get("funding_rate", float("nan"))),
                adx=float(entry.features_snapshot.get("adx", float("nan"))),
                session=float(entry.features_snapshot.get("session", float("nan"))),
            )
        )
    return records
