"""
Compare quality-issue outlets vs final matched output file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import pandas as pd

from matching_engine import (
    DALDA_SHOP_ID_COL,
    load_table,
    suggest_column_mapping,
)
from dalda_quality_check import _data_columns, _row_content_key


@dataclass
class OverlapReport:
    issues_total: int
    matched_total: int
    overlap_count: int
    issues_only_count: int
    matched_only_count: int
    matched_without_overlap_count: int
    issues_key_column: str
    matched_key_column: str
    match_method: str
    overlap_df: pd.DataFrame
    issues_only_df: pd.DataFrame
    matched_without_overlap_df: pd.DataFrame = field(default_factory=pd.DataFrame)

    def to_lines(self) -> list[str]:
        pct_issues = (
            f"{100 * self.overlap_count / max(self.issues_total, 1):.2f}%"
            if self.issues_total
            else "0%"
        )
        return [
            f"Issues file rows (10_all_rows_with_any_issue): {self.issues_total:,}",
            f"Matched output file rows:                         {self.matched_total:,}",
            f"Match method: {self.match_method}",
            f"  Issues key column:  {self.issues_key_column}",
            f"  Matched key column: {self.matched_key_column}",
            "",
            f"Shops in BOTH files (should be 0):  {self.overlap_count:,}  ({pct_issues} of issues file)",
            f"Shops only in issues file:          {self.issues_only_count:,}",
            f"Shops only in matched file:         {self.matched_only_count:,}",
            f"Matched file WITHOUT overlap rows:  {self.matched_without_overlap_count:,}",
            "",
            (
                "OK: No issue rows appear in the matched file."
                if self.overlap_count == 0
                else "WARNING: Some issue rows ARE in the matched file — review overlap export."
            ),
            "",
            "Export includes 04_matched_without_overlap.xlsx (safe matched rows only).",
        ]


def _detect_shop_id_column(df: pd.DataFrame) -> str | None:
    priority = [
        DALDA_SHOP_ID_COL,
        "dalda_shop_id",
        "Shop_ID",
        "Shop ID",
        "Shop Code",
        "Shop Code ",
        "shop_id",
        "shop_code",
        "Customer Code",
        "Outlet ID",
    ]
    cols_lower = {str(c).strip().lower(): c for c in df.columns}
    for name in priority:
        if name.lower() in cols_lower:
            return cols_lower[name.lower()]
    mapping = suggest_column_mapping(list(df.columns))
    return mapping.shop_id


def _keys_from_column(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col].map(
        lambda v: None
        if pd.isna(v) or str(v).strip() == ""
        else str(v).strip()
    )


def _filter_matched_without_overlap(
    issues_df: pd.DataFrame,
    matched_df: pd.DataFrame,
    report: OverlapReport,
) -> pd.DataFrame:
    """Rows from matched file that do not appear in the issues file."""
    if report.match_method.startswith("Shop ID"):
        issues_col = report.issues_key_column
        matched_col = report.matched_key_column
        issues_keys = set(_keys_from_column(issues_df, issues_col).dropna())
        matched_keys = _keys_from_column(matched_df, matched_col)
        keep = ~matched_keys.isin(issues_keys)
        return matched_df[keep].copy()

    issues_fp = set(_row_content_key(issues_df[_data_columns(issues_df)]))
    matched_dalda_cols = [c for c in matched_df.columns if str(c).startswith("dalda_")]
    if not matched_dalda_cols:
        matched_dalda_cols = _data_columns(matched_df)
    matched_fp = _row_content_key(matched_df[matched_dalda_cols])
    keep = ~matched_fp.isin(issues_fp)
    return matched_df[keep].copy()


def _compare_by_shop_id(issues_df: pd.DataFrame, matched_df: pd.DataFrame) -> OverlapReport | None:
    issues_col = _detect_shop_id_column(issues_df)
    matched_col = _detect_shop_id_column(matched_df)
    if not issues_col or not matched_col:
        return None

    issues_keys = _keys_from_column(issues_df, issues_col)
    matched_keys = _keys_from_column(matched_df, matched_col)

    issues_with_key = issues_df[issues_keys.notna()].copy()
    issues_keys_valid = issues_keys[issues_keys.notna()]
    matched_keys_valid = matched_keys[matched_keys.notna()]

    issues_set = set(issues_keys_valid)
    matched_set = set(matched_keys_valid)
    overlap_mask = issues_keys_valid.isin(matched_set)

    overlap_df = issues_with_key[overlap_mask].copy()
    issues_only_df = issues_with_key[~overlap_mask].copy()
    matched_only_count = int((~matched_keys_valid.isin(issues_set)).sum())

    report = OverlapReport(
        issues_total=len(issues_df),
        matched_total=len(matched_df),
        overlap_count=len(overlap_df),
        issues_only_count=len(issues_only_df),
        matched_only_count=matched_only_count,
        matched_without_overlap_count=0,
        issues_key_column=issues_col,
        matched_key_column=matched_col,
        match_method="Shop ID (exact string match)",
        overlap_df=overlap_df,
        issues_only_df=issues_only_df,
    )
    clean = _filter_matched_without_overlap(issues_df, matched_df, report)
    report.matched_without_overlap_df = clean
    report.matched_without_overlap_count = len(clean)
    return report


def _compare_by_row_fingerprint(issues_df: pd.DataFrame, matched_df: pd.DataFrame) -> OverlapReport:
    issues_data = issues_df[_data_columns(issues_df)]
    matched_dalda_cols = [c for c in matched_df.columns if str(c).startswith("dalda_")]
    if not matched_dalda_cols:
        matched_dalda_cols = _data_columns(matched_df)

    issues_fp = _row_content_key(issues_data)
    matched_fp = _row_content_key(matched_df[matched_dalda_cols])

    issues_fp_set = set(issues_fp)
    overlap_mask = issues_fp.isin(set(matched_fp.dropna()))

    overlap_df = issues_df[overlap_mask].copy()
    issues_only_df = issues_df[~overlap_mask].copy()
    matched_only_count = int((~matched_fp.isin(issues_fp_set)).sum())

    report = OverlapReport(
        issues_total=len(issues_df),
        matched_total=len(matched_df),
        overlap_count=len(overlap_df),
        issues_only_count=len(issues_only_df),
        matched_only_count=matched_only_count,
        matched_without_overlap_count=0,
        issues_key_column="(all data columns)",
        matched_key_column="(dalda_* columns)",
        match_method="Full row fingerprint (all data columns exact)",
        overlap_df=overlap_df,
        issues_only_df=issues_only_df,
    )
    clean = _filter_matched_without_overlap(issues_df, matched_df, report)
    report.matched_without_overlap_df = clean
    report.matched_without_overlap_count = len(clean)
    return report


def compare_issues_vs_matched(issues_path: str, matched_path: str) -> OverlapReport:
    issues_df = load_table(issues_path)
    matched_df = load_table(matched_path)

    report = _compare_by_shop_id(issues_df, matched_df)
    if report is not None:
        issues_col = report.issues_key_column
        id_fill_rate = issues_df[issues_col].notna().mean() if issues_col else 0
        if id_fill_rate >= 0.5:
            return report

    return _compare_by_row_fingerprint(issues_df, matched_df)


def export_overlap_report(report: OverlapReport, folder_path: str) -> list[str]:
    os.makedirs(folder_path, exist_ok=True)
    written: list[str] = []

    summary_path = os.path.join(folder_path, "00_overlap_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report.to_lines()))
    written.append(summary_path)

    metrics = pd.DataFrame(
        {
            "Metric": [
                "Issues file rows",
                "Matched file rows",
                "In BOTH (overlap)",
                "Only in issues file",
                "Only in matched file",
                "Matched without overlap (export)",
            ],
            "Count": [
                report.issues_total,
                report.matched_total,
                report.overlap_count,
                report.issues_only_count,
                report.matched_only_count,
                report.matched_without_overlap_count,
            ],
        }
    )
    metrics_path = os.path.join(folder_path, "01_overlap_metrics.xlsx")
    metrics.to_excel(metrics_path, index=False)
    written.append(metrics_path)

    overlap_path = os.path.join(folder_path, "02_SHOPS_IN_BOTH_warning.xlsx")
    if len(report.overlap_df):
        report.overlap_df.to_excel(overlap_path, index=False)
    else:
        pd.DataFrame({"message": ["No overlap — good"]}).to_excel(overlap_path, index=False)
    written.append(overlap_path)

    issues_only_path = os.path.join(folder_path, "03_issues_only_not_in_matched.xlsx")
    report.issues_only_df.to_excel(issues_only_path, index=False)
    written.append(issues_only_path)

    clean_path = os.path.join(folder_path, "04_matched_without_overlap.xlsx")
    if len(report.matched_without_overlap_df):
        report.matched_without_overlap_df.to_excel(clean_path, index=False)
    else:
        pd.DataFrame({"message": ["No rows"]}).to_excel(clean_path, index=False)
    written.append(clean_path)

    return written
