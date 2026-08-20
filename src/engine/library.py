"""素材库管理：BGM 库 / 水印库，以及「一键批量拆 BGM」。

核心能力：
- 库目录管理（默认位于 用户/Documents/图转视频素材库，可自定义）；
- 导入音频/图片到对应库，BGM 导入时做「避重」识别（内容指纹去重）；
- 从一批视频中批量抽取音轨保存为 MP3 到 BGM 库，自动跳过重复 BGM、
  无音轨的视频，并实时上报进度事件；
- 水印库按文件哈希精确去重，BGM 库按 1 秒 RMS 响度曲线指纹去重，
  可识别同一首歌的不同码率/格式副本。

指纹说明：把音频解码为 16kHz 单声道 PCM，按秒计算 RMS 响度向量，
归一化后比较。同一首歌即使码率、封装、响度不同，其归一化响度曲线
依然高度一致，从而判定为重复；不同歌曲的曲线差异明显，不会被误判。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

try:
    import numpy as _np
except Exception:  # pragma: no cover - 纯 Python 环境回退
    _np = None

from . import mp4_strip  # noqa: F401  # box 级「去假轨」清洗（处理 chap 章节引用轨）

try:
    from ..utils.ffmpeg_runtime import resolve_ffprobe_path
except Exception:  # pragma: no cover
    resolve_ffprobe_path = None

try:
    import send2trash as _send2trash
except Exception:  # pragma: no cover - 无 send2trash 依赖的环境
    _send2trash = None


def _trash(path: Path) -> None:
    """把文件/文件夹移入系统回收站（Windows），给用户反悔机会。

    未安装 send2trash 或移入失败时抛出明确错误，调用方（前端）据此提示，
    文件保留在原位，绝不静默回退为永久删除。
    """
    if _send2trash is None:
        raise ValueError("未安装回收站组件（send2trash），无法安全删除")
    try:
        _send2trash.send2trash(str(path))
    except Exception as exc:  # pragma: no cover - 取决于系统环境
        raise ValueError(f"移入回收站失败：{exc}") from exc


AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma", ".aiff"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"}
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm", ".m4v",
    ".ts", ".mpg", ".mpeg", ".3gp", ".rmvb", ".f4v",
}
# 水印库同时接受图片与视频素材（视频水印：mov/mp4 等）
WATERMARK_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

LIBRARY_ROOT_NAME = "图转视频素材库"
INDEX_FILE_NAME = ".library_index.json"
SMART_FOLDERS_FILE_NAME = ".smart_folders.json"

# 指纹参数
FINGERPRINT_SAMPLE_RATE = 16000
FINGERPRINT_CHANNELS = 1
FINGERPRINT_SAMPLE_WIDTH = 2
FINGERPRINT_MAX_SECONDS = 180  # 超过 3 分钟只分析前 3 分钟，足够区分歌曲
FINGERPRINT_DECODE_TIMEOUT = 90

# 避重判定参数
DURATION_TOLERANCE = 2.5  # 时长差（秒）在容差内才可能重复
SHIFT_TOLERANCE = 1  # 允许 ±1 秒的对齐误差
DUP_MAE_THRESHOLD = 0.07  # 归一化响度曲线平均绝对误差阈值
MIN_OVERLAP_FRACTION = 0.5  # 比较时至少需要重叠的比例

EXTRACT_AUDIO_TIMEOUT = 300
EXTRACT_BITRATE = "192k"

try:
    from ..utils.ffmpeg_runtime import resolve_ffprobe_path
except Exception:  # pragma: no cover
    resolve_ffprobe_path = None
DUP_PHASH_THRESHOLD = 8  # dHash 汉明距离阈值：≤8（共 64 位）视为相似图片
DUP_SCAN_MAX_IMAGES = 2000  # 单次去重扫描最多计算感知哈希的图片数，防止超大库卡顿


EventCallback = Callable[[dict[str, Any]], None]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _safe_name(name: str) -> str:
    """去掉路径分隔符与非法字符，避免写出到子目录。"""
    cleaned = "".join(
        character if character not in '<>:"/\\|?*' and ord(character) >= 32 else "_"
        for character in name
    ).strip()
    return cleaned or "未命名"


def _unique_path(directory: Path, name: str, existing_sha: dict[str, str]) -> Path:
    """在目录内找一个不冲突的文件名；与已有文件内容相同时直接复用原名。"""
    target = directory / name
    if not target.exists():
        return target
    if target.is_file() and existing_sha.get(target.name) == _file_sha256(target):
        return target
    stem = Path(name).stem
    suffix = Path(name).suffix
    counter = 2
    while True:
        candidate = directory / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _relative_folder(folder: Any) -> str:
    """把前端传入的文件夹参数规范化为相对路径（"" 表示库根目录）。

    拒绝绝对路径、上级目录跳转与非法字符，保证路径安全。
    """
    raw = str(folder or "").replace("\\", "/").strip().strip("/")
    parts = [part for part in raw.split("/") if part and part not in {".", ".."}]
    if not parts:
        return ""
    for part in parts:
        if len(part) > 80 or any(character in part for character in '<>:"|?*'):
            raise ValueError("文件夹名称包含非法字符")
    return "/".join(parts)


def _file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _image_dhash(path: Path, size: int = 8) -> str | None:
    """计算图片 dHash（感知哈希），返回 64 位十六进制字符串；失败返回 None。"""
    try:
        from PIL import Image

        with Image.open(path) as image:
            gray = image.convert("L").resize((size + 1, size), Image.LANCZOS)
            pixels = list(gray.getdata())
        bits: list[str] = []
        for row in range(size):
            offset = row * (size + 1)
            for col in range(size):
                bits.append("1" if pixels[offset + col] > pixels[offset + col + 1] else "0")
        return hex(int("".join(bits), 2))[2:].zfill(size * size // 4)
    except Exception:
        return None


def _hamming_distance(first: str, second: str) -> int:
    return sum(1 for x, y in zip(first, second) if x != y)


def _probe_audio_streams(ffprobe_path: str | None, path: Path) -> bool:
    """返回视频是否包含音频流；没有 ffprobe 时退回 True 由 ffmpeg 报错兜底。"""
    if not ffprobe_path:
        return True
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
                ffprobe_path,
                "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return bool(result.stdout.strip())


def _probe_duration(ffprobe_path: str | None, path: Path) -> float | None:
    """读取媒体时长（秒），失败返回 None。"""
    if not ffprobe_path:
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
                ffprobe_path,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _probe_streams(ffprobe_path: str | None, path: Path) -> list[dict[str, Any]]:
    """探测文件的所有流（index / codec_type / codec_name / duration / attached_pic）。

    失败返回空列表（调用方按“无法探测”处理，不阻断扫描）。
    """
    if not ffprobe_path or not path.is_file():
        return []
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
                ffprobe_path,
                "-v", "error",
                "-show_entries",
                "stream=index,codec_type,codec_name,duration:stream_disposition=attached_pic",
                "-of", "json",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError:
        return []
    streams: list[dict[str, Any]] = []
    for raw in data.get("streams") or []:
        if not isinstance(raw, dict):
            continue
        disposition = raw.get("disposition")
        attached_pic = bool(isinstance(disposition, dict) and disposition.get("attached_pic"))
        streams.append({
            "index": int(raw.get("index", 0) or 0),
            "codec_type": str(raw.get("codec_type") or ""),
            "codec_name": str(raw.get("codec_name") or ""),
            "duration": raw.get("duration"),
            "attached_pic": attached_pic,
        })
    return streams


def _taint_reason(streams: list[dict[str, Any]], kind: str) -> str | None:
    """判断文件是否含“假字幕轨/异常数据轨”。

    - 字幕轨（subtitle / mov_text / srt 等）：异常；
    - bin_data / text 数据轨（如部分后期软件写入的 encd 假时长轨）：异常；
    - 音频文件（BGM）里出现非封面（attached_pic）的视频轨：异常；
    - 内嵌封面（attached_pic 视频轨）属于正常内容，不视为异常。
    返回异常原因描述；没有异常返回 None。
    """
    for stream in streams:
        codec_type = stream.get("codec_type") or ""
        codec_name = stream.get("codec_name") or ""
        duration = stream.get("duration")
        duration_text = f"{float(duration):.1f} 秒" if isinstance(duration, (int, float)) else "未知时长"
        if codec_type == "subtitle":
            return f"含字幕轨（{codec_name}，{duration_text}）"
        if codec_type == "data" or codec_name == "bin_data" or codec_name == "text":
            return f"含异常数据轨（{codec_name or codec_type}，{duration_text}）"
        if kind == "bgm" and codec_type == "video" and not stream.get("attached_pic"):
            return f"音频文件含视频轨（{codec_name}，{duration_text}）"
    return None


def _tainted_indexes(streams: list[dict[str, Any]], kind: str) -> set[int]:
    """返回异常流的序号集合（与 _taint_reason 判定一致）。"""
    indexes: set[int] = set()
    for stream in streams:
        codec_type = stream.get("codec_type") or ""
        codec_name = stream.get("codec_name") or ""
        if codec_type == "subtitle":
            indexes.add(int(stream.get("index", 0)))
        elif codec_type == "data" or codec_name == "bin_data" or codec_name == "text":
            indexes.add(int(stream.get("index", 0)))
        elif kind == "bgm" and codec_type == "video" and not stream.get("attached_pic"):
            indexes.add(int(stream.get("index", 0)))
    return indexes


def _clean_tainted_file(ffmpeg_path: str | None, ffprobe_path: str | None, path: Path) -> dict[str, Any]:
    """清洗单个文件：丢弃字幕/数据轨（无损）。

    - mp4/mov/m4a 等 moov 容器：直接重写 moov 删除假轨与章节引用（不动媒体数据，
      连 ffmpeg -map 都拦不住的 chap 引用轨也能去掉）；
    - 其他容器：FFmpeg 流复制重封装（只保留正常音视频轨）。

    成功后原文件先移入回收站（可还原），干净版本占用原文件名；
    失败时临时文件清理、原文件保持不动。
    """
    streams = _probe_streams(ffprobe_path, path)
    kind = "bgm" if path.suffix.lower() in AUDIO_EXTENSIONS else "watermark"
    indexes = _tainted_indexes(streams, kind)
    if not indexes:
        return {"ok": False, "reason": "未检测到异常轨，跳过"}

    temporary = path.with_name(f".{path.stem}.clean-{os.getpid()}.tmp{path.suffix}")
    try:
        if mp4_strip.has_moov_container(path.suffix):
            if not indexes:
                return {"ok": False, "reason": "未检测到异常轨，跳过"}
            ok, message = mp4_strip.strip_tainted_tracks(path, indexes, temporary)
            if not ok or not temporary.is_file() or temporary.stat().st_size == 0:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                return {"ok": False, "reason": f"清洗失败: {message}"}
        else:
            if not ffmpeg_path:
                return {"ok": False, "reason": "FFmpeg 不可用"}
            suffix = path.suffix.lower()
            if suffix in AUDIO_EXTENSIONS:
                maps = ["-map", "0:a", "-map", "0:v?"]  # 音频 + 内嵌封面（若有）
            elif suffix in VIDEO_EXTENSIONS:
                maps = ["-map", "0:v", "-map", "0:a?"]  # 视频 + 音频（若有）
            else:
                return {"ok": False, "reason": f"不支持的文件类型: {suffix}"}
            result = _run_ffmpeg(
                [ffmpeg_path, "-y", "-i", str(path), *maps, "-c", "copy",
                 "-map_metadata", "0", "-movflags", "+faststart", str(temporary)],
                timeout=240,
            )
            if result is None or result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                return {"ok": False, "reason": "重封装失败"}
    except Exception as exc:  # noqa: BLE001 - 统一转为失败原因
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "reason": f"清洗异常: {exc}"}
    try:
        _trash(path)
        os.replace(temporary, path)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "reason": f"替换原文件失败: {exc}"}


def _extract_audio_cover(ffmpeg_path: str | None, path: Path) -> str | None:
    """从音频文件的内嵌封面提取图片并缓存；没有封面或失败返回 None。

    缓存目录位于系统临时目录（image-to-video-engine/library-covers），
    与资产协议作用域一致，前端可直接通过 asset:// 读取。
    """
    if not ffmpeg_path or not path.is_file():
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    cache_key = f"cover:{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
    digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()
    cover_dir = Path(tempfile.gettempdir()) / "image-to-video-engine" / "library-covers"
    try:
        cover_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    cover_path = cover_dir / f"{digest}.jpg"
    if cover_path.is_file() and cover_path.stat().st_size > 0:
        return str(cover_path)

    # 临时文件保留 .jpg 扩展名，ffmpeg 才能推断输出格式（与预览的 .tmp.mp3 同理）
    temporary_path = cover_path.with_name(f".{cover_path.stem}-{os.getpid()}-{threading.get_ident()}.tmp.jpg")
    try:
        result = _run_ffmpeg(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(path),
                "-an",
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-c:v",
                "copy",
                str(temporary_path),
            ],
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        if result.returncode != 0 or not temporary_path.is_file() or temporary_path.stat().st_size == 0:
            temporary_path.unlink(missing_ok=True)
            return None
        temporary_path.replace(cover_path)
        return str(cover_path)
    except OSError:
        return None


def _run_ffmpeg(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    startupinfo = None
    creationflags = 0
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = subprocess.CREATE_NO_WINDOW
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )


def _rms_signature(pcm: bytes, sample_rate: int, sample_width: int) -> list[float]:
    """把 16 位 PCM 原始字节切成每秒一块，返回每秒 RMS 响度（0..1）。"""
    bytes_per_second = sample_rate * sample_width
    second_count = len(pcm) // bytes_per_second
    if second_count < 1:
        return []
    if _np is not None:
        samples = _np.frombuffer(pcm[: second_count * bytes_per_second], dtype="<i2")
        frames = samples.reshape(second_count, sample_rate).astype(_np.float64) / 32768.0
        return _np.sqrt(_np.mean(frames * frames, axis=1)).tolist()
    signature: list[float] = []
    scale = 1.0 / 32768.0
    for index in range(second_count):
        chunk = pcm[index * bytes_per_second : (index + 1) * bytes_per_second]
        sample_count = len(chunk) // sample_width
        if sample_count <= 0:
            signature.append(0.0)
            continue
        values = struct.unpack(f"<{sample_count}h", chunk[: sample_count * sample_width])
        mean_square = sum(sample * sample for sample in values) / len(values)
        signature.append((mean_square ** 0.5) * scale)
    return signature


# 指纹解码按路径加锁：并发快照/导入时同一文件只解码一次
_fingerprint_locks: dict[str, threading.Lock] = {}


def compute_audio_fingerprint(
    ffmpeg_path: str | None,
    path: str | Path,
    max_seconds: int = FINGERPRINT_MAX_SECONDS,
) -> dict[str, Any] | None:
    """解码音频得到指纹；无 ffmpeg / 解码失败 / 音频过短时返回 None。

    同一路径的并发调用（如多个面板同时快照）会串行化，避免重复解码。
    """
    if not ffmpeg_path or not Path(path).is_file():
        return None
    lock = _fingerprint_locks.setdefault(str(Path(path).resolve()), threading.Lock())
    with lock:
        return _decode_audio_fingerprint(ffmpeg_path, path, max_seconds)


def _decode_audio_fingerprint(
    ffmpeg_path: str | None,
    path: str | Path,
    max_seconds: int,
) -> dict[str, Any] | None:
    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel", "error",
                "-nostdin",
                "-y",
                "-t", str(max_seconds),
                "-i", str(path),
                "-map", "0:a:0",
                "-vn",
                "-ac", str(FINGERPRINT_CHANNELS),
                "-ar", str(FINGERPRINT_SAMPLE_RATE),
                "-f", "s16le",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=FINGERPRINT_DECODE_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    signature = _rms_signature(result.stdout, FINGERPRINT_SAMPLE_RATE, FINGERPRINT_SAMPLE_WIDTH)
    if not signature:
        return None
    duration = float(len(signature))
    return {"duration": duration, "signature": signature}


def _normalize(values: list[float]) -> list[float]:
    peak = max(values) if values else 0.0
    if peak <= 1e-9:
        return values
    return [value / peak for value in values]


def _overlap_mae(first: list[float], second: list[float], shift: int) -> float | None:
    """second 相对 first 偏移 shift 秒后的平均绝对误差（重叠区）。"""
    if shift >= 0:
        first_start, second_start = 0, shift
    else:
        first_start, second_start = -shift, 0
    overlap = min(len(first) - first_start, len(second) - second_start)
    if overlap <= 0 or overlap < MIN_OVERLAP_FRACTION * min(len(first), len(second)):
        return None
    total = 0.0
    for index in range(overlap):
        total += abs(first[first_start + index] - second[second_start + index])
    return total / overlap


def fingerprints_duplicate(
    first_sig: list[float],
    first_duration: float,
    second_sig: list[float],
    second_duration: float,
) -> bool:
    """判断两条指纹是否指向同一段音频（避重）。"""
    if abs(first_duration - second_duration) > DURATION_TOLERANCE:
        return False
    if first_sig == second_sig:
        return True
    first_norm = _normalize(first_sig)
    second_norm = _normalize(second_sig)
    best: float | None = None
    for shift in range(-SHIFT_TOLERANCE, SHIFT_TOLERANCE + 1):
        distance = _overlap_mae(first_norm, second_norm, shift)
        if distance is not None and (best is None or distance < best):
            best = distance
    return best is not None and best <= DUP_MAE_THRESHOLD


class LibraryManager:
    """负责素材库目录、索引与批量拆 BGM 的后台任务。"""

    def __init__(
        self,
        project_root: str | Path,
        ffmpeg_path: str | None,
        callback: EventCallback | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.ffmpeg_path = ffmpeg_path
        self.callback = callback or (lambda payload: None)
        self._ffprobe_path: str | None = None
        self._tasks: dict[str, dict[str, Any]] = {}
        self._tasks_lock = threading.Lock()
        self._index_locks: dict[str, threading.Lock] = {}

    # ---------- 目录与索引 ----------

    def default_dirs(self) -> dict[str, str]:
        home = Path.home()
        documents = home / "Documents"
        base = documents if documents.is_dir() else home
        root = base / LIBRARY_ROOT_NAME
        return {
            "library_root": str(root),
            "bgm_dir": str(root / "BGM"),
            "watermark_dir": str(root / "水印"),
        }

    def _resolve_dirs(self, bgm_dir: str | None = None, watermark_dir: str | None = None) -> tuple[Path, Path]:
        defaults = self.default_dirs()
        bgm = Path(str(bgm_dir or "")).expanduser() if bgm_dir else Path(defaults["bgm_dir"])
        watermark = Path(str(watermark_dir or "")).expanduser() if watermark_dir else Path(defaults["watermark_dir"])
        return bgm, watermark

    def _ffprobe(self) -> str | None:
        if self._ffprobe_path is None:
            self._ffprobe_path = (
                resolve_ffprobe_path(self.project_root, self.ffmpeg_path)
                if resolve_ffprobe_path is not None
                else None
            )
        return self._ffprobe_path

    def _index_lock(self, directory: Path) -> threading.Lock:
        key = str(directory.resolve())
        with self._tasks_lock:
            return self._index_locks.setdefault(key, threading.Lock())

    def _index_path(self, directory: Path) -> Path:
        return directory / INDEX_FILE_NAME

    def _load_index(self, directory: Path) -> dict[str, Any]:
        path = self._index_path(directory)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        entries = data.get("entries")
        if not isinstance(entries, dict):
            entries = {}
        return {"version": int(data.get("version", 1) or 1), "kind": data.get("kind"), "entries": entries}

    def _save_index(self, directory: Path, index: dict[str, Any]) -> None:
        path = self._index_path(directory)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(index, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    # ---------- 快照 ----------

    def snapshot(self, params: dict[str, Any]) -> dict[str, Any]:
        bgm_dir, watermark_dir = self._resolve_dirs(
            params.get("bgm_dir"), params.get("watermark_dir")
        )
        # 首次打开素材库时自动创建目录，保证「打开目录」等操作可用。
        bgm_dir.mkdir(parents=True, exist_ok=True)
        watermark_dir.mkdir(parents=True, exist_ok=True)
        bgm_items, bgm_folders = self._scan_tree(bgm_dir, AUDIO_EXTENSIONS, "bgm")
        watermark_items, watermark_folders = self._scan_tree(watermark_dir, WATERMARK_EXTENSIONS, "watermark")
        return {
            "library_root": str(self.default_dirs()["library_root"]),
            "bgm_dir": str(bgm_dir),
            "watermark_dir": str(watermark_dir),
            "bgm": bgm_items,
            "bgm_folders": bgm_folders,
            "watermark": watermark_items,
            "watermark_folders": watermark_folders,
        }

    # ---------- 假字幕轨体检与清洗 ----------

    def scan_tainted(self, params: dict[str, Any]) -> dict[str, Any]:
        """扫描素材库（kind=bgm/watermark），找出含异常字幕轨/数据轨的文件。

        返回 {"scanned": 扫描文件数, "tainted": [{path, name, folder, size_bytes,
        taint, streams}]}；无异常时 tainted 为空列表。
        """
        kind = str(params.get("kind", "bgm") or "bgm")
        if kind not in ("bgm", "watermark"):
            raise ValueError("kind 必须是 bgm 或 watermark")
        bgm_dir, watermark_dir = self._resolve_dirs(
            params.get("bgm_dir"), params.get("watermark_dir")
        )
        base = bgm_dir if kind == "bgm" else watermark_dir
        if not base.is_dir():
            return {"scanned": 0, "tainted": []}
        extensions = AUDIO_EXTENSIONS if kind == "bgm" else WATERMARK_EXTENSIONS
        ffprobe = self._ffprobe()
        findings: list[dict[str, Any]] = []
        scanned = 0
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            scanned += 1
            streams = _probe_streams(ffprobe, path)
            taint = _taint_reason(streams, kind)
            if taint:
                folder = str(path.parent.relative_to(base)).replace("\\", "/")
                findings.append({
                    "path": str(path),
                    "name": path.name,
                    "folder": "" if folder == "." else folder,
                    "size_bytes": path.stat().st_size,
                    "taint": taint,
                    "streams": streams,
                })
        return {"scanned": scanned, "tainted": findings}

    def clean_tainted(self, params: dict[str, Any]) -> dict[str, Any]:
        """清洗指定素材文件：重封装去掉字幕/数据轨（流复制，不重编码）。

        每个文件处理前会重新探测确认确有异常，避免误清洗；
        原文件移入回收站（可还原），干净版本以原文件名落盘。
        返回 {"results": [{path, ok, reason}], "cleaned": N}。
        """
        raw_paths = params.get("paths") or []
        if not isinstance(raw_paths, list) or not raw_paths:
            raise ValueError("请先选择要清洗的文件")
        results: list[dict[str, Any]] = []
        for raw in raw_paths:
            path = Path(str(raw or "")).expanduser()
            if not path.is_file():
                results.append({"path": str(raw or ""), "ok": False, "reason": "文件不存在"})
                continue
            outcome = _clean_tainted_file(self.ffmpeg_path, self._ffprobe(), path)
            results.append({"path": str(path), **outcome})
        return {"results": results, "cleaned": sum(1 for item in results if item.get("ok"))}

    def audio_cover(self, params: dict[str, Any]) -> dict[str, Any]:
        """提取音频内嵌封面（如有）并返回缓存路径；没有封面返回 cover_path=None。"""
        path = str(params.get("path", "") or "").strip()
        source = Path(path).expanduser()
        if not source.is_file():
            return {"cover_path": None}
        return {"cover_path": _extract_audio_cover(self.ffmpeg_path, source)}

    def preview_video(self, params: dict[str, Any]) -> dict[str, Any]:
        """把素材库中的视频准备为 WebView 可播放的预览（缓存于资产作用域内）。

        已经是浏览器可直接播放的格式（h264 mp4/mov、webm 等）时直接拷贝；
        其余格式用 FFmpeg 转码为 H.264 MP4（丢弃音频）。返回 transcoded 标记。
        """
        source = Path(str(params.get("path", "") or "")).expanduser()
        if not source.is_file():
            raise ValueError("视频文件不存在")
        stat = source.stat()
        cache_key = f"video-preview-v1:{source.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
        preview_dir = Path(tempfile.gettempdir()) / "image-to-video-engine" / "video-previews"
        try:
            preview_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"无法创建视频预览目录：{exc}") from exc

        playable, output_ext = self._webview_playable_plan(source)
        digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()
        preview_path = preview_dir / f"{digest}{output_ext}"
        if preview_path.is_file() and preview_path.stat().st_size > 0:
            return {"preview_path": str(preview_path), "transcoded": not playable}

        temporary = preview_path.with_name(
            f".{preview_path.stem}-{os.getpid()}-{threading.get_ident()}.tmp{output_ext}"
        )
        try:
            if playable:
                shutil.copy2(source, temporary)
            else:
                if not self.ffmpeg_path:
                    raise ValueError("未找到 FFmpeg，无法生成视频预览")
                result = _run_ffmpeg(
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
                        "0:v:0",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "23",
                        "-pix_fmt",
                        "yuv420p",
                        "-an",
                        "-movflags",
                        "+faststart",
                        str(temporary),
                    ],
                    timeout=300,
                )
                if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
                    detail = next(
                        (line.strip() for line in reversed(result.stderr.splitlines()) if line.strip()),
                        source.name,
                    )
                    raise ValueError(f"视频预览转换失败：{detail}")
            os.replace(temporary, preview_path)
        except subprocess.TimeoutExpired as exc:
            temporary.unlink(missing_ok=True)
            raise ValueError("视频预览转换超时，请稍后重试") from exc
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ValueError(f"视频预览失败：{exc}") from exc
        return {"preview_path": str(preview_path), "transcoded": not playable}

    def _webview_playable_plan(self, path: Path) -> tuple[bool, str]:
        """判断视频是否可直接由 WebView2 播放，返回 (可直接拷贝, 目标扩展名)。"""
        suffix = path.suffix.lower()
        if suffix == ".webm":
            return True, ".webm"
        if suffix not in {".mp4", ".mov", ".m4v", ".mkv"}:
            return False, ".mp4"
        codec = self._probe_video_codec(path)
        if codec in {"h264", "vp8", "vp9", "hevc"}:
            return True, suffix
        if codec == "":
            # 探测不到编码信息时按原样拷贝，播放失败由前端提示
            return True, suffix
        return False, ".mp4"

    def _probe_video_codec(self, path: Path) -> str:
        """读取视频首个视频流编码名；不可用时返回空字符串。"""
        ffprobe_path = self._ffprobe()
        if not ffprobe_path:
            return ""
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
                    ffprobe_path,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name",
                    "-of",
                    "csv=p=0",
                    str(path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return result.stdout.strip().lower()

    def _scan_tree(
        self,
        base: Path,
        extensions: set[str],
        kind: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """递归扫描库目录：返回 (素材列表, 文件夹列表)。

        素材带 folder 相对路径字段（"" 表示库根目录）；文件夹带递归计数
        （含子文件夹内的素材），空文件夹也会出现在列表中。
        """
        items: list[dict[str, Any]] = []
        direct_counts: dict[str, int] = {}
        all_dirs: set[str] = set()
        for directory, dirnames, filenames in os.walk(base):
            dirnames.sort(key=str.lower)
            relative = str(Path(directory).relative_to(base))
            folder = "" if relative == "." else relative.replace("\\", "/")
            all_dirs.add(folder)
            index = self._load_index(Path(directory))
            entries = index.get("entries", {})
            changed = False
            for name in sorted(filenames, key=str.lower):
                if name.startswith("."):
                    continue
                path = Path(directory) / name
                if path.suffix.lower() not in extensions:
                    continue
                stat = path.stat()
                entry = entries.get(name)
                if not isinstance(entry, dict) or entry.get("mtime_ns") != stat.st_mtime_ns or entry.get("size") != stat.st_size:
                    sha256 = _file_sha256(path)
                    duration: float | None = None
                    media_type = "image"
                    if kind == "bgm":
                        fingerprint = compute_audio_fingerprint(self.ffmpeg_path, path)
                        if fingerprint:
                            duration = fingerprint["duration"]
                    elif path.suffix.lower() in VIDEO_EXTENSIONS:
                        media_type = "video"
                        duration = _probe_duration(self._ffprobe(), path)
                    entry = {
                        "sha256": sha256,
                        "duration": duration,
                        "type": media_type,
                        "added_at": _now_iso(),
                        "mtime_ns": stat.st_mtime_ns,
                        "size": stat.st_size,
                    }
                    if kind == "bgm" and fingerprint:
                        entry["signature"] = fingerprint["signature"]
                    entries[name] = entry
                    changed = True
                direct_counts[folder] = direct_counts.get(folder, 0) + 1
                items.append({
                    "name": name,
                    "path": str(path.resolve()),
                    "folder": folder,
                    "type": entry.get("type", "image" if kind != "bgm" else "audio"),
                    "size_bytes": stat.st_size,
                    "duration": entry.get("duration"),
                    "added_at": entry.get("added_at"),
                    "duplicate_key": str(entry.get("sha256", "")),
                    "tags": entry.get("tags") if isinstance(entry.get("tags"), list) else [],
                    "starred": bool(entry.get("starred", False)),
                    "note": str(entry.get("note", "") or ""),
                })
            if changed:
                with self._index_lock(Path(directory)):
                    self._save_index(Path(directory), index)
        folders: list[dict[str, Any]] = []
        for folder in sorted(all_dirs):
            if folder == "":
                continue
            count = sum(
                value for key, value in direct_counts.items()
                if key == folder or key.startswith(folder + "/")
            )
            folders.append({
                "relative": folder,
                "name": folder.rsplit("/", 1)[-1],
                "path": str((base / folder).resolve()),
                "count": count,
            })
        return items, folders

    def _dir_content_hashes(self, directory: Path, extensions: set[str]) -> dict[str, str]:
        """扫描目录内所有素材文件的实际内容哈希（磁盘为准，含未索引文件）。"""
        hashes: dict[str, str] = {}
        if not directory.is_dir():
            return hashes
        for path in directory.iterdir():
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() not in extensions:
                continue
            try:
                hashes[path.name] = _file_sha256(path)
            except OSError:
                continue
        return hashes

    def _all_index_entries(self, base: Path) -> list[tuple[str, str, dict[str, Any]]]:
        """读取库内所有子目录（含根目录）的索引，返回 (相对文件夹, 文件名, entry)。"""
        collected: list[tuple[str, str, dict[str, Any]]] = []
        if not base.is_dir():
            return collected
        for index_path in sorted(base.rglob(INDEX_FILE_NAME)):
            try:
                data = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            raw = data.get("entries") if isinstance(data, dict) else None
            if not isinstance(raw, dict):
                continue
            folder = str(index_path.parent.relative_to(base)).replace("\\", "/")
            folder = "" if folder == "." else folder
            for name, entry in raw.items():
                if isinstance(entry, dict):
                    collected.append((folder, name, entry))
        return collected

    # ---------- 导入 ----------

    def import_files(self, params: dict[str, Any]) -> dict[str, Any]:
        kind = str(params.get("kind", "") or "").strip()
        paths = params.get("paths") or []
        if kind not in {"bgm", "watermark"}:
            raise ValueError("素材类型必须是 bgm 或 watermark")
        if not isinstance(paths, list) or not paths:
            raise ValueError("没有可导入的素材")
        bgm_dir, watermark_dir = self._resolve_dirs(
            params.get("bgm_dir"), params.get("watermark_dir")
        )
        base = bgm_dir if kind == "bgm" else watermark_dir
        relative = _relative_folder(params.get("folder"))
        target_dir = base / relative if relative else base
        target_dir.mkdir(parents=True, exist_ok=True)
        extensions = AUDIO_EXTENSIONS if kind == "bgm" else WATERMARK_EXTENSIONS
        # 全库避重：跨文件夹识别相同素材
        global_entries = self._all_index_entries(base)
        global_shas: list[tuple[str, str, Any]] = [
            (folder, name, entry.get("sha256"))
            for folder, name, entry in global_entries
        ]
        global_signatures: list[tuple[str, str, Any, float]] = []
        if kind == "bgm":
            global_signatures = [
                (folder, name, entry.get("signature") or [], float(entry.get("duration") or 0.0))
                for folder, name, entry in global_entries
            ]
        results: list[dict[str, Any]] = []
        with self._index_lock(target_dir):
            index = self._load_index(target_dir)
            entries = index.setdefault("entries", {})
            # 目标文件夹以磁盘内容为准（涵盖用户手动放入、尚未建索引的文件）
            local_shas = self._dir_content_hashes(target_dir, extensions)
            for raw in paths:
                source = Path(str(raw or "")).expanduser()
                result: dict[str, Any] = {
                    "name": source.name,
                    "path": str(source),
                    "status": "failed",
                    "reason": "文件不存在",
                }
                if not source.is_file():
                    results.append(result)
                    continue
                if source.suffix.lower() not in extensions:
                    result["reason"] = f"不支持的格式 {source.suffix or '（无扩展名）'}"
                    results.append(result)
                    continue
                try:
                    stat = source.stat()
                    sha256 = _file_sha256(source)
                    duplicate = next(
                        (
                            (folder, name) for folder, name, cached in global_shas
                            if cached == sha256
                        ),
                        None,
                    )
                    duration: float | None = None
                    if duplicate is None and kind == "bgm":
                        fingerprint = compute_audio_fingerprint(self.ffmpeg_path, source)
                        if fingerprint:
                            duration = fingerprint["duration"]
                            duplicate = next(
                                (
                                    (folder, name)
                                    for folder, name, signature, cached_duration in global_signatures
                                    if fingerprints_duplicate(
                                        fingerprint["signature"],
                                        fingerprint["duration"],
                                        signature,
                                        cached_duration,
                                    )
                                ),
                                None,
                            )
                    if duplicate:
                        folder, name = duplicate
                        display = f"{folder}/{name}" if folder else name
                        results.append({
                            "name": source.name,
                            "path": str(source.resolve()),
                            "status": "duplicate",
                            "reason": f"库中已有相同素材：{display}",
                            "size_bytes": stat.st_size,
                            "duration": duration,
                        })
                        continue
                    target = _unique_path(target_dir, source.name, local_shas)
                    shutil.copy2(source, target)
                    entry = {
                        "sha256": sha256,
                        "added_at": _now_iso(),
                        "mtime_ns": target.stat().st_mtime_ns,
                        "size": target.stat().st_size,
                    }
                    if kind == "bgm":
                        fingerprint = compute_audio_fingerprint(self.ffmpeg_path, target)
                        if fingerprint:
                            entry["signature"] = fingerprint["signature"]
                            entry["duration"] = fingerprint["duration"]
                            duration = fingerprint["duration"]
                    else:
                        entry["type"] = "video" if target.suffix.lower() in VIDEO_EXTENSIONS else "image"
                        if entry["type"] == "video":
                            entry["duration"] = _probe_duration(self._ffprobe(), target)
                    entries[target.name] = entry
                    local_shas[target.name] = sha256
                    # 本批次内后续文件也要能识别重复
                    global_shas.append((relative, target.name, sha256))
                    if kind == "bgm" and fingerprint:
                        global_signatures.append((relative, target.name, fingerprint["signature"], fingerprint["duration"]))
                    results.append({
                        "name": target.name,
                        "path": str(target.resolve()),
                        "status": "imported",
                        "folder": relative,
                        "size_bytes": entry["size"],
                        "duration": duration,
                    })
                except (OSError, subprocess.SubprocessError) as exc:
                    results.append({
                        "name": source.name,
                        "path": str(source.resolve()),
                        "status": "failed",
                        "reason": str(exc),
                    })
            self._save_index(target_dir, index)
        return {"results": results}

    def remove(self, params: dict[str, Any]) -> dict[str, Any]:
        kind = str(params.get("kind", "") or "").strip()
        path = Path(str(params.get("path", "") or "")).expanduser()
        if kind not in {"bgm", "watermark"}:
            raise ValueError("素材类型必须是 bgm 或 watermark")
        bgm_dir, watermark_dir = self._resolve_dirs(
            params.get("bgm_dir"), params.get("watermark_dir")
        )
        base = bgm_dir if kind == "bgm" else watermark_dir
        target = path if path.is_absolute() else base / path
        if not target.is_file() or not self._inside(base, target):
            raise ValueError("只能删除素材库内的文件")
        _trash(target)
        directory = target.parent
        with self._index_lock(directory):
            index = self._load_index(directory)
            index.get("entries", {}).pop(target.name, None)
            self._save_index(directory, index)
        return {"removed": True, "path": str(target.resolve())}

    def remove_batch(self, params: dict[str, Any]) -> dict[str, Any]:
        """批量删除素材：一次调用处理多个文件，逐个送回收站并返回结果。"""
        kind = str(params.get("kind", "") or "").strip()
        paths = params.get("paths") or []
        if kind not in {"bgm", "watermark"}:
            raise ValueError("素材类型必须是 bgm 或 watermark")
        if not isinstance(paths, list) or not paths:
            raise ValueError("没有可删除的素材")
        bgm_dir, watermark_dir = self._resolve_dirs(
            params.get("bgm_dir"), params.get("watermark_dir")
        )
        base = bgm_dir if kind == "bgm" else watermark_dir
        results: list[dict[str, Any]] = []
        for raw in paths:
            path = Path(str(raw or "")).expanduser()
            target = path if path.is_absolute() else base / path
            result: dict[str, Any] = {
                "name": target.name,
                "path": str(target),
                "status": "failed",
                "reason": "文件不存在",
            }
            if not target.is_file():
                results.append(result)
                continue
            if not self._inside(base, target):
                result["reason"] = "只能删除素材库内的文件"
                results.append(result)
                continue
            try:
                _trash(target)
                directory = target.parent
                with self._index_lock(directory):
                    index = self._load_index(directory)
                    index.get("entries", {}).pop(target.name, None)
                    self._save_index(directory, index)
                result["status"] = "removed"
                result["path"] = str(target.resolve())
                result.pop("reason", None)
            except (OSError, ValueError) as exc:
                result["reason"] = str(exc)
            results.append(result)
        return {"results": results}

    def rename_item(self, params: dict[str, Any]) -> dict[str, Any]:
        """重命名素材（仅改文件名，保留原扩展名与所在文件夹）。"""
        kind = str(params.get("kind", "") or "").strip()
        path = Path(str(params.get("path", "") or "")).expanduser()
        new_name = str(params.get("new_name", "") or "").strip()
        if kind not in {"bgm", "watermark"}:
            raise ValueError("素材类型必须是 bgm 或 watermark")
        bgm_dir, watermark_dir = self._resolve_dirs(
            params.get("bgm_dir"), params.get("watermark_dir")
        )
        base = bgm_dir if kind == "bgm" else watermark_dir
        target = path if path.is_absolute() else base / path
        if not target.is_file() or not self._inside(base, target):
            raise ValueError("只能重命名素材库内的文件")
        if not new_name or new_name in {".", ".."} or "/" in new_name or "\\" in new_name:
            raise ValueError("请输入合法的文件名")
        if any(character in new_name for character in '<>:"|?*'):
            raise ValueError("文件名包含非法字符")
        # 强制沿用原扩展名，避免改扩展名导致文件不可用
        final_name = f"{Path(new_name).stem}{target.suffix}"
        if not Path(new_name).stem:
            raise ValueError("请输入文件名")
        new_target = target.parent / final_name
        if new_target == target:
            return {"renamed": True, "name": final_name, "path": str(target.resolve())}
        if new_target.exists():
            raise ValueError("同名文件已存在")
        os.rename(target, new_target)
        directory = target.parent
        with self._index_lock(directory):
            index = self._load_index(directory)
            entries = index.get("entries", {})
            entry = entries.pop(target.name, None)
            if isinstance(entry, dict):
                entry["mtime_ns"] = new_target.stat().st_mtime_ns
                entry["size"] = new_target.stat().st_size
                entries[new_target.name] = entry
            self._save_index(directory, index)
        return {"renamed": True, "name": final_name, "path": str(new_target.resolve())}

    # ---------- 素材元数据（标签 / 星标 / 备注） ----------

    def set_metadata(self, params: dict[str, Any]) -> dict[str, Any]:
        """更新素材元数据：tags（标签列表）/ starred（星标）/ note（备注）。

        只更新传入的字段；标签自动去重、截断（单标签 ≤30 字符、最多 50 个）。
        """
        kind = str(params.get("kind", "") or "").strip()
        path = Path(str(params.get("path", "") or "")).expanduser()
        if kind not in {"bgm", "watermark"}:
            raise ValueError("素材类型必须是 bgm 或 watermark")
        base = self._library_base(kind, params)
        if not path.is_file() or not self._inside(base, path):
            raise ValueError("只能编辑素材库内的素材")
        directory = path.parent
        with self._index_lock(directory):
            index = self._load_index(directory)
            entries = index.setdefault("entries", {})
            entry = entries.get(path.name)
            if not isinstance(entry, dict):
                stat = path.stat()
                entry = {
                    "sha256": _file_sha256(path),
                    "added_at": _now_iso(),
                    "mtime_ns": stat.st_mtime_ns,
                    "size": stat.st_size,
                }
                entries[path.name] = entry
            changed = False
            if "tags" in params:
                raw = params.get("tags")
                if not isinstance(raw, list):
                    raise ValueError("tags 必须是字符串列表")
                tags: list[str] = []
                for tag in raw:
                    cleaned = str(tag or "").strip()
                    if cleaned and cleaned not in tags:
                        tags.append(cleaned[:30])
                entry["tags"] = tags[:50]
                changed = True
            if "starred" in params:
                entry["starred"] = bool(params.get("starred"))
                changed = True
            if "note" in params:
                note = str(params.get("note", "") or "").strip()
                entry["note"] = note[:500]
                changed = True
            if not changed:
                raise ValueError("没有需要更新的元数据字段")
            self._save_index(directory, index)
        return {
            "path": str(path.resolve()),
            "tags": entry.get("tags") if isinstance(entry.get("tags"), list) else [],
            "starred": bool(entry.get("starred", False)),
            "note": str(entry.get("note", "") or ""),
        }

    def get_tags(self, params: dict[str, Any]) -> dict[str, Any]:
        """汇总全库标签及每个标签的素材数量（按数量降序），用于标签筛选与管理。"""
        kind = str(params.get("kind", "") or "").strip()
        if kind not in {"bgm", "watermark"}:
            raise ValueError("素材类型必须是 bgm 或 watermark")
        base = self._library_base(kind, params)
        counts: dict[str, int] = {}
        for _folder, _name, entry in self._all_index_entries(base):
            for tag in entry.get("tags") if isinstance(entry.get("tags"), list) else []:
                key = str(tag).strip()
                if key:
                    counts[key] = counts.get(key, 0) + 1
        tags = [
            {"name": name, "count": count}
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        return {"tags": tags}

    # ---------- 重复 / 相似素材查找 ----------

    def find_duplicates(self, params: dict[str, Any]) -> dict[str, Any]:
        """扫描全库，按内容分组重复/相似素材，供前端一键清理。

        - 水印库：先按 SHA-256 精确分组；剩余图片再用 dHash 感知哈希聚类相似组。
        - BGM 库：先按 SHA-256 精确分组；剩余音频再用响度指纹识别同曲不同版本。
        每组返回代表项与其余重复项（含可释放字节数）。
        """
        kind = str(params.get("kind", "") or "").strip()
        if kind not in {"bgm", "watermark"}:
            raise ValueError("素材类型必须是 bgm 或 watermark")
        base = self._library_base(kind, params)
        extensions = AUDIO_EXTENSIONS if kind == "bgm" else WATERMARK_EXTENSIONS
        snapshot_items, _folders = self._scan_tree(base, extensions, kind)
        groups: list[dict[str, Any]] = []
        by_sha: dict[str, list[dict[str, Any]]] = {}
        for item in snapshot_items:
            by_sha.setdefault(item["duplicate_key"], []).append(item)
        used_paths: set[str] = set()
        for members in by_sha.values():
            if len(members) < 2:
                continue
            groups.append(self._make_dup_group(members))
            used_paths.update(item["path"] for item in members)
        remaining = [item for item in snapshot_items if item["path"] not in used_paths]
        if kind == "bgm":
            groups.extend(self._cluster_bgm_similar(base, remaining))
        else:
            groups.extend(self._cluster_image_similar(remaining))
        groups.sort(key=lambda group: (-group["saved_bytes"], group["representative"]["name"].lower()))
        return {"groups": groups, "scanned": len(snapshot_items)}

    @staticmethod
    def _make_dup_group(members: list[dict[str, Any]]) -> dict[str, Any]:
        """把一组重复素材整理为 {representative, duplicates, ...}，代表项取名称排序首个。"""
        members = sorted(members, key=lambda item: (item["name"].lower(), item["path"]))
        representative = members[0]
        duplicates = members[1:]
        return {
            "reason": "内容完全相同",
            "representative": representative,
            "duplicates": duplicates,
            "count": len(members),
            "saved_bytes": sum(int(item.get("size_bytes") or 0) for item in duplicates),
        }

    def _cluster_image_similar(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """用 dHash 把相似图片聚类；返回重复组列表。"""
        clusters: list[list[dict[str, Any]]] = []
        cluster_hashes: list[str] = []
        for item in items[:DUP_SCAN_MAX_IMAGES]:
            if item.get("type") != "image":
                continue
            digest = _image_dhash(Path(item["path"]))
            if not digest:
                continue
            matched = next(
                (
                    index
                    for index, reference in enumerate(cluster_hashes)
                    if _hamming_distance(digest, reference) <= DUP_PHASH_THRESHOLD
                ),
                None,
            )
            if matched is None:
                clusters.append([item])
                cluster_hashes.append(digest)
            else:
                clusters[matched].append(item)
        groups: list[dict[str, Any]] = []
        for members in clusters:
            if len(members) < 2:
                continue
            group = self._make_dup_group(members)
            group["reason"] = "图片内容相似"
            groups.append(group)
        return groups

    def _cluster_bgm_similar(self, base: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """用音频响度指纹把同曲不同版本聚类；返回重复组列表。"""
        signatures: dict[str, tuple[list[float], float]] = {}
        for folder, name, entry in self._all_index_entries(base):
            signature = entry.get("signature")
            duration = entry.get("duration")
            if isinstance(signature, list) and signature and isinstance(duration, (int, float)) and duration:
                path_key = str((base / folder / name).resolve()) if folder else str((base / name).resolve())
                signatures[path_key] = (signature, float(duration))
        clusters: list[list[dict[str, Any]]] = []
        cluster_sigs: list[tuple[list[float], float]] = []
        for item in items:
            signature = signatures.get(str(Path(item["path"]).resolve()))
            if not signature:
                continue
            matched = next(
                (index for index, reference in enumerate(cluster_sigs) if fingerprints_duplicate(signature[0], signature[1], reference[0], reference[1])),
                None,
            )
            if matched is None:
                clusters.append([item])
                cluster_sigs.append(signature)
            else:
                clusters[matched].append(item)
        groups: list[dict[str, Any]] = []
        for members in clusters:
            if len(members) < 2:
                continue
            group = self._make_dup_group(members)
            group["reason"] = "音频内容相似（同曲不同版本）"
            groups.append(group)
        return groups

    # ---------- 批量重命名 ----------

    def rename_batch(self, params: dict[str, Any]) -> dict[str, Any]:
        """批量重命名素材：按模板与起始序号生成新文件名（扩展名保持不变）。

        模板占位符：{name}=原文件名（不含扩展名）、{n}=序号（补零）、{date}=当天日期。
        序号按传入 paths 的顺序依次递增，补零宽度取「总数位数」与 2 的较大值。
        """
        kind = str(params.get("kind", "") or "").strip()
        paths = params.get("paths") or []
        pattern = str(params.get("pattern", "") or "").strip()
        if kind not in {"bgm", "watermark"}:
            raise ValueError("素材类型必须是 bgm 或 watermark")
        if not isinstance(paths, list) or not paths:
            raise ValueError("没有可重命名的素材")
        if not pattern:
            raise ValueError("请输入重命名模板")
        try:
            start_index = max(1, int(params.get("start_index", 1) or 1))
        except (TypeError, ValueError):
            start_index = 1
        base = self._library_base(kind, params)
        pad = max(2, len(str(start_index + len(paths) - 1)))
        date_stamp = time.strftime("%Y%m%d")
        seen_names: set[str] = set()
        results: list[dict[str, Any]] = []
        for offset, raw in enumerate(paths):
            source = Path(str(raw or "")).expanduser()
            result: dict[str, Any] = {
                "name": source.name,
                "path": str(source),
                "status": "failed",
                "reason": "文件不存在",
            }
            if not source.is_file() or not self._inside(base, source):
                results.append(result)
                continue
            stem = Path(source.name).stem
            suffix = source.suffix
            number = str(start_index + offset).zfill(pad)
            new_stem = (
                pattern.replace("{name}", stem)
                .replace("{n}", number)
                .replace("{date}", date_stamp)
            )
            if not new_stem.strip() or any(character in new_stem for character in '<>:"/\\|?*'):
                result["reason"] = "生成的文件名包含非法字符"
                results.append(result)
                continue
            new_name = f"{new_stem}{suffix}"
            if new_name in seen_names:
                result["reason"] = f"与本次批量中的「{new_name}」重名"
                results.append(result)
                continue
            new_target = source.parent / new_name
            if new_target.exists() and new_target != source:
                result["reason"] = f"目标文件已存在：{new_name}"
                results.append(result)
                continue
            seen_names.add(new_name)
            try:
                if new_target != source:
                    os.rename(source, new_target)
                directory = source.parent
                with self._index_lock(directory):
                    index = self._load_index(directory)
                    entries = index.get("entries", {})
                    entry = entries.pop(source.name, None)
                    if isinstance(entry, dict):
                        entry["mtime_ns"] = new_target.stat().st_mtime_ns
                        entry["size"] = new_target.stat().st_size
                        entries[new_name] = entry
                    self._save_index(directory, index)
                result.update({
                    "status": "renamed",
                    "old_name": source.name,
                    "name": new_name,
                    "path": str(new_target.resolve()),
                })
            except OSError as exc:
                result["reason"] = str(exc)
            results.append(result)
        return {"results": results, "pattern": pattern}

    # ---------- 智能文件夹（规则虚拟集合，仅持久化规则，匹配在前端完成） ----------

    def _smart_file(self, params: dict[str, Any]) -> Path:
        bgm_dir, _watermark_dir = self._resolve_dirs(params.get("bgm_dir"))
        parent = bgm_dir.resolve().parent
        parent.mkdir(parents=True, exist_ok=True)
        return parent / SMART_FOLDERS_FILE_NAME

    def smart_folders_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """读取已保存的智能文件夹规则列表。"""
        path = self._smart_file(params)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        folders = data.get("folders") if isinstance(data, dict) else None
        return {"path": str(path), "folders": folders if isinstance(folders, list) else []}

    def smart_folders_save(self, params: dict[str, Any]) -> dict[str, Any]:
        """保存智能文件夹规则（整表覆盖）。"""
        folders = params.get("folders")
        if not isinstance(folders, list):
            raise ValueError("folders 必须是列表")
        cleaned: list[dict[str, Any]] = []
        for folder in folders:
            if not isinstance(folder, dict):
                raise ValueError("智能文件夹必须是对象")
            name = str(folder.get("name", "") or "").strip()
            if not name:
                raise ValueError("智能文件夹名称不能为空")
            if any(character in name for character in '<>:"/\\|?*'):
                raise ValueError("智能文件夹名称包含非法字符")
            kind = str(folder.get("kind", "") or "").strip()
            if kind not in {"bgm", "watermark"}:
                raise ValueError("智能文件夹类型必须是 bgm 或 watermark")
            conditions = folder.get("conditions")
            if not isinstance(conditions, list):
                raise ValueError("智能文件夹缺少条件列表")
            for condition in conditions:
                if not isinstance(condition, dict):
                    raise ValueError("条件必须是对象")
                field = str(condition.get("field", "") or "").strip()
                op = str(condition.get("op", "") or "").strip()
                if field not in {"type", "duration", "size", "folder", "name", "tag", "starred"}:
                    raise ValueError(f"不支持的条件字段: {field}")
                if op not in {"eq", "ne", "gt", "lt", "contains", "exists"}:
                    raise ValueError(f"不支持的条件操作符: {op}")
            cleaned.append({
                "id": str(folder.get("id", "") or "").strip() or f"smart-{int(time.time() * 1000)}-{len(cleaned)}",
                "name": name,
                "kind": kind,
                "conditions": conditions,
            })
        path = self._smart_file(params)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps({"version": 1, "folders": cleaned}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return {"path": str(path), "folders": cleaned}

    # ---------- 文件夹管理 ----------

    def create_folder(self, params: dict[str, Any]) -> dict[str, Any]:
        kind = str(params.get("kind", "") or "").strip()
        relative = _relative_folder(params.get("folder"))
        if kind not in {"bgm", "watermark"}:
            raise ValueError("素材类型必须是 bgm 或 watermark")
        if not relative:
            raise ValueError("请输入文件夹名称")
        base = self._library_base(kind, params)
        target = base / relative
        target.mkdir(parents=True, exist_ok=True)
        return {"created": True, "folder": relative, "path": str(target.resolve())}

    def rename_folder(self, params: dict[str, Any]) -> dict[str, Any]:
        kind = str(params.get("kind", "") or "").strip()
        folder = _relative_folder(params.get("folder"))
        new_name = str(params.get("new_name", "") or "").strip()
        if kind not in {"bgm", "watermark"}:
            raise ValueError("素材类型必须是 bgm 或 watermark")
        if not folder:
            raise ValueError("不能重命名库根目录")
        if not new_name or "/" in new_name or "\\" in new_name or new_name in {".", ".."}:
            raise ValueError("请输入合法的文件夹名称")
        if any(character in new_name for character in '<>:"|?*'):
            raise ValueError("文件夹名称包含非法字符")
        base = self._library_base(kind, params)
        old = base / folder
        if not old.is_dir():
            raise ValueError("文件夹不存在")
        new = old.parent / new_name
        if new.exists():
            raise ValueError("目标文件夹已存在")
        os.rename(old, new)
        relative = str(new.relative_to(base)).replace("\\", "/")
        return {"renamed": True, "folder": relative, "path": str(new.resolve())}

    def delete_folder(self, params: dict[str, Any]) -> dict[str, Any]:
        kind = str(params.get("kind", "") or "").strip()
        folder = _relative_folder(params.get("folder"))
        if kind not in {"bgm", "watermark"}:
            raise ValueError("素材类型必须是 bgm 或 watermark")
        if not folder:
            raise ValueError("不能删除库根目录")
        base = self._library_base(kind, params)
        target = base / folder
        if not target.is_dir():
            raise ValueError("文件夹不存在")
        if any(target.iterdir()):
            raise ValueError("文件夹不为空，请先清空或移走其中的文件")
        _trash(target)
        return {"deleted": True, "folder": folder}

    def move(self, params: dict[str, Any]) -> dict[str, Any]:
        kind = str(params.get("kind", "") or "").strip()
        paths = params.get("paths") or []
        relative = _relative_folder(params.get("folder"))
        if kind not in {"bgm", "watermark"}:
            raise ValueError("素材类型必须是 bgm 或 watermark")
        if not isinstance(paths, list) or not paths:
            raise ValueError("没有可移动的素材")
        base = self._library_base(kind, params)
        target_dir = base / relative if relative else base
        target_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        for raw in paths:
            source = Path(str(raw or "")).expanduser()
            result: dict[str, Any] = {
                "name": source.name,
                "path": str(source),
                "status": "failed",
                "reason": "文件不存在",
            }
            if not source.is_file():
                results.append(result)
                continue
            if not self._inside(base, source):
                result["reason"] = "只能移动素材库内的文件"
                results.append(result)
                continue
            if source.parent.resolve() == target_dir.resolve():
                result["status"] = "moved"
                result["reason"] = "已在目标文件夹"
                results.append(result)
                continue
            try:
                with self._index_lock(target_dir):
                    target_index = self._load_index(target_dir)
                    target_entries = target_index.setdefault("entries", {})
                    sha256 = _file_sha256(source)
                    # 目标文件夹以磁盘内容为准（涵盖未建索引的手动文件）
                    target_hashes = self._dir_content_hashes(
                        target_dir,
                        AUDIO_EXTENSIONS if kind == "bgm" else WATERMARK_EXTENSIONS,
                    )
                    duplicate_name = next(
                        (name for name, cached in target_hashes.items() if cached == sha256),
                        None,
                    )
                    if duplicate_name:
                        results.append({
                            "name": source.name,
                            "path": str(source.resolve()),
                            "status": "duplicate",
                            "reason": f"目标文件夹已有相同素材：{duplicate_name}",
                        })
                        continue
                    target = _unique_path(target_dir, source.name, target_hashes)
                    entry = self._pop_index_entry(source.parent, source.name)
                    os.replace(source, target)
                    entry.update({
                        "sha256": sha256,
                        "mtime_ns": target.stat().st_mtime_ns,
                        "size": target.stat().st_size,
                    })
                    target_entries[target.name] = entry
                    self._save_index(target_dir, target_index)
                    results.append({
                        "name": target.name,
                        "path": str(target.resolve()),
                        "status": "moved",
                        "folder": relative,
                        "size_bytes": entry["size"],
                        "duration": entry.get("duration"),
                    })
            except OSError as exc:
                results.append({
                    "name": source.name,
                    "path": str(source.resolve()),
                    "status": "failed",
                    "reason": str(exc),
                })
        return {"results": results}

    def _pop_index_entry(self, directory: Path, name: str) -> dict[str, Any]:
        """从目录索引中取走一个条目（用于跨文件夹移动时迁移指纹）。"""
        with self._index_lock(directory):
            index = self._load_index(directory)
            entry = index.get("entries", {}).pop(name, {})
            self._save_index(directory, index)
        return entry if isinstance(entry, dict) else {}

    def _library_base(self, kind: str, params: dict[str, Any]) -> Path:
        bgm_dir, watermark_dir = self._resolve_dirs(
            params.get("bgm_dir"), params.get("watermark_dir")
        )
        return bgm_dir if kind == "bgm" else watermark_dir

    @staticmethod
    def _inside(base: Path, path: Path) -> bool:
        try:
            path.resolve().relative_to(base.resolve())
            return True
        except ValueError:
            return False

    # ---------- 批量拆 BGM ----------

    def start_extract(self, params: dict[str, Any]) -> dict[str, Any]:
        """启动后台批量拆 BGM 任务，立即返回 task_id，进度通过事件上报。"""
        bgm_dir, _watermark_dir = self._resolve_dirs(params.get("bgm_dir"))
        if not self.ffmpeg_path:
            raise ValueError("未找到 FFmpeg，无法拆解 BGM")
        video_paths = self._collect_videos(params.get("paths") or [], params.get("folder"))
        if not video_paths:
            raise ValueError("没有找到可处理的视频文件")
        options = params.get("options") or {}
        if not isinstance(options, dict):
            options = {}
        relative = _relative_folder(params.get("save_folder"))
        target_dir = bgm_dir / relative if relative else bgm_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        task_id = f"extract-{int(time.time() * 1000)}-{threading.get_ident()}"
        task = {
            "task_id": task_id,
            "total": len(video_paths),
            "done": 0,
            "results": [],
            "avoid_duplicates": bool(options.get("avoid_duplicates", True)),
            "cancelled": False,
        }
        with self._tasks_lock:
            self._tasks[task_id] = task
        thread = threading.Thread(
            target=self._extract_worker,
            args=(task_id, video_paths, bgm_dir, target_dir, task),
            daemon=True,
        )
        thread.start()
        return {"task_id": task_id, "total": len(video_paths)}

    def cancel_extract(self, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id", "") or "")
        with self._tasks_lock:
            task = self._tasks.get(task_id)
        if not task:
            raise KeyError("拆 BGM 任务不存在")
        task["cancelled"] = True
        return {"cancelled": True, "task_id": task_id}

    def _collect_videos(self, paths: list[str], folder: str | None) -> list[Path]:
        collected: list[Path] = []
        seen: set[str] = set()
        for raw in paths or []:
            path = Path(str(raw or "")).expanduser()
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                key = str(path.resolve())
                if key not in seen:
                    seen.add(key)
                    collected.append(path)
        if folder:
            root = Path(str(folder)).expanduser()
            if root.is_dir():
                for path in sorted(root.rglob("*")):
                    if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                        key = str(path.resolve())
                        if key not in seen:
                            seen.add(key)
                            collected.append(path)
        collected.sort(key=lambda value: str(value).lower())
        return collected

    def _extract_worker(
        self,
        task_id: str,
        video_paths: list[Path],
        bgm_base: Path,
        target_dir: Path,
        task: dict[str, Any],
    ) -> None:
        ffprobe = self._ffprobe()
        total = len(video_paths)
        for video in video_paths:
            if task.get("cancelled"):
                result = {
                    "video": str(video),
                    "name": video.name,
                    "path": "",
                    "status": "cancelled",
                    "reason": "任务已取消",
                }
            else:
                result = self._extract_one(video, bgm_base, target_dir, ffprobe, task.get("avoid_duplicates", True))
            task["done"] += 1
            task["results"].append(result)
            self.callback({
                "type": "event",
                "event": "library.extract.progress",
                "payload": {
                    "task_id": task_id,
                    "done": task["done"],
                    "total": total,
                    "current": video.name,
                    "result": result,
                },
            })
        summary = self._summarize(task["results"])
        with self._tasks_lock:
            self._tasks.pop(task_id, None)
        self.callback({
            "type": "event",
            "event": "library.extract.done",
            "payload": {
                "task_id": task_id,
                "results": task["results"],
                "summary": summary,
                "total": total,
            },
        })

    def _extract_one(
        self,
        video: Path,
        bgm_base: Path,
        target_dir: Path,
        ffprobe: str | None,
        avoid_duplicates: bool,
    ) -> dict[str, Any]:
        def fail(reason: str) -> dict[str, Any]:
            return {
                "video": str(video),
                "name": video.name,
                "path": "",
                "status": "failed",
                "reason": reason,
            }

        if not video.is_file():
            return fail("视频文件不存在")
        if not _probe_audio_streams(ffprobe, video):
            return {
                "video": str(video),
                "name": video.name,
                "path": "",
                "status": "no_audio",
                "reason": "视频没有音轨",
            }

        stem = _safe_name(Path(video).stem) or "未命名"
        temporary = target_dir / f".extract-{os.getpid()}-{threading.get_ident()}.tmp.mp3"
        try:
            result = _run_ffmpeg(
                [
                    self.ffmpeg_path,
                    "-hide_banner",
                    "-loglevel", "error",
                    "-nostdin",
                    "-y",
                    "-i", str(video),
                    "-map", "0:a:0",
                    "-vn",
                    "-c:a", "libmp3lame",
                    "-b:a", EXTRACT_BITRATE,
                    "-ar", "44100",
                    "-ac", "2",
                    str(temporary),
                ],
                timeout=EXTRACT_AUDIO_TIMEOUT,
            )
            if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
                detail = next(
                    (line.strip() for line in reversed(result.stderr.splitlines()) if line.strip()),
                    "",
                )
                if "does not contain any stream" in detail or "matches no streams" in detail or "no audio" in detail.lower():
                    return {
                        "video": str(video),
                        "name": video.name,
                        "path": "",
                        "status": "no_audio",
                        "reason": "视频没有音轨",
                    }
                return fail(f"拆解失败：{detail or '未知错误'}")
        except subprocess.TimeoutExpired:
            return fail("拆解超时")
        except OSError as exc:
            return fail(f"拆解失败：{exc}")

        duration: float | None = _probe_duration(ffprobe, temporary)
        fingerprint = compute_audio_fingerprint(self.ffmpeg_path, temporary)
        if fingerprint and duration is None:
            duration = fingerprint["duration"]

        saved = {
            "video": str(video),
            "name": temporary.name,
            "path": str(temporary),
            "status": "saved",
            "duration": duration,
        }
        with self._index_lock(target_dir):
            index = self._load_index(target_dir)
            entries = index.setdefault("entries", {})
            if avoid_duplicates and fingerprint:
                # 全库避重：跨文件夹比对所有 BGM 指纹
                for cached_folder, cached_name, cached_entry in self._all_index_entries(bgm_base):
                    cached_signature = cached_entry.get("signature") or []
                    if not cached_signature:
                        continue
                    if fingerprints_duplicate(
                        fingerprint["signature"],
                        fingerprint["duration"],
                        cached_signature,
                        float(cached_entry.get("duration") or 0.0),
                    ):
                        temporary.unlink(missing_ok=True)
                        display = f"{cached_folder}/{cached_name}" if cached_folder else cached_name
                        return {
                            "video": str(video),
                            "name": video.name,
                            "path": "",
                            "status": "duplicate",
                            "reason": f"库中已有相同 BGM：{display}",
                            "duration": duration,
                        }
            target = _unique_path(target_dir, f"{stem}.mp3", {name: entry.get("sha256") for name, entry in entries.items()})
            os.replace(temporary, target)
            entry = {
                "sha256": _file_sha256(target),
                "added_at": _now_iso(),
                "mtime_ns": target.stat().st_mtime_ns,
                "size": target.stat().st_size,
                "duration": duration,
            }
            if fingerprint:
                entry["signature"] = fingerprint["signature"]
            entries[target.name] = entry
            self._save_index(target_dir, index)
        saved["name"] = target.name
        saved["path"] = str(target.resolve())
        return saved

    @staticmethod
    def _summarize(results: list[dict[str, Any]]) -> dict[str, int]:
        summary = {"saved": 0, "duplicate": 0, "no_audio": 0, "failed": 0, "cancelled": 0}
        for result in results:
            status = result.get("status")
            if status in summary:
                summary[status] += 1
        summary["total"] = len(results)
        return summary
