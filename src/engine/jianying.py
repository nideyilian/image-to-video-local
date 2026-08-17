"""剪映（JianYing Pro）草稿扫描：读取草稿中的本地 BGM / 视频 / 图片素材。

原理：剪映草稿目录（默认 %LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\
com.lveditor.draft\\<草稿名>\\）下的 draft_content.json（新版）或
draft_info.json（旧版）记录了草稿引用的素材本地路径。解析这些 JSON，
收集音频（导入 BGM 库）与视频/图片（导入水印库），供素材库「从剪映导入」使用。

注意：剪映内置模板与曲库资源受会员/版权约束，读取仅限个人本地使用，
不应随应用打包分发。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .library import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS


def jianying_draft_root() -> Path | None:
    """自动探测剪映草稿箱根目录；未安装或找不到时返回 None。"""
    if sys.platform != "win32":
        return None
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(local_appdata) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
        Path(local_appdata) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft" / "draft",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def jianying_cache_root() -> Path | None:
    """自动探测剪映内置资源缓存目录（已下载的 BGM / 特效 / 转场等）。"""
    if sys.platform != "win32":
        return None
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(local_appdata) / "JianyingPro" / "User Data" / "Cache",
        Path(local_appdata) / "JianyingPro" / "Cache",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


# 内置缓存扫描过滤：音乐/音效与视频资源的最小体积（过滤碎片与图标类文件）
CACHE_AUDIO_MIN_BYTES = 200 * 1024
CACHE_VIDEO_MIN_BYTES = 50 * 1024
CACHE_MAX_FILES = 60000


def _cache_display_name(path: Path) -> str:
    """尽力从同目录同名清单 JSON 读取资源名称；失败时回退为文件名。"""
    candidates = (path.with_suffix(".json"), path.with_name(f"{path.stem}.json"))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for key in ("name", "display_name", "title"):
            raw = data.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        material = data.get("material")
        if isinstance(material, dict):
            for key in ("name", "display_name"):
                raw = material.get(key)
                if isinstance(raw, str) and raw.strip():
                    return raw.strip()
    return path.name


def _load_draft_json(draft_dir: Path) -> dict[str, Any] | None:
    """读取草稿主 JSON（新版 draft_content.json 优先，兼容旧版 draft_info.json）。"""
    for name in ("draft_content.json", "draft_info.json"):
        path = draft_dir / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _draft_materials(payload: dict[str, Any], group: str) -> list[dict[str, Any]]:
    """按新旧两种结构取素材列表：新版 materials.videos，旧版 materials_videos。"""
    materials = payload.get("materials")
    if isinstance(materials, dict):
        items = materials.get(group)
    else:
        items = payload.get(f"materials_{group}")
    return items if isinstance(items, list) else []


def _draft_name(draft_dir: Path, payload: dict[str, Any]) -> str:
    raw = payload.get("name")
    return str(raw).strip() if raw else draft_dir.name


def jianying_scan(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """扫描剪映草稿箱，收集音频 / 视频 / 图片素材（按路径去重、只保留存在的文件）。

    参数：draft_root 可选，手动指定草稿箱根目录（默认自动探测）。
    返回：{draft_root, drafts: [{name, path, counts}], audios, videos, images,
    effects, transitions}，每项素材为 {path, name, draft}。

    特效 / 转场仅收集「本地资源型」条目（path 指向存在的视频 / 图片文件）；
    纯云端模板（无本地文件）会被跳过——剪映模板是私有格式，本地资源可导入
    水印库作为视频水印叠加使用。
    """
    raw = (params or {}).get("draft_root", "")
    root_path = Path(str(raw).strip()).expanduser() if str(raw or "").strip() else jianying_draft_root()
    if not root_path or not root_path.is_dir():
        raise ValueError("未找到剪映草稿目录。请确认已安装剪映，或在弹窗中手动选择「com.lveditor.draft」目录。")

    drafts: list[dict[str, Any]] = []
    audios: list[dict[str, str]] = []
    videos: list[dict[str, str]] = []
    images: list[dict[str, str]] = []
    effects: list[dict[str, str]] = []
    transitions: list[dict[str, str]] = []
    seen: set[str] = set()

    def collect(target: list[dict[str, str]], path: Path, draft: str) -> None:
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        target.append({"path": key, "name": path.name, "draft": draft})

    try:
        children = sorted((child for child in root_path.iterdir() if child.is_dir()), key=lambda p: p.name.lower())
    except OSError as exc:
        raise ValueError(f"读取剪映草稿目录失败：{exc}") from exc

    for draft_dir in children:
        payload = _load_draft_json(draft_dir)
        if payload is None:
            continue
        name = _draft_name(draft_dir, payload)
        counts = {"audio": 0, "video": 0, "image": 0, "effect": 0, "transition": 0}

        for item in _draft_materials(payload, "audios"):
            path = Path(str(item.get("path", "") or "").strip())
            if path.suffix.lower() not in AUDIO_EXTENSIONS or not path.is_file():
                continue
            collect(audios, path, name)
            counts["audio"] += 1

        for item in _draft_materials(payload, "videos"):
            path = Path(str(item.get("path", "") or "").strip())
            suffix = path.suffix.lower()
            if not path.is_file():
                continue
            is_photo = str(item.get("type", "") or "").strip().lower() == "photo"
            if suffix in IMAGE_EXTENSIONS or (is_photo and suffix in IMAGE_EXTENSIONS):
                collect(images, path, name)
                counts["image"] += 1
            elif suffix in VIDEO_EXTENSIONS:
                collect(videos, path, name)
                counts["video"] += 1

        for group, target, counter in (
            ("effects", effects, "effect"),
            ("transitions", transitions, "transition"),
        ):
            for item in _draft_materials(payload, group):
                path = Path(str(item.get("path", "") or "").strip())
                suffix = path.suffix.lower()
                if not path.is_file():
                    continue  # 纯云端模板没有本地文件，跳过
                if suffix in IMAGE_EXTENSIONS or suffix in VIDEO_EXTENSIONS:
                    collect(target, path, name)
                    counts[counter] += 1

        drafts.append({"name": name, "path": str(draft_dir), "counts": counts})

    return {
        "draft_root": str(root_path.resolve()),
        "drafts": drafts,
        "audios": audios,
        "videos": videos,
        "images": images,
        "effects": effects,
        "transitions": transitions,
    }


def jianying_cache_scan(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """扫描剪映内置资源缓存，收集已下载的音频（BGM）与视频资源（特效/转场媒体）。

    参数：cache_root 可选，手动指定缓存目录（默认自动探测 User Data\\Cache）。
    只收集体积达标的音频 / 视频文件（过滤图标与碎片）；图片序列帧不收集，
    避免导入大量序列帧文件。返回 {cache_root, audios, videos, scanned_files,
    truncated}，每项素材为 {path, name, draft}，name 尽力从清单 JSON 解析。
    """
    raw = (params or {}).get("cache_root", "")
    root_path = Path(str(raw).strip()).expanduser() if str(raw or "").strip() else jianying_cache_root()
    if not root_path or not root_path.is_dir():
        raise ValueError(
            "未找到剪映内置资源缓存目录。请确认已安装剪映且下载过内置资源，"
            "或在弹窗中手动选择「User Data\\Cache」目录。"
        )

    audios: list[dict[str, str]] = []
    videos: list[dict[str, str]] = []
    seen: set[str] = set()
    scanned_files = 0
    truncated = False

    def collect(target: list[dict[str, str]], path: Path) -> None:
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        target.append({"path": key, "name": _cache_display_name(path), "draft": "内置缓存"})

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames.sort(key=str.lower)
        for filename in filenames:
            scanned_files += 1
            if scanned_files > CACHE_MAX_FILES:
                truncated = True
                break
            path = Path(dirpath) / filename
            suffix = path.suffix.lower()
            if suffix not in AUDIO_EXTENSIONS and suffix not in VIDEO_EXTENSIONS:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if suffix in AUDIO_EXTENSIONS and size >= CACHE_AUDIO_MIN_BYTES:
                collect(audios, path)
            elif suffix in VIDEO_EXTENSIONS and size >= CACHE_VIDEO_MIN_BYTES:
                collect(videos, path)
        if truncated:
            break

    return {
        "cache_root": str(root_path.resolve()),
        "audios": audios,
        "videos": videos,
        "scanned_files": scanned_files,
        "truncated": truncated,
    }
