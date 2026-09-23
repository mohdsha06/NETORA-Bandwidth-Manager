from __future__ import annotations

import math
from typing import Dict

PALETTE: Dict[str, str] = {
    "BG_BASE":         "#1E1E1E",
    "BG_SURFACE":      "#252525",
    "BG_ELEVATED":     "#2D2D2D",
    "BG_OVERLAY":      "#181818",

    "BORDER":          "#333333",
    "BORDER_STRONG":   "#444444",
    "DIVIDER":         "#2A2A2A",

    "ACCENT_BLUE":     "#0078D4",
    "ACCENT_CYAN":     "#60CDFF",
    "ACCENT_PURPLE":   "#B180F0",
    "ACCENT_WARNING":  "#FCE100",
    "ACCENT_DANGER":   "#F85149",

    "TEXT_PRIMARY":    "#FFFFFF",
    "TEXT_SECONDARY":  "#9E9E9E",
    "TEXT_DISABLED":   "#555555",
}

def format_bytes(bytes_per_sec: float) -> str:
    try:
        val = float(bytes_per_sec)
    except (TypeError, ValueError):
        return "0 KB/s"

    if math.isnan(val) or val <= 0:
        return "0 KB/s"

    if val < 1024 * 1024:
        kb = val / 1024.0
        return f"{kb:.0f} KB/s" if kb >= 10 else f"{kb:.1f} KB/s"
    else:
        mb = val / (1024.0 * 1024.0)
        return f"{mb:.2f} MB/s" if mb < 100 else f"{mb:.1f} MB/s"


NETORA_QSS = f"""
QMainWindow, QWidget {{
    background-color: {PALETTE['BG_BASE']};
    color: {PALETTE['TEXT_PRIMARY']};
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    font-size: 13px;
}}

QFrame#Card {{
    background-color: {PALETTE['BG_SURFACE']};
    border: 1px solid {PALETTE['BORDER']};
    border-radius: 8px;
}}

QTableWidget {{
    background-color: {PALETTE['BG_BASE']};
    alternate-background-color: {PALETTE['BG_SURFACE']};
    color: {PALETTE['TEXT_PRIMARY']};
    border: none;
    outline: 0;
    gridline-color: transparent;
}}

QTableWidget::item {{
    border: none;
    border-bottom: 1px solid {PALETTE['DIVIDER']};
    padding: 6px 10px;
    height: 30px;
}}

QTableWidget::item:selected {{
    background-color: {PALETTE['BG_ELEVATED']};
    color: {PALETTE['TEXT_PRIMARY']};
    border-left: 3px solid {PALETTE['ACCENT_CYAN']};
}}

QHeaderView::section {{
    background-color: {PALETTE['BG_BASE']};
    color: {PALETTE['TEXT_SECONDARY']};
    font-size: 11px;
    font-weight: 600;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid {PALETTE['BORDER']};
}}

QLineEdit, QSpinBox, QComboBox {{
    background-color: {PALETTE['BG_SURFACE']};
    color: {PALETTE['TEXT_PRIMARY']};
    border: 1px solid {PALETTE['BORDER']};
    border-radius: 6px;
    padding: 6px 10px;
}}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {PALETTE['ACCENT_CYAN']};
}}

QPushButton {{
    background-color: {PALETTE['BG_ELEVATED']};
    color: {PALETTE['TEXT_PRIMARY']};
    border: 1px solid {PALETTE['BORDER']};
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: #383838;
    border-color: {PALETTE['BORDER_STRONG']};
}}

QPushButton#PrimaryBtn {{
    background-color: {PALETTE['ACCENT_BLUE']};
    color: #FFFFFF;
    border: none;
}}

QPushButton#PrimaryBtn:hover {{
    background-color: #0086F0;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {PALETTE['BORDER']};
    border-radius: 3px;
    min-height: 25px;
}}
QScrollBar::handle:vertical:hover {{
    background: {PALETTE['BORDER_STRONG']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""

def apply_theme(app) -> None:
    app.setStyleSheet(NETORA_QSS)
