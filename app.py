from __future__ import annotations

import sys
import time
from collections import deque

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QCloseEvent
from PyQt6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
import pyqtgraph as pg

from engine import is_admin, QoSController, NetworkMonitorWorker
from theme import PALETTE, format_bytes, apply_theme

GRAPH_WINDOW_SECONDS = 60

class TelemetryBuffer:
    def __init__(self, maxlen: int = 120):
        self._samples: deque[tuple[float, float, float]] = deque(maxlen=maxlen)

    def push(self, down_bps: float, up_bps: float) -> None:
        self._samples.append((time.monotonic(), max(0.0, down_bps), max(0.0, up_bps)))

    def clear(self) -> None:
        self._samples.clear()

    def series(self) -> tuple[list[float], list[float], list[float]]:
        if not self._samples: return [], [], []
        now = time.monotonic()
        cutoff = now - GRAPH_WINDOW_SECONDS
        xs, downs, ups = [], [], []
        for t, d, u in self._samples:
            if t >= cutoff:
                xs.append(t - now)
                downs.append(d)
                ups.append(u)
        return xs, downs, ups


class NetoraWindow(QMainWindow):
    HEADERS = ["Name", "PID", "Download", "Upload", "Status / Limit"]
    PID_ROLE = int(Qt.ItemDataRole.UserRole)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Netora — Bandwidth Manager")
        self.resize(1180, 720)
        self.setMinimumSize(960, 580)

        self.qos = QoSController()
        self._admin = bool(is_admin())

        self._selected_pid: int | None = None
        self._selected_name: str = ""
        self._filter_text: str = ""
        self._last_stats: dict | None = None
        self._graph_buffer = TelemetryBuffer()

        self._build_ui()

        self.worker = NetworkMonitorWorker(qos=self.qos, parent=self)
        self.worker.stats_updated.connect(self.on_stats_updated)
        self.worker.start()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(12)
        self.setCentralWidget(root)

        root_layout.addWidget(self._build_header())

        split = QHBoxLayout()
        split.setSpacing(12)
        root_layout.addLayout(split, stretch=1)

        split.addWidget(self._build_table_panel(), stretch=6)

        right_panel = QVBoxLayout()
        right_panel.setSpacing(12)
        right_panel.addWidget(self._build_limiter_panel())
        right_panel.addWidget(self._build_graph_panel(), stretch=1)
        split.addLayout(right_panel, stretch=4)

        self.status_lbl = QLabel("Ready • WinDivert Packet Shaper Ready" if self._admin else "Elevated Admin Privileges Required for Throttling")
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.addWidget(self.status_lbl)

    def _build_header(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)

        title = QLabel("NETORA")
        title.setStyleSheet("font-size: 18px; font-weight: 800; letter-spacing: 2px;")
        lay.addWidget(title)

        admin_badge = QLabel("ADMIN ACTIVE" if self._admin else "STANDARD USER")
        badge_color = PALETTE["ACCENT_CYAN"] if self._admin else PALETTE["ACCENT_DANGER"]
        admin_badge.setStyleSheet(f"background: {badge_color}22; color: {badge_color}; border: 1px solid {badge_color}; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 700;")
        lay.addWidget(admin_badge)

        lay.addSpacing(16)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter processes…")
        self.search_box.setMaximumWidth(280)
        self.search_box.textChanged.connect(self._on_search_changed)
        lay.addWidget(self.search_box)

        lay.addStretch()

        self.down_metric = QLabel("Total Down: 0 KB/s")
        self.down_metric.setStyleSheet(f"color: {PALETTE['ACCENT_CYAN']}; font-weight: 700; font-size: 14px;")
        self.up_metric = QLabel("Total Up: 0 KB/s")
        self.up_metric.setStyleSheet(f"color: {PALETTE['ACCENT_PURPLE']}; font-weight: 700; font-size: 14px;")

        lay.addWidget(self.down_metric)
        lay.addSpacing(16)
        lay.addWidget(self.up_metric)
        return card

    def _build_table_panel(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 10, 10, 10)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        vertical_header = self.table.verticalHeader()
        if vertical_header is not None:
            vertical_header.setVisible(False)
        horizontal_header = self.table.horizontalHeader()
        if horizontal_header is not None:
            horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            for i in range(1, len(self.HEADERS)):
                horizontal_header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        self.table.itemSelectionChanged.connect(self._on_row_selected)
        lay.addWidget(self.table)
        return card

    def _build_limiter_panel(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        title = QLabel("SPEED CEILING CONTROLLER")
        title.setStyleSheet(f"color: {PALETTE['TEXT_SECONDARY']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        lay.addWidget(title)

        self.target_label = QLabel("No Process Selected")
        self.target_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        lay.addWidget(self.target_label)

        dl_row = QHBoxLayout()
        self.dl_check = QCheckBox("Limit Download")
        self.dl_check.setChecked(True)
        self.dl_spin = QSpinBox()
        self.dl_spin.setRange(1, 100000)
        self.dl_spin.setValue(500)
        self.dl_unit = QComboBox()
        self.dl_unit.addItems(["KB/s", "MB/s"])
        dl_row.addWidget(self.dl_check)
        dl_row.addWidget(self.dl_spin)
        dl_row.addWidget(self.dl_unit)
        lay.addLayout(dl_row)

        ul_row = QHBoxLayout()
        self.ul_check = QCheckBox("Limit Upload")
        self.ul_spin = QSpinBox()
        self.ul_spin.setRange(1, 100000)
        self.ul_spin.setValue(100)
        self.ul_unit = QComboBox()
        self.ul_unit.addItems(["KB/s", "MB/s"])
        ul_row.addWidget(self.ul_check)
        ul_row.addWidget(self.ul_spin)
        ul_row.addWidget(self.ul_unit)
        lay.addLayout(ul_row)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("Apply Ceiling")
        self.apply_btn.setObjectName("PrimaryBtn")
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        self.clear_btn = QPushButton("Remove Ceiling")
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        btn_row.addWidget(self.apply_btn)
        btn_row.addWidget(self.clear_btn)
        lay.addLayout(btn_row)

        self.feedback_lbl = QLabel("")
        self.feedback_lbl.setStyleSheet(f"color: {PALETTE['ACCENT_CYAN']}; font-size: 11px;")
        lay.addWidget(self.feedback_lbl)
        return card

    def _build_graph_panel(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)

        header = QLabel("LIVE TELEMETRY (60s)")
        header.setStyleSheet(f"color: {PALETTE['TEXT_SECONDARY']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        lay.addWidget(header)

        self.graph = pg.PlotWidget(background=PALETTE["BG_SURFACE"])
        self.graph.showGrid(x=True, y=True, alpha=0.15)
        self.graph.setXRange(-GRAPH_WINDOW_SECONDS, 0)
        self.graph.enableAutoRange(axis="y", enable=True)
        self.graph.setMouseEnabled(x=False, y=False)

        self.dl_curve = self.graph.plot(pen=pg.mkPen(PALETTE["ACCENT_CYAN"], width=2), fillLevel=0.0, fillBrush=QColor(PALETTE["ACCENT_CYAN"]).getRgb()[:3] + (40,))
        self.ul_curve = self.graph.plot(pen=pg.mkPen(PALETTE["ACCENT_PURPLE"], width=1.8))
        lay.addWidget(self.graph)
        return card

    def _on_search_changed(self, text: str) -> None:
        self._filter_text = text.strip().lower()
        if self._last_stats is not None:
            self._render_process_table(self._last_stats)

    def _on_row_selected(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        row = self.table.row(selected[0])
        name_cell = self.table.item(row, 0)
        if name_cell is None:
            return

        self._selected_name = name_cell.text()
        self._selected_pid = name_cell.data(self.PID_ROLE)
        self.target_label.setText(f"{self._selected_name} (PID: {self._selected_pid})")

    def _to_kbps(self, spin: QSpinBox, combo: QComboBox) -> int:
        val = spin.value()
        return val * 1024 if combo.currentText() == "MB/s" else val

    def _on_apply_clicked(self) -> None:
        if not self._admin:
            self.feedback_lbl.setText("Error: Run Netora as Administrator.")
            return
        if self._selected_pid is None:
            self.feedback_lbl.setText("Please select a process from the table first.")
            return

        dl = self._to_kbps(self.dl_spin, self.dl_unit) if self.dl_check.isChecked() else None
        ul = self._to_kbps(self.ul_spin, self.ul_unit) if self.ul_check.isChecked() else None

        if dl is None and ul is None:
            self.feedback_lbl.setText("Select at least one ceiling (DL or UL).")
            return

        if self.qos.apply_limits(self._selected_pid, self._selected_name, dl, ul):
            msg = []
            if dl:
                msg.append(f"DL -> {format_bytes(dl * 1024)}")
            if ul:
                msg.append(f"UL -> {format_bytes(ul * 1024)}")
            self.feedback_lbl.setText(f"Capped {self._selected_name}: " + " | ".join(msg))
        else:
            self.feedback_lbl.setText(f"Failed: {self.qos.last_error or 'Unable to apply ceiling.'}")

    def _on_clear_clicked(self) -> None:
        self.qos.clear_limits()
        self.feedback_lbl.setText("Ceiling removed.")

    def on_stats_updated(self, stats: dict) -> None:
        self._last_stats = stats
        total_down = float(stats.get("total_down_bps", 0.0))
        total_up = float(stats.get("total_up_bps", 0.0))
        self.down_metric.setText(f"Total Down: {format_bytes(total_down)}")
        self.up_metric.setText(f"Total Up: {format_bytes(total_up)}")

        self._graph_buffer.push(total_down, total_up)
        xs, downs, ups = self._graph_buffer.series()
        self.dl_curve.setData(xs, downs)
        self.ul_curve.setData(xs, ups)

        self._render_process_table(stats)

    def _render_process_table(self, stats: dict) -> None:
        processes = list(stats.get("processes", []))
        if self._filter_text:
            processes = [p for p in processes if self._filter_text in str(p.get("name", "")).lower()]
        processes = [
            p for p in processes
            if float(p.get("down_bps", 0.0)) > 0.0
            or float(p.get("up_bps", 0.0)) > 0.0
            or p.get("limit_details")
        ]
        processes.sort(
            key=lambda p: (
                float(p.get("down_bps", 0.0)),
                float(p.get("up_bps", 0.0)),
            ),
            reverse=True,
        )

        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(processes))
            for row, p in enumerate(processes):
                name_item = QTableWidgetItem(str(p["name"]))
                name_item.setData(self.PID_ROLE, int(p["pid"]))

                pid_item = QTableWidgetItem(str(p["pid"]))
                pid_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

                down_item = QTableWidgetItem(format_bytes(float(p["down_bps"])))
                down_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                down_item.setForeground(QColor(PALETTE["ACCENT_CYAN"]))

                up_item = QTableWidgetItem(format_bytes(float(p["up_bps"])))
                up_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                up_item.setForeground(QColor(PALETTE["ACCENT_PURPLE"]))

                limits = p.get("limit_details", {})
                if limits:
                    lim_text = " | ".join(f"{'DL' if k=='download' else 'UL'}: {format_bytes(v*1024)}" for k, v in limits.items())
                    status_item = QTableWidgetItem(f"● {lim_text}")
                    status_item.setForeground(QColor(PALETTE["ACCENT_WARNING"]))
                else:
                    status_item = QTableWidgetItem("—")
                    status_item.setForeground(QColor(PALETTE["TEXT_SECONDARY"]))

                for col, it in enumerate((name_item, pid_item, down_item, up_item, status_item)):
                    self.table.setItem(row, col, it)

            if self._selected_pid is not None:
                for r in range(self.table.rowCount()):
                    it = self.table.item(r, 0)
                    if it and it.data(self.PID_ROLE) == self._selected_pid:
                        self.table.selectRow(r)
                        break
        finally:
            self.table.blockSignals(False)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        try:
            self.worker.stop()
            self.qos.close()
        except Exception:
            pass
        super().closeEvent(a0)


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    window = NetoraWindow()
    window.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())