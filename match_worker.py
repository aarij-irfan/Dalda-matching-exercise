"""Background workers for loading data and running matches."""

from __future__ import annotations

import os
import time
import traceback

import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal

from matching_engine import (
    ColumnMapping,
    MatchSettings,
    MatchStats,
    load_table,
    prepare_census_coordinates,
    run_matching,
    suggest_column_mapping,
)


class LoadPreviewWorker(QThread):
    """Load a file and return column names for UI mapping."""

    finished_ok = pyqtSignal(str, list, int)  # path, columns, row_count
    failed = pyqtSignal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            df = load_table(self.path)
            self.finished_ok.emit(self.path, list(df.columns), len(df))
        except Exception as exc:
            self.failed.emit(str(exc))


class MatchWorker(QThread):
    """Load census + Dalda, run matching, emit single output DataFrame."""

    progress = pyqtSignal(int, int, str)
    finished_ok = pyqtSignal(object, object)  # DataFrame, MatchStats
    failed = pyqtSignal(str)

    def __init__(
        self,
        dalda_path: str,
        census_path: str,
        dalda_mapping: ColumnMapping,
        census_mapping: ColumnMapping,
        settings: MatchSettings,
        output_path: str,
    ):
        super().__init__()
        self.dalda_path = dalda_path
        self.census_path = census_path
        self.dalda_mapping = dalda_mapping
        self.census_mapping = census_mapping
        self.settings = settings
        self.output_path = output_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _cancelled_check(self) -> bool:
        return self._cancelled

    def run(self):
        try:
            self.progress.emit(0, 100, "Loading Dalda file...")
            dalda_df = load_table(self.dalda_path)
            dalda_count = len(dalda_df)

            if self._cancelled:
                return

            self.progress.emit(5, 100, "Loading census database...")
            census_df = load_table(self.census_path)
            self.progress.emit(15, 100, f"Census loaded: {len(census_df):,} shops")

            if self._cancelled:
                return

            self.progress.emit(20, 100, "Preparing GPS coordinates...")
            census_df = prepare_census_coordinates(census_df, self.census_mapping)
            self.progress.emit(25, 100, f"Valid census GPS: {len(census_df):,} shops")

            match_started = time.time()

            def _fmt_eta(seconds: float) -> str:
                if seconds < 60:
                    return f"{seconds:.0f}s"
                if seconds < 3600:
                    return f"{int(seconds // 60)}m {int(seconds % 60)}s"
                return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"

            def on_progress(done: int, total: int):
                pct = 25 + int(70 * done / max(total, 1))
                elapsed = time.time() - match_started
                rate = done / elapsed if elapsed > 0 and done > 0 else 0.0
                remaining = (total - done) / rate if rate > 0 else 0.0
                pct_done = 100.0 * done / max(total, 1)
                msg = (
                    f"Matching… {done:,} / {total:,} ({pct_done:.1f}%) | "
                    f"{rate:.1f} outlets/s | ETA {_fmt_eta(remaining)}"
                )
                self.progress.emit(pct, 100, msg)

            self.progress.emit(
                30,
                100,
                f"Matching {dalda_count:,} outlets ({self.settings.worker_threads} threads)…",
            )

            result_df, stats = run_matching(
                dalda_df=dalda_df,
                census_df=census_df,
                dalda_mapping=self.dalda_mapping,
                census_mapping=self.census_mapping,
                settings=self.settings,
                progress_callback=on_progress,
                cancel_check=self._cancelled_check,
            )

            if len(result_df) != dalda_count:
                raise RuntimeError(
                    f"Output row count ({len(result_df)}) does not match "
                    f"Dalda input ({dalda_count})."
                )

            self.progress.emit(95, 100, "Writing output file...")
            os.makedirs(os.path.dirname(self.output_path) or ".", exist_ok=True)
            lower = self.output_path.lower()
            if lower.endswith(".csv"):
                result_df.to_csv(self.output_path, index=False, encoding="utf-8-sig")
            else:
                result_df.to_excel(self.output_path, index=False)

            self.progress.emit(100, 100, "Done")
            self.finished_ok.emit(result_df, stats)

        except InterruptedError:
            self.failed.emit("Matching was cancelled.")
        except Exception:
            self.failed.emit(traceback.format_exc())


def auto_detect_mappings(columns: list[str]) -> ColumnMapping:
    return suggest_column_mapping(columns)
