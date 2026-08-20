#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
视频时长回归测试：保证输出时长严格按设置生成。

背景：create_video / create_video_turbo_enhanced / create_video_with_ffmpeg
曾用 int(duration * fps) 截断帧数，且存在"每图至少 0.5 秒静态显示"的钳制逻辑，
导致每图时长 < 0.5 秒时（例如 0.1s/0.2s/0.3s）每张图被强制写到 0.5 秒，
输出视频远长于用户设置（0.1s x 5 张曾生成 2.5s）。

修复约定（见 src/gui/main_window.py 的 compute_video_frame_plan）：
- 每图帧数 = max(1, round(时长 × 帧率))，不做 int() 截断；
- 总帧数 = round(图片数 × 时长 × 帧率)，余数由最后一张图吸收，
  实际总时长与设置的偏差不超过半帧；
- 转场只减不增：静态帧 + 转场帧 ≡ 每图总帧数；
- 无转场时不做"每图至少 0.5 秒"的钳制。
"""

from __future__ import annotations

import pytest

from src.gui.main_window import compute_video_frame_plan


@pytest.mark.parametrize(
    "duration,fps,images",
    [
        (0.1, 30, 5),
        (0.2, 30, 5),
        (0.3, 30, 5),
        (0.4, 30, 5),
        (0.5, 30, 5),
        (0.3, 24, 8),
        (0.7, 25, 6),
        (1.0, 30, 5),
        (2.0, 30, 4),
        (3.0, 30, 10),
        (8.0, 30, 3),
        (2.5, 25, 4),
        (3.3, 24, 5),
    ],
)
def test_no_transition_duration_exact(duration, fps, images):
    """无转场：总帧数 = round(图片数 × 时长 × 帧率)，实际时长偏差 < 半帧。"""
    _, tf, _, last_img_frames = compute_video_frame_plan(images, duration, fps, 0, "无转场")
    assert tf == 0
    total_frames = (images - 1) * _per_img(images, duration, fps) + last_img_frames
    actual = total_frames / fps
    expected = duration * images
    assert abs(actual - expected) < 0.5 / fps


def _per_img(images, duration, fps):
    frames_per_img, _, _, last_img_frames = compute_video_frame_plan(images, duration, fps, 0, "无转场")
    return frames_per_img


@pytest.mark.parametrize(
    "duration,fps",
    [(0.1, 30), (0.2, 30), (0.3, 30), (0.4, 30), (0.3, 24), (0.5, 25)],
)
def test_short_duration_not_inflated(duration, fps):
    """回归：每图时长 < 0.5s 时不得被钳制抬升到 fps//2。"""
    frames_per_img, _, _, _ = compute_video_frame_plan(3, duration, fps, 0, "无转场")
    # 每图帧数必须严格等于 round(时长×帧率)——若存在"至少0.5秒"钳制，
    # 短时长会被抬升到 fps//2（例如 0.1s@30fps 被抬到 15 帧）
    assert frames_per_img == max(1, int(round(duration * fps)))
    assert frames_per_img <= fps // 2  # 未被钳制抬升（round 结果不可能超过 fps//2 的半帧范围）


def test_round_not_truncate():
    """回归：0.3s x 25fps = 7.5 帧应进位到 8，而不是 int() 截断成 7。"""
    frames_per_img, _, _, _ = compute_video_frame_plan(3, 0.3, 25, 0, "无转场")
    assert frames_per_img == 8


def test_with_transition_still_exact():
    """开转场：静态 + 转场 = 每图总帧数，总时长仍严格等于设置。"""
    frames_per_img, tf, display, _ = compute_video_frame_plan(5, 3.0, 30, 15, "淡入淡出")
    assert frames_per_img == 90
    assert tf == 15
    assert display == 75
    assert tf + display == frames_per_img


def test_transition_never_exceeds_total():
    """转场帧数只减不增：极端情况下转场不能把每图帧数撑大。"""
    for duration, fps in [(0.1, 30), (0.2, 30), (0.4, 30)]:
        frames_per_img, tf, display, _ = compute_video_frame_plan(5, duration, fps, 15, "淡入淡出")
        assert tf + display == frames_per_img
        assert 0 <= tf <= frames_per_img


def test_known_regression_case():
    """复现历史故障：0.1s x 5 张 @30fps 应生成 0.5s（曾错误生成 2.5s）。"""
    frames_per_img, tf, display, last_img_frames = compute_video_frame_plan(5, 0.1, 30, 0, "无转场")
    assert frames_per_img == 3
    assert display == 3
    total = (5 - 1) * frames_per_img + last_img_frames
    assert total == 15  # round(5 * 0.1 * 30) = 15
    assert total / 30 == 0.5
