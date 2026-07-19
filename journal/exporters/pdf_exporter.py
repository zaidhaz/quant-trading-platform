"""PDF export is on the roadmap but not implemented in this pass — it needs a PDF
rendering dependency (e.g. reportlab) that isn't in pyproject.toml yet and wasn't
otherwise justified for the research-engine milestone. CSV export
(`csv_exporter.py`) covers the same data in the meantime."""

from pathlib import Path

from journal.journal_recorder import JournalEntry


def export_pdf(entries: list[JournalEntry], path: Path) -> None:
    raise NotImplementedError(
        "PDF export not yet implemented — see journal/exporters/pdf_exporter.py docstring"
    )
