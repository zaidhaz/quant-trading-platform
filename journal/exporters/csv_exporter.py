import csv
import json
from pathlib import Path

from journal.journal_recorder import JournalEntry

FIELDNAMES = [
    "symbol",
    "strategy_id",
    "side",
    "entry_ts",
    "entry_price",
    "entry_reason",
    "confidence_score",
    "features_snapshot",
    "market_regime",
    "position_size",
    "risk_pct",
    "implied_leverage",
    "fees",
    "funding",
    "exit_ts",
    "exit_price",
    "exit_reason",
    "pnl",
    "holding_time_seconds",
    "screenshot_url",
    "notes",
]


def entry_to_row(entry: JournalEntry) -> dict[str, object]:
    return {
        "symbol": entry.symbol,
        "strategy_id": entry.strategy_id,
        "side": entry.side.value,
        "entry_ts": entry.entry_ts.isoformat(),
        "entry_price": entry.entry_price,
        "entry_reason": entry.entry_reason,
        "confidence_score": entry.confidence_score,
        "features_snapshot": json.dumps(entry.features_snapshot),
        "market_regime": json.dumps(entry.market_regime),
        "position_size": entry.position_size,
        "risk_pct": entry.risk_pct,
        "implied_leverage": entry.implied_leverage,
        "fees": entry.fees,
        "funding": entry.funding,
        "exit_ts": entry.exit_ts.isoformat() if entry.exit_ts else "",
        "exit_price": entry.exit_price,
        "exit_reason": entry.exit_reason,
        "pnl": entry.pnl,
        "holding_time_seconds": entry.holding_time_seconds,
        "screenshot_url": entry.screenshot_url or "",
        "notes": entry.notes,
    }


def export_csv(entries: list[JournalEntry], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry_to_row(entry))
