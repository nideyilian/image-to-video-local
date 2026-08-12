"""NDJSON bridge used by desktop shells to control the local Python engine."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from ..utils.ffmpeg_runtime import configure_ffmpeg_environment, probe_ffmpeg
from .config import build_default_config, normalize_config, scan_audio_files, scan_images, validate_config, validate_config_detailed
from .preview_random import preview_choice, preview_sample
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
        # ffmpeg 版本探测需要启动 ffmpeg 子进程（安装版首次运行还会触发杀软扫描），
        # 属于重操作。启动关键路径上只解析路径，真正的版本探测延迟到首次需要时再做。
        self.ffmpeg_path = configure_ffmpeg_environment(self.project_root)
        self.ffmpeg_available: bool | None = None
        self.ffmpeg_version: str | None = None
        self._ffmpeg_probed = False
        self._ffmpeg_probe_lock = threading.Lock()
        self._output_lock = threading.Lock()
        self._running = True
        self.jobs = JobManager(self.project_root, callback=self.emit)

    def _ensure_ffmpeg_probed(self) -> None:
        """惰性探测 ffmpeg，只在 system_snapshot / 预览等真正需要时才执行。"""
        if self._ffmpeg_probed:
            return
        with self._ffmpeg_probe_lock:
            if self._ffmpeg_probed:
                return
            self.ffmpeg_available, self.ffmpeg_version = probe_ffmpeg(self.ffmpeg_path)
            self._ffmpeg_probed = True

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
        if method == "validate_config_detailed":
            issues = validate_config_detailed(params.get("config"), check_files=bool(params.get("check_files", True)))
            return {"valid": not issues, "issues": issues}
        if method == "scan_images":
            all_images = scan_images(str(params.get("input_dir", "")))
            preview_sequence = int(params.get("preview_sequence", 0) or 0)
            limit = params.get("limit")
            images = (
                preview_sample(all_images, len(all_images) if limit is None else limit, preview_sequence, "images")
                if preview_sequence > 0
                else all_images if limit is None
                else all_images[: max(0, int(limit or 0))]
            )
            return {
                "count": len(all_images),
                "images": [
                    {"path": path, "name": Path(path).name}
                    for path in images
                ],
            }
        if method == "preview_thumbnail":
            return self._preview_thumbnail(params)
        if method == "preview_effect_frame":
            from .effect_preview import render_effect_preview

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

        self._ensure_ffmpeg_probed()
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
        from PIL import Image

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

    def _preview_bgm(self, params: dict[str, Any]) -> dict[str, Any]:
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

        preview_sequence = int(params.get("preview_sequence", 0) or 0)
        source = Path(candidates[0])
        if preview_sequence > 0:
            source = Path(preview_choice(candidates, preview_sequence, "bgm") or candidates[0])
        elif bool(config.get("random_bgm")) and len(candidates) > 1:
            seed = hashlib.sha1(str(Path(bgm_dir).resolve()).encode("utf-8")).digest()
            source = Path(candidates[int.from_bytes(seed[:4], "big") % len(candidates)])

        stat = source.stat()
        cache_key = f"mp3-v1:{source.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
        preview_dir = Path(tempfile.gettempdir()) / "image-to-video-engine" / "audio-previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = preview_dir / f"{hashlib.sha1(cache_key.encode('utf-8')).hexdigest()}.mp3"
        if not preview_path.exists():
            if not self.ffmpeg_path:
                raise ValueError("未找到 FFmpeg，无法读取 BGM 预览")
            temporary_path = preview_path.with_name(
                f".{preview_path.stem}-{os.getpid()}-{threading.get_ident()}.tmp.mp3"
            )
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
                        self.ffmpeg_path,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-nostdin",
                        "-y",
                        "-i",
                        str(source),
                        "-map",
                        "0:a:0",
                        "-vn",
                        "-c:a",
                        "libmp3lame",
                        "-q:a",
                        "4",
                        "-ar",
                        "44100",
                        "-ac",
                        "2",
                        str(temporary_path),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                    check=False,
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                )
                if result.returncode != 0 or not temporary_path.is_file():
                    detail = next(
                        (line.strip() for line in reversed(result.stderr.splitlines()) if line.strip()),
                        source.name,
                    )
                    raise ValueError(f"BGM预览转换失败：{detail}")
                os.replace(temporary_path, preview_path)
            except subprocess.TimeoutExpired as exc:
                raise ValueError("BGM预览转换超时，请检查音频文件") from exc
            finally:
                temporary_path.unlink(missing_ok=True)
        return {
            "enabled": True,
            "source": str(source.resolve()),
            "preview_path": str(preview_path.resolve()),
            "name": source.name,
            "mime_type": "audio/mpeg",
            "random": bool(config.get("random_bgm")),
        }

    def serve(self) -> int:
        # 引擎已就绪，立即通知前端关闭启动屏（无需等待 ffmpeg 探测或配置加载完成）。
        self.emit({"type": "event", "event": "engine.ready", "payload": {"protocol": PROTOCOL_VERSION}})
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
