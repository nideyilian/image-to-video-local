#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import random
import re
import copy
import sys
import tempfile
import time
import uuid
from base64 import b64decode, b64encode
from typing import Any, Dict, List

import cv2
import numpy as np
from PySide6.QtCore import Qt, QProcess, QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.utils.transition_constants import (
    GUI_TRANSITIONS,
    DEFAULT_ENABLED_TRANSITIONS,
    TRANSITION_DESCRIPTIONS,
)
from src.utils.timeline import timeline_slot_count
from src.core.transition_engine import get_turbo_transition_engine

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except Exception:
    QAudioOutput = None
    QMediaPlayer = None


DEFAULT_VIDEO_EFFECTS = [
    "心跳跳动",
    "反复缩放",
    "轻微摇摆",
    "左右晃动",
    "上下浮动",
    "镜头呼吸",
    "脉冲放大",
    "旋转摆动",
    "旋转呼吸",
    "摇摆推拉",
    "圆周漂移",
    "螺旋摆动",
    "双轴呼吸",
    "心跳摇摆",
    "波浪平移",
    "8字漂移",
    "径向脉冲旋转",
    "镜头抖动呼吸",
    "反向双旋",
    "呼吸变焦扫光",
    "旋摆模糊脉冲",
    "透视呼吸摆动",
    "涡旋推拉",
    "变焦摇移",
    "旋转漂移闪动",
    "双频摆动",
    "环形巡航",
    "呼吸鱼眼旋摆",
    "水波扭曲",
    "漩涡旋转",
    "鱼眼镜头",
    "故障抖动",
    "镜像扫光",
    "呼吸模糊",
    "径向拉伸",
    "边缘闪烁",
    "透视俯仰",
    "滚动快门",
    "灵魂出窍",
]

DEFAULT_RESOLUTION_PRESETS = [
    "1280x720",
    "1920x1080",
    "2560x1440",
    "3840x2160",
    "1080x1920",
    "720x1280",
    "1080x1080",
]

TRANSITION_GROUPS = {
    "基础转场": ["淡入淡出", "左右滑动", "上下滑动", "交叉溶解", "缩放过渡", "圆形扩展"],
    "纹理与几何": ["百叶窗", "棋盘格", "像素化", "方块过渡", "对角擦除", "门式打开"],
    "动感冲击": ["旋转变换", "波浪", "颜色混合", "放大冲击", "缩小爆炸", "旋转放大", "弹性缩放", "3D翻转", "推入效果", "闪光过渡", "碎片飞散"],
    "高级水印转场": ["光晕扩散", "径向旋切", "漩涡扭曲", "菱形开幕", "镜头虚焦", "纵向拉幕", "横向拉幕", "液态融合", "流光擦拭", "时钟扫描"],
}

VIDEO_EFFECT_GROUPS = {
    "基础单图特效": ["心跳跳动", "反复缩放", "轻微摇摆", "左右晃动", "上下浮动", "镜头呼吸", "脉冲放大", "旋转摆动"],
    "复合循环特效A": ["旋转呼吸", "摇摆推拉", "圆周漂移", "螺旋摆动", "双轴呼吸", "心跳摇摆", "波浪平移", "8字漂移", "径向脉冲旋转", "镜头抖动呼吸"],
    "复合循环特效B": ["反向双旋", "呼吸变焦扫光", "旋摆模糊脉冲", "透视呼吸摆动", "涡旋推拉", "变焦摇移", "旋转漂移闪动", "双频摆动", "环形巡航", "呼吸鱼眼旋摆"],
    "高级镜头风格": ["水波扭曲", "漩涡旋转", "鱼眼镜头", "故障抖动", "镜像扫光", "呼吸模糊", "径向拉伸", "边缘闪烁", "透视俯仰", "滚动快门"],
    "灵魂特效": ["灵魂出窍"],
}

LIGHT_THEME_QSS = """
QMainWindow, QWidget {
    background: #f5f6f8;
    color: #1f2329;
    font-size: 12px;
}
QFrame#TopBar, QFrame#Panel, QFrame#Card, QFrame#BottomPanel {
    background: #f8f9fb;
    border: 1px solid #d8dce3;
    border-radius: 8px;
}
QLabel#SecondaryText { color: #5f6b7a; }
QLabel#Title { color: #ffffff; font-weight: 600; }
QLabel#PreviewSurface {
    border: 1px solid #b7bcc6;
    border-radius: 6px;
    background: #b8bbc2;
    color: #ffffff;
}
QPushButton {
    background: #f3f5f8;
    color: #1f2329;
    border: 1px solid #cfd5de;
    border-radius: 6px;
    padding: 4px 10px;
}
QPushButton:hover { background: #e9edf4; }
QPushButton:pressed { background: #dde3ee; }
QPushButton#PrimaryButton {
    background: #2b8cff;
    color: #ffffff;
    border: 1px solid #2b8cff;
}
QPushButton#PrimaryButton:hover { background: #4e9eff; }
QPushButton#PrimaryButton:pressed { background: #1f79ea; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    color: #1f2329;
    border: 1px solid #cfd5de;
    border-radius: 6px;
    padding: 3px 6px;
}
QComboBox QAbstractItemView, QListWidget, QMenu {
    background: #ffffff;
    color: #1f2329;
    border: 1px solid #cfd5de;
}
QTabWidget::pane {
    border: 1px solid #d8dce3;
    border-radius: 6px;
    top: -1px;
}
QTabBar::tab {
    background: #edf1f7;
    color: #334155;
    border: 1px solid #d1d8e3;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 5px 10px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #111827;
}
QProgressBar {
    border: 1px solid #cfd5de;
    border-radius: 5px;
    background: #eef2f8;
    text-align: center;
}
QProgressBar::chunk { background: #2b8cff; border-radius: 4px; }
QSlider::groove:horizontal { height: 6px; background: #d6dce8; border-radius: 3px; }
QSlider::handle:horizontal {
    width: 12px;
    margin: -4px 0;
    border-radius: 6px;
    background: #2b8cff;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #9aa7bb;
    border-radius: 3px;
    background: #ffffff;
}
QCheckBox::indicator:checked { background: #2b8cff; border-color: #2b8cff; }
QScrollBar:vertical, QScrollBar:horizontal {
    background: transparent;
    border: none;
    margin: 0;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #c4ccda;
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {
    border: none;
    background: transparent;
}
"""

DARK_THEME_QSS = """
QMainWindow, QWidget {
    background: #1f2128;
    color: #d4d7de;
    font-size: 12px;
}
QFrame#TopBar, QFrame#Panel, QFrame#Card, QFrame#BottomPanel {
    background: #252831;
    border: 1px solid #343945;
    border-radius: 8px;
}
QLabel#SecondaryText { color: #8f97a6; }
QLabel#Title { color: #e5e7eb; font-weight: 600; }
QLabel#PreviewSurface {
    border: 1px solid #454b59;
    border-radius: 6px;
    background: #3a3f4b;
    color: #f3f4f6;
}
QPushButton {
    background: #2a2e38;
    color: #d4d7de;
    border: 1px solid #3a4050;
    border-radius: 6px;
    padding: 4px 10px;
}
QPushButton:hover { background: #323746; border-color: #4a5263; }
QPushButton:pressed { background: #242936; }
QPushButton#PrimaryButton {
    background: #3b82f6;
    color: #ffffff;
    border: 1px solid #3b82f6;
}
QPushButton#PrimaryButton:hover { background: #4a8df6; }
QPushButton#PrimaryButton:pressed { background: #2f72df; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #20242d;
    color: #d4d7de;
    border: 1px solid #3c4252;
    border-radius: 6px;
    padding: 3px 6px;
    selection-background-color: #3b82f6;
}
QComboBox QAbstractItemView, QListWidget, QMenu {
    background: #252a34;
    color: #d4d7de;
    border: 1px solid #3c4252;
}
QTabWidget::pane {
    border: 1px solid #343945;
    border-radius: 6px;
    top: -1px;
}
QTabBar::tab {
    background: #2a2e38;
    color: #aeb6c5;
    border: 1px solid #3b4150;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 5px 10px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #343a46;
    color: #e5e7eb;
}
QProgressBar {
    border: 1px solid #3a4050;
    border-radius: 5px;
    background: #232730;
    color: #c9ced8;
    text-align: center;
}
QProgressBar::chunk { background: #3b82f6; border-radius: 4px; }
QSlider::groove:horizontal { height: 6px; background: #3a4050; border-radius: 3px; }
QSlider::handle:horizontal {
    width: 12px;
    margin: -4px 0;
    border-radius: 6px;
    background: #3b82f6;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #566074;
    border-radius: 3px;
    background: #1f2430;
}
QCheckBox::indicator:checked { background: #3b82f6; border-color: #3b82f6; }
QScrollBar:vertical, QScrollBar:horizontal {
    background: transparent;
    border: none;
    margin: 0;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #4d5566;
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {
    border: none;
    background: transparent;
}
"""


class PreviewClickableLabel(QLabel):
    """可点击的预览标签：左键单击触发播放/暂停切换。"""

    def __init__(self, on_click, text: str = "", parent=None, on_enter=None):
        super().__init__(text, parent)
        self._on_click = on_click
        self._on_enter = on_enter

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and callable(self._on_click):
            self._on_click()
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event):
        if callable(self._on_enter):
            self._on_enter()
        super().enterEvent(event)


