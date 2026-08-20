#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
图片水印文件夹模式测试。

背景：
1. 水印图层"浏览"只能选单个文件，无法选择文件夹；
2. 文件夹模式（多张水印图）未勾选"目录随机1个"时按 image_index 顺序轮转贴图，
   用户要求改为随机贴（每次从目录水印中随机选一张）。

修复：
- 浏览按钮支持选择文件夹（UI 改动，此处不测）；
- _apply_image_watermark_layer：多图水印改为 random.choice 随机贴；
- _get_image_files_in_dir 支持 .webp/.tiff。
"""

from __future__ import annotations

import os
import tempfile

import cv2
import numpy as np
import pytest


def _require_tk():
    try:
        import tkinter as tk
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk 不可用，跳过 GUI 测试：{exc}")
    root.withdraw()
    return root


def _make_watermark_dir(tmp_dir: str, count: int = 3) -> str:
    """生成 count 张不同颜色的水印 PNG 目录。"""
    wm_dir = os.path.join(tmp_dir, "wm")
    os.makedirs(wm_dir, exist_ok=True)
    colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0), (255, 255, 0), (0, 255, 255)]
    for i in range(count):
        img = np.full((40, 40, 3), colors[i % len(colors)], dtype=np.uint8)
        cv2.imwrite(os.path.join(wm_dir, f"wm_{i}.png"), img)
    return wm_dir


def _base_image():
    return np.full((120, 120, 3), 200, dtype=np.uint8)


def test_folder_layers_loaded_all_images():
    """未勾选目录随机1个：文件夹内全部水印图都被加载。"""
    root = _require_tk()
    from src.gui.main_window import ImageToVideoTab

    app = ImageToVideoTab(root)
    try:
        tmp_dir = tempfile.mkdtemp(prefix="dsh_wm_")
        wm_dir = _make_watermark_dir(tmp_dir, 4)
        app.watermark_layers = [{
            "enabled": True, "type": "图片", "path": wm_dir,
            "position": "右下", "size_mode": "固定比例", "scale": 20.0,
            "blend_mode": "正常", "opacity": 1.0, "fixed": False,
            "folder_random_single": False,
        }]
        prepared = app._prepare_image_watermark_layers()
        assert len(prepared) == 1
        assert len(prepared[0]["images"]) == 4, "文件夹模式应加载全部水印图"
    finally:
        app.parent.destroy()


def test_folder_random_single_picks_one():
    """勾选目录随机1个：每次准备只随机挑 1 张，且整条视频固定使用该张。"""
    root = _require_tk()
    from src.gui.main_window import ImageToVideoTab

    app = ImageToVideoTab(root)
    try:
        tmp_dir = tempfile.mkdtemp(prefix="dsh_wm_")
        wm_dir = _make_watermark_dir(tmp_dir, 3)
        app.watermark_layers = [{
            "enabled": True, "type": "图片", "path": wm_dir,
            "position": "右下", "size_mode": "固定比例", "scale": 20.0,
            "blend_mode": "正常", "opacity": 1.0, "fixed": False,
            "folder_random_single": True,
        }]
        prepared = app._prepare_image_watermark_layers()
        assert len(prepared) == 1
        assert len(prepared[0]["images"]) == 1, "目录随机1个应只保留 1 张"
        # 同一 prepared 层多次贴图结果一致（固定一张）
        base1 = _base_image()
        base2 = _base_image()
        out1 = app.apply_image_watermark_layers(base1, prepared, image_index=0)
        out2 = app.apply_image_watermark_layers(base2, prepared, image_index=5)
        assert np.array_equal(out1, out2), "目录随机1个：同一视频内应固定同一张水印"
    finally:
        app.parent.destroy()


def test_folder_multi_random_not_rotating():
    """未勾选目录随机1个：同一 image_index 多次贴图应出现随机变化（而非固定轮转）。"""
    root = _require_tk()
    from src.gui.main_window import ImageToVideoTab

    app = ImageToVideoTab(root)
    try:
        tmp_dir = tempfile.mkdtemp(prefix="dsh_wm_")
        wm_dir = _make_watermark_dir(tmp_dir, 3)
        app.watermark_layers = [{
            "enabled": True, "type": "图片", "path": wm_dir,
            "position": "右下", "size_mode": "固定比例", "scale": 20.0,
            "blend_mode": "正常", "opacity": 1.0, "fixed": False,
            "folder_random_single": False,
        }]
        prepared = app._prepare_image_watermark_layers()
        assert len(prepared[0]["images"]) == 3
        # 同一 image_index=0 连续贴 24 次，若为随机应出现至少 2 种水印
        # （轮转实现下同一 index 恒为同一种颜色，必然失败）
        outputs = []
        for _ in range(24):
            out = app.apply_image_watermark_layers(_base_image(), prepared, image_index=0)
            outputs.append(tuple(out[0, 0].tolist()))  # 水印在右下，但首像素为底色
            # 直接比较水印区域（右下 40x40 区域中心像素）
            outputs[-1] = tuple(out[95, 95].tolist())
        distinct = len(set(outputs))
        assert distinct >= 2, f"多图文件夹应随机贴图，但 24 次都得到同一种（{distinct} 种）"
    finally:
        app.parent.destroy()
