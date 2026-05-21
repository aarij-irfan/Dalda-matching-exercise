"""
Dalda outlet file data-quality analysis: duplicates, GPS issues, summary stats.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from matching_engine import (
    ColumnMapping,
    load_table,
    parse_gps_value,
    suggest_column_mapping,
)

# Rough Pakistan bounding box (suspicious if outside — not always wrong)
PAK_LAT_MIN, PAK_LAT_MAX = 23.0, 37.5
PAK_LON_MIN, PAK_LON_MAX = 60.5, 77.5

# Original data columns only (no underscore meta columns)
def _data_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if not str(c).startswith("_")]


@dataclass
class QualitySummary:
    total_rows: int = 0
    missing_gps: int = 0
    invalid_gps: int = 0
    zero_gps: int = 0
    out_of_range_gps: int = 0
    outside_pakistan_gps: int = 0
    duplicate_shop_id: int = 0
    duplicate_gps: int = 0
    exact_duplicate_row: int = 0
    exact_duplicate_groups: int = 0
    duplicate_shop_id_groups: int = 0
    duplicate_gps_groups: int = 0
    any_gps_issue: int = 0
    any_issue: int = 0
    clean_rows: int = 0

    def to_lines(self) -> list[str]:
        t = max(self.total_rows, 1)
        pct = lambda n: f"{n:,} ({100 * n / t:.2f}%)"

        return [
            f"Total outlets (rows): {self.total_rows:,}",
            "",
            "── GPS issues ──",
            f"  Missing / no GPS:        {pct(self.missing_gps)}",
            f"  Invalid (unparseable):   {pct(self.invalid_gps)}",
            f"  Zero coordinates (0,0):  {pct(self.zero_gps)}",
            f"  Out of range (lat/lon):  {pct(self.out_of_range_gps)}",
            f"  Outside Pakistan box:    {pct(self.outside_pakistan_gps)}",
            f"  Any GPS issue:           {pct(self.any_gps_issue)}",
            "",
            "── Duplicates (separate checks; name NOT flagged) ──",
            f"  Exact duplicate row:     {pct(self.exact_duplicate_row)}"
            + (
                f"  [{self.exact_duplicate_groups:,} identical-row groups]"
                if self.exact_duplicate_groups
                else ""
            ),
            "      (all data columns exactly the same — true duplicates)",
            f"  Duplicate shop ID only:  {pct(self.duplicate_shop_id)}"
            + (
                f"  [{self.duplicate_shop_id_groups:,} ID groups]"
                if self.duplicate_shop_id_groups
                else ""
            ),
            "      (same ID, other columns may differ — check export file)",
            f"  Duplicate GPS only:      {pct(self.duplicate_gps)}"
            + (
                f"  [{self.duplicate_gps_groups:,} GPS groups]"
                if self.duplicate_gps_groups
                else ""
            ),
            "",
            "── Summary ──",
            f"  Rows with ANY issue:     {pct(self.any_issue)}",
            f"  Clean rows (match-ready):{pct(self.clean_rows)}",
            "",
            "Clean = valid GPS, NOT exact duplicate row, NOT duplicate GPS location.",
            "Duplicate shop names alone are NOT flagged (many shops share names).",
            "Duplicate shop ID only is exported separately but still counts as clean.",
        ]


@dataclass
class QualityReport:
    summary: QualitySummary
    flagged_df: pd.DataFrame
    mapping: ColumnMapping
    slices: dict[str, pd.DataFrame]


def _resolve_row_gps(row: pd.Series, mapping: ColumnMapping) -> tuple[float | None, float | None, str]:
    lat_col, lon_col, gps_col = mapping.latitude, mapping.longitude, mapping.gps_combined
    lat, lon = None, None

    if lat_col and lon_col and lat_col in row.index:
        try:
            lat = float(row[lat_col])
            lon = float(row[lon_col])
        except (TypeError, ValueError):
            lat, lon = None, None

    if (lat is None or lon is None) and gps_col and gps_col in row.index:
        lat, lon = parse_gps_value(row.get(gps_col))

    if lat is None or lon is None or (pd.isna(lat) or pd.isna(lon)):
        return None, None, "missing"

    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None, None, "invalid"

    if lat == 0 and lon == 0:
        return lat, lon, "zero"
    if lat == 0 or lon == 0:
        return lat, lon, "zero"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return lat, lon, "out_of_range"
    if not (PAK_LAT_MIN <= lat <= PAK_LAT_MAX and PAK_LON_MIN <= lon <= PAK_LON_MAX):
        return lat, lon, "outside_pakistan"
    return lat, lon, "ok"


def _non_empty_key(val) -> str | None:
    if pd.isna(val):
        return None
    s = str(val).strip()
    return s if s else None


def _row_content_key(df: pd.DataFrame) -> pd.Series:
    """Fingerprint from ALL data columns (exact row duplicate detection)."""
    data = df[_data_columns(df)].fillna("").astype(str)
    return data.agg("\x1f".join, axis=1)


def analyze_dalda_file(
    path: str,
    mapping: ColumnMapping | None = None,
) -> QualityReport:
    df = load_table(path)
    mapping = mapping or suggest_column_mapping(list(df.columns))
    n = len(df)

    issues: list[list[str]] = [[] for _ in range(n)]
    latitudes = [np.nan] * n
    longitudes = [np.nan] * n
    gps_statuses = [""] * n

    for i in range(n):
        row = df.iloc[i]
        lat, lon, status = _resolve_row_gps(row, mapping)
        gps_statuses[i] = status
        latitudes[i] = lat if lat is not None else np.nan
        longitudes[i] = lon if lon is not None else np.nan
        if status == "missing":
            issues[i].append("missing_gps")
        elif status == "invalid":
            issues[i].append("invalid_gps")
        elif status == "zero":
            issues[i].append("zero_gps")
        elif status == "out_of_range":
            issues[i].append("out_of_range_gps")
        elif status == "outside_pakistan":
            issues[i].append("outside_pakistan_gps")

    out = df.copy()
    out["_row_number"] = np.arange(1, n + 1)
    out["_latitude_parsed"] = latitudes
    out["_longitude_parsed"] = longitudes
    out["_gps_status"] = gps_statuses

    # --- Exact duplicate: every data column identical ---
    content_key = _row_content_key(df)
    key_counts = content_key.value_counts()
    exact_dup_mask = content_key.map(lambda k: key_counts[k] > 1)
    exact_dup_groups = int((key_counts > 1).sum())
    group_labels = {}
    gid = 1
    for k, cnt in key_counts.items():
        if cnt > 1:
            group_labels[k] = f"EXACT_DUP_{gid:05d}"
            gid += 1
    out["_exact_dup_group"] = content_key.map(lambda k: group_labels.get(k, ""))

    for i in range(n):
        if exact_dup_mask.iloc[i]:
            issues[i].append("exact_duplicate_row")

    # --- Duplicate shop ID (informational; not same as exact row) ---
    id_groups = 0
    if mapping.shop_id and mapping.shop_id in df.columns:
        ids = df[mapping.shop_id].map(_non_empty_key)
        id_dup_mask = ids.notna() & ids.duplicated(keep=False)
        id_groups = int((ids[ids.notna()].value_counts() > 1).sum())
        for i in range(n):
            if id_dup_mask.iloc[i]:
                issues[i].append("duplicate_shop_id")

    # --- Duplicate GPS (informational) ---
    gps_groups = 0
    gps_keys = []
    for i in range(n):
        if gps_statuses[i] == "ok":
            gps_keys.append(f"{latitudes[i]:.5f},{longitudes[i]:.5f}")
        else:
            gps_keys.append(None)
    gps_series = pd.Series(gps_keys)
    gps_dup_mask = gps_series.notna() & gps_series.duplicated(keep=False)
    gps_groups = int((gps_series[gps_series.notna()].value_counts() > 1).sum())
    for i in range(n):
        if gps_dup_mask.iloc[i]:
            issues[i].append("duplicate_gps")

    out["_quality_issues"] = ["; ".join(x) if x else "" for x in issues]
    out["_has_issue"] = out["_quality_issues"] != ""

    gps_bad = [gps_statuses[i] != "ok" for i in range(n)]
    # Match-ready: good GPS and not a duplicate outlet (exact row or same GPS location)
    clean_mask = pd.Series(
        [
            gps_statuses[i] == "ok"
            and not exact_dup_mask.iloc[i]
            and not gps_dup_mask.iloc[i]
            for i in range(n)
        ],
        index=out.index,
    )

    summary = QualitySummary(
        total_rows=n,
        missing_gps=sum(1 for s in gps_statuses if s == "missing"),
        invalid_gps=sum(1 for s in gps_statuses if s == "invalid"),
        zero_gps=sum(1 for s in gps_statuses if s == "zero"),
        out_of_range_gps=sum(1 for s in gps_statuses if s == "out_of_range"),
        outside_pakistan_gps=sum(1 for s in gps_statuses if s == "outside_pakistan"),
        duplicate_shop_id=sum(1 for i in range(n) if "duplicate_shop_id" in issues[i]),
        duplicate_gps=sum(1 for i in range(n) if "duplicate_gps" in issues[i]),
        exact_duplicate_row=int(exact_dup_mask.sum()),
        exact_duplicate_groups=exact_dup_groups,
        duplicate_shop_id_groups=id_groups,
        duplicate_gps_groups=gps_groups,
        any_gps_issue=sum(gps_bad),
        any_issue=int(out["_has_issue"].sum()),
        clean_rows=int(clean_mask.sum()),
    )

    def _slice(mask) -> pd.DataFrame:
        return out.loc[mask].copy()

    id_mask = pd.Series(
        ["duplicate_shop_id" in issues[i] for i in range(n)], index=out.index
    )
    gps_issue_mask = pd.Series(gps_bad, index=out.index)

    slices = {
        "exact_duplicate_rows": _slice(exact_dup_mask),
        "duplicate_shop_id_rows": _slice(id_mask & ~exact_dup_mask),
        "duplicate_gps_rows": _slice(
            out["_quality_issues"].str.contains("duplicate_gps", na=False)
        ),
        "missing_gps_rows": _slice(pd.Series(gps_statuses) == "missing"),
        "invalid_gps_rows": _slice(pd.Series(gps_statuses) == "invalid"),
        "zero_gps_rows": _slice(pd.Series(gps_statuses) == "zero"),
        "out_of_range_gps_rows": _slice(pd.Series(gps_statuses) == "out_of_range"),
        "outside_pakistan_gps_rows": _slice(pd.Series(gps_statuses) == "outside_pakistan"),
        "any_gps_issue_rows": _slice(gps_issue_mask),
        "all_rows_with_any_issue": _slice(out["_has_issue"]),
        "clean_match_ready_rows": _slice(clean_mask),
    }

    return QualityReport(summary=summary, flagged_df=out, mapping=mapping, slices=slices)


def _summary_metrics_table(s: QualitySummary) -> pd.DataFrame:
    t = max(s.total_rows, 1)
    rows = [
        ("Total outlets (rows)", s.total_rows, "100.00%"),
        ("Missing / no GPS", s.missing_gps, f"{100 * s.missing_gps / t:.2f}%"),
        ("Invalid GPS (unparseable)", s.invalid_gps, f"{100 * s.invalid_gps / t:.2f}%"),
        ("Zero coordinates (0,0)", s.zero_gps, f"{100 * s.zero_gps / t:.2f}%"),
        ("Out of range lat/lon", s.out_of_range_gps, f"{100 * s.out_of_range_gps / t:.2f}%"),
        ("Outside Pakistan GPS box", s.outside_pakistan_gps, f"{100 * s.outside_pakistan_gps / t:.2f}%"),
        ("Any GPS issue", s.any_gps_issue, f"{100 * s.any_gps_issue / t:.2f}%"),
        ("Exact duplicate row (all columns)", s.exact_duplicate_row, f"{100 * s.exact_duplicate_row / t:.2f}%"),
        ("Exact duplicate groups", s.exact_duplicate_groups, ""),
        ("Duplicate shop ID only (rows)", s.duplicate_shop_id, f"{100 * s.duplicate_shop_id / t:.2f}%"),
        ("Duplicate shop ID groups", s.duplicate_shop_id_groups, ""),
        ("Duplicate GPS only (rows)", s.duplicate_gps, f"{100 * s.duplicate_gps / t:.2f}%"),
        ("Duplicate GPS groups", s.duplicate_gps_groups, ""),
        ("Rows with ANY issue", s.any_issue, f"{100 * s.any_issue / t:.2f}%"),
        ("Clean rows (match-ready)", s.clean_rows, f"{100 * s.clean_rows / t:.2f}%"),
        (
            "Excluded from clean (GPS+dup GPS+exact row)",
            t - s.clean_rows,
            f"{100 * (t - s.clean_rows) / t:.2f}%",
        ),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Count", "Percent"])


def export_quality_report_folder(report: QualityReport, folder_path: str) -> list[str]:
    """
    Export one file per issue type into a folder for manual review.
    Returns list of written file paths.
    """
    os.makedirs(folder_path, exist_ok=True)
    written: list[str] = []

    summary_path = os.path.join(folder_path, "00_Summary.xlsx")
    with pd.ExcelWriter(summary_path, engine="openpyxl") as writer:
        _summary_metrics_table(report.summary).to_excel(writer, sheet_name="Metrics", index=False)
        pd.DataFrame({"Line": report.summary.to_lines()}).to_excel(
            writer, sheet_name="Report_Text", index=False
        )
    written.append(summary_path)

    file_map = [
        ("01_exact_duplicate_rows_ALL_COLUMNS_SAME.xlsx", "exact_duplicate_rows"),
        ("02_duplicate_shop_id_ONLY_not_exact_row.xlsx", "duplicate_shop_id_rows"),
        ("03_duplicate_gps_location.xlsx", "duplicate_gps_rows"),
        ("04_missing_gps.xlsx", "missing_gps_rows"),
        ("05_invalid_gps.xlsx", "invalid_gps_rows"),
        ("06_zero_gps.xlsx", "zero_gps_rows"),
        ("07_out_of_range_gps.xlsx", "out_of_range_gps_rows"),
        ("08_outside_pakistan_gps.xlsx", "outside_pakistan_gps_rows"),
        ("09_any_gps_issue.xlsx", "any_gps_issue_rows"),
        ("10_all_rows_with_any_issue.xlsx", "all_rows_with_any_issue"),
        ("11_clean_match_ready.xlsx", "clean_match_ready_rows"),
        ("12_all_rows_flagged_copy.xlsx", None),
    ]

    for filename, key in file_map:
        path = os.path.join(folder_path, filename)
        if key is None:
            df = report.flagged_df
        else:
            df = report.slices.get(key, pd.DataFrame())
        if filename.endswith(".xlsx"):
            if len(df) == 0:
                pd.DataFrame({"message": ["No rows"]}).to_excel(path, index=False)
            else:
                df.to_excel(path, index=False)
        written.append(path)

    return written


def export_quality_report(report: QualityReport, output_path: str) -> str:
    """
    Export to a folder (if path ends with / or no extension) or single Excel workbook.
    Returns actual output path (folder or file).
    """
    if output_path.endswith(os.sep) or (
        not output_path.lower().endswith((".xlsx", ".csv", ".xls"))
    ):
        folder = output_path.rstrip(os.sep)
        if not folder:
            folder = output_path
        export_quality_report_folder(report, folder)
        return folder

    summary_df = _summary_metrics_table(report.summary)
    flagged = report.flagged_df
    lower = output_path.lower()

    if lower.endswith(".csv"):
        base = output_path.rsplit(".", 1)[0]
        parent = os.path.dirname(base) or "."
        name = os.path.basename(base)
        folder = os.path.join(parent, f"{name}_files")
        export_quality_report_folder(report, folder)
        summary_df.to_csv(f"{base}_summary.csv", index=False, encoding="utf-8-sig")
        return folder

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        pd.DataFrame({"Report": report.summary.to_lines()}).to_excel(
            writer, sheet_name="Summary_Text", index=False
        )
        for key, df in report.slices.items():
            sheet = key[:31]
            (df if len(df) else pd.DataFrame({"message": ["No rows"]})).to_excel(
                writer, sheet_name=sheet, index=False
            )
        flagged.to_excel(writer, sheet_name="All_Rows_Flagged", index=False)
    return output_path
