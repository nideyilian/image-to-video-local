"""Resolve and configure the FFmpeg binary used by every desktop runtime."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np


def _candidate_bases(project_root: str | Path | None = None) -> Iterable[Path]:
    values: list[Path] = []
    if project_root:
        values.append(Path(project_root))
    values.append(Path.cwd())
    values.append(Path(sys.executable).resolve().parent)
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        values.append(Path(meipass))
    values.append(Path(__file__).resolve().parents[2])

    seen: set[str] = set()
    for value in values:
        try:
            normalized = str(value.resolve())
        except OSError:
            normalized = str(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        yield Path(normalized)


def _is_executable_file(value: str | Path | None) -> bool:
    if not value:
        return False
    try:
        return Path(value).is_file()
    except OSError:
        return False


def resolve_ffmpeg_path(project_root: str | Path | None = None) -> str | None:
    """Find FFmpeg in explicit config, app folders, PATH, or imageio-ffmpeg."""
    for variable in ("IMAGEIO_FFMPEG_EXE", "FFMPEG_BINARY"):
        configured = os.environ.get(variable, "").strip().strip('"')
        if _is_executable_file(configured):
            return str(Path(configured).resolve())

    system_ffmpeg = shutil.which("ffmpeg")
    if _is_executable_file(system_ffmpeg):
        return str(Path(system_ffmpeg).resolve())

    relative_candidates = (
        Path("tools/ffmpeg/bin/ffmpeg.exe"),
        Path("tools/ffmpeg/ffmpeg.exe"),
        Path("ffmpeg/bin/ffmpeg.exe"),
        Path("ffmpeg.exe"),
        Path("bin/ffmpeg.exe"),
    )
    for base in _candidate_bases(project_root):
        for relative in relative_candidates:
            candidate = base / relative
            if _is_executable_file(candidate):
                return str(candidate.resolve())

    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if _is_executable_file(bundled):
            return str(Path(bundled).resolve())
    except Exception:
        pass

    for base in _candidate_bases(project_root):
        binary_dir = base / "imageio_ffmpeg" / "binaries"
        if not binary_dir.is_dir():
            continue
        for candidate in sorted(binary_dir.glob("ffmpeg*.exe")):
            if _is_executable_file(candidate):
                return str(candidate.resolve())
    return None


def resolve_ffprobe_path(
    project_root: str | Path | None = None,
    ffmpeg_path: str | Path | None = None,
) -> str | None:
    """Find ffprobe when a full FFmpeg distribution is available."""
    configured = os.environ.get("FFPROBE_BINARY", "").strip().strip('"')
    if _is_executable_file(configured):
        return str(Path(configured).resolve())
    system_ffprobe = shutil.which("ffprobe")
    if _is_executable_file(system_ffprobe):
        return str(Path(system_ffprobe).resolve())
    if ffmpeg_path:
        sibling = Path(ffmpeg_path).resolve().with_name("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
        if _is_executable_file(sibling):
            return str(sibling)
    relative_candidates = (
        Path("tools/ffmpeg/bin/ffprobe.exe"),
        Path("ffmpeg/bin/ffprobe.exe"),
        Path("ffprobe.exe"),
        Path("bin/ffprobe.exe"),
    )
    for base in _candidate_bases(project_root):
        for relative in relative_candidates:
            candidate = base / relative
            if _is_executable_file(candidate):
                return str(candidate.resolve())
    return None


def configure_ffmpeg_environment(project_root: str | Path | None = None) -> str | None:
    """Configure MoviePy/imageio and child workers to use the resolved FFmpeg."""
    ffmpeg_path = resolve_ffmpeg_path(project_root)
    if not ffmpeg_path:
        return None

    os.environ["FFMPEG_BINARY"] = ffmpeg_path
    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path
    ffprobe_path = resolve_ffprobe_path(project_root, ffmpeg_path)
    if ffprobe_path:
        os.environ["FFPROBE_BINARY"] = ffprobe_path
    binary_dir = str(Path(ffmpeg_path).parent)
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    if binary_dir not in path_entries:
        os.environ["PATH"] = os.pathsep.join([binary_dir, *path_entries])
    return ffmpeg_path


def read_video_frames_rgba(
    ffmpeg_path: str | None,
    path: str | Path,
    max_frames: int = 6000,
    max_total_bytes: int = 256 * 1024 * 1024,
) -> list[Any] | None:
    """用 ffmpeg 把视频完整解码为 RGBA 帧列表（保留透明通道）。

    解码失败、帧数或内存超过上限时返回 None，由调用方回退到其他读取方式
    （例如 OpenCV VideoCapture——注意它通常会丢弃 alpha 通道）。
    """
    if not ffmpeg_path or not Path(str(path)).is_file():
        return None
    startupinfo = None
    creationflags = 0
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [
                str(ffmpeg_path),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(path),
                "-an",
                "-f",
                "image2pipe",
                "-c:v",
                "png",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    try:
        from PIL import Image
    except Exception:
        return None

    frames: list[Any] = []
    total_bytes = 0
    signature = b"\x89PNG\r\n\x1a\n"
    cursor = 0
    stream = result.stdout
    while cursor < len(stream):
        start = stream.find(signature, cursor)
        if start < 0:
            break
        end = stream.find(signature, start + len(signature))
        if end < 0:
            end = len(stream)
        blob = stream[start:end]
        cursor = end
        if not blob:
            continue
        try:
            with Image.open(io.BytesIO(blob)) as image:
                rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        except Exception:
            continue
        frames.append(rgba)
        total_bytes += rgba.shape[0] * rgba.shape[1] * 4
        if len(frames) > max_frames or total_bytes > max_total_bytes:
            return None
    return frames or None


def probe_ffmpeg(ffmpeg_path: str | None) -> tuple[bool, str | None]:
    """Run a bounded version probe and return availability plus version text."""
    if not _is_executable_file(ffmpeg_path):
        return False, None
    startupinfo = None
    creationflags = 0
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [str(ffmpeg_path), "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError):
        return False, None
    if result.returncode != 0:
        return False, None
    first_line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), None)
    return True, first_line
