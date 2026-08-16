"""Render preview frames with the same effect implementation as legacy export."""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np

from ..utils.opencv_silent import import_cv2_silent
from .config import build_default_config, normalize_config, scan_images
from .preview_random import preview_choice


cv2 = import_cv2_silent()

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".webm"}
VIDEO_WATERMARK_ALPHA = {
    "正常": 0.50,
    "滤色": 1.00,
    "叠加": 0.90,
    "正片叠底": 0.85,
    "变亮": 0.90,
    "变暗": 0.90,
    "相加": 0.95,
}

# 素材库「特效 / 转场」演示图尺寸与帧数
LIBRARY_PREVIEW_WIDTH = 192
LIBRARY_PREVIEW_HEIGHT = 108
LIBRARY_PREVIEW_FRAMES = 8


def ensure_effect_library_assets(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """生成（或复用）特效/转场演示源图，返回两张不同色系的图片路径。

    A 图用于特效与转场的第一张，B 图仅用于转场第二张，保证过渡动画清晰可辨。
    用户可通过 effect_library_set_asset 自定义演示图；自定义图存在时优先使用，
    返回 custom_a / custom_b 标记与原始来源路径。
    """
    from PIL import Image, ImageDraw

    preview_dir = Path(tempfile.gettempdir()) / "image-to-video-engine" / "effect-library"
    preview_dir.mkdir(parents=True, exist_ok=True)
    source_a = preview_dir / "source-a.png"
    source_b = preview_dir / "source-b.png"

    manifest = _load_user_assets(preview_dir)
    user_a = _resolve_user_asset(preview_dir, manifest.get("a"))
    user_b = _resolve_user_asset(preview_dir, manifest.get("b"))

    if not source_a.is_file() or not source_b.is_file():
        def draw_demo(path: Path, top: tuple[int, int, int], bottom: tuple[int, int, int], shape: str) -> None:
            image = Image.new("RGB", (480, 270))
            draw = ImageDraw.Draw(image)
            for y in range(270):
                ratio = y / 269
                color = tuple(int(top[c] + (bottom[c] - top[c]) * ratio) for c in range(3))
                draw.line([(0, y), (479, y)], fill=color)
            if shape == "circle":
                draw.ellipse([140, 60, 340, 210], fill=(255, 255, 255, 255), outline=(20, 30, 60, 255), width=6)
                draw.ellipse([210, 120, 270, 180], fill=(30, 50, 90, 255))
            else:
                draw.polygon([(240, 50), (380, 220), (100, 220)], fill=(255, 255, 255, 255), outline=(60, 30, 20, 255))
                draw.ellipse([200, 95, 280, 175], fill=(90, 50, 30, 255))
            draw.text((18, 14), "演示画面 A" if path.name == "source-a.png" else "演示画面 B", fill=(255, 255, 255, 255))
            image.save(path, "PNG")

        draw_demo(source_a, (40, 90, 200), (120, 40, 160), "circle")
        draw_demo(source_b, (200, 90, 40), (160, 40, 120), "triangle")

    return {
        "source_a": str((user_a or source_a).resolve()),
        "source_b": str((user_b or source_b).resolve()),
        "custom_a": user_a is not None,
        "custom_b": user_b is not None,
        "user_path_a": manifest.get("a", {}).get("source", "") if user_a else "",
        "user_path_b": manifest.get("b", {}).get("source", "") if user_b else "",
    }


_USER_ASSET_MANIFEST = ".user-assets.json"


def _load_user_assets(preview_dir: Path) -> dict[str, dict[str, str]]:
    """读取自定义演示图清单；损坏或缺失时返回空清单。"""
    try:
        data = json.loads((preview_dir / _USER_ASSET_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    result: dict[str, dict[str, str]] = {}
    for slot in ("a", "b"):
        entry = data.get(slot)
        if isinstance(entry, dict) and isinstance(entry.get("file"), str) and isinstance(entry.get("source"), str):
            result[slot] = {"file": entry["file"], "source": entry["source"]}
    return result


def _save_user_assets(preview_dir: Path, manifest: dict[str, dict[str, str]]) -> None:
    temporary = preview_dir / f".{_USER_ASSET_MANIFEST}.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    temporary.replace(preview_dir / _USER_ASSET_MANIFEST)


def _resolve_user_asset(preview_dir: Path, entry: dict[str, str] | None) -> Path | None:
    """返回可用的自定义演示图路径；临时目录被清理时尝试从原始路径恢复。"""
    if not entry:
        return None
    user_file = preview_dir / entry["file"]
    if not user_file.is_file():
        source = Path(entry.get("source", ""))
        if source.is_file():
            try:
                shutil.copy2(source, user_file)
            except OSError:
                return None
    return user_file if user_file.is_file() else None


def _validate_image_file(path: Path) -> None:
    from PIL import Image

    try:
        with Image.open(path) as image:
            image.verify()
    except Exception as exc:
        raise ValueError(f"不是有效的图片文件：{path.name}") from exc


def effect_library_set_asset(params: dict[str, Any]) -> dict[str, Any]:
    """把用户选择的图片设为特效/转场演示图（which = a 或 b），返回最新资产。"""
    slot = str(params.get("which", "") or "").strip().lower()
    if slot not in {"a", "b"}:
        raise ValueError("which 必须是 a 或 b")
    source = str(params.get("path", "") or "").strip()
    source_path = Path(source).expanduser()
    if not source_path.is_file():
        raise ValueError("图片文件不存在，请重新选择")
    _validate_image_file(source_path)

    preview_dir = Path(tempfile.gettempdir()) / "image-to-video-engine" / "effect-library"
    preview_dir.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"}:
        suffix = ".png"
    user_file = preview_dir / f"user-{slot}{suffix}"

    manifest = _load_user_assets(preview_dir)
    previous = manifest.get(slot, {}).get("file")
    if previous and previous != user_file.name:
        try:
            (preview_dir / previous).unlink(missing_ok=True)
        except OSError:
            pass
    if source_path.resolve() != user_file.resolve():
        shutil.copy2(source_path, user_file)
    manifest[slot] = {"file": user_file.name, "source": str(source_path.resolve())}
    _save_user_assets(preview_dir, manifest)
    return ensure_effect_library_assets()


def effect_library_reset_assets() -> dict[str, Any]:
    """清除自定义演示图，恢复内置演示图。"""
    preview_dir = Path(tempfile.gettempdir()) / "image-to-video-engine" / "effect-library"
    manifest = _load_user_assets(preview_dir)
    for entry in manifest.values():
        try:
            (preview_dir / entry["file"]).unlink(missing_ok=True)
        except OSError:
            pass
    try:
        (preview_dir / _USER_ASSET_MANIFEST).unlink(missing_ok=True)
    except OSError:
        pass
    return ensure_effect_library_assets()


def render_effect_animation(params: dict[str, Any]) -> dict[str, Any]:
    """渲染单个特效/转场的动画帧序列（素材库展示用）。

    参数：kind = "effect" | "transition"；name = 特效/转场名称；
    frames = 帧数（默认 8）；width/height = 帧尺寸（默认 192x108）。
    帧通过 render_effect_preview 渲染并落盘缓存，重复调用直接命中。
    """
    kind = str(params.get("kind", "") or "").strip()
    name = str(params.get("name", "") or "").strip()
    if kind not in {"effect", "transition"}:
        raise ValueError("动画类型必须是 effect 或 transition")
    if not name:
        raise ValueError("缺少效果名称")
    frame_count = max(3, min(24, int(params.get("frames", LIBRARY_PREVIEW_FRAMES) or LIBRARY_PREVIEW_FRAMES)))
    width = max(96, min(480, int(params.get("width", LIBRARY_PREVIEW_WIDTH) or LIBRARY_PREVIEW_WIDTH)))
    height = max(54, min(270, int(params.get("height", LIBRARY_PREVIEW_HEIGHT) or LIBRARY_PREVIEW_HEIGHT)))

    assets = ensure_effect_library_assets()
    config = build_default_config()
    config.update({
        "duration": 1.0,
        "fps": 30,
        "resolution_preset": f"{width}x{height}",
        "width": width,
        "height": height,
        "use_transition": kind == "transition",
        "transition_type": name if kind == "transition" else "淡入淡出",
        "random_transition": False,
        "use_video_effect": kind == "effect",
        "video_effect_type": name if kind == "effect" else "无特效",
        "random_video_effect": False,
        "use_watermark": False,
        "use_image_watermark": False,
        "use_bgm": False,
    })
    static_duration, transition_duration = preview_phase_timing(config, 1.0, kind == "transition")
    frame_paths: list[str] = []
    for index in range(frame_count):
        ratio = index / max(1, frame_count - 1)
        if kind == "transition" and transition_duration > 0:
            time_sec = static_duration + transition_duration * ratio
        else:
            time_sec = static_duration * ratio
        result = render_effect_preview({
            "path": assets["source_a"],
            "next_path": assets["source_b"] if kind == "transition" else "",
            "config": config,
            "time_sec": time_sec,
            "max_width": width,
            "max_height": height,
        })
        frame_paths.append(result["preview_path"])
    return {
        "kind": kind,
        "name": name,
        "frames": frame_paths,
        "width": width,
        "height": height,
        "assets": assets,
    }


class _VideoWatermarkReader:
    """Keep one decoder open while the preview clock advances.

    OpenCV 解码视频时会丢弃 alpha 通道，因此优先用 ffmpeg 解码出 RGBA
    帧列表（保留透明通道）；失败时回退到 OpenCV 逐帧读取。
    """

    def __init__(self, path: Path):
        self.path = path
        self.capture = cv2.VideoCapture(str(path))
        self.fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 0.0)
        self.frame_count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.last_frame_index = -1
        self.last_frame: np.ndarray | None = None
        try:
            from ..utils.ffmpeg_runtime import read_video_frames_rgba, resolve_ffmpeg_path

            alpha_frames = read_video_frames_rgba(resolve_ffmpeg_path(), path)
        except Exception:
            alpha_frames = None
        if alpha_frames is not None:
            self.alpha_frames = alpha_frames
            if self.frame_count <= 0:
                self.frame_count = len(alpha_frames)
        else:
            self.alpha_frames = None

    @property
    def is_opened(self) -> bool:
        return bool(self.capture.isOpened()) or self.alpha_frames is not None

    @property
    def duration(self) -> float:
        if self.fps <= 0 or self.frame_count <= 0:
            return 0.0
        return self.frame_count / self.fps

    def read(self, frame_index: int) -> np.ndarray | None:
        if self.alpha_frames is not None:
            if frame_index < 0 or frame_index >= len(self.alpha_frames):
                return None
            return self.alpha_frames[frame_index].copy()

        if frame_index == self.last_frame_index and self.last_frame is not None:
            return self.last_frame.copy()

        ok = False
        frame = None
        sequential_limit = max(4, int(round(self.fps)))
        if (
            self.last_frame_index >= 0
            and self.last_frame_index < frame_index
            and frame_index - self.last_frame_index <= sequential_limit
        ):
            for _ in range(self.last_frame_index + 1, frame_index + 1):
                ok, frame = self.capture.read()
                if not ok:
                    break
        else:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, float(frame_index))
            ok, frame = self.capture.read()

        if not ok or frame is None:
            return None
        self.last_frame_index = frame_index
        self.last_frame = frame
        return frame.copy()

    def release(self) -> None:
        self.capture.release()


_VIDEO_WATERMARK_READER_LIMIT = 4
_VIDEO_WATERMARK_READER_LOCK = threading.RLock()
_VIDEO_WATERMARK_READERS: OrderedDict[
    str, tuple[tuple[int, int], _VideoWatermarkReader]
] = OrderedDict()


def _clear_video_watermark_reader_cache() -> None:
    with _VIDEO_WATERMARK_READER_LOCK:
        while _VIDEO_WATERMARK_READERS:
            _, (_, reader) = _VIDEO_WATERMARK_READERS.popitem()
            reader.release()


atexit.register(_clear_video_watermark_reader_cache)


class _LegacyEffectAdapter:
    """Provide only the methods used by ImageToVideoTab's stateless renderer."""

    @staticmethod
    def _center_crop(img: np.ndarray, target_width: int, target_height: int) -> np.ndarray:
        h, w = img.shape[:2]
        if h < target_height or w < target_width:
            return cv2.resize(img, (target_width, target_height))
        x_start = max((w - target_width) // 2, 0)
        y_start = max((h - target_height) // 2, 0)
        return img[y_start:y_start + target_height, x_start:x_start + target_width]

    def apply_single_image_effect(
        self,
        img: np.ndarray,
        effect_type: str,
        time_sec: float,
        duration_sec: float,
        intensity: float = 100.0,
        speed: float = 1.0,
    ) -> np.ndarray:
        from ..gui.main_window import ImageToVideoTab

        return ImageToVideoTab.apply_single_image_effect(
            self, img, effect_type, time_sec, duration_sec, intensity, speed
        )


def _read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取预览图片: {path.name}")
    return image


def _target_size(config: dict[str, Any], max_width: int, max_height: int) -> tuple[int, int]:
    width = int(config.get("width") or 0)
    height = int(config.get("height") or 0)
    match = re.search(r"(\d+)\s*[xX×]\s*(\d+)", str(config.get("resolution_preset", "")))
    if match:
        width, height = int(match.group(1)), int(match.group(2))
    if width <= 0 or height <= 0:
        width, height = 1280, 720
    scale = min(1.0, max_width / width, max_height / height)
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def _resize_for_export(image: np.ndarray, width: int, height: int, keep_aspect: bool) -> np.ndarray:
    if not keep_aspect:
        return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    source_h, source_w = image.shape[:2]
    scale = min(width / source_w, height / source_h)
    resized_w = max(1, int(source_w * scale))
    resized_h = max(1, int(source_h * scale))
    resized = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_AREA)
    result = np.zeros((height, width, 3), dtype=np.uint8)
    x = (width - resized_w) // 2
    y = (height - resized_h) // 2
    result[y:y + resized_h, x:x + resized_w] = resized
    return result


def render_effect_frame(
    image: np.ndarray,
    effect_type: str,
    time_sec: float,
    duration_sec: float,
    intensity: float,
    speed: float,
) -> np.ndarray:
    """Apply the production ImageToVideoTab effect without constructing Tk widgets."""
    return _LegacyEffectAdapter().apply_single_image_effect(
        image, effect_type, time_sec, duration_sec, intensity, speed
    )


def _legacy_watermark_adapter(config: dict[str, Any]):
    from ..gui.main_window import ImageToVideoTab

    adapter = ImageToVideoTab.__new__(ImageToVideoTab)
    adapter.watermark_layers = config.get("watermark_layers") or []
    return adapter


def _prepare_image_watermark_layers(
    adapter: Any,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prepared: list[dict[str, Any]] = []
    signatures: list[dict[str, Any]] = []
    if not bool(config.get("use_image_watermark")):
        return prepared, signatures

    for raw_layer in config.get("watermark_layers") or []:
        if not isinstance(raw_layer, dict) or not raw_layer.get("enabled", True):
            continue
        path_value = str(raw_layer.get("path", "") or "").strip()
        path = Path(path_value)
        if not path_value:
            continue
        if path.is_dir():
            files = sorted(
                candidate
                for candidate in path.iterdir()
                if candidate.is_file() and candidate.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
            )
        else:
            files = [path]
        images = []
        for candidate in files:
            watermark = adapter._safe_read_image_with_alpha(str(candidate))
            if watermark is None:
                continue
            images.append(watermark)
            signatures.append({"path": str(candidate.resolve()), "mtime": candidate.stat().st_mtime_ns})
            if bool(raw_layer.get("folder_random_single")):
                break
        if not images:
            continue
        prepared.append({
            "images": images,
            "position": raw_layer.get("position", "右下"),
            "size_mode": raw_layer.get("size_mode", "自适应覆盖"),
            "scale": raw_layer.get("scale", 20.0),
            "blend_mode": raw_layer.get("blend_mode", "正常"),
            "opacity": raw_layer.get("opacity", 0.5),
            "fixed": bool(raw_layer.get("fixed", False)),
            "folder_random_single": bool(raw_layer.get("folder_random_single", False)),
        })
    return prepared, signatures


def _resolve_video_watermark(config: dict[str, Any], preview_sequence: int = 0) -> Path | None:
    if not bool(config.get("use_watermark")):
        return None
    path_value = str(config.get("watermark_path", "") or "").strip()
    if not path_value:
        return None
    path = Path(path_value)
    if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
        return path
    if path.is_dir():
        candidates = [
            candidate
            for candidate in sorted(path.iterdir())
            if candidate.is_file() and candidate.suffix.lower() in VIDEO_EXTENSIONS
        ]
        if preview_sequence > 0:
            return preview_choice(candidates, preview_sequence, "video-watermark")
        return candidates[0] if candidates else None
    return None


def _read_video_watermark_frame(
    path: Path,
    time_sec: float,
    output_duration: float,
    match_method: str,
) -> np.ndarray | None:
    resolved_path = path.resolve()
    stat = resolved_path.stat()
    signature = (stat.st_mtime_ns, stat.st_size)
    cache_key = str(resolved_path)
    with _VIDEO_WATERMARK_READER_LOCK:
        cached = _VIDEO_WATERMARK_READERS.pop(cache_key, None)
        if cached is not None and cached[0] != signature:
            cached[1].release()
            cached = None
        if cached is None:
            reader = _VideoWatermarkReader(resolved_path)
            if not reader.is_opened:
                reader.release()
                return None
            cached = (signature, reader)
        _VIDEO_WATERMARK_READERS[cache_key] = cached
        while len(_VIDEO_WATERMARK_READERS) > _VIDEO_WATERMARK_READER_LIMIT:
            _, (_, stale_reader) = _VIDEO_WATERMARK_READERS.popitem(last=False)
            stale_reader.release()

        reader = cached[1]
        source_duration = reader.duration
        target_time = max(0.0, time_sec)
        if source_duration > 0:
            if match_method == "循环":
                target_time %= source_duration
            elif match_method == "拉伸":
                target_time = min(source_duration, target_time / max(0.001, output_duration) * source_duration)
            elif target_time >= source_duration:
                return None
        frame_index = max(0, int(target_time * reader.fps + 1e-7))
        if reader.frame_count > 0:
            frame_index = min(reader.frame_count - 1, frame_index)
        return reader.read(frame_index)


def preview_phase_timing(
    config: dict[str, Any],
    duration_sec: float,
    has_next_image: bool,
) -> tuple[float, float]:
    """Match the exporter's static/effect and transition frame allocation."""
    fps = max(1, int(config.get("fps", 30) or 30))
    total_frames = max(1, int(max(0.001, duration_sec) * fps))
    transition_frames = 0
    if has_next_image and bool(config.get("use_transition")):
        transition_frames = min(15, total_frames // 3)
        display_frames = total_frames - transition_frames
        minimum_display_frames = min(total_frames, max(1, fps // 2))
        if display_frames < minimum_display_frames:
            display_frames = minimum_display_frames
            transition_frames = max(0, total_frames - display_frames)
    display_frames = total_frames - transition_frames
    return display_frames / fps, transition_frames / fps


def _apply_transition_preview(
    image: np.ndarray,
    next_image: np.ndarray | None,
    config: dict[str, Any],
    time_sec: float,
    static_duration: float,
    transition_duration: float,
    preview_sequence: int = 0,
) -> tuple[np.ndarray, bool, str]:
    if (
        next_image is None
        or not bool(config.get("use_transition"))
        or transition_duration <= 0
    ):
        return image, False, "无转场"
    transition_type = str(config.get("transition_type", "淡入淡出") or "淡入淡出")
    if bool(config.get("random_transition")):
        enabled = config.get("enabled_transitions") or []
        if enabled:
            transition_type = str(
                preview_choice(enabled, preview_sequence, "transition")
                if preview_sequence > 0
                else enabled[0]
            )
    fps = max(1, int(config.get("fps", 30) or 30))
    frame_count = max(1, int(round(transition_duration * fps)))
    if time_sec < static_duration:
        return image, False, transition_type
    progress = min(1.0, max(0.0, (time_sec - static_duration) / transition_duration))
    try:
        from ..core.transition_engine import get_turbo_transition_engine

        engine = get_turbo_transition_engine()
        frames = engine.generate_transition_frames(image, next_image, transition_type, frame_count, use_cache=True)
        if frames:
            index = min(len(frames) - 1, int(progress * len(frames)))
            return frames[index], True, transition_type
    except Exception:
        pass
    return cv2.addWeighted(image, 1.0 - progress, next_image, progress, 0), True, transition_type


def render_effect_preview(params: dict[str, Any]) -> dict[str, Any]:
    config = normalize_config(params.get("config"))
    source = str(params.get("path", "") or "").strip()
    if not source:
        candidates = scan_images(str(config.get("input_dir", "")), limit=1)
        source = candidates[0] if candidates else ""
    source_path = Path(source)
    if not source_path.is_file():
        raise ValueError("没有可用于特效预览的图片")

    max_width = max(64, min(1920, int(params.get("max_width", 960) or 960)))
    max_height = max(64, min(1080, int(params.get("max_height", 540) or 540)))
    width, height = _target_size(config, max_width, max_height)
    time_sec = max(0.0, float(params.get("time_sec", 0.0) or 0.0))
    preview_sequence = max(0, int(params.get("preview_sequence", 0) or 0))
    duration_sec = max(0.001, float(config.get("duration", 1.0) or 1.0))
    effect_type = str(config.get("video_effect_type", "无特效"))
    if bool(config.get("random_video_effect")):
        enabled_effects = config.get("enabled_video_effects") or []
        if enabled_effects:
            effect_type = str(
                preview_choice(enabled_effects, preview_sequence, "effect")
                if preview_sequence > 0
                else enabled_effects[0]
            )
    enabled = bool(config.get("use_video_effect")) and effect_type != "无特效"

    image = _resize_for_export(
        _read_image(source_path), width, height, bool(config.get("keep_aspect_ratio", True))
    )
    next_source = str(params.get("next_path", "") or "").strip()
    next_path = Path(next_source) if next_source else None
    next_image = None
    if next_path and next_path.is_file() and next_path.resolve() != source_path.resolve():
        next_image = _resize_for_export(
            _read_image(next_path), width, height, bool(config.get("keep_aspect_ratio", True))
        )
    static_duration, transition_duration = preview_phase_timing(
        config, duration_sec, next_image is not None
    )

    adapter = _legacy_watermark_adapter(config)
    image_layers, watermark_signatures = _prepare_image_watermark_layers(adapter, config)
    if image_layers:
        image = adapter.apply_image_watermark_layers(image, image_layers, image_index=0)
        if next_image is not None:
            next_image = adapter.apply_image_watermark_layers(next_image, image_layers, image_index=1)

    image, transition_active, transition_type = _apply_transition_preview(
        image, next_image, config, time_sec, static_duration, transition_duration, preview_sequence
    )
    if enabled and not transition_active:
        image = render_effect_frame(
            image,
            effect_type,
            time_sec,
            static_duration,
            float(config.get("video_effect_intensity", 100.0) or 100.0),
            float(config.get("video_effect_speed", 1.0) or 1.0),
        )

    video_watermark = _resolve_video_watermark(config, preview_sequence)
    if video_watermark is not None:
        watermark_frame = _read_video_watermark_frame(
            video_watermark,
            time_sec,
            duration_sec,
            str(config.get("watermark_match_method", "循环") or "循环"),
        )
        if watermark_frame is not None:
            blend_mode = str(config.get("watermark_blend_mode", "正常") or "正常")
            image = adapter._apply_image_watermark_layer(image, {
                "images": [watermark_frame],
                "position": config.get("watermark_position", "中心"),
                "size_mode": config.get("watermark_size_mode", "自适应覆盖"),
                "scale": config.get("watermark_scale", 100.0),
                "blend_mode": blend_mode,
                "opacity": VIDEO_WATERMARK_ALPHA.get(blend_mode, 0.50),
            })
            watermark_signatures.append({
                "path": str(video_watermark.resolve()),
                "mtime": video_watermark.stat().st_mtime_ns,
            })

    cache_data = {
        "source": str(source_path.resolve()),
        "mtime": source_path.stat().st_mtime_ns,
        "next_source": str(next_path.resolve()) if next_path and next_path.is_file() else "",
        "next_mtime": next_path.stat().st_mtime_ns if next_path and next_path.is_file() else 0,
        "size": [width, height],
        "enabled": enabled,
        "effect": effect_type,
        "time": round(time_sec, 3),
        "duration": duration_sec,
        "static_duration": static_duration,
        "transition_duration": transition_duration,
        "intensity": config.get("video_effect_intensity"),
        "speed": config.get("video_effect_speed"),
        "keep_aspect": config.get("keep_aspect_ratio"),
        "transition": {
            "enabled": config.get("use_transition"),
            "random": config.get("random_transition"),
            "type": transition_type,
            "active": transition_active,
        },
        "video_watermark": {
            "enabled": config.get("use_watermark"),
            "path": config.get("watermark_path"),
            "position": config.get("watermark_position"),
            "match": config.get("watermark_match_method"),
            "size_mode": config.get("watermark_size_mode"),
            "scale": config.get("watermark_scale"),
            "blend": config.get("watermark_blend_mode"),
        },
        "image_watermark": {
            "enabled": config.get("use_image_watermark"),
            "layers": config.get("watermark_layers") or [],
        },
        "watermark_assets": watermark_signatures,
    }
    digest = hashlib.sha1(
        json.dumps(cache_data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    preview_dir = Path(tempfile.gettempdir()) / "image-to-video-engine" / "effect-previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_path = preview_dir / f"{digest}.jpg"
    if not preview_path.exists():
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise RuntimeError("特效预览编码失败")
        encoded.tofile(str(preview_path))
    return {
        "source": str(source_path.resolve()),
        "preview_path": str(preview_path.resolve()),
        "width": width,
        "height": height,
        "effect_type": effect_type if enabled else "无特效",
        "transition_type": transition_type if bool(config.get("use_transition")) else "无转场",
        "transition_active": transition_active,
        "time_sec": time_sec,
        "static_duration": static_duration,
        "transition_duration": transition_duration,
        "video_watermark_name": video_watermark.name if video_watermark is not None else "",
    }
