"""背景音乐：候选筛选与 FFmpeg 混入（与界面无关的渲染内核）。

从 ``src/gui/main_window.py`` 的 ``ImageToVideoTab`` 抽出，函数体逐字保留。
界面侧配置（bgm_dir / use_bgm / random_bgm / loop_bgm / watermark_audio）
均通过 ``read_value(ctx, name)`` 获取。本模块不导入任何 GUI 库。
"""

from __future__ import annotations

import os
import random

from .codec import build_temp_output_path
from .context import RenderContext, notify, read_value
from .images import normalize_path
from .process import probe_video_meta, run_process_with_retry, safe_replace_file


def add_audio_with_ffmpeg(video_path, audio_file, volume=0.5, ctx=None):
    """使用ffmpeg直接添加背景音乐"""
    try:
        # 标准化路径
        video_path = normalize_path(video_path, ctx.notify)
        audio_file = normalize_path(audio_file, ctx.notify)
        
        # 创建临时输出文件
        temp_output = build_temp_output_path(video_path, "temp", ctx)
        
        # 构建ffmpeg命令 - 简化版，更可靠
        volume_str = f"{volume:.2f}"
        loop_audio = True
        _loop = read_value(ctx, "loop_bgm")
        if _loop is not None:
            loop_audio = bool(_loop)
        cmd = [
            ctx.ffmpeg_executable or "ffmpeg", "-y",  # 覆盖输出文件
            "-i", video_path,  # 输入视频
        ]
        if loop_audio:
            cmd += ["-stream_loop", "-1"]  # 循环音频
        cmd += [
            "-i", audio_file,  # 输入音频
            "-filter_complex", f"[1:a]volume={volume_str}[a]",  # 设置音量
            "-map", "0:v", "-map", "[a]",  # 使用原视频和处理后的音频
            "-c:v", "copy",  # 复制视频流
        ]
        if loop_audio:
            # 循环音频无限长，-shortest 以视频时长为准
            cmd += ["-shortest"]
        else:
            # 非循环：用 -t 硬性限定输出时长 = 视频时长，
            # 避免 BGM 比视频短时 -shortest 把视频截短。
            duration_sec = 0.0
            try:
                meta = probe_video_meta(video_path, ctx.ffprobe_executable, ctx.ffmpeg_executable,
                                          ctx.startupinfo, ctx.fps_provider)
                if meta:
                    duration_sec = float(meta.get("duration") or 0.0)
            except Exception:
                duration_sec = 0.0
            if duration_sec > 0:
                cmd += ["-t", f"{duration_sec:.3f}"]
            else:
                cmd += ["-shortest"]
        cmd += [temp_output]
        
        # 打印完整命令方便调试
        cmd_str = " ".join(str(c) for c in cmd)
        notify(ctx, f"执行命令: {cmd_str}")
        
        # 执行命令并获取详细错误信息（含超时与重试）
        result = run_process_with_retry(
            cmd,
            stage="BGM",
            timeout_sec=240,
            retries=2,
            log_func=lambda m: notify(ctx, m),
            startupinfo=ctx.startupinfo,
        )
        if result is None:
            notify(ctx, "ffmpeg执行失败：无可用结果")
            return False
        stderr_output = result.stderr.decode('utf-8', errors='ignore')
        
        if result.returncode != 0:
            notify(ctx, f"ffmpeg命令执行失败，错误码: {result.returncode}")
            notify(ctx, f"错误信息: {stderr_output}")
            return False
        
        # 检查输出文件
        if os.path.exists(temp_output) and os.path.getsize(temp_output) > 1000:
            # 成功生成，替换原文件
            if not safe_replace_file(temp_output, video_path):
                notify(ctx, "替换文件失败: 无法用新文件覆盖旧视频")
                return False
            
            notify(ctx, f"成功使用FFmpeg添加背景音乐")
            return True
        else:
            notify(ctx, "FFmpeg生成的文件无效")
            if os.path.exists(temp_output):
                notify(ctx, f"临时文件大小: {os.path.getsize(temp_output)} 字节")
            return False
    except Exception as e:
        notify(ctx, f"使用FFmpeg添加音频时出错: {str(e)}")
        import traceback
        notify(ctx, traceback.format_exc())
        return False


def get_audio_files(directory, ctx=None):
    """获取目录中的音频文件列表"""
    audio_files = []
    
    try:
        for file in os.listdir(directory):
            if file.lower().endswith(('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac')):
                audio_files.append(os.path.join(directory, file))
    except Exception as e:
        notify(ctx, f"获取音频文件列表时出错: {str(e)}")
    
    return audio_files


def resolve_bgm_candidates(ctx=None):
    """返回本次可用的BGM候选：优先使用素材库显式选定的文件，否则扫描音频目录。"""
    explicit = [
        path for path in read_value(ctx, "_bgm_files") or []
        if os.path.isfile(path)
    ]
    if explicit:
        return sorted(explicit)
    bgm_dir = read_value(ctx, "bgm_dir")
    if not bgm_dir or not os.path.exists(bgm_dir):
        return []
    return sorted(get_audio_files(bgm_dir, ctx))

def select_bgm_file(ctx=None):
    """获取本次应使用的BGM文件。"""
    if not read_value(ctx, "use_bgm", False):
        return None
    audio_strategy = read_value(ctx, "watermark_audio", "使用BGM")
    if audio_strategy not in ("使用BGM", "两者混合"):
        return None
    bgm_files = resolve_bgm_candidates(ctx)
    if not bgm_files:
        return None
    if read_value(ctx, "random_bgm", False):
        return random.choice(bgm_files)
    return bgm_files[0]
