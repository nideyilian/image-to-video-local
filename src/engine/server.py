"""NDJSON bridge used by desktop shells to control the local Python engine."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from PIL import Image

from ..utils.ffmpeg_runtime import configure_ffmpeg_environment, probe_ffmpeg
from .config import build_default_config, normalize_config, scan_audio_files, scan_images, validate_config
from .effect_preview import render_effect_preview
from .runner import JobManager


PROTOCOL_VERSION = 1


def _configure_utf8_stdio() -> None:
    """Keep the desktop bridge lossless for non-ASCII Windows paths."""
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


class EngineServer:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.ffmpeg_path = configure_ffmpeg_environment(self.project_root)
        self.ffmpeg_available, self.ffmpeg_version = probe_ffmpeg(self.ffmpeg_path)
        self._output_lock = threading.Lock()
        self._running = True
        self.jobs = JobManager(self.project_root, callback=self.emit)

    def emit(self, payload: dict[str, Any]) -> None:
        with self._output_lock:
            print(json.dumps(payload, ensure_ascii=False), flush=True)

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("id")
        method = str(request.get("method", "")).strip()
        params = request.get("params")
        if not isinstance(params, dict):
            params = {}
        try:
            result = self._dispatch(method, params)
            return {"type": "response", "id": request_id, "ok": True, "result": result}
        except Exception as exc:
            return {"type": "response", "id": request_id, "ok": False, "error": str(exc)}

    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        if method == "health":
            return {
                "protocol": PROTOCOL_VERSION,
                "engine": "legacy-compatible",
                "pid": os.getpid(),
                "capabilities": [
                    "config",
                    "scan",
                    "preview-thumbnail",
                    "preview-effect",
                    "preview-bgm",
                    "render",
                    "pause",
                    "cancel",
                    "multi-job",
                    "system-snapshot",
                ],
            }
        if method == "system_snapshot":
            return self._system_snapshot(params)
        if method == "optimize_memory":
            return self._optimize_memory()
        if method == "default_config":
            return build_default_config()
        if method == "normalize_config":
            return normalize_config(params.get("config"))
        if method == "validate_config":
            errors = validate_config(params.get("config"), check_files=bool(params.get("check_files", True)))
            return {"valid": not errors, "errors": errors}
        if method == "scan_images":
            images = scan_images(str(params.get("input_dir", "")), params.get("limit"))
            return {
                "count": len(scan_images(str(params.get("input_dir", "")))),
                "images": [
                    {"path": path, "name": Path(path).name}
                    for path in images
                ],
            }
        if method == "preview_thumbnail":
            return self._preview_thumbnail(params)
        if method == "preview_effect_frame":
            return render_effect_preview(params)
        if method == "preview_bgm":
            return self._preview_bgm(params)
        if method == "start_job":
            return self.jobs.start(params.get("config") or {}, params.get("job_id"))
        if method == "pause_job":
            return self.jobs.pause(str(params.get("job_id", "")))
        if method == "resume_job":
            return self.jobs.resume(str(params.get("job_id", "")))
        if method == "cancel_job":
            return self.jobs.cancel(str(params.get("job_id", "")))
        if method == "list_jobs":
            return self.jobs.list_jobs()
        if method == "shutdown":
            self._running = False
            return {"shutting_down": True}
        raise ValueError(f"未知方法: {method}")

    def _system_snapshot(self, params: dict[str, Any]) -> dict[str, Any]:
        import psutil

        output_dir = str(params.get("output_dir", "") or self.project_root)
        disk_target = output_dir if Path(output_dir).exists() else str(self.project_root)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(disk_target)
        process = psutil.Process(os.getpid())
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": round(float(memory.percent), 1),
            "memory_available_gb": round(memory.available / (1024 ** 3), 1),
            "process_memory_mb": round(process.memory_info().rss / (1024 ** 2), 1),
            "disk_free_gb": round(disk.free / (1024 ** 3), 1),
            "ffmpeg_available": self.ffmpeg_available,
            "ffmpeg_path": self.ffmpeg_path,
            "ffmpeg_version": self.ffmpeg_version,
        }

    @staticmethod
    def _optimize_memory() -> dict[str, Any]:
        import psutil

        process = psutil.Process(os.getpid())
        before = process.memory_info().rss / (1024 ** 2)
        collected = gc.collect()
        after = process.memory_info().rss / (1024 ** 2)
        return {
            "collected": collected,
            "before_mb": round(before, 1),
            "after_mb": round(after, 1),
        }

    def _preview_thumbnail(self, params: dict[str, Any]) -> dict[str, Any]:
        source = str(params.get("path", "") or "").strip()
        if not source:
            input_dir = str(params.get("input_dir", "") or "").strip()
            candidates = scan_images(input_dir, limit=1)
            source = candidates[0] if candidates else ""
        if not source or not Path(source).is_file():
            raise ValueError("没有可预览的图片")

        max_width = max(64, min(1920, int(params.get("max_width", 960) or 960)))
        max_height = max(64, min(1080, int(params.get("max_height", 540) or 540)))
        preview_dir = Path(tempfile.gettempdir()) / "image-to-video-engine" / "previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        stat = Path(source).stat()
        cache_key = f"{Path(source).resolve()}:{stat.st_mtime_ns}:{max_width}x{max_height}"
        import hashlib

        preview_path = preview_dir / f"{hashlib.sha1(cache_key.encode('utf-8')).hexdigest()}.jpg"
        with Image.open(source) as image:
            image = image.convert("RGB")
            image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            width, height = image.size
            if not preview_path.exists():
                image.save(preview_path, "JPEG", quality=88, optimize=True)
        return {
            "source": str(Path(source).resolve()),
            "preview_path": str(preview_path.resolve()),
            "width": width,
            "height": height,
        }

    @staticmethod
    def _preview_bgm(params: dict[str, Any]) -> dict[str, Any]:
        config = normalize_config(params.get("config"))
        if not bool(config.get("use_bgm")):
            return {"enabled": False, "reason": "BGM 已关闭"}
        strategy = str(config.get("watermark_audio", "使用BGM") or "使用BGM")
        if strategy not in {"使用BGM", "两者混合"}:
            return {"enabled": False, "reason": f"声音策略：{strategy}"}

        bgm_dir = str(config.get("bgm_dir", "") or "").strip()
        if not bgm_dir or not Path(bgm_dir).is_dir():
            raise ValueError("BGM目录不存在，请重新选择")
        candidates = scan_audio_files(bgm_dir)
        if not candidates:
            raise ValueError("BGM目录中没有可用音频")

        source = Path(candidates[0])
        if bool(config.get("random_bgm")) and len(candidates) > 1:
            seed = hashlib.sha1(str(Path(bgm_dir).resolve()).encode("utf-8")).digest()
            source = Path(candidates[int.from_bytes(seed[:4], "big") % len(candidates)])

        stat = source.stat()
        cache_key = f"{source.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
        preview_dir = Path(tempfile.gettempdir()) / "image-to-video-engine" / "audio-previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = preview_dir / f"{hashlib.sha1(cache_key.encode('utf-8')).hexdigest()}{source.suffix.lower()}"
        if not preview_path.exists():
            shutil.copy2(source, preview_path)
        return {
            "enabled": True,
            "source": str(source.resolve()),
            "preview_path": str(preview_path.resolve()),
            "name": source.name,
            "random": bool(config.get("random_bgm")),
        }

    def serve(self) -> int:
        for raw_line in sys.stdin:
            if not self._running:
                break
            line = raw_line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("请求必须是 JSON 对象")
                response = self.handle(request)
            except Exception as exc:
                response = {"type": "response", "id": None, "ok": False, "error": str(exc)}
            self.emit(response)
            if not self._running:
                break
        return 0


def _run_legacy_worker(argv: list[str]) -> int:
    from src.gui_qt.tk_bridge_runner import main as bridge_main

    previous = sys.argv
    try:
        sys.argv = [argv[0], *[value for value in argv[1:] if value != "--legacy-worker"]]
        return int(bridge_main())
    finally:
        sys.argv = previous


def main() -> int:
    _configure_utf8_stdio()
    if "--legacy-worker" in sys.argv:
        return _run_legacy_worker(sys.argv)

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--once", default="", help="Handle one JSON request and exit")
    args = parser.parse_args()
    server = EngineServer(args.project_root)
    if args.once:
        request = json.loads(args.once)
        server.emit(server.handle(request))
        return 0
    return server.serve()


if __name__ == "__main__":
    raise SystemExit(main())
