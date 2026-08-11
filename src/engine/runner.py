"""Process-backed job control for the current production rendering pipeline."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import normalize_config, validate_config


EventCallback = Callable[[dict[str, Any]], None]


@dataclass
class JobRecord:
    job_id: str
    config: dict[str, Any]
    config_path: Path
    control_path: Path
    process: subprocess.Popen[str] | None = None
    status: str = "queued"
    paused: bool = False
    cancel_requested: bool = False
    progress: int = 0
    overall: int = 0
    speed: str | None = None
    message: str = "等待处理"
    started_at: float | None = None
    finished_at: float | None = None
    return_code: int | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def public_state(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "paused": self.paused,
            "cancel_requested": self.cancel_requested,
            "progress": self.progress,
            "overall": self.overall,
            "speed": self.speed,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "return_code": self.return_code,
        }


class JobManager:
    """Launch and control render workers while emitting frontend-neutral events."""

    def __init__(self, project_root: str | Path, callback: EventCallback | None = None):
        self.project_root = Path(project_root).resolve()
        self.callback = callback or (lambda _event: None)
        self.jobs: dict[str, JobRecord] = {}
        self._jobs_lock = threading.Lock()

    def start(self, raw_config: dict[str, Any], job_id: str | None = None) -> dict[str, Any]:
        config = normalize_config(raw_config)
        errors = validate_config(config)
        if errors:
            raise ValueError(errors[0])

        resolved_job_id = str(job_id or uuid.uuid4().hex)
        with self._jobs_lock:
            existing = self.jobs.get(resolved_job_id)
            if existing and existing.status in {"running", "paused", "cancelling"}:
                raise ValueError("任务正在运行")

        runtime_dir = Path(tempfile.gettempdir()) / "image-to-video-engine"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        config_path = runtime_dir / f"{resolved_job_id}.config.json"
        control_path = runtime_dir / f"{resolved_job_id}.control.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        control_path.write_text(json.dumps({"paused": False, "cancel": False}), encoding="utf-8")

        record = JobRecord(
            job_id=resolved_job_id,
            config=config,
            config_path=config_path,
            control_path=control_path,
            status="running",
            message="开始处理",
            started_at=time.time(),
        )
        with self._jobs_lock:
            self.jobs[resolved_job_id] = record

        args = self._worker_command(config_path, control_path)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            record.process = subprocess.Popen(
                args,
                cwd=str(self.project_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=creation_flags,
            )
        except Exception:
            self._cleanup_runtime_files(record)
            with self._jobs_lock:
                self.jobs.pop(resolved_job_id, None)
            raise

        threading.Thread(target=self._read_stdout, args=(record,), daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(record,), daemon=True).start()
        threading.Thread(target=self._watch, args=(record,), daemon=True).start()
        self._emit("job.started", record.public_state())
        return record.public_state()

    def pause(self, job_id: str) -> dict[str, Any]:
        record = self._require_active(job_id)
        record.paused = True
        record.status = "paused"
        record.message = "已暂停"
        self._write_control(record)
        self._emit("job.status", record.public_state())
        return record.public_state()

    def resume(self, job_id: str) -> dict[str, Any]:
        record = self._require_active(job_id)
        record.paused = False
        record.status = "running"
        record.message = "继续处理"
        self._write_control(record)
        self._emit("job.status", record.public_state())
        return record.public_state()

    def cancel(self, job_id: str) -> dict[str, Any]:
        record = self._require_active(job_id)
        record.cancel_requested = True
        record.paused = False
        record.status = "cancelling"
        record.message = "正在取消"
        self._write_control(record)
        self._emit("job.status", record.public_state())
        return record.public_state()

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._jobs_lock:
            return [record.public_state() for record in self.jobs.values()]

    def _worker_command(self, config_path: Path, control_path: Path) -> list[str]:
        if getattr(sys, "frozen", False):
            return [
                sys.executable,
                "--legacy-worker",
                "--config",
                str(config_path),
                "--control",
                str(control_path),
            ]
        return [
            sys.executable,
            "-m",
            "src.gui_qt.tk_bridge_runner",
            "--config",
            str(config_path),
            "--control",
            str(control_path),
        ]

    def _require_active(self, job_id: str) -> JobRecord:
        with self._jobs_lock:
            record = self.jobs.get(str(job_id))
        if not record:
            raise KeyError("任务不存在")
        if record.status not in {"running", "paused", "cancelling"}:
            raise ValueError("任务已经结束")
        return record

    def _write_control(self, record: JobRecord) -> None:
        with record._lock:
            record.control_path.write_text(
                json.dumps({"paused": record.paused, "cancel": record.cancel_requested}),
                encoding="utf-8",
            )

    def _read_stdout(self, record: JobRecord) -> None:
        if not record.process or not record.process.stdout:
            return
        for raw_line in record.process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                self._emit("job.log", {"job_id": record.job_id, "stream": "stdout", "message": line})
                continue
            self._apply_worker_payload(record, payload)

    def _read_stderr(self, record: JobRecord) -> None:
        if not record.process or not record.process.stderr:
            return
        for raw_line in record.process.stderr:
            line = raw_line.strip()
            if line:
                self._emit("job.log", {"job_id": record.job_id, "stream": "stderr", "message": line})

    def _apply_worker_payload(self, record: JobRecord, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type", ""))
        if event_type == "progress":
            record.progress = int(payload.get("percent", record.progress) or 0)
            record.overall = int(payload.get("overall", record.progress) or 0)
            speed = payload.get("speed")
            record.speed = None if speed is None else str(speed)
            phase = str(payload.get("phase", "") or "").strip()
            if phase:
                record.message = phase
            self._emit("job.progress", {**record.public_state(), **payload})
        elif event_type == "status":
            record.message = str(payload.get("message", "处理中") or "处理中")
            self._emit("job.status", record.public_state())
        elif event_type == "done":
            success = bool(payload.get("success", False))
            record.status = "completed" if success else "failed"
            record.progress = 100 if success else record.progress
            record.overall = 100 if success else record.overall
            record.message = "处理完成" if success else "处理失败"
            self._emit("job.done", {**record.public_state(), "success": success})
        else:
            self._emit("job.log", {"job_id": record.job_id, "stream": "worker", "message": payload})

    def _watch(self, record: JobRecord) -> None:
        if not record.process:
            return
        return_code = record.process.wait()
        record.return_code = return_code
        record.finished_at = time.time()
        if record.cancel_requested:
            record.status = "cancelled"
            record.message = "任务已取消"
        elif record.status not in {"completed", "failed"}:
            record.status = "completed" if return_code == 0 else "failed"
            record.message = "处理完成" if return_code == 0 else f"处理失败（退出码 {return_code}）"
        self._cleanup_runtime_files(record)
        self._emit("job.finished", record.public_state())

    def _cleanup_runtime_files(self, record: JobRecord) -> None:
        for path in (record.config_path, record.control_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        self.callback({"type": "event", "event": event, "payload": payload})
