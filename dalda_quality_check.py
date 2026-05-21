"""
Dalda outlet file data-quality analysis: duplicates, GPS issues, summary stats.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from matching_engine import (
    ColumnMapping,
    load_table,
    normalize_text,
    parse_gps_value,
    suggest_column_mapping,
)

# Rough Pakistan bounding box (suspicious if outside — not always wrong)
PAK_LAT_MIN, PAK_LAT_MAX = 23.0, 37.5
PAK_LON_MIN, PAK_LON_MAX = 60.5, 77.5


@dataclass
class QualitySummary:
    total_rows: int = 0
    missing_gps: int = 0
    invalid_gps: int = 0
    zero_gps: int = 0
    out_of_range_gps: int = 0
    outside_pakistan_gps: int = 0
    duplicate_shop_id: int = 0
    duplicate_shop_name: int = 0
    duplicate_gps: int = 0
    duplicate_full_row: int = 0
    any_duplicate: int = 0
    any_gps_issue: int = 0
    any_issue: int = 0
    clean_rows: int = 0
    duplicate_shop_id_groups: int = 0
    duplicate_name_groups: int = 0
    duplicate_gps_groups: int = 0

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
            "── Duplicates (rows involved) ──",
            f"  Duplicate shop ID:       {pct(self.duplicate_shop_id)}"
            + (
                f"  [{self.duplicate_shop_id_groups:,} duplicate ID groups]"
                if self.duplicate_shop_id_groups
                else ""
            ),
            f"  Duplicate outlet name:   {pct(self.duplicate_shop_name)}"
            + (
                f"  [{self.duplicate_name_groups:,} duplicate name groups]"
                if self.duplicate_name_groups
                else ""
            ),
            f"  Duplicate GPS location:  {pct(self.duplicate_gps)}"
            + (
                f"  [{self.duplicate_gps_groups:,} duplicate GPS groups]"
                if self.duplicate_gps_groups
                else ""
            ),
            f"  Exact duplicate row:     {pct(self.duplicate_full_row)}",
            f"  Any duplicate flag:      {pct(self.any_duplicate)}",
            "",
            "── Summary ──",
            f"  Rows with ANY issue:     {pct(self.any_issue)}",
            f"  Clean rows (match-ready):{pct(self.clean_rows)}",
            "",
            "Clean = valid GPS and not flagged as duplicate (ID, name, GPS, or full row).",
        ]


@dataclass
class QualityReport:
    summary: QualitySummary
    flagged_df: pd.DataFrame
    mapping: ColumnMapping


def _resolve_row_gps(row: pd.Series, mapping: ColumnMapping) -> tuple[float | None, float | None, str]:
    """Return lat, lon, gps_status: ok | missing | invalid | zero | out_of_range | outside_pakistan."""
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

    # --- Duplicate shop ID ---
    id_groups = 0
    if mapping.shop_id and mapping.shop_id in df.columns:
        ids = df[mapping.shop_id].map(_non_empty_key)
        id_dup_mask = ids.notna() & ids.duplicated(keep=False)
        id_groups = ids[ids.notna()].value_counts()
        id_groups = int((id_groups > 1).sum())
        for i in range(n):
            if id_dup_mask.iloc[i]:
                issues[i].append("duplicate_shop_id")

    # --- Duplicate outlet name (normalized) ---
    name_groups = 0
    if mapping.shop_name and mapping.shop_name in df.columns:
        names = df[mapping.shop_name].map(
            lambda x: normalize_text(x) if _non_empty_key(x) else None
        )
        name_dup_mask = names.notna() & names.duplicated(keep=False)
        ng = names[names.notna()].value_counts()
        name_groups = int((ng > 1).sum())
        for i in range(n):
            if name_dup_mask.iloc[i]:
                issues[i].append("duplicate_name")

    # --- Duplicate GPS (rounded) ---
    gps_groups = 0
    gps_keys = []
    for i in range(n):
        if gps_statuses[i] == "ok":
            gps_keys.append(f"{latitudes[i]:.5f},{longitudes[i]:.5f}")
        else:
            gps_keys.append(None)
    gps_series = pd.Series(gps_keys)
    gps_dup_mask = gps_series.notna() & gps_series.duplicated(keep=False)
    gg = gps_series[gps_series.notna()].value_counts()
    gps_groups = int((gg > 1).sum())
    for i in range(n):
        if gps_dup_mask.iloc[i]:
            issues[i].append("duplicate_gps")

    # --- Exact duplicate rows ---
    row_dup_mask = df.duplicated(keep=False)
    for i in range(n):
        if row_dup_mask.iloc[i]:
            issues[i].append("duplicate_full_row")

    out["_quality_issues"] = ["; ".join(x) if x else "" for x in issues]
    out["_has_issue"] = out["_quality_issues"] != ""

    dup_flags = {
        "duplicate_shop_id",
        "duplicate_name",
        "duplicate_gps",
        "duplicate_full_row",
    }
    any_dup = [any(f in issues[i] for f in dup_flags) for i in range(n)]
    gps_bad = [gps_statuses[i] != "ok" for i in range(n)]
    clean = [
        gps_statuses[i] == "ok" and not any_dup[i] for i in range(n)
    ]

    summary = QualitySummary(
        total_rows=n,
        missing_gps=sum(1 for s in gps_statuses if s == "missing"),
        invalid_gps=sum(1 for s in gps_statuses if s == "invalid"),
        zero_gps=sum(1 for s in gps_statuses if s == "zero"),
        out_of_range_gps=sum(1 for s in gps_statuses if s == "out_of_range"),
        outside_pakistan_gps=sum(1 for s in gps_statuses if s == "outside_pakistan"),
        duplicate_shop_id=sum(1 for i in range(n) if "duplicate_shop_id" in issues[i]),
        duplicate_shop_name=sum(1 for i in range(n) if "duplicate_name" in issues[i]),
        duplicate_gps=sum(1 for i in range(n) if "duplicate_gps" in issues[i]),
        duplicate_full_row=int(row_dup_mask.sum()),
        duplicate_shop_id_groups=id_groups,
        duplicate_name_groups=name_groups,
        duplicate_gps_groups=gps_groups,
        any_duplicate=sum(any_dup),
        any_gps_issue=sum(gps_bad),
        any_issue=int(out["_has_issue"].sum()),
        clean_rows=sum(clean),
    )

    return QualityReport(summary=summary, flagged_df=out, mapping=mapping)


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
        ("Duplicate shop ID (rows)", s.duplicate_shop_id, f"{100 * s.duplicate_shop_id / t:.2f}%"),
        ("Duplicate ID groups", s.duplicate_shop_id_groups, ""),
        ("Duplicate outlet name (rows)", s.duplicate_shop_name, f"{100 * s.duplicate_shop_name / t:.2f}%"),
        ("Duplicate name groups", s.duplicate_name_groups, ""),
        ("Duplicate GPS location (rows)", s.duplicate_gps, f"{100 * s.duplicate_gps / t:.2f}%"),
        ("Duplicate GPS groups", s.duplicate_gps_groups, ""),
        ("Exact duplicate row", s.duplicate_full_row, f"{100 * s.duplicate_full_row / t:.2f}%"),
        ("Any duplicate flag", s.any_duplicate, f"{100 * s.any_duplicate / t:.2f}%"),
        ("Rows with ANY issue", s.any_issue, f"{100 * s.any_issue / t:.2f}%"),
        ("Clean rows (match-ready)", s.clean_rows, f"{100 * s.clean_rows / t:.2f}%"),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Count", "Percent"])


def export_quality_report(report: QualityReport, output_path: str) -> None:
    """Write summary + all rows + issue-only rows to Excel or CSV."""
    summary_df = _summary_metrics_table(report.summary)
    flagged = report.flagged_df
    issues_only = flagged[flagged["_has_issue"]].copy()

    lower = output_path.lower()
    if lower.endswith(".csv"):
        flagged.to_csv(output_path, index=False, encoding="utf-8-sig")
        base = output_path.rsplit(".", 1)[0]
        summary_df.to_csv(f"{base}_summary.csv", index=False, encoding="utf-8-sig")
        issues_only.to_csv(f"{base}_issues_only.csv", index=False, encoding="utf-8-sig")
    else:
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="Summary", index=False)
            pd.DataFrame({"Report": report.summary.to_lines()}).to_excel(
                writer, sheet_name="Summary_Text", index=False
            )
            flagged.to_excel(writer, sheet_name="All_Rows", index=False)
            issues_only.to_excel(writer, sheet_name="Rows_With_Issues", index=False)
