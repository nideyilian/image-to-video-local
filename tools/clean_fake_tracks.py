#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
批量修复“假字幕轨 / 异常数据轨”视频与音频文件
================================================

背景：部分后期/录制工具会在 mp4/mov 等文件里写入一条“假时长”的字幕轨或
bin_data 数据轨（例如 encd 轨），Windows 资源管理器与部分播放器会把它的
时长当作视频时长显示（8 秒视频显示成 2 分多钟甚至 5 分多钟），但实际
内容时长是正确的。

本脚本扫描目录中的媒体文件，发现含异常轨的文件后用 FFmpeg 流复制重封装
（只保留正常音视频轨，不重新编码、画质不变），另存为 *_clean 文件，
原文件保持不动。

用法：
    python tools/clean_fake_tracks.py <目录> [--suffix _clean] [--dry-run] [--no-recursive]

    --dry-run       只列出需要修复的文件，不实际生成
    --no-recursive  不递归子目录
    --suffix NAME   干净文件的命名后缀（默认 _clean）

FFmpeg 查找顺序：环境变量 FFMPEG_PATH（或 FFMPEG_DIR）→ PATH 中的 ffmpeg →
常见 WinGet 安装路径。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 复用引擎的 box 级「去假轨」实现（处理 ffmpeg -map 拦不住的 chap 章节引用轨）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.engine.mp4_strip import has_moov_container, strip_tainted_tracks  # noqa: E402

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma", ".aiff"}
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm", ".m4v",
    ".ts", ".mpg", ".mpeg", ".3gp", ".rmvb", ".f4v",
}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


