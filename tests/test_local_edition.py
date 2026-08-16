import os
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def test_excluded_modules_are_not_published():
    excluded = (
        ROOT / "src" / "plugins" / "capcut",
        ROOT / "src" / "gui_qt" / "remote_service.py",
        ROOT / "src" / "gui_qt" / "connect_wizard.py",
        ROOT / "src" / "services" / "frp_manager.py",
        ROOT / "src" / "services" / "video_http_service.py",
        ROOT / "service_main.py",
        ROOT / "run_capcut_workflow.py",
    )
    assert not [path for path in excluded if path.exists()]


def test_local_sources_have_no_excluded_imports():
    forbidden = (
        "plugins.capcut",
        "gui_qt.remote_service",
        "gui_qt.connect_wizard",
        "services.frp_manager",
        "services.video_http_service",
        "RemoteServiceDock",
        "CapCutEffectConfig",
    )
    source_files = [ROOT / "main_qt.py", *sorted((ROOT / "src").rglob("*.py"))]
    matches = []
    for source_file in source_files:
        text = source_file.read_text(encoding="utf-8")
        for value in forbidden:
            if value in text:
                matches.append(f"{source_file.relative_to(ROOT)}: {value}")
    assert matches == []


def test_qt_window_starts_as_local_edition():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from src.gui_qt.main_window import QtMainWindow

    app = QApplication.instance() or QApplication([])
    window = QtMainWindow()
    try:
        assert window.windowTitle() == "图转视频极速版"
        assert not hasattr(window, "remote_service_dock")
        assert not hasattr(window, "remote_service_btn")
    finally:
        window.close()
        app.processEvents()


def test_qt_video_watermark_preview_keeps_effects_visible():
    from src.gui_qt.main_window import QtMainWindow

    base = np.full((2, 2, 3), 200, dtype=np.uint8)
    watermark = np.zeros_like(base)
    alpha = QtMainWindow._video_watermark_alpha("正常")
    mixed = QtMainWindow._blend_with_mode(base, watermark, "正常", alpha)

    assert alpha == 0.50
    assert np.all(mixed == 100)
