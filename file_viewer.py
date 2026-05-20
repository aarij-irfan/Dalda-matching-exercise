"""
In-app CSV / Excel viewer (no Microsoft Excel required).
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from matching_engine import load_table

DATA_FILE_FILTER = "Data files (*.csv *.xlsx *.xls *.xlsm);;CSV (*.csv);;Excel (*.xlsx *.xls *.xlsm);;All files (*.*)"


class LoadDataFileWorker(QThread):
    """Load a data file in the background."""

    finished_ok = pyqtSignal(str, object, list, str)  # path, DataFrame, sheet_names, active_sheet
    failed = pyqtSignal(str)

    def __init__(self, path: str, sheet_name: str | None = None):
        super().__init__()
        self.path = path
        self.sheet_name = sheet_name

    def run(self):
        try:
            path = self.path
            lower = path.lower()
            sheet_names: list[str] = []
            active_sheet = ""

            if lower.endswith((".xlsx", ".xls", ".xlsm")):
                xl = pd.ExcelFile(path)
                sheet_names = list(xl.sheet_names)
                use_sheet = self.sheet_name or sheet_names[0]
                df = pd.read_excel(path, sheet_name=use_sheet)
                active_sheet = use_sheet
            else:
                df = load_table(path)
                sheet_names = []

            self.finished_ok.emit(path, df, sheet_names, active_sheet)
        except Exception as exc:
            self.failed.emit(str(exc))


class PandasTableModel(QAbstractTableModel):
    """Table model for a slice of a DataFrame (pagination)."""

    def __init__(self, df: pd.DataFrame, row_offset: int = 0):
        super().__init__()
        self._df = df
        self._row_offset = row_offset

    def rowCount(self, parent=None) -> int:
        return len(self._df)

    def columnCount(self, parent=None) -> int:
        return len(self._df.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        val = self._df.iloc[index.row(), index.column()]
        if pd.isna(val):
            return ""
        return str(val)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])
        return str(self._row_offset + section + 1)


class FileViewerWidget(QWidget):
    """Browse and preview CSV/Excel files with columns list and paginated grid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers: list = []
        self._df: pd.DataFrame | None = None
        self._path = ""
        self._sheet_names: list[str] = []
        self._page = 0
        self._page_size = 500
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Open CSV or Excel files without Microsoft Excel. "
                "View all column names, types, and row data."
            )
        )

        # --- File picker ---
        pick_box = QGroupBox("Select file")
        pick_row = QHBoxLayout(pick_box)
        self.viewer_path_edit = QLineEdit()
        self.viewer_path_edit.setPlaceholderText("Choose a .csv or .xlsx file…")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_file)
        open_btn = QPushButton("Open")
        open_btn.clicked.connect(self._open_current_path)
        pick_row.addWidget(self.viewer_path_edit, stretch=1)
        pick_row.addWidget(browse_btn)
        pick_row.addWidget(open_btn)
        layout.addWidget(pick_box)

        sheet_row = QHBoxLayout()
        sheet_row.addWidget(QLabel("Excel sheet:"))
        self.sheet_combo = QComboBox()
        self.sheet_combo.setEnabled(False)
        self.sheet_combo.currentTextChanged.connect(self._on_sheet_changed)
        sheet_row.addWidget(self.sheet_combo, stretch=1)
        layout.addLayout(sheet_row)

        self.file_info_label = QLabel("No file loaded")
        self.file_info_label.setWordWrap(True)
        layout.addWidget(self.file_info_label)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # --- Columns summary ---
        cols_box = QGroupBox("Columns (name, type, non-empty, sample)")
        cols_layout = QVBoxLayout(cols_box)
        self.columns_table = QTableWidget()
        self.columns_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.columns_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.columns_table.horizontalHeader().setStretchLastSection(True)
        self.columns_table.setMaximumHeight(220)
        cols_layout.addWidget(self.columns_table)
        splitter.addWidget(cols_box)

        # --- Data grid ---
        data_box = QGroupBox("Data rows")
        data_layout = QVBoxLayout(data_box)

        page_row = QHBoxLayout()
        self.prev_btn = QPushButton("◀ Previous")
        self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn = QPushButton("Next ▶")
        self.next_btn.clicked.connect(self._next_page)
        self.page_label = QLabel("Page —")
        page_row.addWidget(self.prev_btn)
        page_row.addWidget(self.next_btn)
        page_row.addWidget(self.page_label)
        page_row.addStretch()
        page_row.addWidget(QLabel("Rows per page:"))
        self.page_size_spin = QSpinBox()
        self.page_size_spin.setRange(50, 5000)
        self.page_size_spin.setValue(500)
        self.page_size_spin.setSingleStep(50)
        self.page_size_spin.valueChanged.connect(self._on_page_size_changed)
        page_row.addWidget(self.page_size_spin)
        data_layout.addLayout(page_row)

        self.data_table = QTableView()
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setSortingEnabled(False)
        self.data_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.data_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        data_layout.addWidget(self.data_table)
        splitter.addWidget(data_box)

        splitter.setSizes([220, 500])
        layout.addWidget(splitter, stretch=1)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

    def open_file(self, path: str):
        """Open a file from elsewhere in the app (e.g. Dalda path)."""
        if path and os.path.isfile(path):
            self.viewer_path_edit.setText(path)
            self._load_file(path)

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open data file to view",
            self.viewer_path_edit.text() or os.path.expanduser("~"),
            DATA_FILE_FILTER,
        )
        if path:
            self.viewer_path_edit.setText(path)
            self._load_file(path)

    def _open_current_path(self):
        path = self.viewer_path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "View file", "Select a file path first.")
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "View file", f"File not found:\n{path}")
            return
        self._load_file(path)

    def _load_file(self, path: str, sheet_name: str | None = None):
        self.status_label.setText(f"Loading {os.path.basename(path)}…")
        self.setEnabled(False)
        worker = LoadDataFileWorker(path, sheet_name)
        worker.finished_ok.connect(self._on_file_loaded)
        worker.failed.connect(self._on_load_failed)
        self._workers.append(worker)
        worker.start()

    def _on_load_failed(self, error: str):
        self.setEnabled(True)
        self.status_label.setText("")
        QMessageBox.critical(self, "Could not open file", error)

    def _on_file_loaded(
        self,
        path: str,
        df: pd.DataFrame,
        sheet_names: list[str],
        active_sheet: str,
    ):
        self.setEnabled(True)
        self._path = path
        self._df = df
        self._sheet_names = sheet_names
        self._page = 0

        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        if sheet_names:
            self.sheet_combo.addItems(sheet_names)
            self.sheet_combo.setEnabled(True)
            if active_sheet:
                idx = self.sheet_combo.findText(active_sheet)
                if idx >= 0:
                    self.sheet_combo.setCurrentIndex(idx)
        else:
            self.sheet_combo.setEnabled(False)
            self.sheet_combo.addItem("(CSV — single sheet)")
        self.sheet_combo.blockSignals(False)

        rows, cols = len(df), len(df.columns)
        sheet_txt = f" | Sheet: {active_sheet}" if active_sheet else ""
        self.file_info_label.setText(
            f"File: {os.path.basename(path)}{sheet_txt}\n"
            f"Rows: {rows:,}  |  Columns: {cols}"
        )
        self._fill_columns_table(df)
        self._show_page()
        self.status_label.setText(f"Loaded {rows:,} rows × {cols} columns")

    def _on_sheet_changed(self, sheet_name: str):
        if not self._path or not sheet_name or sheet_name.startswith("(CSV"):
            return
        if sheet_name in self._sheet_names:
            self._load_file(self._path, sheet_name)

    def _fill_columns_table(self, df: pd.DataFrame):
        self.columns_table.setColumnCount(5)
        self.columns_table.setHorizontalHeaderLabels(
            ["#", "Column name", "Type", "Non-empty", "Sample value"]
        )
        self.columns_table.setRowCount(len(df.columns))
        for i, col in enumerate(df.columns):
            series = df[col]
            non_empty = int(series.notna().sum())
            sample = ""
            for v in series:
                if pd.notna(v) and str(v).strip() != "":
                    sample = str(v)[:80]
                    break
            items = [
                str(i + 1),
                str(col),
                str(series.dtype),
                f"{non_empty:,} / {len(df):,}",
                sample,
            ]
            for j, text in enumerate(items):
                self.columns_table.setItem(i, j, QTableWidgetItem(text))
        self.columns_table.resizeColumnsToContents()

    def _total_pages(self) -> int:
        if self._df is None or len(self._df) == 0:
            return 1
        return max(1, (len(self._df) + self._page_size - 1) // self._page_size)

    def _show_page(self):
        if self._df is None:
            return
        total_pages = self._total_pages()
        self._page = max(0, min(self._page, total_pages - 1))
        start = self._page * self._page_size
        end = min(start + self._page_size, len(self._df))
        chunk = self._df.iloc[start:end].copy()
        model = PandasTableModel(chunk, row_offset=start)
        self.data_table.setModel(model)
        self.data_table.resizeColumnsToContents()

        self.page_label.setText(
            f"Page {self._page + 1} of {total_pages}  "
            f"(rows {start + 1:,}–{end:,} of {len(self._df):,})"
        )
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < total_pages - 1)

    def _prev_page(self):
        self._page -= 1
        self._show_page()

    def _next_page(self):
        self._page += 1
        self._show_page()

    def _on_page_size_changed(self, value: int):
        self._page_size = value
        self._page = 0
        self._show_page()
