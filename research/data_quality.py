"""Phase 2 — data quality verification and safe auto-repair.

Two categories, kept strictly separate per the "never fabricate" instruction:

- **Repairable**: structural defects that don't require inventing a value
  (out-of-order rows, exact duplicate timestamps). Fixed automatically.
- **Flag-only**: anything that would require inventing a value to "fix"
  (missing bars/gaps, invalid OHLC, funding series holes). Reported, never
  silently patched — a gap stays a gap in the output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from core.constants import TIMEFRAME_TO_MINUTES

_VOLUME_ANOMALY_MULTIPLE = 20.0
_MAINTENANCE_GAP_MAX_MULTIPLE = (
    3.0  # gaps up to this many expected intervals: "short/maintenance-like"
)


@dataclass(slots=True)
class GapInfo:
    start: str
    end: str
    missing_bars: int
    classification: str  # "short (maintenance-like)" | "extended"


@dataclass(slots=True)
class DataQualityReport:
    symbol: str
    timeframe: str
    dataset: str  # "candles" | "funding_rate"
    rows_before_repair: int
    rows_after_repair: int
    start: str | None
    end: str | None
    duplicates_removed: int
    was_unsorted: bool
    gaps: list[GapInfo] = field(default_factory=list)
    invalid_ohlc_rows: int = 0
    nan_price_rows: int = 0
    negative_volume_rows: int = 0
    zero_volume_rows: int = 0
    volume_outlier_rows: int = 0
    funding_out_of_range_rows: int = 0
    open_interest_status: str = (
        "N/A — no OpenInterestDataset exists in this codebase "
        "(see docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md §0)"
    )
    issues: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return (
            not self.gaps
            and self.invalid_ohlc_rows == 0
            and self.nan_price_rows == 0
            and self.negative_volume_rows == 0
            and not self.issues
        )


def _classify_gaps(df: pd.DataFrame, expected_freq: pd.Timedelta) -> list[GapInfo]:
    if df.empty:
        return []
    idx = df.index
    diffs = idx.to_series().diff().dropna()
    gap_locs = diffs[diffs > expected_freq * 1.5]
    gaps = []
    for loc, delta in gap_locs.items():
        pos = idx.get_loc(loc)
        prev_ts = idx[pos - 1]
        missing = int(round(delta / expected_freq)) - 1
        classification = (
            "short (maintenance-like)"
            if delta <= expected_freq * _MAINTENANCE_GAP_MAX_MULTIPLE
            else "extended"
        )
        gaps.append(GapInfo(str(prev_ts), str(loc), missing, classification))
    return gaps


def repair_and_check_candles(
    symbol: str, timeframe: str, df: pd.DataFrame
) -> tuple[pd.DataFrame, DataQualityReport]:
    rows_before = len(df)
    was_unsorted = not df.index.is_monotonic_increasing
    working = df.sort_index()

    duplicate_mask = working.index.duplicated(keep="first")
    duplicates_removed = int(duplicate_mask.sum())
    working = working[~duplicate_mask]

    report = DataQualityReport(
        symbol=symbol,
        timeframe=timeframe,
        dataset="candles",
        rows_before_repair=rows_before,
        rows_after_repair=len(working),
        start=str(working.index.min()) if not working.empty else None,
        end=str(working.index.max()) if not working.empty else None,
        duplicates_removed=duplicates_removed,
        was_unsorted=was_unsorted,
    )
    if working.empty:
        report.issues.append("dataset is empty after repair")
        return working, report

    expected_freq = pd.Timedelta(minutes=TIMEFRAME_TO_MINUTES[timeframe])
    report.gaps = _classify_gaps(working, expected_freq)

    nan_mask = working[["open", "high", "low", "close"]].isna().any(axis=1)
    report.nan_price_rows = int(nan_mask.sum())

    priced = working[~nan_mask]
    invalid_ohlc = (
        (priced["high"] < priced["low"])
        | (priced["open"] > priced["high"])
        | (priced["open"] < priced["low"])
        | (priced["close"] > priced["high"])
        | (priced["close"] < priced["low"])
        | (priced[["open", "high", "low", "close"]] <= 0).any(axis=1)
    )
    report.invalid_ohlc_rows = int(invalid_ohlc.sum())

    report.negative_volume_rows = int((working["volume"] < 0).sum())
    report.zero_volume_rows = int((working["volume"] == 0).sum())

    rolling_median = working["volume"].rolling(200, min_periods=20).median()
    outlier = working["volume"] > rolling_median * _VOLUME_ANOMALY_MULTIPLE
    report.volume_outlier_rows = int(outlier.fillna(False).sum())

    if report.nan_price_rows or report.invalid_ohlc_rows or report.negative_volume_rows:
        report.issues.append(
            "corrupted rows present (NaN price / invalid OHLC / negative volume) — "
            "flagged, NOT auto-repaired, since fixing them would mean inventing a price"
        )
    if any(g.classification == "extended" for g in report.gaps):
        report.issues.append("one or more extended (non-maintenance-scale) gaps present")

    return working, report


def repair_and_check_funding(
    symbol: str, df: pd.DataFrame
) -> tuple[pd.DataFrame, DataQualityReport]:
    rows_before = len(df)
    was_unsorted = not df.index.is_monotonic_increasing
    working = df.sort_index()
    duplicate_mask = working.index.duplicated(keep="first")
    duplicates_removed = int(duplicate_mask.sum())
    working = working[~duplicate_mask]

    report = DataQualityReport(
        symbol=symbol,
        timeframe="8h",
        dataset="funding_rate",
        rows_before_repair=rows_before,
        rows_after_repair=len(working),
        start=str(working.index.min()) if not working.empty else None,
        end=str(working.index.max()) if not working.empty else None,
        duplicates_removed=duplicates_removed,
        was_unsorted=was_unsorted,
    )
    if working.empty:
        report.issues.append("dataset is empty after repair")
        return working, report

    report.gaps = _classify_gaps(working, pd.Timedelta(hours=8))
    report.nan_price_rows = int(working["funding_rate"].isna().sum())
    # Binance caps funding at +/-0.75% per interval for most USDⓈ-M perpetuals — a
    # value outside that is a consistency red flag, not a hard invariant, so it's
    # reported, not repaired.
    out_of_range = working["funding_rate"].abs() > 0.0075
    report.funding_out_of_range_rows = int(out_of_range.fillna(False).sum())
    if report.funding_out_of_range_rows:
        report.issues.append(
            f"{report.funding_out_of_range_rows} funding rate rows outside the "
            "typical +/-0.75% band"
        )
    if any(g.classification == "extended" for g in report.gaps):
        report.issues.append("one or more extended gaps present in funding history")

    return working, report


def format_report(report: DataQualityReport) -> str:
    lines = [
        f"### {report.symbol} [{report.timeframe}] — {report.dataset}",
        f"- Rows: {report.rows_before_repair} -> {report.rows_after_repair} "
        f"(range {report.start} to {report.end})",
        f"- Repaired: sorted={report.was_unsorted}, duplicates removed={report.duplicates_removed}",
        f"- Gaps: {len(report.gaps)} "
        f"({sum(1 for g in report.gaps if g.classification == 'extended')} extended)",
        f"- Invalid OHLC rows: {report.invalid_ohlc_rows}, "
        f"NaN price rows: {report.nan_price_rows}, "
        f"negative volume rows: {report.negative_volume_rows}, "
        f"zero volume rows: {report.zero_volume_rows}",
        f"- Volume outlier rows (>{_VOLUME_ANOMALY_MULTIPLE:.0f}x rolling median): "
        f"{report.volume_outlier_rows}",
        f"- Open Interest: {report.open_interest_status}",
        f"- Overall: {'CLEAN' if report.clean else 'ISSUES FLAGGED'}",
    ]
    if report.funding_out_of_range_rows:
        lines.insert(-1, f"- Funding rate out-of-range rows: {report.funding_out_of_range_rows}")
    for issue in report.issues:
        lines.append(f"  - ISSUE: {issue}")
    return "\n".join(lines)
