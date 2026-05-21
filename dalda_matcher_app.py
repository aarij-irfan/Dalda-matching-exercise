"""
Dalda Outlet Matcher — PyQt6 desktop app.

Matches Dalda outlet files against the Access Retail census database.
Produces ONE output file: all Dalda columns + match scores + all census columns.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_paths import app_base_dir, default_census_dir
from file_viewer import FileViewerWidget
from match_worker import LoadPreviewWorker, MatchWorker, auto_detect_mappings
from quality_widget import DaldaQualityWidget
from overlap_widget import OverlapCheckWidget
from matching_engine import ColumnMapping, MatchSettings, list_census_files


class DaldaMatcherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dalda Outlet Matcher")
        self.resize(1100, 780)

        self._workers: list = []
        self._dalda_columns: list[str] = []
        self._census_columns: list[str] = []
        self._last_progress_log_pct = -1

        self._build_ui()
        self._refresh_census_list()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        header = QLabel(
            "Match Dalda outlets to Access Retail census — one output row per Dalda outlet."
        )
        header.setWordWrap(True)
        header.setFont(QFont("", 10))
        root.addWidget(header)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        tabs = self.tabs

        # --- Files tab ---
        files_tab = QWidget()
        files_layout = QVBoxLayout(files_tab)

        census_box = QGroupBox("Census database (ours)")
        census_form = QFormLayout(census_box)
        self.census_combo = QComboBox()
        self.census_combo.setMinimumWidth(400)
        census_refresh = QPushButton("Refresh")
        census_refresh.clicked.connect(self._refresh_census_list)
        census_browse = QPushButton("Browse…")
        census_browse.clicked.connect(self._browse_census)
        census_view_btn = QPushButton("View file")
        census_view_btn.setToolTip("Open census file in the built-in viewer")
        census_view_btn.clicked.connect(self._view_census_file)
        census_row = QHBoxLayout()
        census_row.addWidget(self.census_combo, stretch=1)
        census_row.addWidget(census_refresh)
        census_row.addWidget(census_browse)
        census_row.addWidget(census_view_btn)
        census_form.addRow("Census file:", census_row)
        files_layout.addWidget(census_box)

        dalda_box = QGroupBox("Dalda outlet file (theirs)")
        dalda_form = QFormLayout(dalda_box)
        self.dalda_path_edit = QLineEdit()
        self.dalda_path_edit.setPlaceholderText("Select CSV or Excel from Dalda…")
        dalda_browse = QPushButton("Browse…")
        dalda_browse.clicked.connect(self._browse_dalda)
        dalda_view_btn = QPushButton("View file")
        dalda_view_btn.setToolTip("Open Dalda file in the built-in viewer (no Excel needed)")
        dalda_view_btn.clicked.connect(self._view_dalda_file)
        dalda_row = QHBoxLayout()
        dalda_row.addWidget(self.dalda_path_edit, stretch=1)
        dalda_row.addWidget(dalda_browse)
        dalda_row.addWidget(dalda_view_btn)
        dalda_form.addRow("Dalda file:", dalda_row)
        self.dalda_info_label = QLabel("No file loaded")
        dalda_form.addRow("", self.dalda_info_label)
        files_layout.addWidget(dalda_box)

        output_box = QGroupBox("Output (single file)")
        output_form = QFormLayout(output_box)
        self.output_path_edit = QLineEdit()
        output_browse = QPushButton("Save as…")
        output_browse.clicked.connect(self._browse_output)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_path_edit, stretch=1)
        output_row.addWidget(output_browse)
        output_form.addRow("Output file:", output_row)
        self.output_hint = QLabel(
            "One file: dalda_* columns → match_* scores → census_* columns. "
            "Shop IDs export as dalda_shop_id and census_shop_id. Row count = Dalda rows."
        )
        self.output_hint.setWordWrap(True)
        output_form.addRow("", self.output_hint)
        files_layout.addWidget(output_box)
        files_layout.addStretch()
        tabs.addTab(files_tab, "Files")

        # --- Column mapping tab ---
        mapping_tab = QWidget()
        mapping_layout = QVBoxLayout(mapping_tab)
        mapping_layout.addWidget(
            QLabel(
                "Map columns dynamically. GPS can be separate Lat/Lon or a combined "
                "“lat,lon” field. Auto-detect runs when you load the Dalda file."
            )
        )

        splitter = QSplitter(Qt.Orientation.Horizontal)

        dalda_map_box = QGroupBox("Dalda columns")
        dalda_map_form = QFormLayout(dalda_map_box)
        self.dalda_shop_id_combo = QComboBox()
        self.dalda_shop_combo = QComboBox()
        self.dalda_lat_combo = QComboBox()
        self.dalda_lon_combo = QComboBox()
        self.dalda_gps_combo = QComboBox()
        self.dalda_addr_combo = QComboBox()
        self.dalda_channel_combo = QComboBox()
        for combo, label in [
            (self.dalda_shop_id_combo, "Shop ID (→ dalda_shop_id)"),
            (self.dalda_shop_combo, "Outlet name * (→ dalda_outlet_name)"),
            (self.dalda_lat_combo, "Latitude"),
            (self.dalda_lon_combo, "Longitude"),
            (self.dalda_gps_combo, "GPS combined"),
            (self.dalda_addr_combo, "Address (optional)"),
            (self.dalda_channel_combo, "Channel (optional)"),
        ]:
            combo.setEditable(False)
            dalda_map_form.addRow(label, combo)
        splitter.addWidget(dalda_map_box)

        census_map_box = QGroupBox("Census columns (optional overrides)")
        census_map_form = QFormLayout(census_map_box)
        self.census_shop_id_combo = QComboBox()
        self.census_shop_combo = QComboBox()
        self.census_gps_combo = QComboBox()
        self.census_lat_combo = QComboBox()
        self.census_lon_combo = QComboBox()
        for combo, label in [
            (self.census_shop_id_combo, "Shop ID (→ census_shop_id)"),
            (self.census_shop_combo, "Outlet name (→ census_outlet_name)"),
            (self.census_gps_combo, "GPS combined"),
            (self.census_lat_combo, "Latitude"),
            (self.census_lon_combo, "Longitude"),
        ]:
            combo.setEditable(False)
            census_map_form.addRow(label, combo)
        splitter.addWidget(census_map_box)
        mapping_layout.addWidget(splitter)

        auto_btn = QPushButton("Re-run auto-detect")
        auto_btn.clicked.connect(self._auto_detect_all)
        mapping_layout.addWidget(auto_btn)
        tabs.addTab(mapping_tab, "Column mapping")

        # --- Settings tab ---
        settings_tab = QWidget()
        settings_layout = QFormLayout(settings_tab)
        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(50, 10000)
        self.radius_spin.setValue(2000)
        self.radius_spin.setSuffix(" m")
        settings_layout.addRow("Max search radius:", self.radius_spin)

        self.topn_spin = QSpinBox()
        self.topn_spin.setRange(5, 500)
        self.topn_spin.setValue(100)
        settings_layout.addRow("Top candidates per outlet:", self.topn_spin)

        self.min_score_spin = QDoubleSpinBox()
        self.min_score_spin.setRange(0, 100)
        self.min_score_spin.setValue(40)
        settings_layout.addRow("Minimum match score:", self.min_score_spin)

        self.high_conf_spin = QDoubleSpinBox()
        self.high_conf_spin.setRange(0, 100)
        self.high_conf_spin.setValue(70)
        settings_layout.addRow("High confidence ≥", self.high_conf_spin)

        self.med_conf_spin = QDoubleSpinBox()
        self.med_conf_spin.setRange(0, 100)
        self.med_conf_spin.setValue(50)
        settings_layout.addRow("Medium confidence ≥", self.med_conf_spin)

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 16)
        self.threads_spin.setValue(4)
        settings_layout.addRow("Worker threads:", self.threads_spin)
        tabs.addTab(settings_tab, "Settings")

        # --- Run tab ---
        run_tab = QWidget()
        run_layout = QVBoxLayout(run_tab)
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Run matching")
        self.run_btn.setMinimumHeight(40)
        self.run_btn.clicked.connect(self._start_matching)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_matching)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.cancel_btn)
        run_layout.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        run_layout.addWidget(self.progress_bar)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(200)
        run_layout.addWidget(self.log_text)
        tabs.addTab(run_tab, "Run")

        # --- View file tab (no Excel required) ---
        self.file_viewer = FileViewerWidget()
        tabs.addTab(self.file_viewer, "View file")

        # --- Data quality tab ---
        self.quality_widget = DaldaQualityWidget()
        tabs.addTab(self.quality_widget, "Data quality")

        self.overlap_widget = OverlapCheckWidget()
        tabs.addTab(self.overlap_widget, "Issues vs matched")

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {msg}")

    def _refresh_census_list(self):
        self.census_combo.clear()
        census_dir = default_census_dir()
        files = list_census_files(census_dir)
        if not files:
            self.census_combo.addItem("(No census files in Census Database/)", "")
            self._log(f"No census files found in {census_dir}")
        else:
            for f in files:
                self.census_combo.addItem(os.path.basename(f), f)
            self._log(f"Found {len(files)} census file(s)")
            self._load_census_preview(files[0])

    def _browse_census(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select census file",
            default_census_dir(),
            "Data files (*.csv *.xlsx *.xls *.xlsm)",
        )
        if path:
            self.census_combo.addItem(os.path.basename(path), path)
            self.census_combo.setCurrentIndex(self.census_combo.count() - 1)
            self._load_census_preview(path)

    def _load_census_preview(self, path: str):
        worker = LoadPreviewWorker(path)
        worker.finished_ok.connect(self._on_census_preview)
        worker.failed.connect(lambda e: self._log(f"Census preview error: {e}"))
        self._workers.append(worker)
        worker.start()

    def _on_census_preview(self, path: str, columns: list, row_count: int):
        self._census_columns = columns
        self._populate_combo(self.census_shop_id_combo, columns, allow_empty=True)
        self._populate_combo(self.census_shop_combo, columns, allow_empty=True)
        self._populate_combo(self.census_gps_combo, columns, allow_empty=True)
        self._populate_combo(self.census_lat_combo, columns, allow_empty=True)
        self._populate_combo(self.census_lon_combo, columns, allow_empty=True)
        from matching_engine import suggest_column_mapping

        mapping = suggest_column_mapping(columns, prefer_census_defaults=True)
        self._set_combo(self.census_shop_id_combo, mapping.shop_id)
        self._set_combo(self.census_shop_combo, mapping.shop_name)
        self._set_combo(self.census_gps_combo, mapping.gps_combined)
        self._set_combo(self.census_lat_combo, mapping.latitude)
        self._set_combo(self.census_lon_combo, mapping.longitude)
        self._log(f"Census: {os.path.basename(path)} — {row_count:,} rows, {len(columns)} columns")

    def _view_dalda_file(self):
        path = self.dalda_path_edit.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "View file", "Select a valid Dalda file first.")
            return
        self.tabs.setCurrentWidget(self.file_viewer)
        self.file_viewer.open_file(path)

    def _view_census_file(self):
        path = self.census_combo.currentData()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "View file", "Select a valid census file first.")
            return
        self.tabs.setCurrentWidget(self.file_viewer)
        self.file_viewer.open_file(path)

    def _browse_dalda(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Dalda outlet file",
            app_base_dir(),
            "Data files (*.csv *.xlsx *.xls *.xlsm)",
        )
        if path:
            self.dalda_path_edit.setText(path)
            if not self.output_path_edit.text():
                base, _ = os.path.splitext(path)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                self.output_path_edit.setText(f"{base}_matched_{ts}.xlsx")
            self._load_dalda_preview(path)
            self.quality_widget.set_dalda_path(path)

    def _load_dalda_preview(self, path: str):
        worker = LoadPreviewWorker(path)
        worker.finished_ok.connect(self._on_dalda_preview)
        worker.failed.connect(lambda e: QMessageBox.critical(self, "Load error", e))
        self._workers.append(worker)
        worker.start()

    def _on_dalda_preview(self, path: str, columns: list, row_count: int):
        self._dalda_columns = columns
        self.dalda_info_label.setText(f"{row_count:,} outlets — {len(columns)} columns")
        self._populate_combo(self.dalda_shop_id_combo, columns, allow_empty=True)
        self._populate_combo(self.dalda_shop_combo, columns)
        self._populate_combo(self.dalda_lat_combo, columns, allow_empty=True)
        self._populate_combo(self.dalda_lon_combo, columns, allow_empty=True)
        self._populate_combo(self.dalda_gps_combo, columns, allow_empty=True)
        self._populate_combo(self.dalda_addr_combo, columns, allow_empty=True)
        self._populate_combo(self.dalda_channel_combo, columns, allow_empty=True)
        self._auto_detect_dalda()
        self._log(f"Dalda: {os.path.basename(path)} — {row_count:,} rows")

    def _populate_combo(self, combo: QComboBox, columns: list[str], allow_empty: bool = False):
        combo.blockSignals(True)
        combo.clear()
        if allow_empty:
            combo.addItem("(none)", "")
        for c in columns:
            combo.addItem(c, c)
        combo.blockSignals(False)

    def _set_combo(self, combo: QComboBox, value: str | None):
        if not value:
            if combo.count() and combo.itemData(0) == "":
                combo.setCurrentIndex(0)
            return
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.addItem(value, value)
            combo.setCurrentIndex(combo.count() - 1)

    def _combo_value(self, combo: QComboBox) -> str | None:
        v = combo.currentData()
        if v is None or v == "":
            return None
        return str(v)

    def _auto_detect_dalda(self):
        if not self._dalda_columns:
            return
        m = auto_detect_mappings(self._dalda_columns)
        self._set_combo(self.dalda_shop_id_combo, m.shop_id)
        self._set_combo(self.dalda_shop_combo, m.shop_name)
        self._set_combo(self.dalda_lat_combo, m.latitude)
        self._set_combo(self.dalda_lon_combo, m.longitude)
        self._set_combo(self.dalda_gps_combo, m.gps_combined)
        self._set_combo(self.dalda_addr_combo, m.address)
        self._set_combo(self.dalda_channel_combo, m.channel)

    def _auto_detect_all(self):
        self._auto_detect_dalda()
        if self._census_columns:
            from matching_engine import suggest_column_mapping

            m = suggest_column_mapping(self._census_columns, prefer_census_defaults=True)
            self._set_combo(self.census_shop_id_combo, m.shop_id)
            self._set_combo(self.census_shop_combo, m.shop_name)
            self._set_combo(self.census_gps_combo, m.gps_combined)
            self._set_combo(self.census_lat_combo, m.latitude)
            self._set_combo(self.census_lon_combo, m.longitude)
        self._log("Column mapping auto-detected")

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save matched output",
            self.output_path_edit.text() or app_base_dir(),
            "Excel (*.xlsx);;CSV (*.csv)",
        )
        if path:
            if not path.lower().endswith((".xlsx", ".csv")):
                path += ".xlsx"
            self.output_path_edit.setText(path)

    def _get_dalda_mapping(self) -> ColumnMapping:
        return ColumnMapping(
            shop_id=self._combo_value(self.dalda_shop_id_combo),
            shop_name=self._combo_value(self.dalda_shop_combo),
            latitude=self._combo_value(self.dalda_lat_combo),
            longitude=self._combo_value(self.dalda_lon_combo),
            gps_combined=self._combo_value(self.dalda_gps_combo),
            address=self._combo_value(self.dalda_addr_combo),
            channel=self._combo_value(self.dalda_channel_combo),
        )

    def _get_census_mapping(self) -> ColumnMapping:
        return ColumnMapping(
            shop_id=self._combo_value(self.census_shop_id_combo),
            shop_name=self._combo_value(self.census_shop_combo),
            latitude=self._combo_value(self.census_lat_combo),
            longitude=self._combo_value(self.census_lon_combo),
            gps_combined=self._combo_value(self.census_gps_combo),
        )

    def _get_settings(self) -> MatchSettings:
        return MatchSettings(
            max_radius_m=self.radius_spin.value(),
            top_n_candidates=self.topn_spin.value(),
            min_score_threshold=self.min_score_spin.value(),
            high_confidence_threshold=self.high_conf_spin.value(),
            medium_confidence_threshold=self.med_conf_spin.value(),
            worker_threads=self.threads_spin.value(),
        )

    def _validate(self) -> str | None:
        census_path = self.census_combo.currentData()
        if not census_path:
            return "Select a census database file."
        if not os.path.isfile(census_path):
            return f"Census file not found: {census_path}"
        dalda_path = self.dalda_path_edit.text().strip()
        if not dalda_path or not os.path.isfile(dalda_path):
            return "Select a valid Dalda outlet file."
        output_path = self.output_path_edit.text().strip()
        if not output_path:
            return "Choose an output file path."
        mapping = self._get_dalda_mapping()
        has_latlon = mapping.latitude and mapping.longitude
        has_gps = mapping.gps_combined
        if not has_latlon and not has_gps:
            return "Map Dalda GPS: either Lat+Lon or a combined GPS column."
        if not mapping.shop_name:
            return "Map Dalda shop name column."
        return None

    def _start_matching(self):
        err = self._validate()
        if err:
            QMessageBox.warning(self, "Validation", err)
            return

        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self._last_progress_log_pct = -1
        self._log("Starting match…")

        self._match_worker = MatchWorker(
            dalda_path=self.dalda_path_edit.text().strip(),
            census_path=self.census_combo.currentData(),
            dalda_mapping=self._get_dalda_mapping(),
            census_mapping=self._get_census_mapping(),
            settings=self._get_settings(),
            output_path=self.output_path_edit.text().strip(),
        )
        self._match_worker.progress.connect(self._on_progress)
        self._match_worker.finished_ok.connect(self._on_match_done)
        self._match_worker.failed.connect(self._on_match_failed)
        self._workers.append(self._match_worker)
        self._match_worker.start()

    def _cancel_matching(self):
        if hasattr(self, "_match_worker") and self._match_worker.isRunning():
            self._match_worker.cancel()
            self._log("Cancellation requested…")

    def _on_progress(self, value: int, maximum: int, message: str):
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)
        self.status_bar.showMessage(message)
        # Also log to Run tab (every ~2% so it feels like Pepsi console output)
        if value - self._last_progress_log_pct >= 2 or value >= maximum:
            self._log(message)
            self._last_progress_log_pct = value

    def _on_match_done(self, result_df, stats):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        out = self.output_path_edit.text().strip()
        msg = (
            f"Complete.\n\n"
            f"Dalda outlets: {stats.total_dalda:,}\n"
            f"Matched: {stats.matched:,}\n"
            f"Below threshold: {stats.below_threshold:,}\n"
            f"No match: {stats.unmatched - stats.below_threshold:,}\n"
            f"Avg score (matched): {stats.average_score:.1f}\n"
            f"Avg distance: {stats.average_distance_m:.1f} m\n\n"
            f"Output rows: {len(result_df):,} (same as input)\n"
            f"Saved to:\n{out}"
        )
        self._log(msg.replace("\n", " | "))
        QMessageBox.information(self, "Matching complete", msg)
        self.status_bar.showMessage(f"Saved {len(result_df):,} rows → {os.path.basename(out)}")

    def _on_match_failed(self, error: str):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._log(f"Error: {error[:200]}")
        QMessageBox.critical(self, "Matching failed", error)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = DaldaMatcherWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
