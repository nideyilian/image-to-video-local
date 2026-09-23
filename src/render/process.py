"""子进程、文件与视频元信息的基础工具（与界面无关的渲染内核）。

从 ``src/gui/main_window.py`` 的 ``ImageToVideoTab`` 抽出，函数体逐字保留，仅把
实例状态（startupinfo / 日志文件 / ffprobe 路径 / 回退 fps）改为可注入参数。
本模块不导入任何 GUI 库。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

from ..utils.ffmpeg_runtime import resolve_ffprobe_path
from ..utils.opencv_silent import import_cv2_silent

cv2 = import_cv2_silent()


def ensure_even_frame(frame):
    """确保帧尺寸为偶数，满足H.264编码要求"""
    if frame is None:
        return None
    h, w = frame.shape[:2]
    pad_w = w % 2
    pad_h = h % 2
    if pad_w == 0 and pad_h == 0:
        return frame
    return cv2.copyMakeBorder(
        frame,
        0, pad_h, 0, pad_w,
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0)
    )

def log_pipeline_stage(stage, message, log_func=None, log_file=None):
    """统一流水线日志输出（阶段5：可观测性）。"""
    line = f"[PIPELINE][{stage}] {message}"
    if log_func:
        log_func(line)
    else:
        print(line)
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {line}\n")
    except Exception:
        pass

def run_process_with_retry(cmd, stage="PROC", timeout_sec=300, retries=1, log_func=None,
                           startupinfo=None):
    """子进程执行守护：超时、重试、统一日志。"""
    attempts = max(1, int(retries))
    last_result = None
    for attempt in range(attempts):
        try:
            if log_func:
                log_func(f"[{stage}] 执行命令（尝试 {attempt + 1}/{attempts}）")
            last_result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                timeout=max(10, int(timeout_sec)),
            )
            if last_result.returncode == 0:
                return last_result
            if log_func:
                err = (last_result.stderr or b"").decode("utf-8", errors="ignore")
                log_func(f"[{stage}] 命令失败: code={last_result.returncode}, err={err[:220]}")
        except subprocess.TimeoutExpired:
            if log_func:
                log_func(f"[{stage}] 命令超时: {timeout_sec}s")
        except Exception as e:
            if log_func:
                log_func(f"[{stage}] 命令异常: {str(e)}")
    return last_result

def safe_replace_file(src_path, dst_path):
    """安全替换文件，优先原子替换，失败回退复制。"""
    if not os.path.exists(src_path):
        return False
    try:
        if os.path.exists(dst_path):
            os.remove(dst_path)
        os.replace(src_path, dst_path)
        return True
    except Exception:
        try:
            shutil.copy2(src_path, dst_path)
            os.remove(src_path)
            return True
        except Exception:
            return False

def probe_video_meta(video_path, ffprobe_executable=None, ffmpeg_executable=None,
                     startupinfo=None, fallback_fps_provider=None):
    """读取视频元信息。"""
    def _safe_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    def _safe_int(value, default=0):
        try:
            return int(float(value))
        except Exception:
            return int(default)

    def _parse_fps(value):
        text = str(value or "").strip()
        if not text or text in ("0/0", "N/A"):
            return 0.0
        if "/" in text:
            num_text, den_text = text.split("/", 1)
            num = _safe_float(num_text, 0.0)
            den = _safe_float(den_text, 0.0)
            if den > 0:
                return num / den
            return 0.0
        return _safe_float(text, 0.0)

    # 1) 优先用 ffprobe，避免 OpenCV 在部分编码/容器上返回异常 FPS（常见导致时长异常）
    ffprobe_path = ffprobe_executable or resolve_ffprobe_path(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ffmpeg_executable,
    )
    try:
        if not ffprobe_path:
            raise FileNotFoundError("ffprobe unavailable")
        cmd = [
            ffprobe_path,
            "-v", "error",
            "-show_entries", "format=duration:stream=width,height,avg_frame_rate,r_frame_rate,nb_frames",
            "-select_streams", "v:0",
            "-of", "json",
            video_path,
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            timeout=20,
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout.decode("utf-8", errors="ignore") or "{}")
            streams = payload.get("streams") or []
            if streams:
                stream = streams[0]
                width = _safe_int(stream.get("width"), 0)
                height = _safe_int(stream.get("height"), 0)
                fps = _parse_fps(stream.get("avg_frame_rate"))
                if fps <= 0:
                    fps = _parse_fps(stream.get("r_frame_rate"))
                frames = _safe_int(stream.get("nb_frames"), 0)
                duration = _safe_float((payload.get("format") or {}).get("duration"), 0.0)

                if duration <= 0 and fps > 0 and frames > 0:
                    duration = frames / fps
                if frames <= 0 and fps > 0 and duration > 0:
                    frames = int(round(fps * duration))

                if width > 0 and height > 0:
                    return {
                        "width": width,
                        "height": height,
                        "fps": fps,
                        "frames": max(0, int(frames)),
                        "duration": max(0.0, float(duration)),
                    }
    except Exception:
        pass

    # 2) 回退 OpenCV
    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            return None
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = (frames / fps) if fps > 0 else 0.0

        # OpenCV 读取到异常 FPS 时，回落到用户设置值，避免后处理重编码后时长被拉长
        if fps <= 1.0 or fps > 240.0:
            try:
                fallback_fps = float(fallback_fps_provider() if fallback_fps_provider else 0.0)
                if fallback_fps > 0:
                    fps = fallback_fps
            except Exception:
                pass

        return {
            "width": width,
            "height": height,
            "fps": fps,
            "frames": frames,
            "duration": duration,
        }
    finally:
        cap.release()
