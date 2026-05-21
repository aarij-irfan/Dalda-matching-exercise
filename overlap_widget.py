"""PyQt tab: compare issue outlets vs matched output file."""

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

from overlap_check import OverlapReport, compare_issues_vs_matched, export_overlap_report


class OverlapCheckWorker(QThread):
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, issues_path: str, matched_path: str):
        super().__init__()
        self.issues_path = issues_path
        self.matched_path = matched_path

    def run(self):
        try:
            report = compare_issues_vs_matched(self.issues_path, self.matched_path)
            self.finished_ok.emit(report)
        except Exception as exc:
            self.failed.emit(str(exc))


class OverlapCheckWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._report: OverlapReport | None = None
        self._workers: list = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Check that outlets in 10_all_rows_with_any_issue are NOT in your "
                "final matched file. Uses Shop ID when available, otherwise exact row match."
            )
        )

        files = QGroupBox("Files")
        form = QFormLayout(files)

        issues_row = QHBoxLayout()
        self.issues_edit = QLineEdit()
        issues_browse = QPushButton("Browse…")
        issues_browse.clicked.connect(self._browse_issues)
        issues_row.addWidget(self.issues_edit, stretch=1)
        issues_row.addWidget(issues_browse)
        form.addRow("Issues file:", issues_row)

        matched_row = QHBoxLayout()
        self.matched_edit = QLineEdit()
        matched_browse = QPushButton("Browse…")
        matched_browse.clicked.connect(self._browse_matched)
        use_output = QPushButton("Use output from Files tab")
        use_output.clicked.connect(self._use_output_path)
        matched_row.addWidget(self.matched_edit, stretch=1)
        matched_row.addWidget(matched_browse)
        matched_row.addWidget(use_output)
        form.addRow("Matched file:", matched_row)

        layout.addWidget(files)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Compare files")
        self.run_btn.clicked.connect(self._run)
        self.export_btn = QPushButton("Export overlap report…")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.export_btn)
        layout.addLayout(btn_row)

        self.results = QTextEdit()
        self.results.setReadOnly(True)
        self.results.setMinimumHeight(280)
        layout.addWidget(self.results, stretch=1)

    def _browse_issues(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select 10_all_rows_with_any_issue file",
            self.issues_edit.text() or os.path.expanduser("~"),
            "Excel (*.xlsx *.xls);;CSV (*.csv)",
        )
        if path:
            self.issues_edit.setText(path)

    def _browse_matched(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select matched output file",
            self.matched_edit.text() or os.path.expanduser("~"),
            "Excel (*.xlsx *.xls);;CSV (*.csv)",
        )
        if path:
            self.matched_edit.setText(path)

    def _use_output_path(self):
        win = self.window()
        if hasattr(win, "output_path_edit"):
            p = win.output_path_edit.text().strip()
            if p:
                self.matched_edit.setText(p)
            else:
                QMessageBox.information(
                    self, "Compare", "Set matched output path on Files tab first."
                )

    def _run(self):
        issues = self.issues_edit.text().strip()
        matched = self.matched_edit.text().strip()
        if not issues or not os.path.isfile(issues):
            QMessageBox.warning(self, "Compare", "Select a valid issues file.")
            return
        if not matched or not os.path.isfile(matched):
            QMessageBox.warning(self, "Compare", "Select a valid matched output file.")
            return

        self.run_btn.setEnabled(False)
        self.results.setPlainText("Comparing…")
        worker = OverlapCheckWorker(issues, matched)
        worker.finished_ok.connect(self._on_done)
        worker.failed.connect(self._on_fail)
        self._workers.append(worker)
        worker.start()

    def _on_done(self, report: OverlapReport):
        self._report = report
        self.run_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        self.results.setPlainText("\n".join(report.to_lines()))
        if report.overlap_count > 0:
            QMessageBox.warning(
                self,
                "Overlap found",
                f"{report.overlap_count:,} shops from the issues file also appear "
                f"in the matched file.\n\nReview 02_SHOPS_IN_BOTH in export.",
            )

    def _on_fail(self, err: str):
        self.run_btn.setEnabled(True)
        QMessageBox.critical(self, "Compare failed", err)

    def _export(self):
        if not self._report:
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Save overlap report folder", ""
        )
        if not folder:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(folder, f"overlap_check_{ts}")
        try:
            export_overlap_report(self._report, out)
            QMessageBox.information(self, "Exported", f"Saved to:\n{out}")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