def find_ffmpeg() -> str | None:
    candidates = [
        os.environ.get("FFMPEG_PATH"),
        os.environ.get("FFMPEG_DIR"),
        shutil.which("ffmpeg"),
    ]
    for raw in candidates:
        if raw:
            path = Path(raw)
            if path.is_file():
                return str(path)
            if path.is_dir():
                for name in ("ffmpeg.exe", "ffmpeg"):
                    found = path / name
                    if found.is_file():
                        return str(found)
    # 常见 WinGet 安装路径兜底
    for base in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages",
        Path.home() / "scoop" / "apps" / "ffmpeg" / "current" / "bin",
    ):
        if base.is_dir():
            matches = sorted(base.glob("*/ffmpeg-n*/bin/ffmpeg.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
            if matches:
                return str(matches[0])
            direct = base / "bin" / "ffmpeg.exe"
            if direct.is_file():
                return str(direct)
    return None


def probe_streams(ffprobe: str, path: Path) -> list[dict]:
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "stream=index,codec_type,codec_name,duration:stream_disposition=attached_pic",
             "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError:
        return []
    streams = []
    for raw in data.get("streams") or []:
        if not isinstance(raw, dict):
            continue
        disposition = raw.get("disposition")
        streams.append({
            "index": int(raw.get("index", 0) or 0),
            "codec_type": str(raw.get("codec_type") or ""),
            "codec_name": str(raw.get("codec_name") or ""),
            "duration": raw.get("duration"),
            "attached_pic": bool(isinstance(disposition, dict) and disposition.get("attached_pic")),
        })
    return streams


def taint_reason(streams: list[dict], is_audio: bool) -> str | None:
    for stream in streams:
        codec_type = stream.get("codec_type") or ""
        codec_name = stream.get("codec_name") or ""
        duration = stream.get("duration")
        duration_text = f"{float(duration):.1f} 秒" if isinstance(duration, (int, float)) else "未知时长"
        if codec_type == "subtitle":
            return f"含字幕轨（{codec_name}，{duration_text}）"
        if codec_type == "data" or codec_name in ("bin_data", "text"):
            return f"含异常数据轨（{codec_name or codec_type}，{duration_text}）"
        if is_audio and codec_type == "video" and not stream.get("attached_pic"):
            return f"音频文件含视频轨（{codec_name}，{duration_text}）"
    return None


def taint_indexes(streams: list[dict], is_audio: bool) -> set[int]:
    indexes: set[int] = set()
    for stream in streams:
        codec_type = stream.get("codec_type") or ""
        codec_name = stream.get("codec_name") or ""
        if codec_type == "subtitle":
            indexes.add(int(stream.get("index", 0)))
        elif codec_type == "data" or codec_name in ("bin_data", "text"):
            indexes.add(int(stream.get("index", 0)))
        elif is_audio and codec_type == "video" and not stream.get("attached_pic"):
            indexes.add(int(stream.get("index", 0)))
    return indexes


def clean_file(ffmpeg: str, source: Path, suffix: str) -> tuple[bool, str]:
    """清洗单个文件：moov 容器走 box 级去假轨（无损、连章节引用轨也能处理），
    其他容器用 FFmpeg 流复制重封装。输出 *_clean 文件，原文件不动。"""
    streams = probe_streams(find_ffprobe(ffmpeg), source)
    is_audio = source.suffix.lower() in AUDIO_EXTENSIONS
    indexes = taint_indexes(streams, is_audio)
    if not indexes:
        return False, "未检测到异常轨"
    target = source.with_name(f"{source.stem}{suffix}{source.suffix}")
    temporary = source.with_name(f".{source.stem}.clean-tmp{suffix}{source.suffix}")
    try:
        if has_moov_container(source.suffix):
            ok, message = strip_tainted_tracks(source, indexes, temporary)
            if not ok or not temporary.is_file() or temporary.stat().st_size == 0:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                return False, f"box 级清洗失败: {message}"
        else:
            if is_audio:
                maps = ["-map", "0:a", "-map", "0:v?"]
            else:
                maps = ["-map", "0:v", "-map", "0:a?"]
            result = subprocess.run(
                [ffmpeg, "-y", "-i", str(source), *maps, "-c", "copy",
                 "-map_metadata", "0", "-movflags", "+faststart", str(temporary)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=300, check=False,
            )
            if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                return False, (result.stderr or "重封装失败").strip().splitlines()[-1][:200]
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False, f"执行失败: {exc}"
    try:
        os.replace(temporary, target)
        return True, str(target)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False, f"写入失败: {exc}"


def find_ffprobe(ffmpeg: str) -> str:
    candidate = str(Path(ffmpeg).with_name("ffprobe.exe"))
    return candidate if Path(candidate).is_file() else (shutil.which("ffprobe") or "ffprobe")


def main() -> int:
    parser = argparse.ArgumentParser(description="批量修复带假字幕轨/异常数据轨的媒体文件")
    parser.add_argument("directory", help="要扫描的目录")
    parser.add_argument("--suffix", default="_clean", help="干净文件后缀（默认 _clean）")
    parser.add_argument("--dry-run", action="store_true", help="只列出需要修复的文件，不实际生成")
    parser.add_argument("--no-recursive", action="store_true", help="不递归子目录")
    args = parser.parse_args()

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("[错误] 未找到 FFmpeg。请安装 ffmpeg 并加入 PATH，或设置环境变量 FFMPEG_PATH。", file=sys.stderr)
        return 1
    ffprobe = find_ffprobe(ffmpeg)

    root = Path(args.directory).resolve()
    if not root.is_dir():
        print(f"[错误] 目录不存在: {root}", file=sys.stderr)
        return 1

    pattern = "*" if args.no_recursive else "**/*"
    files = sorted(
        path for path in root.glob(pattern)
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS
    )
    scanned = tainted = cleaned = failed = 0
    for path in files:
        scanned += 1
        streams = probe_streams(ffprobe, path)
        if not streams:
            continue
        reason = taint_reason(streams, path.suffix.lower() in AUDIO_EXTENSIONS)
        if not reason:
            continue
        tainted += 1
        if args.dry_run:
            print(f"  [需修复] {path.name}：{reason}")
            continue
        ok, detail = clean_file(ffmpeg, path, args.suffix)
        if ok:
            cleaned += 1
            print(f"  [已修复] {path.name} → {Path(detail).name}（原因：{reason}）")
        else:
            failed += 1
            print(f"  [失败] {path.name}：{detail}", file=sys.stderr)

    print("-" * 60)
    print(f"扫描 {scanned} 个文件，发现异常 {tainted} 个，"
          f"{'待修复（dry-run）' if args.dry_run else f'已生成干净文件 {cleaned} 个'}，失败 {failed} 个。")
    if not args.dry_run and cleaned:
        print(f"干净文件位于原文件旁（后缀 {args.suffix}），确认无误后可删除原文件。")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