class QtMainWindow(QMainWindow):
    """PySide6 主窗口（阶段2：配置与事件桥接）"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("图转视频极速版 - 本地版")
        self.resize(1400, 900)
        self.setMinimumSize(1024, 640)

        self.config_file = os.path.join(os.getcwd(), "img2video_config.json")
        self.ui_state_file = os.path.join(os.getcwd(), "img2video_qt_ui_state.json")
        self.enabled_transitions: List[str] = GUI_TRANSITIONS.copy()
        self.enabled_video_effects: List[str] = DEFAULT_VIDEO_EFFECTS.copy()
        self._preview_anim_timer = QTimer(self)
        self._preview_anim_timer.timeout.connect(self._animate_preview)
        self._preview_phase = 0.0
        self._preview_playing = False
        self._preview_frames: List[QPixmap] = []
        self._preview_frame_index = 0
        self._preview_frame_tick = 0
        self._preview_total_tick = 0
        self._preview_cache_key = ""
        self._preview_transition_engine = get_turbo_transition_engine()
        self._preview_transition_cache: Dict[str, List[QPixmap]] = {}
        self._legacy_effect_adapter = None
        self._preview_error_reported = False
        self._preview_stale = False
        self._preview_has_rendered = False
        self._preview_hint_shown_once = False
        self._preview_audio_player = None
        self._preview_audio_output = None
        self._preview_audio_source = ""
        self._preview_bgm_pool: List[str] = []
        self._preview_asset_cache: Dict[str, np.ndarray] = {}
        self._preview_video_wm_cache: Dict[str, Dict[str, Any]] = {}
        self._preview_frame_bgr_cache: Dict[str, np.ndarray] = {}
        self._preview_selected_transition = ""
        self._preview_selected_effect = ""
        self._preview_selected_bgm = ""
        self._preview_selected_video_watermark = ""
        self._preview_selected_image_watermarks: Dict[str, str] = {}
        self._preview_scrubbing = False
        self._preview_scrub_restore_playing = False
        self._dark_theme_enabled = False
        self.tab_contexts: List[Dict[str, Any]] = []
        self._active_tab_index = -1
        self._last_splitter_mode = ""
        cpu_count = max(1, int(os.cpu_count() or 1))
        # 批量任务并发上限：优先稳定性，避免多标签同时导出导致资源争用。
        if cpu_count <= 6:
            self._batch_running_limit = 1
        elif cpu_count <= 12:
            self._batch_running_limit = 2
        else:
            self._batch_running_limit = 3
        self._batch_queue: List[int] = []
        self._batch_expected_total = 0
        self._batch_started_total = 0
        self._batch_skipped_tabs: List[int] = []

        self._build_ui()
        self._apply_adaptive_layout()
        self._apply_theme()
        self.load_config()
        self._load_ui_state()
        self._apply_responsive_rules(self.width())

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 6, 8, 6)
        root_layout.setSpacing(6)
        root_layout.addWidget(self._build_top_bar_container())

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._add_tab("标签页 1", self.config_file)
        tab_bar = self.tabs.tabBar()
        tab_bar.setContextMenuPolicy(Qt.CustomContextMenu)
        tab_bar.customContextMenuRequested.connect(self._on_tab_context_menu_requested)
        root_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

    def _build_top_bar_container(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bar = self._build_top_bar()
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        scroll.setWidget(bar)
        return scroll

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self.theme_toggle_btn = QPushButton("切换深色")
        self.theme_toggle_btn.clicked.connect(self._toggle_theme)
        layout.addWidget(self.theme_toggle_btn)

        self.batch_btn = QPushButton("批量处理")
        self.batch_btn.setObjectName("PrimaryButton")
        self.batch_btn.clicked.connect(self.start_batch_processing)
        layout.addWidget(self.batch_btn)

        self.open_output_btn = QPushButton("打开输出")
        self.open_output_btn.clicked.connect(self._open_output_dir)
        layout.addWidget(self.open_output_btn)

        self.save_config_btn = QPushButton("保存配置")
        self.save_config_btn.clicked.connect(self.save_config)
        layout.addWidget(self.save_config_btn)

        self.reload_btn = QPushButton("重载配置")
        self.reload_btn.clicked.connect(self.load_config)
        layout.addWidget(self.reload_btn)

        self.perf_btn = QPushButton("性能统计")
        self.perf_btn.clicked.connect(self._show_performance_stats)
        layout.addWidget(self.perf_btn)

        self.memory_btn = QPushButton("内存优化")
        self.memory_btn.clicked.connect(self._optimize_memory)
        layout.addWidget(self.memory_btn)

        self.status_hint_label = QLabel("✓ 就绪")
        self.status_hint_label.setObjectName("SecondaryText")
        layout.addWidget(self.status_hint_label)
        layout.addStretch(1)

        self.add_tab_btn = QPushButton("+添加")
        self.add_tab_btn.clicked.connect(lambda: self._add_tab())
        layout.addWidget(self.add_tab_btn)
        self.remove_tab_btn = QPushButton("×移除")
        self.remove_tab_btn.clicked.connect(self._remove_current_tab)
        layout.addWidget(self.remove_tab_btn)

        return bar

    def _build_single_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        content = QFrame()
        content.setObjectName("Panel")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(6)

        upper_split = QHBoxLayout()
        upper_split.setSpacing(8)
        self.left_sidebar = self._build_left_sidebar()
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.left_sidebar)
        splitter.addWidget(self._build_preview_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        self.main_splitter = splitter
        upper_split.addWidget(splitter, 1)
        content_layout.addLayout(upper_split, 1)

        content_layout.addWidget(self._build_bgm_watermark_panel())
        content_layout.addWidget(self._build_export_panel())
        self._wire_preview_dependencies()
        layout.addWidget(content)
        return tab

    def _build_left_sidebar(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumWidth(220)
        scroll.setMaximumWidth(700)
        scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(self._group_paths())
        v.addWidget(self._group_video_basic())
        v.addWidget(self._group_effects())
        v.addWidget(self._group_advanced())
        # 让转场模块吸收剩余高度，避免下方出现空白区域
        v.addWidget(self._group_transition(), 1)
        scroll.setWidget(host)
        return scroll

    def _group_paths(self) -> QGroupBox:
        box = QGroupBox("")
        box.setStyleSheet("QGroupBox { margin-top: 0px; }")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.input_dir_edit = QLineEdit()
        self.output_dir_edit = QLineEdit()
        in_btn = QPushButton("浏览")
        in_btn.clicked.connect(self._browse_input_dir)
        out_btn = QPushButton("浏览")
        out_btn.clicked.connect(self._browse_output_dir)
        grid.addWidget(QLabel("输入目录"), 0, 0)
        grid.addWidget(self.input_dir_edit, 0, 1)
        grid.addWidget(in_btn, 0, 2)
        grid.addWidget(QLabel("输出目录"), 1, 0)
        grid.addWidget(self.output_dir_edit, 1, 1)
        grid.addWidget(out_btn, 1, 2)
        grid.setColumnStretch(1, 1)
        self.input_dir_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.output_dir_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return box

    def _group_video_basic(self) -> QGroupBox:
        box = QGroupBox("")
        box.setStyleSheet("QGroupBox { margin-top: 0px; }")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        self.num_images_spin = QSpinBox()
        self.num_images_spin.setRange(1, 1000)
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.1, 120.0)
        self.duration_spin.setSingleStep(0.1)
        self.total_duration_spin = QDoubleSpinBox()
        self.total_duration_spin.setRange(0.0, 86400.0)
        self.total_duration_spin.setSingleStep(0.1)
        self.total_duration_spin.setSpecialValueText("自动")
        self.total_duration_spin.setToolTip("0 表示按图片数自动计算；设置后会循环图片直到达到总时长")
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 120)
        self.video_count_spin = QSpinBox()
        self.video_count_spin.setRange(1, 1000000)

        self.resolution_combo = QComboBox()
        self.resolution_combo.setEditable(True)
        self.resolution_combo.addItems(DEFAULT_RESOLUTION_PRESETS)
        self.keep_ratio_check = QCheckBox("保持比例")
        self.add_resolution_btn = QPushButton("+预设")
        self.add_resolution_btn.clicked.connect(self._add_resolution_preset)
        self.remove_resolution_btn = QPushButton("-预设")
        self.remove_resolution_btn.clicked.connect(self._remove_resolution_preset)

        self.video_format_combo = QComboBox()
        self.video_format_combo.addItems(["mp4", "mov", "avi"])
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["H264", "mp4v", "XVID", "MJPG"])
        self.bitrate_spin = QSpinBox()
        self.bitrate_spin.setRange(500, 100000)
        self.bitrate_spin.setValue(2000)
        self.bitrate_spin.setSingleStep(500)
        self.image_selection_combo = QComboBox()
        self.image_selection_combo.addItems(["随机选择", "按名称排序"])

        grid.addWidget(QLabel("图片数"), 0, 0)
        grid.addWidget(self.num_images_spin, 0, 1)
        grid.addWidget(QLabel("每图时长"), 0, 2)
        grid.addWidget(self.duration_spin, 0, 3)
        grid.addWidget(QLabel("FPS"), 0, 4)
        grid.addWidget(self.fps_spin, 0, 5)

        grid.addWidget(QLabel("分辨率"), 1, 0)
        grid.addWidget(self.resolution_combo, 1, 1, 1, 2)
        grid.addWidget(self.keep_ratio_check, 1, 3)
        grid.addWidget(self.add_resolution_btn, 1, 4)
        grid.addWidget(self.remove_resolution_btn, 1, 5)

        grid.addWidget(QLabel("视频数"), 2, 0)
        grid.addWidget(self.video_count_spin, 2, 1)

        grid.addWidget(QLabel("格式"), 2, 2)
        grid.addWidget(self.video_format_combo, 2, 3)
        grid.addWidget(QLabel("编码"), 2, 4)
        grid.addWidget(self.codec_combo, 2, 5)

        grid.addWidget(QLabel("图片"), 3, 0)
        grid.addWidget(self.image_selection_combo, 3, 1)
        grid.addWidget(QLabel("码率"), 3, 2)
        grid.addWidget(self.bitrate_spin, 3, 3)
        grid.addWidget(QLabel("总时长"), 3, 4)
        grid.addWidget(self.total_duration_spin, 3, 5)
        for col in (1, 3, 5):
            grid.setColumnStretch(col, 1)
        return box

    def _group_effects(self) -> QGroupBox:
        box = QGroupBox("")
        box.setStyleSheet("QGroupBox { margin-top: 0px; }")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        self.use_effect_check = QCheckBox("启用特效")
        self.random_effect_check = QCheckBox("随机特效")
        self.effect_combo = QComboBox()
        self.effect_combo.addItems(["无特效"] + DEFAULT_VIDEO_EFFECTS)
        self.effect_intensity_spin = QDoubleSpinBox()
        self.effect_intensity_spin.setRange(1.0, 9999.0)
        self.effect_intensity_spin.setValue(100.0)
        self.effect_speed_spin = QDoubleSpinBox()
        self.effect_speed_spin.setRange(0.01, 9999.0)
        self.effect_speed_spin.setValue(1.3)

        cfg_btn = QPushButton("配置随机...")
        cfg_btn.clicked.connect(self._configure_random_effects)

        grid.addWidget(self.use_effect_check, 0, 0)
        grid.addWidget(self.random_effect_check, 0, 1)
        grid.addWidget(cfg_btn, 0, 2, 1, 2)
        grid.addWidget(QLabel("特效"), 1, 0)
        grid.addWidget(self.effect_combo, 1, 1, 1, 3)
        grid.addWidget(QLabel("强度%"), 2, 0)
        grid.addWidget(self.effect_intensity_spin, 2, 1)
        grid.addWidget(QLabel("速度"), 2, 2)
        grid.addWidget(self.effect_speed_spin, 2, 3)
        for col in (1, 3):
            grid.setColumnStretch(col, 1)
        return box

    def _group_advanced(self) -> QGroupBox:
        box = QGroupBox("")
        box.setStyleSheet("QGroupBox { margin-top: 0px; }")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        self.use_date_prefix_check = QCheckBox("日期前缀")
        self.use_first_image_name_check = QCheckBox("使用首图名称")
        self.custom_prefix_edit = QLineEdit()
        self.custom_prefix_edit.setPlaceholderText("自定义前缀")

        self.use_first_image_name_check.stateChanged.connect(self._sync_prefix_state)

        grid.addWidget(self.use_date_prefix_check, 0, 0)
        grid.addWidget(self.use_first_image_name_check, 0, 1)
        grid.addWidget(self.custom_prefix_edit, 0, 2, 1, 2)

        for col in (1, 3):
            grid.setColumnStretch(col, 1)
        self._sync_prefix_state()
        return box

    def _group_transition(self) -> QGroupBox:
        box = QGroupBox("")
        box.setStyleSheet("QGroupBox { margin-top: 0px; }")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        self.use_transition_check = QCheckBox("启用转场")
        self.random_transition_check = QCheckBox("随机")
        self.transition_combo = QComboBox()
        self.transition_combo.addItems(GUI_TRANSITIONS)
        cfg_btn = QPushButton("配置随机...")
        cfg_btn.clicked.connect(self._configure_random_transitions)
        grid.addWidget(self.use_transition_check, 0, 0)
        grid.addWidget(self.random_transition_check, 0, 1)
        grid.addWidget(QLabel("效果"), 0, 2)
        grid.addWidget(self.transition_combo, 0, 3)
        grid.addWidget(cfg_btn, 0, 4)
        grid.setColumnStretch(3, 1)
        return box

    def _build_preview_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Card")
        v = QVBoxLayout(panel)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        title = QLabel("预览窗口")
        title.setObjectName("SecondaryText")
        title.hide()
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        self.preview_play_btn = QPushButton("播放预览")
        self.preview_play_btn.clicked.connect(self._start_preview_playback)
        self.preview_pause_btn = QPushButton("暂停预览")
        self.preview_pause_btn.clicked.connect(self._pause_preview_playback)
        self.preview_pause_btn.setEnabled(False)
        self.preview_play_btn.hide()
        self.preview_pause_btn.hide()
        self.preview_random_btn = QPushButton("随机参数")
        self.preview_random_btn.clicked.connect(self._randomize_preview_parameters)
        controls.addWidget(self.preview_play_btn)
        controls.addWidget(self.preview_pause_btn)
        controls.addWidget(self.preview_random_btn)
        controls.addStretch(1)
        v.addLayout(controls)
        self.preview_label = PreviewClickableLabel(
            self._toggle_preview_playback,
            "预览窗口",
            on_enter=self._show_preview_discovery_hint_once,
        )
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setObjectName("Title")
        self.preview_label.setMinimumHeight(0)
        self.preview_label.setMinimumWidth(240)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setCursor(Qt.PointingHandCursor)
        self.preview_label.setToolTip("单击预览窗口：播放/暂停")
        self.preview_label.setFrameStyle(QFrame.Box)
        self.preview_label.setObjectName("PreviewSurface")
        self.preview_label.setText("预览窗口\n单击预览窗口：播放/暂停")
        v.addWidget(self.preview_label, 1)
        timeline_row = QHBoxLayout()
        timeline_row.setContentsMargins(0, 0, 0, 0)
        timeline_row.setSpacing(6)
        timeline_row.addWidget(QLabel("时间轴"), 0)
        self.preview_timeline_slider = QSlider(Qt.Horizontal)
        self.preview_timeline_slider.setRange(0, 1000)
        self.preview_timeline_slider.setValue(0)
        self.preview_timeline_slider.sliderPressed.connect(self._on_preview_timeline_pressed)
        self.preview_timeline_slider.sliderReleased.connect(self._on_preview_timeline_released)
        self.preview_timeline_slider.valueChanged.connect(self._on_preview_timeline_changed)
        self.preview_timecode_label = QLabel("00:00.0 / 00:00.0")
        self.preview_timecode_label.setMinimumWidth(140)
        timeline_row.addWidget(self.preview_timeline_slider, 1)
        timeline_row.addWidget(self.preview_timecode_label, 0)
        v.addLayout(timeline_row)
        return panel

    def _apply_adaptive_layout(self) -> None:
        """应用自适应布局：避免挤压，也避免无效留白。"""
        for layout in self.findChildren(QGridLayout):
            layout.setHorizontalSpacing(6)
            layout.setVerticalSpacing(6)
            layout.setContentsMargins(6, 6, 6, 6)

        for layout in self.findChildren(QHBoxLayout):
            layout.setSpacing(6)

        for layout in self.findChildren(QVBoxLayout):
            layout.setSpacing(6)

        for widget in self.findChildren(QLineEdit):
            widget.setMinimumWidth(96)
            widget.setMaximumWidth(16777215)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for widget in self.findChildren(QComboBox):
            widget.setMinimumWidth(88)
            widget.setMaximumWidth(16777215)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for widget in self.findChildren(QSpinBox):
            widget.setMinimumWidth(72)
            widget.setMaximumWidth(16777215)
            widget.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
            widget.setButtonSymbols(QAbstractSpinBox.NoButtons)
        for widget in self.findChildren(QDoubleSpinBox):
            widget.setMinimumWidth(72)
            widget.setMaximumWidth(16777215)
            widget.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
            widget.setButtonSymbols(QAbstractSpinBox.NoButtons)
        for widget in self.findChildren(QPushButton):
            widget.setMinimumWidth(max(56, widget.sizeHint().width() - 12))
            widget.setMaximumWidth(16777215)
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        for widget in self.findChildren(QProgressBar):
            widget.setMinimumWidth(140)
            widget.setMaximumWidth(16777215)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # 左侧栏内组件改为自适应：允许随侧栏宽度变化伸缩
        if hasattr(self, "left_sidebar") and self.left_sidebar:
            for widget in self.left_sidebar.findChildren(QLineEdit):
                widget.setMaximumWidth(16777215)
                widget.setMinimumWidth(72)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            for widget in self.left_sidebar.findChildren(QComboBox):
                widget.setMaximumWidth(16777215)
                widget.setMinimumWidth(68)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            for widget in self.left_sidebar.findChildren(QSpinBox):
                widget.setMaximumWidth(16777215)
                widget.setMinimumWidth(56)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            for widget in self.left_sidebar.findChildren(QDoubleSpinBox):
                widget.setMaximumWidth(16777215)
                widget.setMinimumWidth(56)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _build_bgm_watermark_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("BottomPanel")
        root_layout = QVBoxLayout(panel)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        # 模块1：BGM
        bgm_box = QGroupBox("")
        bgm_box.setStyleSheet("QGroupBox { margin-top: 0px; }")
        bgm_grid = QGridLayout(bgm_box)
        bgm_grid.setContentsMargins(8, 8, 8, 8)
        bgm_grid.setHorizontalSpacing(8)
        bgm_grid.setVerticalSpacing(6)
        self.use_bgm_check = QCheckBox("启用BGM")
        self.random_bgm_check = QCheckBox("随机")
        self.loop_bgm_check = QCheckBox("循环")
        self.bgm_dir_edit = QLineEdit()
        self.bgm_dir_edit.setMaximumWidth(460)
        self.bgm_volume_spin = QDoubleSpinBox()
        self.bgm_volume_spin.setRange(0.1, 1.0)
        self.bgm_volume_spin.setSingleStep(0.1)
        self.bgm_volume_spin.setValue(0.5)
        self.watermark_audio_combo = QComboBox()
        self.watermark_audio_combo.addItems(["使用BGM", "使用水印", "两者混合", "静音"])
        bgm_btn = QPushButton("浏览")
        bgm_btn.clicked.connect(self._browse_bgm_dir)
        bgm_grid.addWidget(self.use_bgm_check, 0, 0)
        bgm_grid.addWidget(self.random_bgm_check, 0, 1)
        bgm_grid.addWidget(self.loop_bgm_check, 0, 2)
        bgm_grid.addWidget(QLabel("目录"), 0, 3)
        bgm_grid.addWidget(self.bgm_dir_edit, 0, 4, 1, 2)
        bgm_grid.addWidget(bgm_btn, 0, 6)
        bgm_grid.addWidget(QLabel("音量%"), 0, 7)
        bgm_grid.addWidget(self.bgm_volume_spin, 0, 8)
        bgm_grid.addWidget(QLabel("声音"), 0, 9)
        bgm_grid.addWidget(self.watermark_audio_combo, 0, 10)
        bgm_grid.setColumnStretch(4, 2)
        bgm_grid.setColumnStretch(10, 1)
        root_layout.addWidget(bgm_box)

        # 模块2：视频水印
        video_wm_box = QGroupBox("")
        video_wm_box.setStyleSheet("QGroupBox { margin-top: 0px; }")
        wm_grid = QGridLayout(video_wm_box)
        wm_grid.setContentsMargins(8, 8, 8, 8)
        wm_grid.setHorizontalSpacing(8)
        wm_grid.setVerticalSpacing(6)
        self.use_watermark_check = QCheckBox("启用视频水印")
        self.watermark_mode_combo = QComboBox()
        self.watermark_mode_combo.addItems(["单文件", "文件夹"])
        self.watermark_match_method_combo = QComboBox()
        self.watermark_match_method_combo.addItems(["循环", "拉伸", "单次"])
        self.watermark_size_mode_combo = QComboBox()
        self.watermark_size_mode_combo.addItems(["固定比例", "自适应覆盖", "完全覆盖"])
        self.watermark_path_edit = QLineEdit()
        wm_btn = QPushButton("浏览")
        wm_btn.clicked.connect(self._browse_watermark_path)
        self.watermark_blend_combo = QComboBox()
        self.watermark_blend_combo.addItems(["正常", "滤色", "叠加", "正片叠底", "变亮", "变暗", "相加"])
        self.use_watermark_check.stateChanged.connect(self._sync_watermark_advanced_state)
        self.watermark_mode_combo.currentTextChanged.connect(self._sync_watermark_advanced_state)

        wm_grid.addWidget(self.use_watermark_check, 0, 0)
        wm_grid.addWidget(QLabel("模式"), 0, 1)
        wm_grid.addWidget(self.watermark_mode_combo, 0, 2)
        wm_grid.addWidget(QLabel("路径"), 0, 3)
        wm_grid.addWidget(self.watermark_path_edit, 0, 4, 1, 2)
        wm_grid.addWidget(wm_btn, 0, 6)
        wm_grid.addWidget(QLabel("匹配"), 0, 7)
        wm_grid.addWidget(self.watermark_match_method_combo, 0, 8)
        wm_grid.addWidget(QLabel("大小模式"), 0, 9)
        wm_grid.addWidget(self.watermark_size_mode_combo, 0, 10)
        wm_grid.addWidget(QLabel("混合"), 0, 11)
        wm_grid.addWidget(self.watermark_blend_combo, 0, 12)
        wm_grid.setColumnStretch(4, 2)
        wm_grid.setColumnStretch(10, 1)
        wm_grid.setColumnStretch(12, 1)
        root_layout.addWidget(video_wm_box)

        # 模块3：图片水印
        image_wm_box = QGroupBox("")
        image_wm_box.setStyleSheet("QGroupBox { margin-top: 0px; }")
        image_wm_layout = QVBoxLayout(image_wm_box)
        image_wm_layout.setContentsMargins(8, 8, 8, 8)
        image_wm_layout.setSpacing(6)
        self.use_image_watermark_check = QCheckBox("启用图片水印")
        self.use_image_watermark_check.setChecked(True)
        self.use_image_watermark_check.stateChanged.connect(self._sync_image_watermark_state)
        self.add_layer_btn = QPushButton("添加图层")
        self.add_layer_btn.clicked.connect(self._add_watermark_layer_row)
        image_wm_top = QHBoxLayout()
        image_wm_top.setContentsMargins(0, 0, 0, 0)
        image_wm_top.setSpacing(6)
        image_wm_top.addWidget(self.use_image_watermark_check, 0)
        image_wm_top.addStretch(1)
        image_wm_top.addWidget(self.add_layer_btn, 0)
        self.layer_rows_host = QWidget()
        self.layer_rows_layout = QVBoxLayout(self.layer_rows_host)
        self.layer_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.layer_rows_layout.setSpacing(4)
        image_wm_layout.addLayout(image_wm_top, 0)
        image_wm_layout.addWidget(self.layer_rows_host, 1)
        root_layout.addWidget(image_wm_box)

        self._add_watermark_layer_row()
        self._sync_watermark_advanced_state()
        self._sync_image_watermark_state()
        return panel

    def _build_export_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("BottomPanel")
        grid = QGridLayout(panel)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        self.start_btn = QPushButton("开始处理")
        self.start_btn.setObjectName("PrimaryButton")
        self.start_btn.clicked.connect(self.start_processing)
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.clicked.connect(self._toggle_pause_processing)
        self.pause_btn.setEnabled(False)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self._cancel_processing)
        self.cancel_btn.setEnabled(False)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(460)
        self.progress_label = QLabel("进度: 0%")
        self.progress_label.setFixedWidth(86)
        self.speed_label = QLabel("速度: 0.0 张/秒")
        self.speed_label.setFixedWidth(130)
        self.overall_label = QLabel("总进度: 0%")
        self.overall_label.setFixedWidth(96)
        self.status_label = QLabel("状态: 就绪")
        self.status_label.setFixedWidth(240)
        self.progress_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.speed_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.overall_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        sep1 = QLabel("|")
        sep2 = QLabel("|")
        sep3 = QLabel("|")
        for sep in (sep1, sep2, sep3):
            sep.setFixedWidth(10)
            sep.setObjectName("SecondaryText")
            sep.setAlignment(Qt.AlignCenter)

        grid.addWidget(self.start_btn, 0, 0)
        grid.addWidget(self.pause_btn, 0, 1)
        grid.addWidget(self.cancel_btn, 0, 2)
        grid.addWidget(self.progress_bar, 0, 3, 1, 3)
        grid.addWidget(self.progress_label, 0, 6)
        grid.addWidget(sep1, 0, 7)
        grid.addWidget(self.speed_label, 0, 8)
        grid.addWidget(sep2, 0, 9)
        grid.addWidget(self.overall_label, 0, 10)
        grid.addWidget(sep3, 0, 11)
        grid.addWidget(self.status_label, 0, 12)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(4, 1)
        grid.setColumnStretch(5, 1)
        grid.setColumnStretch(12, 1)
        return panel

    # ----- 多标签管理 -----
    def _build_tab_config_file(self) -> str:
        tab_id = str(uuid.uuid4())[:8]
        return os.path.join(os.getcwd(), f"img2video_qt_config_{tab_id}.json")

    def _capture_widget_refs(self) -> Dict[str, Any]:
        keys = [
            "input_dir_edit", "output_dir_edit", "num_images_spin", "duration_spin", "total_duration_spin", "fps_spin",
            "video_count_spin", "resolution_combo", "keep_ratio_check", "video_format_combo", "codec_combo",
            "add_resolution_btn", "remove_resolution_btn",
            "bitrate_spin", "image_selection_combo", "use_effect_check", "random_effect_check", "effect_combo",
            "effect_intensity_spin", "effect_speed_spin", "use_transition_check", "random_transition_check",
            "transition_combo", "preview_label", "preview_play_btn", "preview_pause_btn",
            "preview_random_btn", "preview_timeline_slider", "preview_timecode_label",
            "left_sidebar", "main_splitter",
            "use_bgm_check", "random_bgm_check", "loop_bgm_check",
            "bgm_dir_edit", "bgm_volume_spin", "use_watermark_check", "watermark_mode_combo",
            "watermark_path_edit", "watermark_blend_combo",
            "use_date_prefix_check", "use_first_image_name_check", "custom_prefix_edit",
            "watermark_match_method_combo", "watermark_audio_combo",
            "watermark_size_mode_combo", "use_image_watermark_check",
            "add_layer_btn", "layer_rows_host", "layer_rows_layout",
            "start_btn", "pause_btn", "cancel_btn",
            "progress_bar", "progress_label", "speed_label", "status_label", "overall_label",
        ]
        return {k: getattr(self, k) for k in keys if hasattr(self, k)}

    def _apply_widget_refs(self, refs: Dict[str, Any]) -> None:
        for k, v in refs.items():
            setattr(self, k, v)

    def _add_tab(self, title: str | None = None, config_file: str | None = None) -> None:
        prev_active = self._active_tab_index
        if prev_active >= 0:
            self._save_current_tab_context(prev_active)
        prev_context = self.tab_contexts[prev_active] if 0 <= prev_active < len(self.tab_contexts) else None
        prev_refs = prev_context.get("refs") if isinstance(prev_context, dict) else None
        tab_title = title or f"标签页 {self.tabs.count() + 1}"
        tab_widget = self._build_single_tab()
        new_refs = self._capture_widget_refs()
        index = self.tabs.addTab(tab_widget, tab_title)
        context = {
            "config_file": config_file or self._build_tab_config_file(),
            "enabled_transitions": GUI_TRANSITIONS.copy(),
            "enabled_video_effects": DEFAULT_VIDEO_EFFECTS.copy(),
            "config": {},
            "refs": new_refs,
        }
        context["config"] = self._read_json_dict(context["config_file"]) or self._default_config()
        self.tab_contexts.append(context)
        # 恢复到原活动标签的控件引用，避免 setCurrentIndex 触发保存时误把空白新页写回旧页配置。
        if prev_refs:
            self._apply_widget_refs(prev_refs)
            if prev_context:
                self.config_file = str(prev_context.get("config_file", self.config_file))
                self.enabled_transitions = list(prev_context.get("enabled_transitions", self.enabled_transitions))
                self.enabled_video_effects = list(prev_context.get("enabled_video_effects", self.enabled_video_effects))
        self.tabs.setCurrentIndex(index)
        # 兜底：若 currentChanged 未触发，主动切换一次上下文。
        if self._active_tab_index != index:
            self._on_tab_changed(index)

    def _remove_current_tab(self) -> None:
        idx = self.tabs.currentIndex()
        if idx < 0 or self.tabs.count() <= 1:
            return
        worker_state = self._get_tab_worker_state(idx)
        proc = worker_state.get("process")
        if isinstance(proc, QProcess) and proc.state() != QProcess.NotRunning:
            QMessageBox.warning(self, "提示", "该标签页任务仍在运行，无法移除")
            return
        self.tabs.removeTab(idx)
        self.tab_contexts.pop(idx)
        new_idx = max(0, idx - 1)
        self.tabs.setCurrentIndex(new_idx)

    def _save_current_tab_context(self, idx: int | None = None) -> None:
        if idx is None:
            idx = self._active_tab_index if self._active_tab_index >= 0 else self.tabs.currentIndex()
        if idx < 0 or idx >= len(self.tab_contexts):
            return
        context = self.tab_contexts[idx]
        context["enabled_transitions"] = self.enabled_transitions.copy()
        context["enabled_video_effects"] = self.enabled_video_effects.copy()
        target_config = str(context.get("config_file", "") or "").strip() or self._build_tab_config_file()
        context["config_file"] = target_config

        # 仅写入内存快照，避免标签切换时高频磁盘 IO 导致卡顿和状态串扰。
        try:
            context["config"] = self.collect_config()
        except Exception:
            context["config"] = context.get("config") or self._default_config()

    def _on_tab_changed(self, index: int) -> None:
        if index < 0 or index >= len(self.tab_contexts):
            return
        if self._active_tab_index >= 0 and self._active_tab_index < len(self.tab_contexts):
            self._save_current_tab_context(self._active_tab_index)
        context = self.tab_contexts[index]
        self._stop_preview_playback()
        self._apply_widget_refs(context["refs"])
        # 新增/复制标签页后，确保新控件也应用统一自适应规则，避免侧边栏宽度挤压导致滚动条出现。
        self._apply_adaptive_layout()
        self.config_file = context["config_file"]
        self.enabled_transitions = context.get("enabled_transitions", GUI_TRANSITIONS.copy())
        self.enabled_video_effects = context.get("enabled_video_effects", DEFAULT_VIDEO_EFFECTS.copy())
        cfg = context.get("config")
        if not isinstance(cfg, dict) or not cfg:
            cfg = self._read_json_dict(self.config_file) or self._default_config()
            context["config"] = cfg
        self.apply_config(cfg)
        self._apply_responsive_rules(self.width(), force=False)
        self._active_tab_index = index

    def _build_duplicated_tab_title(self, source_title: str) -> str:
        base = f"{str(source_title or '标签页').strip()} - 副本"
        candidate = base
        existing = {self.tabs.tabText(i) for i in range(self.tabs.count())}
        suffix = 2
        while candidate in existing:
            candidate = f"{base} {suffix}"
            suffix += 1
        return candidate

    def _duplicate_tab(self, source_index: int) -> None:
        if source_index < 0 or source_index >= len(self.tab_contexts):
            return
        if source_index == self.tabs.currentIndex():
            self._save_current_tab_context(source_index)

        source_ctx = self.tab_contexts[source_index]
        source_title = self.tabs.tabText(source_index)
        source_cfg_file = str(source_ctx.get("config_file", "") or "").strip()
        source_transitions = list(source_ctx.get("enabled_transitions", GUI_TRANSITIONS.copy()))
        source_effects = list(source_ctx.get("enabled_video_effects", DEFAULT_VIDEO_EFFECTS.copy()))

        new_cfg_file = self._build_tab_config_file()
        copied_cfg: Dict[str, Any] = self._default_config()
        try:
            source_cfg = source_ctx.get("config")
            if isinstance(source_cfg, dict) and source_cfg:
                copied_cfg = copy.deepcopy(source_cfg)
            elif source_cfg_file and os.path.exists(source_cfg_file):
                with open(source_cfg_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        copied_cfg = loaded
            copied_cfg["enabled_transitions"] = source_transitions.copy()
            copied_cfg["enabled_video_effects"] = source_effects.copy()
            with open(new_cfg_file, "w", encoding="utf-8") as f:
                json.dump(copied_cfg, f, ensure_ascii=False, indent=4)
        except Exception as exc:
            QMessageBox.warning(self, "复制失败", f"复制标签页配置失败：{exc}")
            return

        self._add_tab(title=self._build_duplicated_tab_title(source_title), config_file=new_cfg_file)
        new_idx = self.tabs.currentIndex()
        if 0 <= new_idx < len(self.tab_contexts):
            self.tab_contexts[new_idx]["enabled_transitions"] = source_transitions.copy()
            self.tab_contexts[new_idx]["enabled_video_effects"] = source_effects.copy()
            self.tab_contexts[new_idx]["config"] = copy.deepcopy(copied_cfg)
            source_refs = self.tab_contexts[source_index].get("refs", {})
            new_refs = self.tab_contexts[new_idx].get("refs", {})
            src_splitter = source_refs.get("main_splitter")
            dst_splitter = new_refs.get("main_splitter")
            try:
                if src_splitter is not None and dst_splitter is not None:
                    # 复制完整分栏状态（方向+比例+句柄位置），确保新旧标签布局完全一致。
                    state = bytes(src_splitter.saveState())
                    if state:
                        dst_splitter.restoreState(state)
                    else:
                        dst_splitter.setOrientation(src_splitter.orientation())
                        src_sizes = src_splitter.sizes()
                        if src_sizes:
                            dst_splitter.setSizes(src_sizes)
            except Exception:
                pass
            self.enabled_transitions = source_transitions.copy()
            self.enabled_video_effects = source_effects.copy()
        self._set_status(f"已复制标签页: {source_title}")

    def _rename_tab(self, tab_index: int) -> None:
        if tab_index < 0 or tab_index >= self.tabs.count():
            return
        old_title = self.tabs.tabText(tab_index).strip() or f"标签页 {tab_index + 1}"
        new_title, ok = QInputDialog.getText(self, "重命名标签页", "标签页名称：", QLineEdit.Normal, old_title)
        if not ok:
            return
        new_title = str(new_title or "").strip()
        if not new_title:
            QMessageBox.warning(self, "重命名失败", "标签页名称不能为空")
            return
        self.tabs.setTabText(tab_index, new_title)
        self._set_status(f"标签页已重命名为: {new_title}")

    def _on_tab_context_menu_requested(self, pos) -> None:
        tab_bar = self.tabs.tabBar()
        tab_index = tab_bar.tabAt(pos)
        if tab_index < 0:
            return

        menu = QMenu(self)
        copy_action = menu.addAction("复制")
        rename_action = menu.addAction("重命名")
        chosen = menu.exec(tab_bar.mapToGlobal(pos))
        if chosen is copy_action:
            self._duplicate_tab(tab_index)
        elif chosen is rename_action:
            self._rename_tab(tab_index)

    @staticmethod
    def _read_json_dict(path: str) -> Dict[str, Any]:
        try:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    @staticmethod
    def _write_json_dict(path: str, payload: Dict[str, Any]) -> bool:
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)
            return True
        except Exception:
            return False

    def _serialize_tabs_state(self) -> Dict[str, Any]:
        tabs_payload: List[Dict[str, Any]] = []
        for idx, context in enumerate(self.tab_contexts):
            cfg_file = str(context.get("config_file", "") or "").strip()
            cfg = context.get("config")
            if not isinstance(cfg, dict) or not cfg:
                cfg = self._read_json_dict(cfg_file) or self._default_config()
            refs = context.get("refs", {})
            splitter_state = ""
            splitter = refs.get("main_splitter") if isinstance(refs, dict) else None
            if splitter is not None:
                try:
                    splitter_state = b64encode(bytes(splitter.saveState())).decode("ascii")
                except Exception:
                    splitter_state = ""
            tabs_payload.append({
                "title": self.tabs.tabText(idx),
                "config_file": cfg_file,
                "config": cfg,
                "enabled_transitions": list(context.get("enabled_transitions", GUI_TRANSITIONS.copy())),
                "enabled_video_effects": list(context.get("enabled_video_effects", DEFAULT_VIDEO_EFFECTS.copy())),
                "splitter_state": splitter_state,
            })
        return {
            "current_tab_index": int(self.tabs.currentIndex()),
            "tabs": tabs_payload,
        }

    def _restore_tabs_state(self, state: Dict[str, Any]) -> None:
        tabs_payload = state.get("tabs", [])
        if not isinstance(tabs_payload, list) or not tabs_payload:
            return

        # 清空现有标签，按会话状态重建。
        self.tabs.clear()
        self.tab_contexts = []
        self._active_tab_index = -1

        for item in tabs_payload:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "") or "").strip() or f"标签页 {self.tabs.count() + 1}"
            cfg_file = str(item.get("config_file", "") or "").strip() or self._build_tab_config_file()
            cfg = item.get("config", {})
            if not isinstance(cfg, dict):
                cfg = self._default_config()
            self._write_json_dict(cfg_file, cfg)

            self._add_tab(title=title, config_file=cfg_file)
            new_idx = self.tabs.currentIndex()
            if 0 <= new_idx < len(self.tab_contexts):
                self.tab_contexts[new_idx]["config"] = copy.deepcopy(cfg)
                transitions = [t for t in item.get("enabled_transitions", []) if t in GUI_TRANSITIONS]
                effects = [e for e in item.get("enabled_video_effects", []) if str(e) != "无特效"]
                if transitions:
                    self.tab_contexts[new_idx]["enabled_transitions"] = transitions
                if effects:
                    self.tab_contexts[new_idx]["enabled_video_effects"] = effects
                self.enabled_transitions = self.tab_contexts[new_idx]["enabled_transitions"].copy()
                self.enabled_video_effects = self.tab_contexts[new_idx]["enabled_video_effects"].copy()

                splitter_state = str(item.get("splitter_state", "") or "")
                if splitter_state:
                    refs = self.tab_contexts[new_idx].get("refs", {})
                    splitter = refs.get("main_splitter") if isinstance(refs, dict) else None
                    if splitter is not None:
                        try:
                            splitter.restoreState(b64decode(splitter_state.encode("ascii")))
                        except Exception:
                            pass

        target_index = int(state.get("current_tab_index", 0) or 0)
        target_index = max(0, min(target_index, self.tabs.count() - 1))
        self.tabs.setCurrentIndex(target_index)
        if self._active_tab_index != target_index:
            self._on_tab_changed(target_index)

    def _apply_responsive_rules(self, view_width: int, force: bool = False) -> None:
        splitter = getattr(self, "main_splitter", None)
        if splitter is None:
            return
        mode = "vertical" if view_width < 1180 else "horizontal"
        if mode == "vertical":
            if force or self._last_splitter_mode != "vertical":
                splitter.setOrientation(Qt.Vertical)
                splitter.setSizes([max(300, int(view_width * 0.44)), max(320, int(view_width * 0.56))])
            self.left_sidebar.setMinimumWidth(0)
            self.preview_label.setMinimumWidth(0)
        else:
            if force or self._last_splitter_mode != "horizontal":
                splitter.setOrientation(Qt.Horizontal)
                splitter.setSizes([max(280, int(view_width * 0.34)), max(460, int(view_width * 0.66))])
            self.left_sidebar.setMinimumWidth(220)
            self.preview_label.setMinimumWidth(240)
        self._last_splitter_mode = mode

    # ----- 配置 -----
    def _default_config(self) -> Dict[str, Any]:
        return {
            "input_dir": "",
            "output_dir": "",
            "num_images": 1,
            "duration": 8.0,
            "total_duration": 0.0,
            "fps": 30,
            "video_count": 1,
            "video_format": "mp4",
            "resolution_preset": "1280x720",
            "resolution_presets": DEFAULT_RESOLUTION_PRESETS.copy(),
            "keep_aspect_ratio": True,
            "use_transition": True,
            "transition_type": GUI_TRANSITIONS[0] if GUI_TRANSITIONS else "淡入淡出",
            "random_transition": False,
            "enabled_transitions": GUI_TRANSITIONS.copy(),
            "use_video_effect": False,
            "video_effect_type": "无特效",
            "random_video_effect": False,
            "enabled_video_effects": DEFAULT_VIDEO_EFFECTS.copy(),
            "video_effect_intensity": 100.0,
            "video_effect_speed": 1.3,
            "use_bgm": False,
            "bgm_dir": "",
            "random_bgm": False,
            "bgm_volume": 0.5,
            "loop_bgm": False,
            "codec": "H264",
            "use_watermark": False,
            "watermark_type": "视频",
            "watermark_position": "中心",
            "watermark_match_method": "循环",
            "watermark_audio": "使用BGM",
            "watermark_size_mode": "自适应覆盖",
            "watermark_scale": 100.0,
            "use_image_watermark": False,
            "watermark_layers": [],
            "watermark_mode": "单文件",
            "watermark_path": "",
            "watermark_blend_mode": "正常",
            "use_date_prefix": True,
            "use_first_image_name": False,
            "custom_prefix": "video",
            "image_selection_mode": "随机选择",
            "bitrate": 2000,
            "_qt_watermark_defaults_v2": True,
        }

    def _read_existing_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_file):
            return {}
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def collect_config(self) -> Dict[str, Any]:
        # 保留旧配置中 Qt 尚未提供控件的字段，避免“功能看似失效（被重置）”。
        cfg = self._read_existing_config()
        if not cfg:
            cfg = self._default_config()
        cfg.update({
            "input_dir": self.input_dir_edit.text().strip(),
            "output_dir": self.output_dir_edit.text().strip(),
            "num_images": int(self.num_images_spin.value()),
            "duration": float(self.duration_spin.value()),
            "total_duration": float(self.total_duration_spin.value()),
            "fps": int(self.fps_spin.value()),
            "video_count": int(self.video_count_spin.value()),
            "video_format": self.video_format_combo.currentText(),
            "resolution_preset": self.resolution_combo.currentText().strip(),
            "resolution_presets": [self.resolution_combo.itemText(i) for i in range(self.resolution_combo.count())],
            "keep_aspect_ratio": self.keep_ratio_check.isChecked(),
            "use_transition": self.use_transition_check.isChecked(),
            "transition_type": self.transition_combo.currentText(),
            "random_transition": self.random_transition_check.isChecked(),
            "enabled_transitions": self.enabled_transitions.copy(),
            "use_video_effect": self.use_effect_check.isChecked(),
            "video_effect_type": self.effect_combo.currentText(),
            "random_video_effect": self.random_effect_check.isChecked(),
            "enabled_video_effects": self.enabled_video_effects.copy(),
            "video_effect_intensity": float(self.effect_intensity_spin.value()),
            "video_effect_speed": float(self.effect_speed_spin.value()),
            "use_bgm": self.use_bgm_check.isChecked(),
            "bgm_dir": self.bgm_dir_edit.text().strip(),
            "random_bgm": self.random_bgm_check.isChecked(),
            "bgm_volume": float(self.bgm_volume_spin.value()),
            "loop_bgm": self.loop_bgm_check.isChecked(),
            "codec": self.codec_combo.currentText(),
            "use_watermark": self.use_watermark_check.isChecked(),
            "watermark_mode": self.watermark_mode_combo.currentText(),
            "watermark_path": self.watermark_path_edit.text().strip(),
            "watermark_position": "中心",
            "watermark_match_method": self.watermark_match_method_combo.currentText(),
            "watermark_audio": self.watermark_audio_combo.currentText(),
            "watermark_size_mode": self.watermark_size_mode_combo.currentText(),
            "watermark_scale": 100.0,
            "use_image_watermark": self.use_image_watermark_check.isChecked(),
            "watermark_blend_mode": self.watermark_blend_combo.currentText(),
            "watermark_layers": self._collect_watermark_layers_from_ui(),
            "use_date_prefix": self.use_date_prefix_check.isChecked(),
            "use_first_image_name": self.use_first_image_name_check.isChecked(),
            "custom_prefix": self.custom_prefix_edit.text().strip() or "video",
            "image_selection_mode": self.image_selection_combo.currentText(),
            "bitrate": int(self.bitrate_spin.value()),
            "_qt_watermark_defaults_v2": True,
        })

        # 同步旧字段，兼容 Tk 配置读取
        w, h = self._parse_resolution(cfg["resolution_preset"])
        cfg["width"] = w
        cfg["height"] = h
        cfg["watermark_type"] = "视频"
        return cfg

    def apply_config(self, cfg: Dict[str, Any]) -> None:
        cfg = self._migrate_watermark_legacy_defaults(cfg)
        self.input_dir_edit.setText(str(cfg.get("input_dir", "")))
        self.output_dir_edit.setText(str(cfg.get("output_dir", "")))
        self.num_images_spin.setValue(int(cfg.get("num_images", 1)))
        self.duration_spin.setValue(float(cfg.get("duration", 8.0)))
        self.total_duration_spin.setValue(float(cfg.get("total_duration", 0.0)))
        self.fps_spin.setValue(int(cfg.get("fps", 30)))
        self.video_count_spin.setValue(int(cfg.get("video_count", 1)))
        self.video_format_combo.setCurrentText(str(cfg.get("video_format", "mp4")))

        presets = cfg.get("resolution_presets", [])
        if isinstance(presets, list) and presets:
            self.resolution_combo.clear()
            self.resolution_combo.addItems([str(x) for x in presets])
        self.resolution_combo.setCurrentText(str(cfg.get("resolution_preset", "1280x720")))

        self.keep_ratio_check.setChecked(bool(cfg.get("keep_aspect_ratio", True)))
        self.use_transition_check.setChecked(bool(cfg.get("use_transition", True)))
        self.random_transition_check.setChecked(bool(cfg.get("random_transition", False)))
        self.transition_combo.setCurrentText(str(cfg.get("transition_type", self.transition_combo.currentText())))

        transitions = cfg.get("enabled_transitions")
        if isinstance(transitions, list):
            self.enabled_transitions = [t for t in transitions if t in GUI_TRANSITIONS] or GUI_TRANSITIONS.copy()

        self.use_effect_check.setChecked(bool(cfg.get("use_video_effect", False)))
        self.random_effect_check.setChecked(bool(cfg.get("random_video_effect", False)))
        self.effect_combo.setCurrentText(str(cfg.get("video_effect_type", self.effect_combo.currentText())))
        effects = cfg.get("enabled_video_effects")
        if isinstance(effects, list):
            clean_effects = [str(e) for e in effects if str(e) != "无特效"]
            if clean_effects:
                self.enabled_video_effects = clean_effects
                for item in clean_effects:
                    if self.effect_combo.findText(item) < 0:
                        self.effect_combo.addItem(item)

        self.effect_intensity_spin.setValue(float(cfg.get("video_effect_intensity", 100.0)))
        self.effect_speed_spin.setValue(float(cfg.get("video_effect_speed", 1.3)))

        self.use_bgm_check.setChecked(bool(cfg.get("use_bgm", False)))
        self.random_bgm_check.setChecked(bool(cfg.get("random_bgm", False)))
        self.loop_bgm_check.setChecked(bool(cfg.get("loop_bgm", False)))
        self.bgm_dir_edit.setText(str(cfg.get("bgm_dir", "")))
        self.bgm_volume_spin.setValue(float(cfg.get("bgm_volume", 0.5)))
        self.codec_combo.setCurrentText(str(cfg.get("codec", "H264")))

        self.use_watermark_check.setChecked(bool(cfg.get("use_watermark", False)))
        self.watermark_mode_combo.setCurrentText(str(cfg.get("watermark_mode", cfg.get("watermark_type", "单文件"))))
        self.watermark_path_edit.setText(str(cfg.get("watermark_path", "")))
        self.watermark_match_method_combo.setCurrentText(str(cfg.get("watermark_match_method", "循环")))
        self.watermark_audio_combo.setCurrentText(str(cfg.get("watermark_audio", "使用BGM")))
        self.watermark_size_mode_combo.setCurrentText(str(cfg.get("watermark_size_mode", "自适应覆盖")))
        self.watermark_blend_combo.setCurrentText(str(cfg.get("watermark_blend_mode", "正常")))
        self.use_image_watermark_check.setChecked(bool(cfg.get("use_image_watermark", True)))

        self.use_date_prefix_check.setChecked(bool(cfg.get("use_date_prefix", True)))
        self.use_first_image_name_check.setChecked(bool(cfg.get("use_first_image_name", False)))
        self.custom_prefix_edit.setText(str(cfg.get("custom_prefix", "video")))
        self.image_selection_combo.setCurrentText(str(cfg.get("image_selection_mode", "随机选择")))
        self.bitrate_spin.setValue(int(cfg.get("bitrate", 2000)))
        self._load_watermark_layers_to_ui(cfg.get("watermark_layers", []))
        self._sync_prefix_state()
        self._sync_watermark_advanced_state()
        self._sync_image_watermark_state()

    def _migrate_watermark_legacy_defaults(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """迁移旧默认值：右下/20 -> 中心/100（仅迁移历史默认，不覆盖用户个性化配置）。"""
        if not isinstance(cfg, dict):
            return cfg
        if bool(cfg.get("_qt_watermark_defaults_v2", False)):
            return cfg

        migrated = dict(cfg)

        raw_position = str(migrated.get("watermark_position", "")).strip()
        raw_scale = migrated.get("watermark_scale", None)
        try:
            numeric_scale = float(raw_scale) if raw_scale is not None else None
        except Exception:
            numeric_scale = None

        if raw_position in ("", "右下"):
            migrated["watermark_position"] = "中心"
        if numeric_scale is None or abs(numeric_scale - 20.0) < 1e-6:
            migrated["watermark_scale"] = 100.0

        layers = migrated.get("watermark_layers", [])
        if isinstance(layers, list):
            normalized_layers: List[Dict[str, Any]] = []
            for item in layers:
                if not isinstance(item, dict):
                    continue
                row = dict(item)
                row_position = str(row.get("position", "")).strip()
                row_scale_raw = row.get("scale", None)
                try:
                    row_scale = float(row_scale_raw) if row_scale_raw is not None else None
                except Exception:
                    row_scale = None
                if row_position in ("", "右下"):
                    row["position"] = "中心"
                if row_scale is None or abs(row_scale - 20.0) < 1e-6:
                    row["scale"] = 100.0
                normalized_layers.append(row)
            migrated["watermark_layers"] = normalized_layers

        migrated["_qt_watermark_defaults_v2"] = True
        return migrated

    def save_config(self, show_message: bool = True) -> None:
        cfg = self.collect_config()
        if 0 <= self._active_tab_index < len(self.tab_contexts):
            self.tab_contexts[self._active_tab_index]["config"] = copy.deepcopy(cfg)
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=4)
            if show_message:
                self._set_status(f"配置已保存: {self.config_file}")
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))

    def load_config(self, show_message: bool = True) -> None:
        if not os.path.exists(self.config_file):
            cfg = self._default_config()
            self.apply_config(cfg)
            if 0 <= self._active_tab_index < len(self.tab_contexts):
                self.tab_contexts[self._active_tab_index]["config"] = copy.deepcopy(cfg)
            if show_message:
                self._set_status("未找到配置文件，已使用默认配置")
            return
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.apply_config(cfg)
            if 0 <= self._active_tab_index < len(self.tab_contexts):
                self.tab_contexts[self._active_tab_index]["config"] = copy.deepcopy(cfg)
            if show_message:
                self._set_status("已加载配置")
        except Exception as exc:
            QMessageBox.warning(self, "加载配置失败", str(exc))
            cfg = self._default_config()
            self.apply_config(cfg)
            if 0 <= self._active_tab_index < len(self.tab_contexts):
                self.tab_contexts[self._active_tab_index]["config"] = copy.deepcopy(cfg)

    # ----- 事件 -----
    def _browse_input_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输入目录", self.input_dir_edit.text() or os.getcwd())
        if path:
            self.input_dir_edit.setText(path)

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_dir_edit.text() or os.getcwd())
        if path:
            self.output_dir_edit.setText(path)

    def _browse_bgm_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择BGM目录", self.bgm_dir_edit.text() or os.getcwd())
        if path:
            self.bgm_dir_edit.setText(path)

    def _browse_watermark_path(self) -> None:
        if self.watermark_mode_combo.currentText() == "文件夹":
            path = QFileDialog.getExistingDirectory(self, "选择水印目录", self.watermark_path_edit.text() or os.getcwd())
            if path:
                self.watermark_path_edit.setText(path)
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择水印文件",
            self.watermark_path_edit.text() or os.getcwd(),
            "视频/图片 (*.mp4 *.mov *.avi *.png *.jpg *.jpeg *.webp);;所有文件 (*.*)",
        )
        if file_path:
            self.watermark_path_edit.setText(file_path)

    def _add_resolution_preset(self) -> None:
        text = self.resolution_combo.currentText().strip()
        if not text:
            return
        w, h = self._parse_resolution(text)
        normalized = f"{w}x{h}"
        if self.resolution_combo.findText(normalized) < 0:
            self.resolution_combo.addItem(normalized)
        self.resolution_combo.setCurrentText(normalized)

    def _remove_resolution_preset(self) -> None:
        current = self.resolution_combo.currentText().strip()
        idx = self.resolution_combo.findText(current)
        if idx < 0:
            return
        if self.resolution_combo.count() <= 1:
            self._set_status("至少保留一个分辨率预设")
            return
        self.resolution_combo.removeItem(idx)
        self.resolution_combo.setCurrentIndex(max(0, idx - 1))

    def _sync_prefix_state(self) -> None:
        allow_custom = not self.use_first_image_name_check.isChecked()
        self.custom_prefix_edit.setEnabled(allow_custom)

    def _sync_watermark_advanced_state(self) -> None:
        # 视频水印模块的控件始终可编辑；是否生效由“启用视频水印”控制。
        # 这样避免出现“复选框未勾选时下拉框完全不可操作”的体验问题。
        enabled = True
        for widget in (
            self.watermark_match_method_combo,
            self.watermark_audio_combo,
            self.watermark_size_mode_combo,
            self.watermark_blend_combo,
        ):
            widget.setEnabled(enabled)

    def _sync_image_watermark_state(self) -> None:
        enabled = bool(getattr(self, "use_image_watermark_check", None) and self.use_image_watermark_check.isChecked())
        if hasattr(self, "add_layer_btn"):
            self.add_layer_btn.setEnabled(enabled)
        for row in getattr(self, "_watermark_layer_rows", []):
            for key in ("path", "browse", "position", "fixed", "size_mode", "scale", "blend", "opacity", "delete"):
                if key in row and row[key] is not None:
                    row[key].setEnabled(enabled)

    def _save_ui_state(self) -> None:
        try:
            self._save_current_tab_context(self._active_tab_index)
            state: Dict[str, Any] = {
                "window": {
                    "x": int(self.x()),
                    "y": int(self.y()),
                    "width": int(self.width()),
                    "height": int(self.height()),
                    "maximized": bool(self.isMaximized()),
                },
                "theme": {
                    "dark": bool(self._dark_theme_enabled),
                },
            }
            state.update(self._serialize_tabs_state())
            splitter = getattr(self, "main_splitter", None)
            if splitter is not None:
                state["splitter_state"] = b64encode(bytes(splitter.saveState())).decode("ascii")
            with open(self.ui_state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_ui_state(self) -> None:
        if not os.path.exists(self.ui_state_file):
            return
        try:
            with open(self.ui_state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            if not isinstance(state, dict):
                return
            self._restore_tabs_state(state)
            window = state.get("window", {})
            if isinstance(window, dict):
                w = int(window.get("width", self.width()))
                h = int(window.get("height", self.height()))
                x = int(window.get("x", self.x()))
                y = int(window.get("y", self.y()))
                self.resize(max(self.minimumWidth(), w), max(self.minimumHeight(), h))
                self.move(x, y)
                if bool(window.get("maximized", False)):
                    QTimer.singleShot(0, self.showMaximized)
            theme = state.get("theme", {})
            if isinstance(theme, dict):
                self._dark_theme_enabled = bool(theme.get("dark", False))
                self._apply_theme()
            splitter = getattr(self, "main_splitter", None)
            splitter_state = state.get("splitter_state", "")
            if splitter is not None and isinstance(splitter_state, str) and splitter_state:
                try:
                    splitter.restoreState(b64decode(splitter_state.encode("ascii")))
                    self._last_splitter_mode = "vertical" if splitter.orientation() == Qt.Vertical else "horizontal"
                except Exception:
                    pass
        except Exception:
            pass

    def _add_watermark_layer_row(self, layer: Dict[str, Any] | None = None) -> None:
        layer = layer or {}
        if not hasattr(self, "_watermark_layer_rows"):
            self._watermark_layer_rows: List[Dict[str, Any]] = []

        row_frame = QFrame()
        row_layout = QHBoxLayout(row_frame)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        path_edit = QLineEdit(str(layer.get("path", "")))
        browse_btn = QPushButton("浏览")
        position_combo = QComboBox()
        position_combo.addItems(["左上", "右上", "左下", "右下", "中心"])
        position_combo.setCurrentText(str(layer.get("position", "中心")))
        fixed_check = QCheckBox("固定")
        fixed_check.setChecked(bool(layer.get("fixed", False)))
        folder_random_single_check = QCheckBox("目录随机1个")
        folder_random_single_check.setChecked(bool(layer.get("folder_random_single", False)))
        size_mode_combo = QComboBox()
        size_mode_combo.addItems(["固定比例", "自适应覆盖", "完全覆盖"])
        size_mode_combo.setCurrentText(str(layer.get("size_mode", "自适应覆盖")))
        scale_spin = QDoubleSpinBox()
        scale_spin.setRange(5.0, 100.0)
        scale_spin.setSingleStep(5.0)
        scale_spin.setValue(float(layer.get("scale", 100.0)))
        scale_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        blend_combo = QComboBox()
        blend_combo.addItems(["正常", "滤色", "叠加", "正片叠底", "变亮", "变暗", "相加"])
        blend_combo.setCurrentText(str(layer.get("blend_mode", "正常")))
        opacity_spin = QDoubleSpinBox()
        opacity_spin.setRange(0.1, 1.0)
        opacity_spin.setSingleStep(0.1)
        opacity_spin.setValue(float(layer.get("opacity", 1.0)))
        opacity_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        delete_btn = QPushButton("删除")
        row_layout.addWidget(QLabel("路径"))
        row_layout.addWidget(path_edit, 1)
        row_layout.addWidget(browse_btn)
        row_layout.addWidget(QLabel("位置"))
        row_layout.addWidget(position_combo)
        row_layout.addWidget(fixed_check)
        row_layout.addWidget(folder_random_single_check)
        row_layout.addWidget(QLabel("大小"))
        row_layout.addWidget(size_mode_combo)
        row_layout.addWidget(QLabel("缩放"))
        row_layout.addWidget(scale_spin)
        row_layout.addWidget(QLabel("混合"))
        row_layout.addWidget(blend_combo)
        row_layout.addWidget(QLabel("透明"))
        row_layout.addWidget(opacity_spin)
        row_layout.addWidget(delete_btn)

        row = {
            "frame": row_frame,
            "path": path_edit,
            "browse": browse_btn,
            "position": position_combo,
            "fixed": fixed_check,
            "folder_random_single": folder_random_single_check,
            "size_mode": size_mode_combo,
            "scale": scale_spin,
            "blend": blend_combo,
            "opacity": opacity_spin,
            "delete": delete_btn,
        }
        browse_btn.clicked.connect(lambda: self._browse_watermark_layer_path(path_edit))
        delete_btn.clicked.connect(lambda: self._remove_watermark_layer_row(row))
        path_edit.textChanged.connect(self._on_preview_setting_changed)
        position_combo.currentTextChanged.connect(self._on_preview_setting_changed)
        fixed_check.stateChanged.connect(self._on_preview_setting_changed)
        folder_random_single_check.stateChanged.connect(self._on_preview_setting_changed)
        size_mode_combo.currentTextChanged.connect(self._on_preview_setting_changed)
        scale_spin.valueChanged.connect(self._on_preview_setting_changed)
        blend_combo.currentTextChanged.connect(self._on_preview_setting_changed)
        opacity_spin.valueChanged.connect(self._on_preview_setting_changed)
        self._watermark_layer_rows.append(row)
        self.layer_rows_layout.addWidget(row_frame)
        self._sync_watermark_advanced_state()

    def _browse_watermark_layer_path(self, target_edit: QLineEdit) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图层文件",
            target_edit.text() or os.getcwd(),
            "视频/图片 (*.mp4 *.mov *.avi *.png *.jpg *.jpeg *.webp);;所有文件 (*.*)",
        )
        if file_path:
            target_edit.setText(file_path)

    def _remove_watermark_layer_row(self, row: Dict[str, Any]) -> None:
        rows = getattr(self, "_watermark_layer_rows", [])
        if row not in rows:
            return
        rows.remove(row)
        row["frame"].setParent(None)
        row["frame"].deleteLater()
        if not rows:
            self._add_watermark_layer_row()
        self._on_preview_setting_changed()

    def _collect_watermark_layers_from_ui(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        image_wm_enabled = bool(getattr(self, "use_image_watermark_check", None) and self.use_image_watermark_check.isChecked())
        for row in getattr(self, "_watermark_layer_rows", []):
            path = row["path"].text().strip()
            if not path:
                continue
            result.append({
                "enabled": bool(image_wm_enabled),
                "path": path,
                "position": row["position"].currentText(),
                "fixed": row["fixed"].isChecked(),
                "folder_random_single": row["folder_random_single"].isChecked(),
                "size_mode": row["size_mode"].currentText(),
                "scale": float(row["scale"].value()),
                "blend_mode": row["blend"].currentText(),
                "opacity": float(row["opacity"].value()),
            })
        return result

    def _load_watermark_layers_to_ui(self, layers: Any) -> None:
        if not hasattr(self, "_watermark_layer_rows"):
            self._watermark_layer_rows = []
        for row in list(self._watermark_layer_rows):
            row["frame"].setParent(None)
            row["frame"].deleteLater()
        self._watermark_layer_rows = []
        if isinstance(layers, list) and layers:
            for item in layers:
                if isinstance(item, dict):
                    self._add_watermark_layer_row(item)
        else:
            self._add_watermark_layer_row()

    def _get_tab_worker_state(self, tab_index: int) -> Dict[str, Any]:
        if tab_index < 0 or tab_index >= len(self.tab_contexts):
            return {}
        context = self.tab_contexts[tab_index]
        state = context.get("worker_state")
        if not isinstance(state, dict):
            state = {
                "process": None,
                "stdout_buffer": "",
                "control_file": "",
                "worker_config_file": "",
                "is_paused": False,
                "process_generation": 0,
                "last_worker_phase": "",
                "last_worker_elapsed_sec": None,
                "last_worker_status_text": "",
                "last_worker_raw_status_text": "",
                "last_worker_stderr_text": "",
            }
            context["worker_state"] = state
        return state

    def _any_worker_running(self) -> bool:
        for idx in range(len(self.tab_contexts)):
            state = self._get_tab_worker_state(idx)
            process = state.get("process")
            if isinstance(process, QProcess) and process.state() != QProcess.NotRunning:
                return True
        return False

    def _write_control_file(self, tab_index: int, paused: bool | None = None, cancel: bool | None = None) -> None:
        state = self._get_tab_worker_state(tab_index)
        control_file = str(state.get("control_file", ""))
        if not control_file:
            return
        payload = {"paused": False, "cancel": False}
        if os.path.exists(control_file):
            try:
                with open(control_file, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                payload = {"paused": False, "cancel": False}
        if paused is not None:
            payload["paused"] = bool(paused)
        if cancel is not None:
            payload["cancel"] = bool(cancel)
        try:
            tmp_file = f"{control_file}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp_file, control_file)
        except Exception:
            pass

    def _cleanup_control_file(self, tab_index: int) -> None:
        state = self._get_tab_worker_state(tab_index)
        control_file = str(state.get("control_file", ""))
        if control_file and os.path.exists(control_file):
            try:
                os.remove(control_file)
            except Exception:
                pass
        state["control_file"] = ""

    def _toggle_pause_processing(self) -> None:
        tab_index = self.tabs.currentIndex()
        state = self._get_tab_worker_state(tab_index)
        process = state.get("process")
        if not isinstance(process, QProcess) or process.state() == QProcess.NotRunning:
            return
        state["is_paused"] = not bool(state.get("is_paused", False))
        self._write_control_file(tab_index, paused=bool(state.get("is_paused", False)))
        self.pause_btn.setText("继续" if bool(state.get("is_paused", False)) else "暂停")
        self._set_status("已暂停" if bool(state.get("is_paused", False)) else "继续处理")

    def _force_stop_worker_if_needed(self, tab_index: int, expected_generation: int) -> None:
        state = self._get_tab_worker_state(tab_index)
        if expected_generation != int(state.get("process_generation", 0)):
            return
        process = state.get("process")
        if not isinstance(process, QProcess) or process.state() == QProcess.NotRunning:
            return
        try:
            process.terminate()
        except Exception:
            pass
        self._set_status("取消中，正在停止任务...")

    def _force_kill_worker_if_needed(self, tab_index: int, expected_generation: int) -> None:
        state = self._get_tab_worker_state(tab_index)
        if expected_generation != int(state.get("process_generation", 0)):
            return
        process = state.get("process")
        if not isinstance(process, QProcess) or process.state() == QProcess.NotRunning:
            return
        try:
            process.kill()
        except Exception:
            pass
        self._set_status("已强制结束任务")

    def _cancel_processing(self) -> None:
        tab_index = self.tabs.currentIndex()
        state = self._get_tab_worker_state(tab_index)
        process = state.get("process")
        if not isinstance(process, QProcess) or process.state() == QProcess.NotRunning:
            return
        generation = int(state.get("process_generation", 0))
        self._write_control_file(tab_index, cancel=True, paused=False)
        state["is_paused"] = False
        self.pause_btn.setText("暂停")
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self._set_status("已请求取消，正在停止...")
        QTimer.singleShot(1200, lambda: self._force_stop_worker_if_needed(tab_index, generation))
        QTimer.singleShot(3000, lambda: self._force_kill_worker_if_needed(tab_index, generation))

    def _open_output_dir(self) -> None:
        out_dir = self.output_dir_edit.text().strip()
        if not out_dir or not os.path.isdir(out_dir):
            QMessageBox.information(self, "提示", "输出目录无效或不存在")
            return
        try:
            if sys.platform == "win32":
                os.startfile(out_dir)
            else:
                QMessageBox.information(self, "提示", f"请手动打开目录: {out_dir}")
        except Exception as exc:
            QMessageBox.warning(self, "打开失败", str(exc))

    def _open_advanced_config_editor(self) -> None:
        cfg = self.collect_config()
        dialog = QDialog(self)
        dialog.setWindowTitle("高级配置 JSON 编辑器")
        dialog.resize(860, 620)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit(dialog)
        editor.setPlainText(json.dumps(cfg, ensure_ascii=False, indent=2))
        layout.addWidget(editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            new_cfg = json.loads(editor.toPlainText())
            if not isinstance(new_cfg, dict):
                raise ValueError("配置必须是 JSON 对象")
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(new_cfg, f, ensure_ascii=False, indent=4)
            self.apply_config(new_cfg)
            self._set_status("高级配置已更新并生效")
        except Exception as exc:
            QMessageBox.warning(self, "配置无效", str(exc))

    def _pick_multi_items_grouped(
        self,
        title: str,
        tip: str,
        candidates: List[str],
        selected: List[str],
        group_def: Dict[str, List[str]],
        default_selected: List[str],
        descriptions: Dict[str, str] | None = None,
    ) -> List[str]:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(920, 680)
        layout = QVBoxLayout(dialog)

        title_label = QLabel(title)
        title_label.setObjectName("Title")
        layout.addWidget(title_label)
        tip_label = QLabel(tip)
        tip_label.setObjectName("SecondaryText")
        layout.addWidget(tip_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

        selected_set = set(selected)
        checkbox_vars: Dict[str, QCheckBox] = {}
        group_vars: Dict[str, QCheckBox] = {}
        group_members: Dict[str, List[str]] = {}

        # 分组布局（补齐“其他”分组，行为与旧版一致）
        placed = set()
        group_layout: List[tuple[str, List[str]]] = []
        for group_name, items in group_def.items():
            group_items = [name for name in items if name in candidates and name not in placed]
            if group_items:
                group_layout.append((group_name, group_items))
                placed.update(group_items)
        remaining = [name for name in candidates if name not in placed]
        if remaining:
            group_layout.append(("其他", remaining))

        for idx, (group_name, items) in enumerate(group_layout):
            col = idx % 2
            row = idx // 2
            frame = QGroupBox("")
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(8, 6, 8, 6)
            frame_layout.setSpacing(4)

            group_check = QCheckBox(f"【{group_name}】")
            group_check.setChecked(all(name in selected_set for name in items))
            frame_layout.addWidget(group_check)
            group_vars[group_name] = group_check
            group_members[group_name] = items

            for name in items:
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(12, 0, 0, 0)
                row_layout.setSpacing(6)
                item_check = QCheckBox(name)
                item_check.setChecked(name in selected_set)
                checkbox_vars[name] = item_check
                row_layout.addWidget(item_check)
                if descriptions and name in descriptions:
                    desc = QLabel(f"({descriptions[name]})")
                    desc.setObjectName("SecondaryText")
                    row_layout.addWidget(desc)
                row_layout.addStretch(1)
                frame_layout.addWidget(row_widget)

                def _on_item_toggled(_checked: bool, g=group_name):
                    members = group_members[g]
                    all_checked = all(checkbox_vars[item].isChecked() for item in members)
                    group_box = group_vars[g]
                    group_box.blockSignals(True)
                    group_box.setChecked(all_checked)
                    group_box.blockSignals(False)

                item_check.toggled.connect(_on_item_toggled)

            def _on_group_toggled(checked: bool, g=group_name):
                for item in group_members[g]:
                    checkbox_vars[item].setChecked(bool(checked))

            group_check.toggled.connect(_on_group_toggled)
            grid.addWidget(frame, row, col)

        action_row = QHBoxLayout()
        all_btn = QPushButton("全选")
        none_btn = QPushButton("全不选")
        default_btn = QPushButton("恢复默认")
        action_row.addWidget(all_btn)
        action_row.addWidget(none_btn)
        action_row.addWidget(default_btn)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        def _select_all():
            for box in checkbox_vars.values():
                box.setChecked(True)

        def _select_none():
            for box in checkbox_vars.values():
                box.setChecked(False)

        def _select_default():
            defaults = set(default_selected)
            for name, box in checkbox_vars.items():
                box.setChecked(name in defaults)

        all_btn.clicked.connect(_select_all)
        none_btn.clicked.connect(_select_none)
        default_btn.clicked.connect(_select_default)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return selected
        result = [name for name in candidates if checkbox_vars.get(name) and checkbox_vars[name].isChecked()]
        return result

    def _configure_random_effects(self) -> None:
        candidates = [self.effect_combo.itemText(i) for i in range(self.effect_combo.count()) if self.effect_combo.itemText(i) != "无特效"]
        picked = self._pick_multi_items_grouped(
            title="配置随机特效",
            tip="勾选后将在生成多个视频时按视频随机应用",
            candidates=candidates,
            selected=self.enabled_video_effects,
            group_def=VIDEO_EFFECT_GROUPS,
            default_selected=DEFAULT_VIDEO_EFFECTS.copy(),
        )
        if not picked:
            QMessageBox.warning(self, "警告", "至少需要选择一个特效！")
            return
        self.enabled_video_effects = picked
        self._set_status(f"随机特效池已更新（{len(self.enabled_video_effects)}项）")

    def _configure_random_transitions(self) -> None:
        picked = self._pick_multi_items_grouped(
            title="配置随机转场效果",
            tip="勾选的效果将在启用“随机转场”时被随机选择",
            candidates=GUI_TRANSITIONS,
            selected=self.enabled_transitions,
            group_def=TRANSITION_GROUPS,
            default_selected=DEFAULT_ENABLED_TRANSITIONS.copy(),
            descriptions=TRANSITION_DESCRIPTIONS,
        )
        if not picked:
            QMessageBox.warning(self, "警告", "至少需要选择一个转场效果！")
            return
        self.enabled_transitions = picked
        self._set_status(f"随机转场池已更新（{len(self.enabled_transitions)}项）")

    # ----- 处理桥接 -----
    def _get_tab_refs(self, tab_index: int) -> Dict[str, Any]:
        if 0 <= tab_index < len(self.tab_contexts):
            refs = self.tab_contexts[tab_index].get("refs", {})
            if isinstance(refs, dict):
                return refs
        return {}

    def _set_processing_buttons_state(self, tab_index: int, running: bool) -> None:
        refs = self._get_tab_refs(tab_index)
        if not refs:
            return
        state = self._get_tab_worker_state(tab_index)
        start_btn = refs.get("start_btn")
        pause_btn = refs.get("pause_btn")
        cancel_btn = refs.get("cancel_btn")
        if running:
            if start_btn is not None:
                start_btn.setEnabled(False)
            if pause_btn is not None:
                pause_btn.setEnabled(True)
                pause_btn.setText("继续" if bool(state.get("is_paused", False)) else "暂停")
            if cancel_btn is not None:
                cancel_btn.setEnabled(True)
        else:
            if start_btn is not None:
                start_btn.setEnabled(True)
            if pause_btn is not None:
                pause_btn.setEnabled(False)
                pause_btn.setText("暂停")
            if cancel_btn is not None:
                cancel_btn.setEnabled(False)

    def _set_processing_progress_ui(self, tab_index: int, percent: int, overall: int, speed=None) -> None:
        refs = self._get_tab_refs(tab_index)
        if not refs:
            return
        progress_bar = refs.get("progress_bar")
        progress_label = refs.get("progress_label")
        overall_label = refs.get("overall_label")
        speed_label = refs.get("speed_label")
        if progress_bar is not None:
            progress_bar.setValue(max(0, min(100, int(percent))))
        if progress_label is not None:
            progress_label.setText(f"进度: {int(percent)}%")
        if overall_label is not None:
            overall_label.setText(f"总进度: {int(overall)}%")
        if speed is not None and speed_label is not None:
            speed_label.setText(f"速度: {speed} 张/秒")

    def _set_processing_status_ui(self, tab_index: int, msg: str) -> None:
        text = str(msg or "").strip()
        if len(text) > 42:
            text = text[:42] + "..."
        refs = self._get_tab_refs(tab_index)
        status_label = refs.get("status_label") if isinstance(refs, dict) else None
        if status_label is not None:
            status_label.setText(f"状态: {text}")
        # 仅当前显示标签同步顶部提示，避免跨标签误导。
        if self.tabs.currentIndex() == tab_index:
            if hasattr(self, "status_label") and self.status_label is not None:
                self.status_label.setText(f"状态: {text}")
            if hasattr(self, "status_hint_label"):
                self.status_hint_label.setText(f"✓ {text}")

    def _collect_config_for_tab(self, tab_index: int) -> Dict[str, Any]:
        """按标签页采集配置：活动页实时采集，非活动页使用内存快照。"""
        if tab_index < 0 or tab_index >= len(self.tab_contexts):
            return {}
        context = self.tab_contexts[tab_index]
        if tab_index == self.tabs.currentIndex():
            self._save_current_tab_context(tab_index)
        cfg = context.get("config")
        if isinstance(cfg, dict) and cfg:
            return copy.deepcopy(cfg)
        cfg_file = str(context.get("config_file", "") or "").strip()
        fallback_cfg = self._read_json_dict(cfg_file) or self._default_config()
        context["config"] = copy.deepcopy(fallback_cfg)
        return fallback_cfg

    def _count_images_in_dir(self, input_dir: str) -> int:
        """统计目录中图片数量（递归）。"""
        image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
        total = 0
        try:
            for root, _dirs, files in os.walk(input_dir):
                for name in files:
                    if os.path.splitext(name)[1].lower() in image_exts:
                        total += 1
        except Exception:
            return -1
        return total

    def _validate_config_for_user(self, cfg: Dict[str, Any]) -> str:
        """开始任务前的人话校验提示，避免只显示退出码。"""
        input_dir = str(cfg.get("input_dir", "") or "").strip()
        output_dir = str(cfg.get("output_dir", "") or "").strip()
        selection_mode = str(cfg.get("image_selection_mode", "随机选择") or "随机选择").strip()
        try:
            num_images = int(cfg.get("num_images", 1))
        except Exception:
            num_images = 0
        try:
            video_count = int(cfg.get("video_count", 1))
        except Exception:
            video_count = 0
        try:
            duration = float(cfg.get("duration", 0))
            total_duration = float(cfg.get("total_duration", 0))
            timeline_slot_count(duration, total_duration)
        except (TypeError, ValueError) as exc:
            return str(exc)

        if not input_dir:
            return "请输入输入目录"
        if not os.path.isdir(input_dir):
            return "输入目录不存在，请重新选择"
        if not output_dir:
            return "请输入输出目录"
        if num_images <= 0:
            return "每个视频图片数必须大于 0"
        if video_count <= 0:
            return "视频数量必须大于 0"

        image_count = self._count_images_in_dir(input_dir)
        if image_count < 0:
            return "读取输入目录失败，请检查目录权限"
        if image_count == 0:
            return "输入目录里没有图片，请先放入图片再导出"

        if selection_mode == "按名称排序":
            required = video_count * num_images
            if image_count < required:
                return (
                    f"输出数量超出图片数量：当前只有 {image_count} 张图片，"
                    f"按名称排序模式生成 {video_count} 个视频需要 {required} 张。"
                    "请减少“视频数量”或“每视频图片数”。"
                )
        else:
            if image_count < num_images:
                return (
                    f"图片数量不足：当前只有 {image_count} 张，"
                    f"每个视频需要 {num_images} 张。"
                )
            if image_count < video_count:
                return (
                    f"输出数量超出图片数量：随机模式下为保证首图不重复，"
                    f"当前 {image_count} 张图片最多生成 {image_count} 个视频。"
                )
        return ""

    def _start_processing_for_tab(self, tab_index: int, quiet_on_busy: bool = False) -> bool:
        if tab_index < 0 or tab_index >= len(self.tab_contexts):
            return False
        state = self._get_tab_worker_state(tab_index)
        process = state.get("process")
        if isinstance(process, QProcess) and process.state() != QProcess.NotRunning:
            if not quiet_on_busy and self.tabs.currentIndex() == tab_index:
                self._set_status("该标签页正在处理中，请等待")
            return False
        state["process_generation"] = int(state.get("process_generation", 0)) + 1
        state["stdout_buffer"] = ""
        state["last_worker_phase"] = ""
        state["last_worker_elapsed_sec"] = None
        state["last_worker_status_text"] = ""
        state["last_worker_raw_status_text"] = ""
        state["last_worker_stderr_text"] = ""
        state["is_paused"] = False
        cfg = self._collect_config_for_tab(tab_index)
        if not isinstance(cfg, dict) or not cfg:
            if self.tabs.currentIndex() == tab_index:
                self._set_status("读取标签页配置失败")
            return False
        readable_error = self._validate_config_for_user(cfg)
        if readable_error:
            self._set_processing_status_ui(tab_index, readable_error)
            if self.tabs.currentIndex() == tab_index:
                self._set_status(readable_error)
                QMessageBox.warning(self, "参数提示", readable_error)
            return False
        tab_config_file = str(self.tab_contexts[tab_index].get("config_file", "") or "").strip()
        if not tab_config_file:
            tab_config_file = self._build_tab_config_file()
            self.tab_contexts[tab_index]["config_file"] = tab_config_file
        # 优先保存为用户配置（失败不阻断），便于下次打开恢复。
        try:
            with open(tab_config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

        # 运行时快照配置写入临时目录，避免 Program Files/快捷方式工作目录导致写权限或路径问题。
        runtime_dir = os.path.join(tempfile.gettempdir(), "img2video_qt_runtime")
        try:
            os.makedirs(runtime_dir, exist_ok=True)
            worker_config_file = os.path.join(
                runtime_dir, f"cfg_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.json"
            )
            with open(worker_config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=4)
            state["worker_config_file"] = worker_config_file
        except Exception as exc:
            QMessageBox.critical(self, "运行配置写入失败", str(exc))
            return False

        state["control_file"] = os.path.join(
            tempfile.gettempdir(),
            f".qt_bridge_control_{tab_index}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.json",
        )
        self._write_control_file(tab_index, paused=False, cancel=False)
        process = QProcess(self)
        state["process"] = process
        if bool(getattr(sys, "frozen", False)):
            # 打包后 sys.executable 就是主 exe；通过专用参数切到桥接模式，避免再次打开主窗口。
            process.setProgram(sys.executable)
            process.setArguments(
                ["--qt-bridge-worker", "--config", state["worker_config_file"], "--control", state["control_file"]]
            )
        else:
            runner = os.path.join(os.path.dirname(__file__), "tk_bridge_runner.py")
            process.setProgram(sys.executable)
            process.setArguments([runner, "--config", state["worker_config_file"], "--control", state["control_file"]])
        process.readyReadStandardOutput.connect(lambda idx=tab_index, p=process: self._on_worker_stdout(idx, p))
        process.readyReadStandardError.connect(lambda idx=tab_index, p=process: self._on_worker_stderr(idx, p))
        process.finished.connect(lambda exit_code, status, idx=tab_index, p=process: self._on_worker_finished(idx, p, exit_code, status))

        self._set_processing_buttons_state(tab_index, True)
        self.batch_btn.setEnabled(True)
        self._set_processing_progress_ui(tab_index, percent=0, overall=0, speed="0.0")
        self._set_processing_status_ui(tab_index, "开始处理...")
        if self.tabs.currentIndex() == tab_index:
            self._set_status("开始处理...")
        process.start()
        return True

    def start_processing(self) -> None:
        self._start_processing_for_tab(self.tabs.currentIndex(), quiet_on_busy=False)

    def start_batch_processing(self) -> None:
        total_tabs = self.tabs.count()
        if total_tabs <= 0:
            return
        if self._batch_queue:
            self._set_status("批量任务已在进行中，请等待当前队列完成")
            return
        original_idx = self.tabs.currentIndex()
        self._batch_queue = list(range(total_tabs))
        self._batch_expected_total = total_tabs
        self._batch_started_total = 0
        self._batch_skipped_tabs = []
        self._schedule_batch_jobs()
        if 0 <= original_idx < self.tabs.count():
            self.tabs.setCurrentIndex(original_idx)
        running_now = self._running_worker_count()
        if self._batch_started_total <= 0 and running_now <= 0:
            self._set_status("批量处理未启动：所有标签页均在运行或配置无效")
            self._reset_batch_state()
            return
        if self._batch_skipped_tabs:
            skipped_text = ",".join(str(i) for i in self._batch_skipped_tabs[:8])
            more_text = "..." if len(self._batch_skipped_tabs) > 8 else ""
            self._set_status(
                f"批量已启动 {self._batch_started_total}/{total_tabs} 个标签，并发上限 {self._batch_running_limit}（跳过: {skipped_text}{more_text}）"
            )
        else:
            self._set_status(
                f"批量已启动 {self._batch_started_total}/{total_tabs} 个标签，并发上限 {self._batch_running_limit}"
            )

    def _running_worker_count(self) -> int:
        running = 0
        for idx in range(len(self.tab_contexts)):
            state = self._get_tab_worker_state(idx)
            process = state.get("process")
            if isinstance(process, QProcess) and process.state() != QProcess.NotRunning:
                running += 1
        return running

    def _reset_batch_state(self) -> None:
        self._batch_queue = []
        self._batch_expected_total = 0
        self._batch_started_total = 0
        self._batch_skipped_tabs = []

    def _schedule_batch_jobs(self) -> None:
        while self._batch_queue and self._running_worker_count() < self._batch_running_limit:
            idx = int(self._batch_queue.pop(0))
            if self._start_processing_for_tab(idx, quiet_on_busy=True):
                self._batch_started_total += 1
            else:
                self._batch_skipped_tabs.append(idx + 1)

        if self._batch_expected_total > 0 and not self._batch_queue and self._running_worker_count() == 0:
            skipped_count = len(self._batch_skipped_tabs)
            if skipped_count > 0:
                self._set_status(
                    f"批量处理完成：已启动 {self._batch_started_total}/{self._batch_expected_total} 个标签，跳过 {skipped_count} 个"
                )
            else:
                self._set_status(
                    f"批量处理完成：已启动 {self._batch_started_total}/{self._batch_expected_total} 个标签"
                )
            self._reset_batch_state()

    def _on_worker_stdout(self, tab_index: int, process: QProcess) -> None:
        state = self._get_tab_worker_state(tab_index)
        if state.get("process") is not process:
            return
        chunk = bytes(process.readAllStandardOutput()).decode("utf-8", errors="ignore")
        if not chunk:
            return
        stdout_buffer = str(state.get("stdout_buffer", ""))
        stdout_buffer += chunk
        while "\n" in stdout_buffer:
            line, stdout_buffer = stdout_buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            self._handle_worker_line(tab_index, line)
        state["stdout_buffer"] = stdout_buffer

    def _on_worker_stderr(self, tab_index: int, process: QProcess) -> None:
        state = self._get_tab_worker_state(tab_index)
        if state.get("process") is not process:
            return
        text = bytes(process.readAllStandardError()).decode("utf-8", errors="ignore").strip()
        if text:
            last_line = text.splitlines()[-1].strip()
            if last_line:
                state["last_worker_stderr_text"] = last_line
            formatted = self._format_processing_status(last_line)
            last_worker_phase = str(state.get("last_worker_phase", ""))
            last_worker_elapsed_sec = state.get("last_worker_elapsed_sec")
            if self.tabs.currentIndex() == tab_index:
                if formatted == "任务执行中" and last_worker_phase:
                    if last_worker_elapsed_sec is not None:
                        self._set_status(f"{last_worker_phase} | 耗时 {last_worker_elapsed_sec}s")
                    else:
                        self._set_status(last_worker_phase)
                else:
                    self._set_status(formatted)

    def _on_worker_finished(self, tab_index: int, process: QProcess, exit_code: int, _status) -> None:
        state = self._get_tab_worker_state(tab_index)
        if state.get("process") is not process:
            return
        self._set_processing_buttons_state(tab_index, False)
        state["is_paused"] = False
        self._cleanup_control_file(tab_index)
        worker_config_file = str(state.get("worker_config_file", ""))
        if worker_config_file and os.path.exists(worker_config_file):
            try:
                os.remove(worker_config_file)
            except Exception:
                pass
        state["worker_config_file"] = ""
        state["process"] = None
        if exit_code == 0:
            self._set_processing_status_ui(tab_index, "任务完成 - 处理完成")
            if self.tabs.currentIndex() == tab_index:
                self._set_status("任务完成 - 处理完成")
        else:
            fail_msg = f"任务失败 - 退出码 {exit_code}"
            detail_parts: List[str] = []
            raw_status = str(state.get("last_worker_raw_status_text", "")).strip()
            stderr_line = str(state.get("last_worker_stderr_text", "")).strip()
            last_worker_status_text = str(state.get("last_worker_status_text", "")).strip()
            last_worker_phase = str(state.get("last_worker_phase", "")).strip()

            if raw_status:
                detail_parts.append(raw_status)
            if stderr_line and stderr_line != raw_status:
                detail_parts.append(f"stderr: {stderr_line}")
            if last_worker_status_text and last_worker_status_text not in ("任务执行中", "处理失败"):
                if last_worker_status_text not in detail_parts:
                    detail_parts.append(last_worker_status_text)
            if last_worker_phase and all(last_worker_phase not in p for p in detail_parts):
                detail_parts.append(f"阶段: {last_worker_phase}")

            if detail_parts:
                fail_msg = f"{fail_msg} | {' | '.join(detail_parts[:2])}"
            self._set_processing_status_ui(tab_index, fail_msg)
            if self.tabs.currentIndex() == tab_index:
                self._set_status(fail_msg)

            if detail_parts:
                detail_text = "\n".join(detail_parts[:4])
                QMessageBox.critical(
                    self,
                    "任务失败",
                    f"退出码: {exit_code}\n\n{detail_text}",
                )
            else:
                QMessageBox.critical(
                    self,
                    "任务失败",
                    f"任务执行失败，退出码: {exit_code}",
                )
        # 一个标签页完成后，自动调度批处理队列中的下一个任务。
        self._schedule_batch_jobs()

    def _format_processing_status(self, message: str) -> str:
        """将处理日志映射为更清晰的阶段状态文案。"""
        msg = str(message or "").strip()
        # 清理乱码与控制字符，避免状态栏出现不可读参数噪音。
        msg = re.sub(r"[\x00-\x1f]+", " ", msg)
        msg = re.sub(r"\s+", " ", msg).strip()
        if not msg:
            return "处理中..."

        # 用户可操作的参数提示优先保留原文，避免被“正在读取图片”等阶段文案覆盖。
        if any(k in msg for k in ("不足", "超出", "请选择", "不存在", "无效", "不够", "需要", "不兼容")):
            return msg

        # 错误态优先透传原文，避免被阶段文案覆盖成“任务执行中”。
        if any(k in msg for k in ("错误", "异常", "失败", "Traceback", "退出码", "stderr", "bridge", "Bridge")):
            return msg
        low = msg.lower()
        if any(k in low for k in ("error", "exception", "failed", "not found", "permission denied", "invalid")):
            return msg

        # 任务阶段/耗时文案直接透传，避免被泛化映射覆盖。
        if any(k in msg for k in ("任务进度", "耗时", "渲染中", "水印中", "BGM中", "收尾中")):
            return msg

        # 终态/控制态直接返回，避免过度包装。
        if any(k in msg for k in ("处理完成", "处理失败", "已暂停", "继续处理", "已请求取消", "任务完成", "任务失败")):
            return msg

        if any(k in msg for k in ("获取图片列表", "读取图片", "加载图片", "随机选择图片", "按名称排序", "图片数量", "找到")):
            return "正在读取图片"
        if any(k in msg for k in ("正在生成第", "生成第", "视频")):
            return "正在合成视频"
        if any(k in msg for k in ("转场", "RANDOM")):
            return "正在合成转场"
        if any(k in msg for k in ("水印", "watermark")):
            return "正在添加水印"
        if any(k in msg.lower() for k in ("bgm", "audio", "音频", "add_audio")):
            return "正在添加BGM"
        if any(k in msg for k in ("FFmpeg", "ffmpeg", "编码", "写入", "vcodec", "probe", "视频合成", "输出文件")):
            return "正在编码输出"

        return "任务执行中"

    def _handle_worker_line(self, tab_index: int, line: str) -> None:
        state = self._get_tab_worker_state(tab_index)
        try:
            payload = json.loads(line)
        except Exception:
            if self.tabs.currentIndex() == tab_index:
                self._set_status(self._format_processing_status(line))
            return
        typ = payload.get("type")
        if typ == "status":
            raw_message = str(payload.get("message", "")).strip()
            if raw_message:
                state["last_worker_raw_status_text"] = raw_message
            formatted = self._format_processing_status(raw_message)
            state["last_worker_status_text"] = formatted
            last_worker_phase = str(state.get("last_worker_phase", ""))
            last_worker_elapsed_sec = state.get("last_worker_elapsed_sec")
            if formatted == "任务执行中" and last_worker_phase:
                if self.tabs.currentIndex() == tab_index:
                    if last_worker_elapsed_sec is not None:
                        self._set_status(f"{last_worker_phase} | 耗时 {last_worker_elapsed_sec}s")
                    else:
                        self._set_status(last_worker_phase)
            else:
                if self.tabs.currentIndex() == tab_index:
                    self._set_status(formatted)
            self._set_processing_status_ui(tab_index, formatted)
        elif typ == "progress":
            percent = int(payload.get("percent", 0))
            overall = int(payload.get("overall", percent))
            speed = payload.get("speed")
            self._set_processing_progress_ui(tab_index, percent=percent, overall=overall, speed=speed)
            phase = str(payload.get("phase", "") or "").strip()
            elapsed_sec = payload.get("elapsed_sec", None)
            if phase:
                state["last_worker_phase"] = phase
            if elapsed_sec is not None:
                state["last_worker_elapsed_sec"] = elapsed_sec
            if phase:
                if elapsed_sec is not None:
                    if self.tabs.currentIndex() == tab_index:
                        self._set_status(f"{phase} | 耗时 {elapsed_sec}s")
                else:
                    if self.tabs.currentIndex() == tab_index:
                        self._set_status(phase)
            else:
                last_worker_phase = str(state.get("last_worker_phase", ""))
                last_worker_elapsed_sec = state.get("last_worker_elapsed_sec")
                if last_worker_phase and self.tabs.currentIndex() == tab_index:
                    if last_worker_elapsed_sec is not None:
                        self._set_status(f"{last_worker_phase} | 耗时 {last_worker_elapsed_sec}s")
                    else:
                        self._set_status(last_worker_phase)
        elif typ == "done":
            success = bool(payload.get("success", False))
            if success:
                self._set_processing_progress_ui(tab_index, percent=100, overall=100)
                state["last_worker_phase"] = "收尾中"
            else:
                state["last_worker_status_text"] = "处理失败"
            if self.tabs.currentIndex() == tab_index:
                self._set_status("任务完成 - 处理完成" if success else "任务失败 - 处理失败")

    def _terminate_tab_worker(self, tab_index: int, wait_ms: int = 1500) -> None:
        state = self._get_tab_worker_state(tab_index)
        process = state.get("process")
        if not isinstance(process, QProcess) or process.state() == QProcess.NotRunning:
            self._cleanup_control_file(tab_index)
            return
        self._write_control_file(tab_index, cancel=True, paused=False)
        try:
            process.terminate()
            process.waitForFinished(wait_ms)
            if process.state() != QProcess.NotRunning:
                process.kill()
                process.waitForFinished(500)
        except Exception:
            pass
        self._cleanup_control_file(tab_index)

    def _animate_preview(self) -> None:
        if not self._preview_playing:
            self._preview_anim_timer.stop()
            return
        if not self._preview_frames:
            self._stop_preview_playback()
            return
        transition_mode = self.use_transition_check.isChecked()
        next_index = (self._preview_frame_index + 1) % len(self._preview_frames) if transition_mode else self._preview_frame_index
        self._preview_phase += 0.08
        self._render_preview_current_frame()
        self._update_preview_timeline_ui()

        frame_hold_ticks = self._preview_frame_hold_ticks()
        self._preview_frame_tick += 1
        self._preview_total_tick += 1
        if transition_mode and self._preview_frame_tick >= frame_hold_ticks:
            self._preview_frame_tick = 0
            self._preview_frame_index = next_index

    def _render_preview_pixmap(self, pix: QPixmap) -> None:
        if pix.isNull():
            return
        view = self.preview_label.size()
        fitted = pix.scaled(max(1, view.width() - 10), max(1, view.height() - 10), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(fitted)
        self.preview_label.setText("")

    def _preview_frame_hold_ticks(self) -> int:
        seconds = max(0.2, float(self.duration_spin.value()))
        # 预览节奏更快：每张图显示时长最多 1.5 秒
        fast_seconds = min(1.5, max(0.35, seconds * 0.35))
        return max(6, int(fast_seconds * self._preview_fps()))

    def _preview_fps(self) -> int:
        ui_fps = int(self.fps_spin.value()) if hasattr(self, "fps_spin") else 25
        # 预览帧率跟随输出FPS但限制在可交互范围内，避免UI线程过载。
        return max(12, min(30, ui_fps))

    def _preview_tick_interval_ms(self) -> int:
        return max(16, int(1000 / self._preview_fps()))

    def _preview_target_size(self) -> tuple[int, int]:
        w = max(320, self.preview_label.width())
        h = max(180, self.preview_label.height())
        # 给动效留余量，避免缩放时马上糊掉。
        return min(1920, int(w * 1.4)), min(1080, int(h * 1.4))

    def _build_preview_cache_key(self) -> str:
        input_dir = self.input_dir_edit.text().strip()
        mode = self.image_selection_combo.currentText()
        target_w, target_h = self._preview_target_size()
        if not input_dir or not os.path.isdir(input_dir):
            return f"invalid|{mode}|{target_w}x{target_h}"
        files = []
        latest_mtime = 0.0
        for name in os.listdir(input_dir):
            lower = name.lower()
            if lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
                path = os.path.join(input_dir, name)
                files.append(name)
                try:
                    latest_mtime = max(latest_mtime, os.path.getmtime(path))
                except Exception:
                    pass
        files.sort()
        signature = "|".join(files[:32])
        return f"{input_dir}|{mode}|{target_w}x{target_h}|{len(files)}|{latest_mtime:.3f}|{signature}"

    def _invalidate_preview_cache(self, *_args) -> None:
        had_preview = bool(self._preview_frames) or self._preview_has_rendered
        self._preview_frames = []
        self._preview_cache_key = ""
        self._preview_frame_index = 0
        self._preview_frame_tick = 0
        self._preview_total_tick = 0
        self._preview_error_reported = False
        self._preview_transition_cache.clear()
        self._preview_asset_cache.clear()
        self._preview_frame_bgr_cache.clear()
        self._release_preview_video_resources()
        self._preview_selected_transition = ""
        self._preview_selected_effect = ""
        self._preview_selected_bgm = ""
        self._preview_selected_video_watermark = ""
        self._preview_selected_image_watermarks = {}
        if hasattr(self, "preview_timeline_slider"):
            self.preview_timeline_slider.blockSignals(True)
            self.preview_timeline_slider.setValue(0)
            self.preview_timeline_slider.blockSignals(False)
        if hasattr(self, "preview_timecode_label"):
            self.preview_timecode_label.setText("00:00.0 / 00:00.0")
        if had_preview and not self._preview_stale:
            self._preview_stale = True
            if not self._preview_playing:
                self._set_status("预览已过期，点击刷新/播放重新生成")

    def _show_preview_discovery_hint_once(self) -> None:
        if self._preview_hint_shown_once:
            return
        self._preview_hint_shown_once = True
        self._set_status("提示：单击预览窗口可播放/暂停")

    def _validate_preview_inputs(self) -> str:
        input_dir = self.input_dir_edit.text().strip()
        if not input_dir:
            return "预览失败：请先选择输入目录"
        if not os.path.isdir(input_dir):
            return "预览失败：输入目录无效"
        if int(self.num_images_spin.value()) <= 0:
            return "预览失败：参数无效（图片数必须大于0）"
        if int(self.fps_spin.value()) <= 0:
            return "预览失败：参数无效（FPS必须大于0）"
        if float(self.duration_spin.value()) <= 0:
            return "预览失败：参数无效（持续时间必须大于0）"
        return ""

    @staticmethod
    def _pixmap_to_bgr_frame(pix: QPixmap, target_size=None) -> np.ndarray | None:
        if pix.isNull():
            return None
        from PySide6.QtGui import QImage
        work = pix
        if target_size is not None:
            work = pix.scaled(target_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        image = work.toImage().convertToFormat(QImage.Format_RGB888)
        w = image.width()
        h = image.height()
        ptr = image.bits()
        bytes_per_line = image.bytesPerLine()
        data = np.frombuffer(ptr, dtype=np.uint8, count=h * bytes_per_line)
        # QImage 每行可能有对齐填充字节，先按行宽裁剪到 w*3 再 reshape，避免宽度非4字节对齐时报错。
        row_data = data.reshape((h, bytes_per_line))
        rgb = row_data[:, : w * 3].reshape((h, w, 3))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    def _pixmap_to_bgr_cached(self, pix: QPixmap) -> np.ndarray | None:
        if pix.isNull():
            return None
        key = str(pix.cacheKey())
        cached = self._preview_frame_bgr_cache.get(key)
        if cached is not None:
            return cached.copy()
        frame = self._pixmap_to_bgr_frame(pix)
        if frame is None:
            return None
        self._preview_frame_bgr_cache[key] = frame
        if len(self._preview_frame_bgr_cache) > 96:
            oldest = next(iter(self._preview_frame_bgr_cache.keys()))
            self._preview_frame_bgr_cache.pop(oldest, None)
        return frame.copy()

    @staticmethod
    def _bgr_frame_to_pixmap(frame: np.ndarray) -> QPixmap:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        from PySide6.QtGui import QImage
        qimg = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888).copy()
        return QPixmap.fromImage(qimg)

    @staticmethod
    def _center_crop_frame(frame: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
        h, w = frame.shape[:2]
        if w == target_w and h == target_h:
            return frame
        if w < target_w or h < target_h:
            scale = max(target_w / max(1, w), target_h / max(1, h))
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
            h, w = frame.shape[:2]
        x = max(0, (w - target_w) // 2)
        y = max(0, (h - target_h) // 2)
        return frame[y:y + target_h, x:x + target_w]

    @staticmethod
    def _is_video_file(path: str) -> bool:
        lower = str(path or "").lower()
        return lower.endswith((".mp4", ".mov", ".avi", ".mkv", ".webm"))

    @staticmethod
    def _is_image_file(path: str) -> bool:
        lower = str(path or "").lower()
        return lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp"))

    def _list_audio_files(self, directory: str) -> List[str]:
        if not directory or not os.path.isdir(directory):
            return []
        result: List[str] = []
        for name in os.listdir(directory):
            lower = name.lower()
            if lower.endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")):
                result.append(os.path.join(directory, name))
        result.sort()
        return result

    def _ensure_preview_audio_player(self) -> bool:
        if QMediaPlayer is None or QAudioOutput is None:
            return False
        if self._preview_audio_player is not None and self._preview_audio_output is not None:
            return True
        try:
            self._preview_audio_output = QAudioOutput(self)
            self._preview_audio_player = QMediaPlayer(self)
            self._preview_audio_player.setAudioOutput(self._preview_audio_output)
            return True
        except Exception:
            self._preview_audio_player = None
            self._preview_audio_output = None
            return False

    def _resolve_preview_bgm_source(self) -> str:
        if not self.use_bgm_check.isChecked():
            return ""
        mode = self.watermark_audio_combo.currentText()
        if mode in ("静音", "使用水印"):
            return ""
        files = self._list_audio_files(self.bgm_dir_edit.text().strip())
        self._preview_bgm_pool = files
        if not files:
            return ""
        if self._preview_selected_bgm and self._preview_selected_bgm in files:
            return self._preview_selected_bgm
        return files[0]

    def _refresh_preview_runtime_choices(self, force: bool = False) -> None:
        """预览会话级随机：与导出逻辑一致，随机项一次会话只抽取一次。"""
        # 转场
        if self.random_transition_check.isChecked() and self.enabled_transitions:
            if force or self._preview_selected_transition not in self.enabled_transitions:
                self._preview_selected_transition = random.choice(self.enabled_transitions)
        else:
            self._preview_selected_transition = self.transition_combo.currentText()

        # 特效
        if self.random_effect_check.isChecked() and self.enabled_video_effects:
            if force or self._preview_selected_effect not in self.enabled_video_effects:
                self._preview_selected_effect = random.choice(self.enabled_video_effects)
        else:
            self._preview_selected_effect = self.effect_combo.currentText()

        # BGM
        files = self._list_audio_files(self.bgm_dir_edit.text().strip())
        self._preview_bgm_pool = files
        if files:
            if self.random_bgm_check.isChecked():
                if force or self._preview_selected_bgm not in files:
                    self._preview_selected_bgm = random.choice(files)
            else:
                self._preview_selected_bgm = files[0]
        else:
            self._preview_selected_bgm = ""

        # 视频水印（文件夹模式按导出预期固定到当前视频索引，这里预览默认第1个视频）
        self._preview_selected_video_watermark = ""
        wm_path = self.watermark_path_edit.text().strip()
        if self.use_watermark_check.isChecked() and wm_path:
            if self.watermark_mode_combo.currentText() == "文件夹" and os.path.isdir(wm_path):
                candidates = []
                for name in os.listdir(wm_path):
                    full = os.path.join(wm_path, name)
                    if self._is_video_file(full):
                        candidates.append(full)
                candidates.sort()
                if candidates:
                    self._preview_selected_video_watermark = candidates[0]
            elif os.path.isfile(wm_path) and self._is_video_file(wm_path):
                self._preview_selected_video_watermark = wm_path

    def _play_preview_bgm(self) -> None:
        src = self._resolve_preview_bgm_source()
        if not src:
            self._stop_preview_bgm()
            return
        if not self._ensure_preview_audio_player():
            return
        try:
            volume = max(0.0, min(1.0, float(self.bgm_volume_spin.value())))
            self._preview_audio_output.setVolume(volume)
            if self._preview_audio_source != src:
                self._preview_audio_source = src
                self._preview_audio_player.setSource(QUrl.fromLocalFile(src))
                self._preview_audio_player.setPosition(0)
            self._preview_audio_player.play()
        except Exception:
            pass

    def _pause_preview_bgm(self) -> None:
        try:
            if self._preview_audio_player is not None:
                self._preview_audio_player.pause()
        except Exception:
            pass

    def _stop_preview_bgm(self) -> None:
        try:
            if self._preview_audio_player is not None:
                self._preview_audio_player.stop()
        except Exception:
            pass
        self._preview_audio_source = ""

    def _release_preview_video_resources(self) -> None:
        for data in self._preview_video_wm_cache.values():
            cap = data.get("cap") if isinstance(data, dict) else None
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass
        self._preview_video_wm_cache.clear()

    @staticmethod
    def _blend_with_mode(base: np.ndarray, overlay: np.ndarray, blend_mode: str, opacity: float) -> np.ndarray:
        alpha = max(0.0, min(1.0, float(opacity)))
        if alpha <= 0.0:
            return base
        base_f = base.astype(np.float32)
        over_f = overlay.astype(np.float32)
        mode = str(blend_mode or "正常")
        if mode == "滤色":
            mixed = 255.0 - ((255.0 - base_f) * (255.0 - over_f) / 255.0)
        elif mode == "正片叠底":
            mixed = (base_f * over_f) / 255.0
        elif mode == "叠加":
            low = 2.0 * base_f * over_f / 255.0
            high = 255.0 - 2.0 * (255.0 - base_f) * (255.0 - over_f) / 255.0
            mixed = np.where(base_f < 128.0, low, high)
        elif mode == "变亮":
            mixed = np.maximum(base_f, over_f)
        elif mode == "变暗":
            mixed = np.minimum(base_f, over_f)
        elif mode == "相加":
            mixed = np.clip(base_f + over_f, 0.0, 255.0)
        else:
            mixed = over_f
        out = base_f * (1.0 - alpha) + mixed * alpha
        return np.clip(out, 0.0, 255.0).astype(np.uint8)

    def _calc_overlay_rect(
        self,
        main_w: int,
        main_h: int,
        overlay_w: int,
        overlay_h: int,
        size_mode: str,
        scale_value: float,
        position: str,
    ) -> tuple[int, int, int, int]:
        ratio = overlay_w / max(1, overlay_h)
        main_ratio = main_w / max(1, main_h)
        if size_mode == "自适应覆盖":
            if ratio > main_ratio:
                target_h = main_h
                target_w = int(target_h * ratio)
            else:
                target_w = main_w
                target_h = int(target_w / max(1e-6, ratio))
        elif size_mode == "完全覆盖":
            target_w, target_h = main_w, main_h
        else:
            target_w = max(1, int(main_w * (float(scale_value) / 100.0)))
            target_h = max(1, int(target_w / max(1e-6, ratio)))
        margin = 10 if size_mode == "固定比例" else 0
        if position == "左上":
            x, y = margin, margin
        elif position == "右上":
            x, y = main_w - target_w - margin, margin
        elif position == "左下":
            x, y = margin, main_h - target_h - margin
        elif position == "中心":
            x, y = (main_w - target_w) // 2, (main_h - target_h) // 2
        else:
            x, y = main_w - target_w - margin, main_h - target_h - margin
        return target_w, target_h, x, y

    def _read_video_frame_at(self, path: str, time_sec: float) -> np.ndarray | None:
        cache = self._preview_video_wm_cache.get(path)
        if cache is None:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                return None
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
            frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            cache = {
                "cap": cap,
                "fps": max(1.0, fps),
                "frames": max(1, frames),
                "last_idx": -1,
                "last_frame": None,
            }
            self._preview_video_wm_cache[path] = cache
        cap = cache["cap"]
        fps = float(cache["fps"])
        total = int(cache["frames"])
        idx = int(max(0.0, float(time_sec)) * fps) % max(1, total)
        last_idx = int(cache.get("last_idx", -1))
        if last_idx == idx and cache.get("last_frame") is not None:
            return cache["last_frame"].copy()
        try:
            if idx == (last_idx + 1):
                ok, frame = cap.read()
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ok, frame = cap.read()
            if ok and frame is not None:
                cache["last_idx"] = idx
                cache["last_frame"] = frame
                return frame
        except Exception:
            return None
        return None

    def _resolve_preview_video_watermark_path(self) -> str:
        if not self.use_watermark_check.isChecked():
            return ""
        if self._preview_selected_video_watermark and os.path.exists(self._preview_selected_video_watermark):
            return self._preview_selected_video_watermark
        return ""

    def _apply_video_watermark_preview(self, frame: np.ndarray, time_sec: float) -> np.ndarray:
        wm_path = self._resolve_preview_video_watermark_path()
        if not wm_path:
            return frame
        wm = self._read_video_frame_at(wm_path, time_sec)
        if wm is None:
            return frame
        h, w = frame.shape[:2]
        wh, ww = wm.shape[:2]
        size_mode = self.watermark_size_mode_combo.currentText()
        tw, th, x, y = self._calc_overlay_rect(
            w, h, ww, wh, size_mode=size_mode, scale_value=100.0, position="中心"
        )
        resized = cv2.resize(wm, (max(1, tw), max(1, th)), interpolation=cv2.INTER_LINEAR)
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(w, x + resized.shape[1])
        y2 = min(h, y + resized.shape[0])
        if x2 <= x1 or y2 <= y1:
            return frame
        sx1 = max(0, -x)
        sy1 = max(0, -y)
        sx2 = sx1 + (x2 - x1)
        sy2 = sy1 + (y2 - y1)
        result = frame.copy()
        overlay_roi = resized[sy1:sy2, sx1:sx2]
        base_roi = result[y1:y2, x1:x2]
        mixed = self._blend_with_mode(base_roi, overlay_roi, self.watermark_blend_combo.currentText(), 0.85)
        result[y1:y2, x1:x2] = mixed
        return result

    def _load_image_asset(self, path: str) -> np.ndarray | None:
        cached = self._preview_asset_cache.get(path)
        if cached is not None:
            return cached.copy()
        img = None
        # Windows 下中文/特殊字符路径，cv2.imread 可能失败，优先使用 fromfile + imdecode。
        try:
            if os.path.isfile(path):
                raw = np.fromfile(path, dtype=np.uint8)
                if raw.size > 0:
                    img = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
        except Exception:
            img = None
        if img is None:
            img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        self._preview_asset_cache[path] = img
        return img.copy()

    def _apply_image_watermark_preview(self, frame: np.ndarray, time_sec: float) -> np.ndarray:
        if not self.use_image_watermark_check.isChecked():
            return frame
        layers = self._collect_watermark_layers_from_ui()
        if not layers:
            return frame
        result = frame.copy()
        h, w = result.shape[:2]
        for layer in layers:
            if not layer.get("enabled", True):
                continue
            path = str(layer.get("path", "")).strip()
            if not path:
                continue
            src = None
            if os.path.isdir(path):
                candidates = []
                for name in os.listdir(path):
                    full = os.path.join(path, name)
                    if self._is_image_file(full) or self._is_video_file(full):
                        candidates.append(full)
                candidates.sort()
                if candidates:
                    if bool(layer.get("folder_random_single", False)):
                        layer_key = f"{path}|{layer.get('position', '')}|{layer.get('size_mode', '')}|{layer.get('blend_mode', '')}"
                        chosen = self._preview_selected_image_watermarks.get(layer_key, "")
                        if chosen not in candidates:
                            chosen = random.choice(candidates)
                            self._preview_selected_image_watermarks[layer_key] = chosen
                    else:
                        chosen = candidates[self._preview_frame_index % len(candidates)]
                    if self._is_image_file(chosen):
                        src = self._load_image_asset(chosen)
                    else:
                        src = self._read_video_frame_at(chosen, time_sec)
            elif os.path.isfile(path) and self._is_image_file(path):
                src = self._load_image_asset(path)
            elif os.path.isfile(path) and self._is_video_file(path):
                src = self._read_video_frame_at(path, time_sec)
            if src is None:
                continue
            if src.shape[2] == 4:
                alpha_chan = src[:, :, 3].astype(np.float32) / 255.0
                src_rgb = src[:, :, :3]
            else:
                alpha_chan = None
                src_rgb = src[:, :, :3]
            sh, sw = src_rgb.shape[:2]
            tw, th, x, y = self._calc_overlay_rect(
                w, h, sw, sh,
                size_mode=str(layer.get("size_mode", "固定比例")),
                scale_value=float(layer.get("scale", 100.0)),
                position=str(layer.get("position", "中心")),
            )
            resized_rgb = cv2.resize(src_rgb, (max(1, tw), max(1, th)), interpolation=cv2.INTER_LINEAR)
            resized_alpha = None
            if alpha_chan is not None:
                resized_alpha = cv2.resize(alpha_chan, (max(1, tw), max(1, th)), interpolation=cv2.INTER_LINEAR)
            x1 = max(0, x)
            y1 = max(0, y)
            x2 = min(w, x + resized_rgb.shape[1])
            y2 = min(h, y + resized_rgb.shape[0])
            if x2 <= x1 or y2 <= y1:
                continue
            sx1 = max(0, -x)
            sy1 = max(0, -y)
            sx2 = sx1 + (x2 - x1)
            sy2 = sy1 + (y2 - y1)
            overlay_roi = resized_rgb[sy1:sy2, sx1:sx2]
            base_roi = result[y1:y2, x1:x2]
            opacity = float(layer.get("opacity", 1.0))
            if resized_alpha is not None:
                alpha_roi = resized_alpha[sy1:sy2, sx1:sx2]
                alpha_roi = np.clip(alpha_roi * opacity, 0.0, 1.0)[:, :, None]
                blended = (base_roi.astype(np.float32) * (1.0 - alpha_roi) + overlay_roi.astype(np.float32) * alpha_roi)
                result[y1:y2, x1:x2] = np.clip(blended, 0.0, 255.0).astype(np.uint8)
            else:
                mixed = self._blend_with_mode(base_roi, overlay_roi, str(layer.get("blend_mode", "正常")), opacity)
                result[y1:y2, x1:x2] = mixed
        return result

    def _apply_basic_effect_preview_fallback(
        self,
        src: np.ndarray,
        effect: str,
        time_sec: float,
        intensity: float,
        speed: float,
    ) -> np.ndarray:
        """Qt 本地兜底特效：当 legacy 适配器不可用时仍可预览。"""
        h, w = src.shape[:2]
        intensity_scale = max(0.2, float(intensity) / 100.0)
        omega = 2.0 * np.pi * max(0.01, float(speed))
        phase = omega * float(time_sec)

        def _warp(scale: float = 1.0, angle: float = 0.0, tx: float = 0.0, ty: float = 0.0) -> np.ndarray:
            m = cv2.getRotationMatrix2D((w * 0.5, h * 0.5), angle, scale)
            m[0, 2] += tx
            m[1, 2] += ty
            return cv2.warpAffine(src, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        if effect in ("左右晃动", "波浪平移"):
            tx = 0.03 * w * intensity_scale * np.sin(phase)
            return _warp(scale=1.04 + 0.02 * intensity_scale, tx=tx)
        if effect in ("上下浮动",):
            ty = 0.03 * h * intensity_scale * np.sin(phase)
            return _warp(scale=1.04 + 0.02 * intensity_scale, ty=ty)
        if effect in ("旋转摆动", "旋转呼吸"):
            angle = 5.0 * intensity_scale * np.sin(phase)
            scale = 1.03 + 0.04 * intensity_scale * (0.5 - 0.5 * np.cos(phase))
            return _warp(scale=scale, angle=angle)
        if effect in ("镜头呼吸", "脉冲放大", "心跳跳动", "反复缩放"):
            scale = 1.02 + 0.10 * intensity_scale * (0.5 - 0.5 * np.cos(phase))
            resized = cv2.resize(src, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
            return self._center_crop_frame(resized, w, h)
        if effect in ("故障抖动", "镜头抖动呼吸"):
            tx = 0.012 * w * intensity_scale * np.sin(7.0 * phase)
            ty = 0.012 * h * intensity_scale * np.cos(6.0 * phase)
            return _warp(scale=1.02 + 0.04 * intensity_scale, tx=tx, ty=ty)

        if effect == "灵魂出窍":
            from ..core.video_effect_engine import apply_soul_out
            return apply_soul_out(src, time_sec, speed=speed, intensity=intensity_scale)

        # 通用回退：轻微呼吸，保证“有动效可见”。
        scale = 1.02 + 0.06 * intensity_scale * (0.5 - 0.5 * np.cos(phase))
        resized = cv2.resize(src, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
        return self._center_crop_frame(resized, w, h)

    def _get_legacy_effect_adapter(self):
        if self._legacy_effect_adapter is not None:
            return self._legacy_effect_adapter
        try:
            from src.gui.main_window import ImageToVideoTab
            adapter = object.__new__(ImageToVideoTab)
            self._legacy_effect_adapter = adapter
            return adapter
        except Exception:
            return None

    def _wire_preview_dependencies(self) -> None:
        self.input_dir_edit.textChanged.connect(self._invalidate_preview_cache)
        self.image_selection_combo.currentTextChanged.connect(self._invalidate_preview_cache)
        self.num_images_spin.valueChanged.connect(self._invalidate_preview_cache)
        self.fps_spin.valueChanged.connect(self._on_preview_fps_changed)
        self.use_effect_check.stateChanged.connect(self._on_preview_setting_changed)
        self.random_effect_check.stateChanged.connect(self._on_preview_setting_changed)
        self.effect_combo.currentTextChanged.connect(self._on_preview_setting_changed)
        self.effect_intensity_spin.valueChanged.connect(self._on_preview_setting_changed)
        self.effect_speed_spin.valueChanged.connect(self._on_preview_setting_changed)
        self.use_transition_check.stateChanged.connect(self._on_preview_setting_changed)
        self.random_transition_check.stateChanged.connect(self._on_preview_setting_changed)
        self.transition_combo.currentTextChanged.connect(self._on_preview_setting_changed)
        self.use_bgm_check.stateChanged.connect(self._on_preview_setting_changed)
        self.random_bgm_check.stateChanged.connect(self._on_preview_setting_changed)
        self.loop_bgm_check.stateChanged.connect(self._on_preview_setting_changed)
        self.bgm_dir_edit.textChanged.connect(self._on_preview_setting_changed)
        self.bgm_volume_spin.valueChanged.connect(self._on_preview_setting_changed)
        self.use_watermark_check.stateChanged.connect(self._on_preview_setting_changed)
        self.watermark_mode_combo.currentTextChanged.connect(self._on_preview_setting_changed)
        self.watermark_path_edit.textChanged.connect(self._on_preview_setting_changed)
        self.watermark_match_method_combo.currentTextChanged.connect(self._on_preview_setting_changed)
        self.watermark_size_mode_combo.currentTextChanged.connect(self._on_preview_setting_changed)
        self.watermark_blend_combo.currentTextChanged.connect(self._on_preview_setting_changed)
        self.watermark_audio_combo.currentTextChanged.connect(self._on_preview_setting_changed)
        self.use_image_watermark_check.stateChanged.connect(self._on_preview_setting_changed)

    def _on_preview_fps_changed(self, _value: int) -> None:
        if self._preview_anim_timer.isActive():
            self._preview_anim_timer.setInterval(self._preview_tick_interval_ms())

    def _on_preview_setting_changed(self, *_args) -> None:
        self._refresh_preview_runtime_choices(force=False)
        if self._preview_playing:
            self._play_preview_bgm()
        if not self._preview_frames:
            return
        self._preview_frame_tick = 0
        # 纯特效模式下锁定单图；若同时启用转场，则按转场节奏切图并叠加特效。
        if self.use_effect_check.isChecked() and not self.use_transition_check.isChecked():
            self._preview_frame_index = min(self._preview_frame_index, len(self._preview_frames) - 1)
        if self._preview_playing:
            if not self._preview_anim_timer.isActive():
                self._preview_anim_timer.setInterval(self._preview_tick_interval_ms())
                self._preview_anim_timer.start()
            return
        self._render_preview_current_frame()

    def _effective_transition_name(self) -> str:
        return self._preview_selected_transition or self.transition_combo.currentText()

    def _effective_effect_name_for(self, frame_index: int) -> str:
        return self._preview_selected_effect or self.effect_combo.currentText()

    def _preview_cycle_ticks(self) -> int:
        frame_hold_ticks = self._preview_frame_hold_ticks()
        if self.use_transition_check.isChecked() and self._preview_frames:
            return max(1, len(self._preview_frames) * frame_hold_ticks)
        return max(1, frame_hold_ticks)

    def _update_preview_timeline_ui(self) -> None:
        if not hasattr(self, "preview_timeline_slider"):
            return
        cycle_ticks = self._preview_cycle_ticks()
        fps = max(1.0, float(self._preview_fps()))
        current_sec = float(self._preview_total_tick) / fps
        total_sec = float(cycle_ticks) / fps
        ratio = 0.0 if cycle_ticks <= 0 else (float(self._preview_total_tick % cycle_ticks) / float(cycle_ticks))
        slider_value = int(max(0, min(1000, round(ratio * 1000))))
        self.preview_timeline_slider.blockSignals(True)
        self.preview_timeline_slider.setValue(slider_value)
        self.preview_timeline_slider.blockSignals(False)
        if hasattr(self, "preview_timecode_label"):
            self.preview_timecode_label.setText(
                f"{int(current_sec // 60):02d}:{current_sec % 60:04.1f} / {int(total_sec // 60):02d}:{total_sec % 60:04.1f}"
            )

    def _seek_preview_to_ratio(self, ratio: float) -> None:
        if not self._preview_frames:
            return
        ratio = max(0.0, min(1.0, float(ratio)))
        cycle_ticks = self._preview_cycle_ticks()
        target_tick = int(round(ratio * cycle_ticks))
        target_tick = max(0, min(cycle_ticks - 1, target_tick))
        self._preview_total_tick = target_tick
        frame_hold_ticks = self._preview_frame_hold_ticks()
        if self.use_transition_check.isChecked() and self._preview_frames:
            self._preview_frame_index = min(len(self._preview_frames) - 1, target_tick // max(1, frame_hold_ticks))
            self._preview_frame_tick = target_tick % max(1, frame_hold_ticks)
        else:
            self._preview_frame_tick = target_tick % max(1, frame_hold_ticks)
            self._preview_frame_index = min(self._preview_frame_index, len(self._preview_frames) - 1)
        self._render_preview_current_frame()
        self._update_preview_timeline_ui()

    def _on_preview_timeline_pressed(self) -> None:
        self._preview_scrubbing = True
        self._preview_scrub_restore_playing = bool(self._preview_playing)
        if self._preview_playing:
            self._preview_playing = False
            self._preview_anim_timer.stop()
            self._pause_preview_bgm()

    def _on_preview_timeline_released(self) -> None:
        self._preview_scrubbing = False
        if self._preview_scrub_restore_playing:
            self._preview_playing = True
            if not self._preview_anim_timer.isActive():
                self._preview_anim_timer.setInterval(self._preview_tick_interval_ms())
                self._preview_anim_timer.start()
            self._play_preview_bgm()
        self._preview_scrub_restore_playing = False

    def _on_preview_timeline_changed(self, value: int) -> None:
        if not self._preview_frames:
            return
        self._seek_preview_to_ratio(float(value) / 1000.0)

    def _randomize_preview_parameters(self) -> None:
        changed = []
        old_transition = self._preview_selected_transition
        old_effect = self._preview_selected_effect
        old_bgm = self._preview_selected_bgm
        old_image_wm = dict(self._preview_selected_image_watermarks)
        self._preview_selected_image_watermarks = {}
        self._refresh_preview_runtime_choices(force=True)
        if self.random_transition_check.isChecked() and self._preview_selected_transition:
            if self._preview_selected_transition != old_transition:
                changed.append(f"转场={self._preview_selected_transition}")
        if self.random_effect_check.isChecked() and self._preview_selected_effect:
            if self._preview_selected_effect != old_effect:
                changed.append(f"特效={self._preview_selected_effect}")
        if self.random_bgm_check.isChecked() and self._preview_selected_bgm:
            if self._preview_selected_bgm != old_bgm:
                changed.append(f"BGM={os.path.basename(self._preview_selected_bgm)}")
        if old_image_wm != self._preview_selected_image_watermarks and self._preview_selected_image_watermarks:
            changed.append("图片水印=已重抽")
        if changed:
            self._on_preview_setting_changed()
            self._update_preview_timeline_ui()
            self._set_status("随机参数: " + " | ".join(changed))
        else:
            self._set_status("随机参数未变化")

    def _render_preview_current_frame(self) -> None:
        if not self._preview_frames:
            return
        current = self._preview_frames[self._preview_frame_index]
        try:
            next_index = (self._preview_frame_index + 1) % len(self._preview_frames)
            next_pix = self._preview_frames[next_index]
            frame_hold_ticks = self._preview_frame_hold_ticks()
            transition_start = int(frame_hold_ticks * 0.7)
            progress = 0.0
            if self.use_transition_check.isChecked() and self._preview_frame_tick >= transition_start:
                denom = max(1, frame_hold_ticks - transition_start)
                progress = min(1.0, (self._preview_frame_tick - transition_start) / denom)

            transition_name = self._effective_transition_name()
            effect_name = self._effective_effect_name_for(self._preview_frame_index)
            transition_enabled = self.use_transition_check.isChecked()
            effect_enabled = self.use_effect_check.isChecked() and effect_name != "无特效"
            time_sec = float(self._preview_total_tick) / max(1.0, float(self._preview_fps()))

            # 统一实时预览管线：转场 -> 特效 -> 图片水印 -> 视频水印。
            base = self._compose_transition_pixmap(current, next_pix, progress, transition_name) if transition_enabled else current
            frame = self._pixmap_to_bgr_cached(base)
            if frame is not None:
                if effect_enabled:
                    frame = self._apply_effect_preview_frame(frame, effect_name, time_sec=time_sec)
                frame = self._apply_image_watermark_preview(frame, time_sec=time_sec)
                frame = self._apply_video_watermark_preview(frame, time_sec=time_sec)
                pix = self._bgr_frame_to_pixmap(frame)
            else:
                pix = base
            if pix.isNull():
                pix = current
            self._render_preview_pixmap(pix)
            self._preview_error_reported = False
        except Exception:
            # 任何异常都回退到原始帧，避免预览黑屏或完全不动。
            self._render_preview_pixmap(current)
            if not self._preview_error_reported:
                self._preview_error_reported = True
                self._set_status("预览渲染已回退：请检查特效/转场参数")

    def _collect_preview_frames(self) -> List[QPixmap]:
        invalid_reason = self._validate_preview_inputs()
        if invalid_reason:
            self._set_status(invalid_reason)
            return []

        input_dir = self.input_dir_edit.text().strip()

        image_paths: List[str] = []
        for name in os.listdir(input_dir):
            lower = name.lower()
            if lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
                image_paths.append(os.path.join(input_dir, name))
        if not image_paths:
            self._set_status("预览失败：目录中没有图片")
            return []

        mode = self.image_selection_combo.currentText()
        if mode == "按名称排序":
            image_paths = sorted(image_paths)
        else:
            random.shuffle(image_paths)
        image_paths = image_paths[: min(8, len(image_paths))]

        frames: List[QPixmap] = []
        target_w, target_h = self._preview_target_size()
        for path in image_paths:
            pix = QPixmap(path)
            if not pix.isNull():
                # 预加载阶段先降采样，降低后续每帧变换与缩放开销。
                if pix.width() > target_w or pix.height() > target_h:
                    pix = pix.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                frames.append(pix)
        if not frames:
            self._set_status("预览失败：图片损坏或格式不支持")
        return frames

    def _start_preview_playback(self, force_rebuild: bool = False) -> None:
        self._show_preview_discovery_hint_once()

        invalid_reason = self._validate_preview_inputs()
        if invalid_reason:
            self._set_status(invalid_reason)
            return

        cache_key = self._build_preview_cache_key()
        need_rebuild = force_rebuild or not self._preview_frames or cache_key != self._preview_cache_key
        if need_rebuild:
            self._preview_frames = self._collect_preview_frames()
            self._preview_cache_key = cache_key
            self._preview_frame_index = 0
            self._preview_frame_tick = 0
            self._preview_total_tick = 0
            self._preview_phase = 0.0
        self._refresh_preview_runtime_choices(force=True)
        if not self._preview_frames:
            return
        self._preview_playing = True
        self._preview_stale = False
        self._preview_has_rendered = True
        self.preview_play_btn.setEnabled(False)
        self.preview_pause_btn.setEnabled(True)
        self._preview_anim_timer.setInterval(self._preview_tick_interval_ms())
        if not self._preview_anim_timer.isActive():
            self._preview_anim_timer.start()
        self._play_preview_bgm()
        self._update_preview_timeline_ui()
        self._render_preview_current_frame()
        self._set_status("预览播放中（已应用特效/转场设置）")

    def _toggle_preview_playback(self) -> None:
        if self._preview_playing:
            self._pause_preview_playback()
            return
        self._start_preview_playback()

    def _pause_preview_playback(self) -> None:
        if not self._preview_playing:
            return
        self._preview_playing = False
        self._preview_anim_timer.stop()
        self._pause_preview_bgm()
        self._update_preview_timeline_ui()
        self.preview_play_btn.setEnabled(True)
        self.preview_pause_btn.setEnabled(False)
        self._set_status("预览已暂停")

    def _stop_preview_playback(self) -> None:
        self._preview_playing = False
        self._preview_anim_timer.stop()
        self._stop_preview_bgm()
        self._invalidate_preview_cache()
        self._update_preview_timeline_ui()
        self.preview_play_btn.setEnabled(True)
        self.preview_pause_btn.setEnabled(False)

    def _compose_transition_pixmap(self, current: QPixmap, next_pix: QPixmap, progress: float, transition: str | None = None) -> QPixmap:
        if progress <= 0.0 or not self.use_transition_check.isChecked():
            return current
        progress = max(0.0, min(1.0, progress))

        current_size = current.size()
        if current_size.isEmpty():
            return current
        transition = transition or self.transition_combo.currentText()
        base_current = current.scaled(current_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        next_scaled = next_pix.scaled(current_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)

        try:
            cache_key = f"{base_current.cacheKey()}::{next_scaled.cacheKey()}::{transition}::{current_size.width()}x{current_size.height()}"
            frames = self._preview_transition_cache.get(cache_key)
            if frames is None:
                img1 = self._pixmap_to_bgr_frame(base_current, current_size)
                img2 = self._pixmap_to_bgr_frame(next_scaled, current_size)
                if img1 is None or img2 is None:
                    return base_current
                np_frames = self._preview_transition_engine.generate_transition_frames(
                    img1,
                    img2,
                    transition,
                    num_frames=24,
                    use_cache=True,
                )
                frames = [self._bgr_frame_to_pixmap(f) for f in np_frames if f is not None]
                if not frames:
                    return base_current
                self._preview_transition_cache[cache_key] = frames
                if len(self._preview_transition_cache) > 24:
                    oldest_key = next(iter(self._preview_transition_cache.keys()))
                    self._preview_transition_cache.pop(oldest_key, None)

            idx = min(len(frames) - 1, max(0, int(round(progress * (len(frames) - 1)))))
            return frames[idx]
        except Exception:
            # 回退：至少保证可见，避免因单个转场异常导致黑屏。
            canvas = QPixmap(current_size)
            canvas.fill(Qt.transparent)
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.setOpacity(1.0 - progress)
            painter.drawPixmap(0, 0, base_current)
            painter.setOpacity(progress)
            painter.drawPixmap(0, 0, next_scaled)
            painter.end()
            return canvas

    def _apply_effect_preview(self, pix: QPixmap, effect: str | None = None, time_sec: float | None = None) -> QPixmap:
        if pix.isNull() or not self.use_effect_check.isChecked():
            return pix
        effect = effect or self.effect_combo.currentText()
        if effect == "无特效":
            return pix
        try:
            src = self._pixmap_to_bgr_frame(pix)
            if src is None:
                return pix
            out = self._apply_effect_preview_frame(src, effect=effect, time_sec=time_sec)
            if out is None:
                return pix
            return self._bgr_frame_to_pixmap(out)
        except Exception:
            return pix

    def _apply_effect_preview_frame(
        self,
        src: np.ndarray,
        effect: str | None = None,
        time_sec: float | None = None,
    ) -> np.ndarray | None:
        if src is None:
            return None
        effect = effect or self.effect_combo.currentText()
        if effect == "无特效":
            return src
        try:
            speed = max(0.01, float(self.effect_speed_spin.value()))
            # 固定循环周期，删除“特效预览秒数”后保持特效预览无限循环。
            duration_sec = 4.0
            # 与播放时钟同步，保持“实时变更立即可见”。
            # 预览时间轴使用统一预览FPS，避免引用不存在控件导致特效渲染被异常吞掉。
            if time_sec is None:
                time_sec = float(self._preview_total_tick) / max(1.0, float(self._preview_fps()))
            time_sec = float(time_sec) % duration_sec
            intensity = float(self.effect_intensity_spin.value())
            out = None

            # 优先使用 legacy 实现（效果最全），失败则降级到 Qt 本地兜底实现。
            adapter = self._get_legacy_effect_adapter()
            if adapter is not None:
                try:
                    out = adapter.apply_single_image_effect(
                        src,
                        effect,
                        time_sec=time_sec,
                        duration_sec=duration_sec,
                        intensity=intensity,
                        speed=speed,
                    )
                except Exception:
                    out = None

            if out is None:
                out = self._apply_basic_effect_preview_fallback(
                    src=src,
                    effect=effect,
                    time_sec=time_sec,
                    intensity=intensity,
                    speed=speed,
                )

            if out is None:
                return src
            return out
        except Exception:
            return src

    def _show_performance_stats(self) -> None:
        try:
            from optimization import get_turbo_accelerator
            stats = get_turbo_accelerator().get_performance_stats()
            lines = [f"{k}: {v}" for k, v in stats.items()]
            QMessageBox.information(self, "性能统计", "\n".join(lines))
            self._set_status("已显示性能统计")
        except Exception as exc:
            QMessageBox.warning(self, "性能统计失败", str(exc))

    def _toggle_theme(self) -> None:
        self._dark_theme_enabled = not self._dark_theme_enabled
        self._apply_theme()
        self._set_status("已切换深色主题" if self._dark_theme_enabled else "已切换浅色主题")

    def _apply_theme(self) -> None:
        self.setStyleSheet(DARK_THEME_QSS if self._dark_theme_enabled else LIGHT_THEME_QSS)
        if hasattr(self, "theme_toggle_btn") and self.theme_toggle_btn is not None:
            self.theme_toggle_btn.setText("切换浅色" if self._dark_theme_enabled else "切换深色")

    def _optimize_memory(self) -> None:
        try:
            from optimization import get_turbo_accelerator
            get_turbo_accelerator().force_memory_optimization()
            self._set_status("内存优化完成")
        except Exception as exc:
            QMessageBox.warning(self, "内存优化失败", str(exc))

    def _set_status(self, msg: str) -> None:
        text = str(msg or "").strip()
        if len(text) > 42:
            text = text[:42] + "..."
        self.status_label.setText(f"状态: {text}")
        if hasattr(self, "status_hint_label"):
            self.status_hint_label.setText(f"✓ {text}")

    def closeEvent(self, event) -> None:
        try:
            self._save_current_tab_context()
        except Exception:
            pass
        self._save_ui_state()
        self._stop_preview_playback()
        self._release_preview_video_resources()
        try:
            for idx in range(len(self.tab_contexts)):
                self._terminate_tab_worker(idx)
        except Exception:
            pass
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_rules(event.size().width(), force=False)

    @staticmethod
    def _parse_resolution(text: str) -> tuple[int, int]:
        parts = (text or "").lower().replace(" ", "").split("x")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]), int(parts[1])
        return 720, 1280
