"""Configuration compatibility helpers for the local rendering engine."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.utils.combination import combination_total
from src.utils.transition_constants import GUI_TRANSITIONS
from src.utils.timeline import timeline_slot_count


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}

SUBFOLDER_SELECTION_MODE = "按子文件夹抽取"
"""选图方式之一：每个直接子文件夹抽 1 张，按子文件夹名顺序组成一轮。"""

IMAGE_SELECTION_MODES = ("随机选择", "按名称排序", SUBFOLDER_SELECTION_MODE)
"""全部选图方式，界面下拉与后端判断共用，避免两侧文案不一致导致模式静默失效。"""

DEFAULT_RESOLUTION_PRESETS = [
    "1280x720",
    "720x1280",
    "1080x1920",
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
        "bgm_files": [],
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
    config["custom_prefix"] = str(config.get("custom_prefix") or "").strip()
    raw_files = config.get("bgm_files")
    config["bgm_files"] = [
        str(path) for path in raw_files
        if isinstance(path, str) and str(path).strip()
    ] if isinstance(raw_files, list) else []
    return config


def natural_sort_key(value: str) -> list[Any]:
    """把数字片段当整数比较，使 2 排在 10 前面（不补零的序号按直觉排列）。

    非数字片段统一转小写后按字符比较；中文名按 Unicode 码点排序
    （"一" 会排在 "三" 前面），如需其他顺序请改用「按名称排序」并自行编号。
    """
    return [
        int(token) if token.isdigit() else token.lower()
        for token in re.split(r"(\d+)", str(value))
    ]


def scan_images(input_dir: str, limit: int | None = None) -> list[str]:
    root = Path(str(input_dir or "").strip())
    if not root.is_dir():
        return []
    images = [
        str(path.resolve())
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    images.sort(key=natural_sort_key)
    if limit is not None:
        return images[: max(0, int(limit))]
    return images


def scan_subfolders(input_dir: str) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """按直接子目录分组收集图片，供「按子文件夹抽取」使用。

    只扫描目标文件夹的下一层，不递归；隐藏目录（以 "." 开头）直接跳过。

    Returns:
        ``(分组, 被跳过的子目录名)``。分组只包含有可用图片的子目录，
        按目录名自然排序；每组内的图片路径同样按名称自然排序。
        被跳过的子目录指"存在但里面没有支持的图片"，用于向用户提示。
    """
    root = Path(str(input_dir or "").strip())
    if not root.is_dir():
        return [], []
    groups: list[tuple[str, list[str]]] = []
    skipped: list[str] = []
    for child in sorted(root.iterdir(), key=lambda path: natural_sort_key(path.name)):
        if not child.is_dir() or child.name.startswith("."):
            continue
        images = [
            str(path.resolve())
            for path in child.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]
        if not images:
            skipped.append(child.name)
            continue
        images.sort(key=natural_sort_key)
        groups.append((child.name, images))
    return groups, skipped


def subfolder_combination_total(groups: list[tuple[str, list[str]]]) -> int:
    """返回给定分组能组成的不重复组合总数（各组图片数之积）。"""
    return combination_total([len(images) for _name, images in groups])


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


ValidationIssue = dict[str, str]


def _subfolder_selection_issues(input_dir: str) -> list[ValidationIssue]:
    """「按子文件夹抽取」的校验。

    组合总数少于视频数不算错误：超出部分会复用组合，且重复次数被摊平。
    这里只拦"一个能出图的子文件夹都没有"这种硬错误。
    """
    groups, skipped = scan_subfolders(input_dir)
    if groups:
        return []
    detail = f"，其中 {len(skipped)} 个空文件夹" if skipped else ""
    return [{
        "field": "input_dir",
        "section": "basic",
        "message": f"输入目录里没有包含图片的子文件夹{detail}；请放入形如 1、2、3 的子文件夹，或改用其它选图方式。",
    }]


def validate_config_detailed(raw: dict[str, Any] | None, check_files: bool = True) -> list[ValidationIssue]:
    """返回结构化的配置校验问题，每项包含 field / section / message。

    section 对应前端 Inspector 的标签页 id：basic / motion / watermark。
    旧版界面可调用 :func:`validate_config` 仅获取 message 列表。
    """
    config = normalize_config(raw)
    issues: list[ValidationIssue] = []

    input_dir = str(config.get("input_dir", "")).strip()
    output_dir = str(config.get("output_dir", "")).strip()

    if not input_dir:
        issues.append({"field": "input_dir", "section": "basic", "message": "请先选择「输入目录」（存放图片的文件夹），再开始导出。"})
    elif check_files and not os.path.isdir(input_dir):
        issues.append({"field": "input_dir", "section": "basic", "message": "找不到输入目录，请重新选择已存在的图片文件夹。"})
    if not output_dir:
        issues.append({"field": "output_dir", "section": "basic", "message": "请先选择「输出目录」（视频保存位置）。"})

    if check_files and bool(config.get("use_bgm")) and str(config.get("watermark_audio", "使用BGM")) in {"使用BGM", "两者混合"}:
        bgm_files = config.get("bgm_files") or []
        if bgm_files:
            missing = [path for path in bgm_files if not os.path.isfile(path)]
            if missing:
                issues.append({
                    "field": "bgm_files",
                    "section": "basic",
                    "message": f"选定的 BGM 素材不存在：{os.path.basename(missing[0])}，请在素材库中重新选择。",
                })
        else:
            bgm_dir = str(config.get("bgm_dir", "") or "").strip()
            if not bgm_dir or not Path(bgm_dir).is_dir():
                issues.append({"field": "bgm_dir", "section": "basic", "message": "找不到 BGM 目录，请重新选择存放音频的文件夹。"})
            elif not scan_audio_files(bgm_dir):
                issues.append({"field": "bgm_dir", "section": "basic", "message": "BGM 目录里没有可用的音频文件，请放入 mp3 / wav 等音频后再试。"})

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
    selection_mode = str(config.get("image_selection_mode", "随机选择"))
    # 「按子文件夹抽取」的每视频图片数由子文件夹个数决定，该项被忽略，不参与校验。
    if num_images <= 0 and selection_mode != SUBFOLDER_SELECTION_MODE:
        issues.append({"field": "num_images", "section": "basic", "message": "「图片数」需要大于 0，请把每个视频的图片数调到 1 张以上。"})
    if video_count <= 0:
        issues.append({"field": "video_count", "section": "basic", "message": "「视频数」需要大于 0，请至少导出 1 个视频。"})
    try:
        timeline_slot_count(duration, total_duration)
    except ValueError as exc:
        issues.append({"field": "duration", "section": "basic", "message": str(exc)})

    if issues or not check_files:
        return issues

    if selection_mode == SUBFOLDER_SELECTION_MODE:
        # 该模式下图片放在子文件夹里，根目录本身可以没有图片，
        # 因此先于通用图片数量检查返回。
        return _subfolder_selection_issues(input_dir)

    image_count = len(scan_images(input_dir))
    if image_count == 0:
        return [{"field": "input_dir", "section": "basic", "message": "输入目录里没有图片，请先放入图片再导出"}]

    if selection_mode == "按名称排序":
        required = video_count * num_images
        if image_count < required:
            issues.append({
                "field": "input_dir",
                "section": "basic",
                "message": f"输出数量超出图片数量：当前只有 {image_count} 张图片，"
                           f"按名称排序模式生成 {video_count} 个视频需要 {required} 张",
            })
    else:
        if image_count < num_images:
            issues.append({"field": "input_dir", "section": "basic", "message": f"图片数量不足：当前只有 {image_count} 张，每个视频需要 {num_images} 张"})
        elif image_count < video_count:
            issues.append({
                "field": "input_dir",
                "section": "basic",
                "message": f"输出数量超出图片数量：随机模式下当前 {image_count} 张图片最多生成 {image_count} 个视频",
            })
    return issues


def validate_config(raw: dict[str, Any] | None, check_files: bool = True) -> list[str]:
    """兼容旧版界面：仅返回错误文本列表。"""
    return [issue["message"] for issue in validate_config_detailed(raw, check_files)]
