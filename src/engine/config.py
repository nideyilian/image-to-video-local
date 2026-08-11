"""Configuration compatibility helpers for the local rendering engine."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.utils.transition_constants import GUI_TRANSITIONS
from src.utils.timeline import timeline_slot_count


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}

DEFAULT_RESOLUTION_PRESETS = [
    "1280x720",
    "1920x1080",
    "2560x1440",
    "3840x2160",
    "1080x1920",
    "720x1280",
    "1080x1080",
]

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

VIDEO_EFFECT_ALIASES = {"心跳跃动": "心跳跳动"}


def build_default_config() -> dict[str, Any]:
    """Return a fresh config matching the current Qt/Tk compatibility schema."""
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


def parse_resolution(value: Any) -> tuple[int, int]:
    match = re.match(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$", str(value or ""))
    if not match:
        return 1280, 720
    return max(2, int(match.group(1))), max(2, int(match.group(2)))


def normalize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    config = build_default_config()
    if isinstance(raw, dict):
        config.update(deepcopy(raw))
    width, height = parse_resolution(config.get("resolution_preset"))
    config["width"] = width
    config["height"] = height
    config["watermark_type"] = "视频"
    config["video_effect_type"] = VIDEO_EFFECT_ALIASES.get(
        str(config.get("video_effect_type", "无特效")),
        str(config.get("video_effect_type", "无特效")),
    )
    enabled_effects = config.get("enabled_video_effects")
    if isinstance(enabled_effects, list):
        config["enabled_video_effects"] = [
            VIDEO_EFFECT_ALIASES.get(str(effect), str(effect)) for effect in enabled_effects
        ]
    config["custom_prefix"] = str(config.get("custom_prefix") or "video").strip() or "video"
    return config


def scan_images(input_dir: str, limit: int | None = None) -> list[str]:
    root = Path(str(input_dir or "").strip())
    if not root.is_dir():
        return []
    images = [
        str(path.resolve())
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    images.sort(key=lambda value: [int(token) if token.isdigit() else token.lower() for token in re.split(r"(\d+)", value)])
    if limit is not None:
        return images[: max(0, int(limit))]
    return images


def scan_audio_files(audio_dir: str) -> list[str]:
    root = Path(str(audio_dir or "").strip())
    if not root.is_dir():
        return []
    files = [
        str(path.resolve())
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    ]
    files.sort(key=lambda value: [int(token) if token.isdigit() else token.lower() for token in re.split(r"(\d+)", value)])
    return files


def validate_config(raw: dict[str, Any] | None, check_files: bool = True) -> list[str]:
    config = normalize_config(raw)
    errors: list[str] = []
    input_dir = str(config.get("input_dir", "")).strip()
    output_dir = str(config.get("output_dir", "")).strip()

    if not input_dir:
        errors.append("请输入输入目录")
    elif check_files and not os.path.isdir(input_dir):
        errors.append("输入目录不存在，请重新选择")
    if not output_dir:
        errors.append("请输入输出目录")

    if check_files and bool(config.get("use_bgm")) and str(config.get("watermark_audio", "使用BGM")) in {"使用BGM", "两者混合"}:
        bgm_dir = str(config.get("bgm_dir", "") or "").strip()
        if not bgm_dir or not Path(bgm_dir).is_dir():
            errors.append("BGM目录不存在，请重新选择")
        elif not scan_audio_files(bgm_dir):
            errors.append("BGM目录中没有可用音频")

    try:
        num_images = int(config.get("num_images", 0))
    except (TypeError, ValueError):
        num_images = 0
    try:
        video_count = int(config.get("video_count", 0))
    except (TypeError, ValueError):
        video_count = 0
    try:
        duration = float(config.get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0
    try:
        total_duration = float(config.get("total_duration", 0))
    except (TypeError, ValueError):
        total_duration = -1.0
    if num_images <= 0:
        errors.append("每个视频图片数必须大于 0")
    if video_count <= 0:
        errors.append("视频数量必须大于 0")
    try:
        timeline_slot_count(duration, total_duration)
    except ValueError as exc:
        errors.append(str(exc))

    if errors or not check_files:
        return errors

    image_count = len(scan_images(input_dir))
    if image_count == 0:
        return ["输入目录里没有图片，请先放入图片再导出"]

    if str(config.get("image_selection_mode", "随机选择")) == "按名称排序":
        required = video_count * num_images
        if image_count < required:
            errors.append(
                f"输出数量超出图片数量：当前只有 {image_count} 张图片，"
                f"按名称排序模式生成 {video_count} 个视频需要 {required} 张"
            )
    else:
        if image_count < num_images:
            errors.append(f"图片数量不足：当前只有 {image_count} 张，每个视频需要 {num_images} 张")
        elif image_count < video_count:
            errors.append(
                f"输出数量超出图片数量：随机模式下当前 {image_count} 张图片最多生成 {image_count} 个视频"
            )
    return errors
