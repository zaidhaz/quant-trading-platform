"""Phase 4 — segment trade performance by market condition.

Two segmentation views, deliberately kept separate:

- `by_true_market_condition()`: bull/bear/range x high/low-vol, using the
  *ground-truth* regime label that generated the synthetic bar the trade
  entered on (`research/synthetic_history.RegimeSegment.kind`). Only possible
  because this is synthetic data with a known generator — flagged as such
  everywhere it's used, since real data would have no such ground truth.
- `by_strategy_observed_regime()`: trend/volatility/bias, funding sign, and
  ADX bucket, using only what the strategy itself saw at entry time
  (`JournalEntry.market_regime` / `features_snapshot`) — the version that
  works identically on real data, no privileged knowledge of a generator.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from research.synthetic_history import build_regime_schedule
from research.trade_records import TradeRecord

ADX_TRENDING_THRESHOLD = 25.0  # matches market_regime's own default trend_threshold


@dataclass(slots=True)
class SegmentStats:
    label: str
    count: int
    win_rate: float
    profit_factor: float
    avg_r_multiple: float
    total_pnl: float
    avg_pnl: float


def _stats(label: str, records: list[TradeRecord]) -> SegmentStats:
    if not records:
        return SegmentStats(label, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
    wins = [r for r in records if r.pnl > 0]
    losses = [r for r in records if r.pnl < 0]
    gross_profit = sum(r.pnl for r in wins)
    gross_loss = -sum(r.pnl for r in losses)
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    r_values = [r.r_multiple for r in records if r.r_multiple is not None]
    return SegmentStats(
        label=label,
        count=len(records),
        win_rate=len(wins) / len(records),
        profit_factor=profit_factor,
        avg_r_multiple=float(np.mean(r_values)) if r_values else 0.0,
        total_pnl=float(sum(r.pnl for r in records)),
        avg_pnl=float(np.mean([r.pnl for r in records])),
    )


def by_true_market_condition(symbol: str, records: list[TradeRecord]) -> dict[str, SegmentStats]:
    if not records:
        return {}
    start = min(r.entry_ts for r in records)
    end = max(r.exit_ts for r in records)
    schedule = build_regime_schedule(
        symbol,
        pd.Timestamp(start) - pd.Timedelta(days=200),
        pd.Timestamp(end) + pd.Timedelta(days=1),
    )

    def label_for(ts: pd.Timestamp) -> str:
        ts = pd.Timestamp(ts)
        for seg in schedule:
            if seg.start <= ts < seg.end:
                return f"{seg.kind} / {seg.volatility}-vol"
        return "unknown"

    buckets: dict[str, list[TradeRecord]] = {}
    for record in records:
        buckets.setdefault(label_for(record.entry_ts), []).append(record)
    return {label: _stats(label, recs) for label, recs in buckets.items()}


def by_strategy_observed_regime(records: list[TradeRecord]) -> dict[str, SegmentStats]:
    buckets: dict[str, list[TradeRecord]] = {}

    def add(label: str, record: TradeRecord) -> None:
        buckets.setdefault(label, []).append(record)

    for record in records:
        trend = record.market_regime.get("trend", "unknown")
        volatility = record.market_regime.get("volatility", "unknown")
        bias = record.market_regime.get("bias", "unknown")
        add(f"trend: {trend}", record)
        add(f"volatility: {volatility}", record)
        add(f"bias: {bias}", record)

        if not np.isnan(record.funding_rate):
            add(
                "funding: positive" if record.funding_rate > 0 else "funding: negative/zero", record
            )

        if not np.isnan(record.adx):
            add(
                "ADX: high (>= 25)" if record.adx >= ADX_TRENDING_THRESHOLD else "ADX: low (< 25)",
                record,
            )

        if not np.isnan(record.session):
            session_label = {0.0: "Asia", 1.0: "London", 2.0: "New York", 3.0: "Late US/pre-Asia"}
            add(f"session: {session_label.get(record.session, 'unknown')}", record)

        add(f"side: {record.side}", record)

    return {label: _stats(label, recs) for label, recs in buckets.items()}


def format_segment_table(title: str, segments: dict[str, SegmentStats]) -> str:
    lines = [
        f"### {title}",
        "",
        "| Segment | N | Win Rate | Profit Factor | Avg R | Total PnL |",
        "|---|---|---|---|---|---|",
    ]
    for label, s in sorted(segments.items(), key=lambda kv: kv[0]):
        pf = "inf" if s.profit_factor == float("inf") else f"{s.profit_factor:.2f}"
        lines.append(
            f"| {label} | {s.count} | {s.win_rate:.1%} | {pf} | {s.avg_r_multiple:.3f} | "
            f"{s.total_pnl:,.2f} |"
        )
    return "\n".join(lines)
