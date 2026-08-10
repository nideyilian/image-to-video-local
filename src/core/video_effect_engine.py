#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Single-image effects shared by the local desktop interfaces."""

from __future__ import annotations

import math

import cv2
import numpy as np


VIDEO_EFFECT_NONE = "NONE"
VIDEO_EFFECT_SOUL_OUT = "SOUL_OUT"
VIDEO_EFFECTS = {VIDEO_EFFECT_NONE, VIDEO_EFFECT_SOUL_OUT}

# Jianying effect 634709 / GESticker_SoulScale, defaults: speed=0.33, range=1.0.
# Its shader mixes the source with one centre-scaled copy. The values below are
# the 16 discrete samples produced by the effect package at those defaults.
SOUL_OUT_CURVE_FPS = 29.85
SOUL_OUT_MIX_CURVE = (
    0.411498, 0.340743, 0.283781, 0.237625,
    0.199993, 0.169133, 0.143688, 0.122599,
    0.037117, 0.028870, 0.022595, 0.017788,
    0.010000, 0.010000, 0.010000, 0.010000,
)
SOUL_OUT_SCALE_CURVE = (
    1.6268295, 1.7598855, 1.899264, 2.0450655,
    2.1973845, 2.3563155, 2.521950, 2.694381,
    2.8736985, 3.0599925, 3.2533515, 3.453861,
    3.453861, 3.453861, 3.453861, 3.453861,
)

CAMERA_MOTIONS = {
    "STATIC", "ZOOM_IN", "ZOOM_OUT", "PAN_LEFT", "PAN_RIGHT", "PAN_UP", "PAN_DOWN"
}


def fit_cover(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """等比放大并居中裁剪到指定尺寸。"""
    source_h, source_w = image.shape[:2]
    scale = max(width / source_w, height / source_h)
    resized = cv2.resize(
        image,
        (max(width, int(round(source_w * scale))), max(height, int(round(source_h * scale)))),
        interpolation=cv2.INTER_LANCZOS4,
    )
    y = max(0, (resized.shape[0] - height) // 2)
    x = max(0, (resized.shape[1] - width) // 2)
    return resized[y:y + height, x:x + width].copy()


def apply_camera_motion(image: np.ndarray, motion: str, progress: float) -> np.ndarray:
    motion = str(motion or "STATIC").upper()
    if motion not in CAMERA_MOTIONS:
        raise ValueError("不支持的镜头运动")
    if motion == "STATIC":
        return image.copy()

    h, w = image.shape[:2]
    progress = float(np.clip(progress, 0.0, 1.0))
    if motion in {"ZOOM_IN", "ZOOM_OUT"}:
        amount = progress if motion == "ZOOM_IN" else 1.0 - progress
        scale = 1.0 + 0.12 * amount
        resized = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
        x = (resized.shape[1] - w) // 2
        y = (resized.shape[0] - h) // 2
        return resized[y:y + h, x:x + w]

    scale = 1.12
    resized = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
    max_x = resized.shape[1] - w
    max_y = resized.shape[0] - h
    x = max_x // 2
    y = max_y // 2
    if motion == "PAN_LEFT":
        x = int(max_x * (1.0 - progress))
    elif motion == "PAN_RIGHT":
        x = int(max_x * progress)
    elif motion == "PAN_UP":
        y = int(max_y * (1.0 - progress))
    elif motion == "PAN_DOWN":
        y = int(max_y * progress)
    return resized[y:y + h, x:x + w]


def apply_soul_out(image: np.ndarray, time_sec: float, speed: float = 1.0,
                   intensity: float = 1.0) -> np.ndarray:
    """Apply Jianying's GESticker_SoulScale effect at its default settings."""
    h, w = image.shape[:2]
    intensity = float(np.clip(intensity, 0.0, 2.0))
    speed = max(0.1, float(speed))
    curve_index = math.floor(float(time_sec) * speed * SOUL_OUT_CURVE_FPS) % 16
    scale = 1.0 + (SOUL_OUT_SCALE_CURVE[curve_index] - 1.0) * intensity
    mixture = float(np.clip(SOUL_OUT_MIX_CURVE[curve_index] * intensity, 0.0, 1.0))

    center = ((w - 1) * 0.5, (h - 1) * 0.5)
    transform = cv2.getRotationMatrix2D(center, 0.0, scale)
    zoomed = cv2.warpAffine(
        image, transform, (w, h), flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return cv2.addWeighted(image, 1.0 - mixture, zoomed, mixture, 0.0)


def render_frame(image: np.ndarray, effect: str, motion: str, frame_index: int,
                 total_frames: int, fps: int, intro_fade_ms: int = 0,
                 outro_fade_ms: int = 0) -> np.ndarray:
    progress = frame_index / max(1, total_frames - 1)
    frame = apply_camera_motion(image, motion, progress)
    effect = str(effect or VIDEO_EFFECT_NONE).upper()
    if effect == VIDEO_EFFECT_SOUL_OUT:
        frame = apply_soul_out(frame, frame_index / max(1, fps))
    elif effect != VIDEO_EFFECT_NONE:
        raise ValueError("不支持的视频特效")

    intro_frames = int(intro_fade_ms * fps / 1000)
    outro_frames = int(outro_fade_ms * fps / 1000)
    alpha = 1.0
    if intro_frames > 0 and frame_index < intro_frames:
        alpha = min(alpha, frame_index / intro_frames)
    remaining = total_frames - 1 - frame_index
    if outro_frames > 0 and remaining < outro_frames:
        alpha = min(alpha, remaining / outro_frames)
    return np.clip(frame.astype(np.float32) * alpha, 0, 255).astype(np.uint8)
