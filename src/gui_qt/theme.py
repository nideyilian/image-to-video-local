#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Qt 主题定义（浅色参考图风格）"""

PALETTE = {
    "bg": "#E7E8ED",
    "panel": "#F4F5F8",
    "panel_alt": "#ECEEF2",
    "border": "#B7BCC6",
    "divider": "#CFD3DA",
    "text": "#2D3440",
    "text_secondary": "#555F6E",
    "text_muted": "#7A8493",
    "accent": "#20A4E6",
    "accent_hover": "#3DB2ED",
    "danger": "#EF4444",
    "warning": "#F59E0B",
    "success": "#10B981",
}


def build_stylesheet() -> str:
    c = PALETTE
    return f"""
QWidget {{
    background: {c["bg"]};
    color: {c["text"]};
    font-family: "Segoe UI";
    font-size: 12px;
}}
QLabel, QCheckBox {{
    background: transparent;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {c["border"]};
    border-radius: 3px;
    background: {c["panel"]};
}}
QCheckBox::indicator:checked {{
    border: 1px solid {c["accent"]};
    background: {c["accent"]};
}}
QCheckBox::indicator:unchecked {{
    border: 1px solid {c["border"]};
    background: {c["panel"]};
}}
QFrame#TopBar, QFrame#Panel, QFrame#BottomPanel {{
    background: {c["panel_alt"]};
    border: 1px solid {c["border"]};
    border-radius: 10px;
}}
QFrame#Card {{
    background: {c["panel"]};
    border: 1px solid {c["border"]};
    border-radius: 10px;
}}
QLabel#Title {{
    font-size: 14px;
    font-weight: 700;
}}
QLabel#SecondaryText {{
    color: {c["text_secondary"]};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {c["panel"]};
    border: 1px solid {c["border"]};
    border-radius: 4px;
    min-height: 26px;
    padding: 1px 6px;
}}
QPushButton {{
    background: {c["panel"]};
    border: 1px solid {c["border"]};
    border-radius: 6px;
    min-height: 28px;
    padding: 0 10px;
}}
QPushButton:hover {{
    background: #D9E6F3;
}}
QPushButton#PrimaryButton {{
    background: {c["accent"]};
    border: 1px solid {c["accent"]};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{
    background: {c["accent_hover"]};
}}
QTabWidget::pane {{
    border: 1px solid {c["border"]};
    border-radius: 6px;
    background: {c["panel_alt"]};
    top: -1px;
}}
QTabBar::tab {{
    background: {c["panel"]};
    border: 1px solid {c["border"]};
    padding: 6px 10px;
    margin-right: 4px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    color: {c["text_secondary"]};
}}
QTabBar::tab:selected {{
    background: #DDE8F5;
    color: #1F5E93;
}}
QProgressBar {{
    border: 1px solid {c["border"]};
    border-radius: 4px;
    background: {c["panel"]};
    min-height: 10px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: #2FB36D;
    border-radius: 3px;
}}
QGroupBox {{
    border: 1px solid {c["border"]};
    border-radius: 4px;
    margin-top: 10px;
    background: {c["panel"]};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {c["text_secondary"]};
    background: transparent;
}}
"""
