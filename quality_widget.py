"""PyQt tab for Dalda file quality / duplicate / GPS analysis."""

from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dalda_quality_check import QualityReport, analyze_dalda_file, export_quality_report
from matching_engine import ColumnMapping, suggest_column_mapping


class QualityAnalysisWorker(QThread):
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, path: str, mapping: ColumnMapping):
        super().__init__()
        self.path = path
        self.mapping = mapping

    def run(self):
        try:
            report = analyze_dalda_file(self.path, self.mapping)
            self.finished_ok.emit(report)
        except Exception as exc:
            self.failed.emit(str(exc))


class DaldaQualityWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._report: QualityReport | None = None
        self._workers: list = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Check Dalda file before matching. True duplicates = rows identical on "
                "ALL columns (not shop name alone). Export creates separate Excel files "
                "per issue type for manual review."
            )
        )

        file_box = QGroupBox("Dalda file")
        file_form = QFormLayout(file_box)
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("CSV or Excel from Dalda…")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        use_dalda = QPushButton("Use path from Files tab")
        use_dalda.clicked.connect(self._use_files_tab_path)
        row.addWidget(self.path_edit, stretch=1)
        row.addWidget(browse)
        row.addWidget(use_dalda)
        file_form.addRow("File:", row)
        layout.addWidget(file_box)

        map_box = QGroupBox("Columns (auto-detected when you run)")
        map_form = QFormLayout(map_box)
        self.info_label = QLabel("Load a file and click Run analysis.")
        self.info_label.setWordWrap(True)
        map_form.addRow("", self.info_label)
        layout.addWidget(map_box)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Run quality check")
        self.run_btn.clicked.connect(self._run)
        self.export_btn = QPushButton("Export all files to folder…")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.export_btn)
        layout.addLayout(btn_row)

        self.results = QTextEdit()
        self.results.setReadOnly(True)
        self.results.setMinimumHeight(320)
        self.results.setPlaceholderText("Summary will appear here…")
        layout.addWidget(self.results, stretch=1)

    def set_dalda_path(self, path: str):
        if path:
            self.path_edit.setText(path)

    def _use_files_tab_path(self):
        win = self.window()
        if hasattr(win, "dalda_path_edit"):
            p = win.dalda_path_edit.text().strip()
            if p:
                self.path_edit.setText(p)
            else:
                QMessageBox.information(self, "Quality check", "Set Dalda file on Files tab first.")

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Dalda outlet file",
            self.path_edit.text() or os.path.expanduser("~"),
            "Data files (*.csv *.xlsx *.xls *.xlsm)",
        )
        if path:
            self.path_edit.setText(path)

    def _run(self):
        path = self.path_edit.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "Quality check", "Select a valid Dalda file.")
            return

        import pandas as pd
        from matching_engine import load_table, suggest_column_mapping

        if path.lower().endswith(".csv"):
            cols = list(pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns)
        else:
            cols = list(pd.read_excel(path, nrows=0).columns)
        mapping = suggest_column_mapping(cols)

        self.info_label.setText(
            f"Shop ID: {mapping.shop_id or '(not found)'} | "
            f"Name: {mapping.shop_name or '(not found)'} | "
            f"GPS: {mapping.gps_combined or mapping.latitude or '(not found)'}"
        )

        self.run_btn.setEnabled(False)
        self.results.setPlainText("Analyzing… please wait.")
        worker = QualityAnalysisWorker(path, mapping)
        worker.finished_ok.connect(self._on_done)
        worker.failed.connect(self._on_fail)
        self._workers.append(worker)
        worker.start()

    def _on_done(self, report: QualityReport):
        self._report = report
        self.run_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        lines = report.summary.to_lines()
        self.results.setPlainText("\n".join(lines))

    def _on_fail(self, err: str):
        self.run_btn.setEnabled(True)
        QMessageBox.critical(self, "Quality check failed", err)
        self.results.setPlainText(f"Error:\n{err}")

    def _export(self):
        if not self._report:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"dalda_quality_report_{ts}"
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose folder for quality report files",
            default_name,
        )
        if not folder:
            return
        report_folder = os.path.join(folder, default_name)
        try:
            from dalda_quality_check import export_quality_report_folder

            files = export_quality_report_folder(self._report, report_folder)
            QMessageBox.information(
                self,
                "Exported",
                f"Saved {len(files)} files to:\n{report_folder}\n\n"
                "Includes:\n"
                "• 01_exact_duplicate_rows (all columns same)\n"
                "• 02_duplicate_shop_id_only\n"
                "• 03–09 GPS issue files\n"
                "• 10_all_issues, 11_clean_match_ready",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
