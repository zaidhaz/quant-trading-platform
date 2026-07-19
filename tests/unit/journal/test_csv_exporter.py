import csv
from datetime import UTC, datetime

from core.enums import PositionSide
from journal.exporters.csv_exporter import export_csv
from journal.journal_recorder import JournalEntry


def make_entry(**overrides) -> JournalEntry:
    defaults = dict(
        symbol="BTC/USDT",
        strategy_id="ma_crossover",
        side=PositionSide.LONG,
        entry_ts=datetime(2024, 1, 1, tzinfo=UTC),
        entry_price=100.0,
        entry_reason="EMA crossover",
        confidence_score=72.5,
        features_snapshot={"rsi_14": 55.0},
        market_regime={"trend": "trending", "volatility": "low", "bias": "bullish"},
        position_size=1.0,
        risk_pct=0.01,
    )
    defaults.update(overrides)
    return JournalEntry(**defaults)


def test_export_csv_writes_header_and_row(tmp_path) -> None:
    entry = make_entry()
    entry.exit_ts = datetime(2024, 1, 1, 5, tzinfo=UTC)
    entry.exit_price = 105.0
    entry.exit_reason = "take_profit"
    entry.pnl = 5.0

    out = tmp_path / "journal.csv"
    export_csv([entry], out)

    with out.open() as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "BTC/USDT"
    assert row["side"] == "long"
    assert float(row["pnl"]) == 5.0
    assert '"trend": "trending"' in row["market_regime"] or "trending" in row["market_regime"]


def test_export_csv_creates_parent_directories(tmp_path) -> None:
    out = tmp_path / "nested" / "dir" / "journal.csv"
    export_csv([make_entry()], out)
    assert out.exists()


def test_export_csv_handles_empty_entries(tmp_path) -> None:
    out = tmp_path / "empty.csv"
    export_csv([], out)
    with out.open() as f:
        rows = list(csv.DictReader(f))
    assert rows == []
