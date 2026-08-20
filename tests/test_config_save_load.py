#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
预设保存/加载完整性测试。

背景：save_config 漏保存 watermark_mode（水印模式 单文件/文件夹）与
bgm_files（素材库显式选定的 BGM 文件列表），导致保存配置后重开丢失。

修复：save_config / load_config 均已补齐这两个键。
本测试验证：保存 → 重置 → 加载 往返后参数完整恢复。
"""

from __future__ import annotations

import os
import tempfile

import pytest

from src.gui.main_window import ImageToVideoTab


def _require_tk():
    """创建隐藏 Tk 根窗口；环境不支持时跳过测试（如无桌面会话）。"""
    try:
        import tkinter as tk
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk 不可用，跳过 GUI 测试：{exc}")
    root.withdraw()
    return root


def _make_app(root, config_file):
    app = ImageToVideoTab(root, config_file=config_file)
    return app


def test_save_load_roundtrip_complete():
    """保存的配置参数必须完整：watermark_mode / bgm_files 及其它关键参数往返不丢。"""
    root = _require_tk()
    tmp_dir = tempfile.mkdtemp(prefix="dsh_preset_")
    config_file = os.path.join(tmp_dir, "config.json")

    # 1) 设置一组代表性参数（含曾被漏掉的 watermark_mode / bgm_files）
    app1 = _make_app(root, config_file)
    app1.watermark_mode.set("文件夹")
    app1._bgm_files = [r"C:\music\a.mp3", r"C:\music\b.wav"]
    app1.duration.set(3.0)
    app1.total_duration.set(0.0)
    app1.fps.set(30)
    app1.num_images.set(5)
    app1.video_count.set(2)
    app1.codec_var.set("H264")
    app1.bitrate.set(4000)
    app1.use_date_prefix.set(False)
    app1.custom_prefix.set("我的前缀")
    app1.use_bgm.set(True)
    app1.bgm_dir.set(r"C:\music")
    app1.loop_bgm.set(False)
    app1.save_config(show_message=False)
    app1.parent.destroy()

    # 2) 用全新实例加载同一文件
    root2 = _require_tk()
    app2 = _make_app(root2, config_file)
    app2.load_config()

    try:
        assert app2.watermark_mode.get() == "文件夹", "watermark_mode 未恢复"
        assert app2._bgm_files == [r"C:\music\a.mp3", r"C:\music\b.wav"], "bgm_files 未恢复"
        assert float(app2.duration.get()) == 3.0
        assert int(app2.fps.get()) == 30
        assert int(app2.num_images.get()) == 5
        assert int(app2.video_count.get()) == 2
        assert app2.codec_var.get() == "H264"
        assert int(app2.bitrate.get()) == 4000
        assert bool(app2.use_date_prefix.get()) is False
        assert app2.custom_prefix.get() == "我的前缀"
        assert bool(app2.use_bgm.get()) is True
        assert app2.bgm_dir.get() == r"C:\music"
        assert bool(app2.loop_bgm.get()) is False
    finally:
        app2.parent.destroy()
        for f in os.listdir(tmp_dir):
            try:
                os.remove(os.path.join(tmp_dir, f))
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


def test_save_config_contains_all_schema_keys():
    """save_config 产出的键必须覆盖引擎配置 schema 中的全部用户参数。"""
    from src.engine.config import build_default_config
    from src.gui.main_window import ImageToVideoTab

    schema = build_default_config()
    # 内部标记键（非用户参数）
    schema_keys = {k for k in schema.keys() if not k.startswith("_")}

    root = _require_tk()
    tmp_dir = tempfile.mkdtemp(prefix="dsh_preset_")
    config_file = os.path.join(tmp_dir, "config.json")
    app = ImageToVideoTab(root, config_file=config_file)
    try:
        app.save_config(show_message=False)
        with open(config_file, "r", encoding="utf-8") as f:
            import json
            saved = json.load(f)
        missing = sorted(schema_keys - set(saved.keys()))
        # width/height 由 resolution_preset 派生，允许缺失；其余必须齐全
        missing = [k for k in missing if k not in ("width", "height", "use_image_watermark")]
        assert not missing, f"save_config 缺失参数: {missing}"
    finally:
        app.parent.destroy()
        for f in os.listdir(tmp_dir):
            try:
                os.remove(os.path.join(tmp_dir, f))
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass
