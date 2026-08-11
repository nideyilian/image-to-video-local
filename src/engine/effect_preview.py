"""Render preview frames with the same effect implementation as legacy export."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from ..utils.opencv_silent import import_cv2_silent
from .config import normalize_config, scan_images
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
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return None
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        source_duration = frame_count / fps if fps > 0 and frame_count > 0 else 0.0
        target_time = max(0.0, time_sec)
        if source_duration > 0:
            if match_method == "循环":
                target_time %= source_duration
            elif match_method == "拉伸":
                target_time = min(source_duration, target_time / max(0.001, output_duration) * source_duration)
            elif target_time >= source_duration:
                return None
        capture.set(cv2.CAP_PROP_POS_MSEC, target_time * 1000.0)
        ok, frame = capture.read()
        return frame if ok else None
    finally:
        capture.release()


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
