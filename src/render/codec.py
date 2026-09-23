"""编码器与容器解析（与界面无关的渲染内核）。

从 ``src/gui/main_window.py`` 的 ``ImageToVideoTab`` 抽出，函数体逐字保留：
用户选择的编码器、运行期探测结果、ffmpeg 状态与可执行文件路径、
申请进程标志、探测缓存等界面侧状态统一由 ``CodecContext`` 传入。
本模块不导入任何 GUI 库。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..utils.ffmpeg_runtime import resolve_ffprobe_path
from ..utils.opencv_silent import import_cv2_silent
from .process import probe_video_meta

cv2 = import_cv2_silent()


@dataclass
class CodecContext:
    """编码解析所需的界面侧上下文。全部可选，内核独立使用时留空。"""

    codec_provider: Callable[[], str] | None = None
    runtime_probe: dict[str, Any] | None = None
    ffmpeg_available: bool = False
    ffmpeg_executable: str | None = None
    ffprobe_executable: str | None = None
    startupinfo: Any = None
    notify: Callable[[str], None] | None = None
    fps_provider: Callable[[], float] | None = None
    probe_cache: dict[str, bool] | None = None


def _noop(_message) -> None:
    """默认进度回调：内核被独立使用时静默。"""


def _notify(ctx: "CodecContext", message: str) -> None:
    if ctx.notify:
        ctx.notify(message)


def check_codec_availability(codec, force_recheck=False, ctx=None):
    """检查编码器是否可用"""
    ctx = ctx or CodecContext()
    if not force_recheck:
        cache = ctx.probe_cache if ctx.probe_cache is not None else {}
        if codec in cache:
            return cache[codec]

    # 创建临时视频写入器测试编码器
    try:
        # 尝试创建1帧的临时视频
        fourcc = cv2.VideoWriter_fourcc(*codec)
        temp_file = os.path.join(os.getcwd(), f"temp_{int(time.time())}.mp4")
        temp_writer = cv2.VideoWriter(temp_file, fourcc, 30, (640, 480))
        
        is_opened = temp_writer.isOpened()
        temp_writer.release()
        
        # 清理临时文件
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
            
        if ctx.probe_cache is not None:
            ctx.probe_cache[codec] = is_opened
        return is_opened
    except Exception:
        if ctx.probe_cache is not None:
            ctx.probe_cache[codec] = False
        return False


def get_h264_codec(ctx=None):
    """获取系统支持的H.264编码器标识符"""
    ctx = ctx or CodecContext()
    # 尝试不同的H.264编码器代码
    h264_codecs = ['avc1', 'h264', 'x264', 'H264']
    
    for codec in h264_codecs:
        if check_codec_availability(codec, ctx=ctx):
            _notify(ctx, f"找到可用的H.264编码器: {codec}")
            return codec
    
    # 如果没有找到可用的H.264编码器，返回None
    _notify(ctx, "未找到可用的H.264编码器")
    return None

def get_selected_codec_name(ctx=None):
    """获取用户选择的编码器名称"""
    ctx = ctx or CodecContext()
    if ctx.codec_provider is not None:
        return ctx.codec_provider()
    return "XVID"

def resolve_cv_fourcc(ctx=None):
    """解析用户选择的编码器为OpenCV fourcc"""
    ctx = ctx or CodecContext()
    selected = get_selected_codec_name(ctx)
    if selected == "H264":
        return get_h264_codec(ctx)
    if check_codec_availability(selected, ctx=ctx):
        return selected
    return None

def resolve_processing_fourcc(ctx=None):
    """后处理环节严格沿用用户选择的OpenCV编码器，不再自动回退。"""
    ctx = ctx or CodecContext()
    return resolve_cv_fourcc(ctx)

def get_ffmpeg_vcodec(ctx=None):
    """获取FFmpeg视频编码器名称"""
    ctx = ctx or CodecContext()
    selected = get_selected_codec_name(ctx)
    mapping = {
        "H264": "libx264",
        "XVID": "libxvid",
        "MJPG": "mjpeg",
        "mp4v": "mpeg4"
    }
    return mapping.get(selected, "libx264")

def get_strict_ffmpeg_vcodec_for_output(output_path, ctx=None):
    """获取严格编码器：必须是用户选择且与目标容器兼容。"""
    ctx = ctx or CodecContext()
    selected = get_ffmpeg_vcodec(ctx)
    compatible = get_container_compatible_vcodecs(output_path, ctx=ctx)
    if selected not in compatible:
        return None
    return selected

def get_output_extension(output_path, ctx=None):
    """获取输出文件扩展名（小写），默认.mp4。"""
    ctx = ctx or CodecContext()
    ext = os.path.splitext(str(output_path))[1].lower()
    return ext if ext else ".mp4"

def build_temp_output_path(output_path, suffix, ctx=None):
    """按目标输出扩展名生成临时文件路径。"""
    ctx = ctx or CodecContext()
    base, _ = os.path.splitext(output_path)
    ext = get_output_extension(output_path, ctx=ctx)
    return f"{base}.{suffix}{ext}"

def get_ffmpeg_muxer_for_output(output_path, ctx=None):
    """根据目标扩展名返回FFmpeg muxer。"""
    ctx = ctx or CodecContext()
    ext = get_output_extension(output_path, ctx=ctx)
    mapping = {
        ".mp4": "mp4",
        ".m4v": "mp4",
        ".mov": "mov",
        ".avi": "avi",
        ".mkv": "matroska",
    }
    return mapping.get(ext)

def get_container_compatible_vcodecs(output_path, preferred_codec=None, ctx=None):
    """根据目标容器返回兼容的视频编码器候选列表。"""
    ctx = ctx or CodecContext()
    ext = get_output_extension(output_path, ctx=ctx)
    container_codecs = {
        ".mp4": ["libx264", "mpeg4"],
        ".m4v": ["libx264", "mpeg4"],
        ".mov": ["libx264", "mpeg4", "prores_ks"],
        ".avi": ["libxvid", "mpeg4", "mjpeg"],
        ".mkv": ["libx264", "mpeg4", "libxvid", "mjpeg"],
    }
    candidates = list(container_codecs.get(ext, ["libx264", "mpeg4", "libxvid", "mjpeg"]))
    if preferred_codec and preferred_codec in candidates:
        candidates.remove(preferred_codec)
        candidates.insert(0, preferred_codec)
    return candidates

def get_container_compatible_acodec(output_path, ctx=None):
    """根据目标容器返回兼容音频编码器。"""
    ctx = ctx or CodecContext()
    ext = get_output_extension(output_path, ctx=ctx)
    if ext == ".avi":
        return "mp3"
    return "aac"

def get_fallback_processing_fourcc(ctx=None):
    """为OpenCV处理阶段提供兜底编码器（仅中间文件使用）。"""
    ctx = ctx or CodecContext()
    preferred = None
    if isinstance(ctx.runtime_probe, dict):
        preferred = ctx.runtime_probe.get("preferred_cv_codec")
    candidates = tuple(c for c in (preferred, "mp4v", "XVID", "MJPG") if c)
    for codec in candidates:
        if check_codec_availability(codec, ctx=ctx):
            return codec
    return None

def reencode_video_to_selected_codec(src_path, dst_path, log_func=None, ctx=None):
    """将中间文件重编码为用户指定编码器/容器。"""
    ctx = ctx or CodecContext()
    def _log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)

    if not ctx.ffmpeg_available:
        _log("FFmpeg不可用，无法执行重编码")
        return False

    strict_vcodec = get_strict_ffmpeg_vcodec_for_output(dst_path, ctx=ctx)
    if not strict_vcodec:
        _log(
            f"目标编码器与容器不兼容: codec={get_selected_codec_name(ctx)}, ext={get_output_extension(dst_path, ctx=ctx)}"
        )
        return False

    muxer = get_ffmpeg_muxer_for_output(dst_path, ctx=ctx)
    fps = 30
    try:
        meta = probe_video_meta(src_path, ctx.ffprobe_executable, ctx.ffmpeg_executable,
                         ctx.startupinfo, ctx.fps_provider)
        if meta and meta.get("fps", 0) > 0:
            fps = int(round(meta["fps"]))
    except Exception:
        pass

    cmd = [
        ctx.ffmpeg_executable or "ffmpeg", "-y",
        "-i", src_path,
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c:v", strict_vcodec,
        "-pix_fmt", "yuv420p",
        "-r", str(max(1, fps)),
    ]
    if strict_vcodec == "libx264":
        cmd += ["-preset", "medium"]
    # OpenCV生成的中间文件通常无音频，保留可选映射并设定兼容编码器
    cmd += ["-c:a", get_container_compatible_acodec(dst_path, ctx=ctx), "-b:a", "192k"]
    if muxer:
        cmd += ["-f", muxer]
    cmd += [dst_path]

    _log(f"执行重编码命令: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        startupinfo=ctx.startupinfo,
    )
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="ignore")
        _log(f"重编码失败，错误码={result.returncode}, 详情={err[:300]}")
        return False
    if not (os.path.exists(dst_path) and os.path.getsize(dst_path) > 1000):
        _log("重编码后输出文件无效")
        return False
    log_output_probe(dst_path, log_func, ctx)
    return True

def log_output_probe(output_path, log_func=None, ctx=None):
    """使用ffprobe记录输出文件容器/编码信息，便于排查。"""
    ctx = ctx or CodecContext()
    def _log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)

    ffprobe_path = ctx.ffprobe_executable or resolve_ffprobe_path(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ctx.ffmpeg_executable,
    )
    if not ffprobe_path:
        meta = probe_video_meta(output_path, ctx.ffprobe_executable, ctx.ffmpeg_executable,
                             ctx.startupinfo, ctx.fps_provider)
        if meta:
            _log(
                f"[PROBE] 输出校验: size={meta['width']}x{meta['height']}, "
                f"fps={meta['fps']:.3f}, duration={meta['duration']:.3f}s"
            )
        return

    try:
        cmd = [
            ffprobe_path,
            "-v", "error",
            "-show_entries", "format=format_name:stream=codec_name,pix_fmt,width,height,avg_frame_rate",
            "-select_streams", "v:0",
            "-of", "json",
            output_path
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=ctx.startupinfo,
        )
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="ignore")
            _log(f"[PROBE] ffprobe失败: {err[:240]}")
            return

        payload = json.loads(result.stdout.decode("utf-8", errors="ignore") or "{}")
        fmt = (payload.get("format") or {}).get("format_name", "unknown")
        streams = payload.get("streams") or []
        if streams:
            s = streams[0]
            codec = s.get("codec_name", "unknown")
            pix = s.get("pix_fmt", "unknown")
            w = s.get("width", "?")
            h = s.get("height", "?")
            fps = s.get("avg_frame_rate", "unknown")
            _log(f"[PROBE] 输出校验: format={fmt}, vcodec={codec}, pix_fmt={pix}, size={w}x{h}, fps={fps}")
        else:
            _log(f"[PROBE] 输出校验: format={fmt}, 未找到视频流")
    except Exception as e:
        _log(f"[PROBE] 输出校验异常: {str(e)}")
