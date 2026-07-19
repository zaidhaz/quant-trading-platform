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
_DEFAULT_OPEN_INTEREST_FREQ = pd.Timedelta(minutes=5)


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


def _repair_and_check_series(
    symbol: str,
    dataset: str,
    timeframe_label: str,
    df: pd.DataFrame,
    expected_freq: pd.Timedelta,
    numeric_columns: tuple[str, ...],
) -> tuple[pd.DataFrame, DataQualityReport]:
    """Shared repair/check core for any non-OHLC time series (funding rate,
    open interest, ...): sort + dedupe (repaired), then gap detection and
    NaN/negative-value flagging (never repaired) on the given numeric
    columns. OHLC-shaped datasets (candles, and by extension mark price /
    premium index, which share the same kline row shape) use
    `repair_and_check_candles` instead, since they need the OHLC-specific
    invariant checks this generic path doesn't do."""
    rows_before = len(df)
    was_unsorted = not df.index.is_monotonic_increasing
    working = df.sort_index()
    duplicate_mask = working.index.duplicated(keep="first")
    duplicates_removed = int(duplicate_mask.sum())
    working = working[~duplicate_mask]

    report = DataQualityReport(
        symbol=symbol,
        timeframe=timeframe_label,
        dataset=dataset,
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

    report.gaps = _classify_gaps(working, expected_freq)
    nan_count = int(working[list(numeric_columns)].isna().any(axis=1).sum())
    report.nan_price_rows = nan_count
    negative_count = int((working[list(numeric_columns)] < 0).any(axis=1).sum())
    report.negative_volume_rows = negative_count
    if nan_count:
        report.issues.append(f"{nan_count} rows with a NaN value in {numeric_columns}")
    if negative_count:
        report.issues.append(f"{negative_count} rows with a negative value in {numeric_columns}")
    if any(g.classification == "extended" for g in report.gaps):
        report.issues.append(f"one or more extended gaps present in {dataset} history")

    return working, report


def repair_and_check_funding(
    symbol: str, df: pd.DataFrame
) -> tuple[pd.DataFrame, DataQualityReport]:
    working, report = _repair_and_check_series(
        symbol, "funding_rate", "8h", df, pd.Timedelta(hours=8), ("funding_rate",)
    )
    if working.empty:
        return working, report
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
    return working, report


def repair_and_check_open_interest(
    symbol: str, df: pd.DataFrame, expected_freq: pd.Timedelta = _DEFAULT_OPEN_INTEREST_FREQ
) -> tuple[pd.DataFrame, DataQualityReport]:
    """Gaps are expected and NOT flagged as an issue beyond Binance's own
    ~30-day retention cap (`OPEN_INTEREST_MAX_LOOKBACK_DAYS`) — any request for
    data older than that legitimately returns nothing, which is a documented
    limitation, not a data quality defect."""
    return _repair_and_check_series(
        symbol,
        "open_interest",
        str(expected_freq),
        df,
        expected_freq,
        ("sum_open_interest", "sum_open_interest_value"),
    )


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
