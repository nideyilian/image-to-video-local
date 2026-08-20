"""假字幕轨体检（scan_tainted）与清洗（clean_tainted）测试。"""

import subprocess
from pathlib import Path

import pytest

from src.engine.library import (
    LibraryManager,
    _taint_reason,
)
from src.utils.ffmpeg_runtime import configure_ffmpeg_environment

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def ffmpeg():
    path = configure_ffmpeg_environment(ROOT)
    assert path, "测试需要 ffmpeg"
    return path


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    ffmpeg_path = configure_ffmpeg_environment(ROOT)
    import src.engine.library as library_module

    class FakeTrash:
        """测试用回收站：模拟「移走」效果，不污染系统回收站。"""

        @staticmethod
        def send2trash(path: str):
            target = Path(path)
            if target.is_dir():
                target.rmdir()
            else:
                target.unlink()

    monkeypatch.setattr(library_module, "_send2trash", FakeTrash())
    return LibraryManager(ROOT, ffmpeg_path, callback=lambda payload: None)


def _ffprobe(ffmpeg_path: str, path: Path) -> list[str]:
    ffprobe = str(Path(ffmpeg_path).with_name("ffprobe.exe")) if ffmpeg_path.lower().endswith(".exe") else "ffprobe"
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "compact", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.stdout.split()


def _make_tainted_m4a(ffmpeg_path: str, target: Path) -> None:
    """生成带 mov_text 字幕轨的 m4a（模拟剪映缓存里带假轨的素材）。"""
    srt = target.with_suffix(".srt")
    srt.write_text("1\n00:00:00,000 --> 00:00:05,000\n假字幕轨测试\n", encoding="utf-8")
    subprocess.run(
        [ffmpeg_path, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-i", str(srt), "-map", "0:a", "-map", "1:0",
         "-c:a", "aac", "-c:s", "mov_text", "-shortest", str(target)],
        capture_output=True, check=True,
    )


def _make_cover_mp3(ffmpeg_path: str, target: Path) -> None:
    """生成带内嵌封面（attached_pic）的 mp3——正常素材，不应被标记。"""
    cover = target.with_suffix(".png")
    from PIL import Image
    Image.new("RGB", (16, 16), "red").save(cover)
    subprocess.run(
        [ffmpeg_path, "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=2",
         "-i", str(cover), "-map", "0:a", "-map", "1:v",
         "-c:a", "libmp3lame", "-c:v", "mjpeg", "-disposition:v", "attached_pic",
         "-id3v2_version", "3", str(target)],
        capture_output=True, check=True,
    )


# ---------- _taint_reason 纯函数 ----------

def test_taint_reason_clean_audio():
    assert _taint_reason([
        {"codec_type": "audio", "codec_name": "aac", "attached_pic": False},
    ], "bgm") is None


def test_taint_reason_attached_cover_is_clean():
    assert _taint_reason([
        {"codec_type": "audio", "codec_name": "aac", "attached_pic": False},
        {"codec_type": "video", "codec_name": "mjpeg", "attached_pic": True},
    ], "bgm") is None


def test_taint_reason_subtitle():
    reason = _taint_reason([
        {"codec_type": "audio", "codec_name": "aac", "attached_pic": False},
        {"codec_type": "subtitle", "codec_name": "mov_text", "duration": 326.4, "attached_pic": False},
    ], "bgm")
    assert reason and "字幕轨" in reason and "326" in reason


def test_taint_reason_bin_data_track():
    """回归：后期工具写入的 encd 假时长轨（codec_type=data / bin_data）。"""
    reason = _taint_reason([
        {"codec_type": "video", "codec_name": "h264", "attached_pic": False},
        {"codec_type": "audio", "codec_name": "aac", "attached_pic": False},
        {"codec_type": "data", "codec_name": "bin_data", "duration": 326.4, "attached_pic": False},
    ], "watermark")
    assert reason and "数据轨" in reason


def test_taint_reason_video_track_in_audio():
    reason = _taint_reason([
        {"codec_type": "audio", "codec_name": "aac", "attached_pic": False},
        {"codec_type": "video", "codec_name": "h264", "attached_pic": False},
    ], "bgm")
    assert reason and "视频轨" in reason


# ---------- 扫描 ----------

def test_scan_tainted_clean_library(tmp_path, manager):
    from tests.test_library import _write_wav
    from PIL import Image

    bgm_dir = tmp_path / "BGM"
    watermark_dir = tmp_path / "水印"
    bgm_dir.mkdir()
    watermark_dir.mkdir()
    _write_wav(bgm_dir / "歌.wav")
    Image.new("RGB", (8, 8), "white").save(watermark_dir / "logo.png")

    bgm = manager.scan_tainted({"kind": "bgm", "bgm_dir": str(bgm_dir), "watermark_dir": str(watermark_dir)})
    wm = manager.scan_tainted({"kind": "watermark", "bgm_dir": str(bgm_dir), "watermark_dir": str(watermark_dir)})

    assert bgm["scanned"] == 1
    assert bgm["tainted"] == []
    assert wm["scanned"] == 1
    assert wm["tainted"] == []


def test_scan_tainted_flags_subtitle_bgm(tmp_path, manager, ffmpeg):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    _make_tainted_m4a(ffmpeg, bgm_dir / "bad.m4a")

    result = manager.scan_tainted({"kind": "bgm", "bgm_dir": str(bgm_dir), "watermark_dir": str(tmp_path / "水印")})

    assert result["scanned"] == 1
    assert len(result["tainted"]) == 1
    assert result["tainted"][0]["name"] == "bad.m4a"
    assert "字幕轨" in result["tainted"][0]["taint"]


def test_scan_tainted_ignores_cover_mp3(tmp_path, manager, ffmpeg):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    _make_cover_mp3(ffmpeg, bgm_dir / "带封面.mp3")

    result = manager.scan_tainted({"kind": "bgm", "bgm_dir": str(bgm_dir), "watermark_dir": str(tmp_path / "水印")})

    assert result["scanned"] == 1
    assert result["tainted"] == []


def test_scan_tainted_flags_watermark_subtitle(tmp_path, manager, ffmpeg):
    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()
    srt = tmp_path / "sub.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nx\n", encoding="utf-8")
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=2",
         "-i", str(srt), "-map", "0:v", "-map", "1:0",
         "-c:v", "libx264", "-c:s", "mov_text", "-shortest", str(watermark_dir / "bad.mp4")],
        capture_output=True, check=True,
    )

    result = manager.scan_tainted({"kind": "watermark", "bgm_dir": str(tmp_path / "BGM"), "watermark_dir": str(watermark_dir)})

    assert len(result["tainted"]) == 1
    assert "字幕轨" in result["tainted"][0]["taint"]


# ---------- 清洗 ----------

def test_clean_tainted_removes_subtitle(tmp_path, manager, ffmpeg):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    tainted = bgm_dir / "bad.m4a"
    _make_tainted_m4a(ffmpeg, tainted)

    result = manager.clean_tainted({"paths": [str(tainted)]})

    assert result["cleaned"] == 1
    assert result["results"][0]["ok"] is True
    assert tainted.is_file(), "清洗后应保留原文件名"
    codec_types = _ffprobe(ffmpeg, tainted)
    assert not any("subtitle" in line for line in codec_types), f"字幕轨应被移除: {codec_types}"


def test_clean_tainted_skips_clean_file(tmp_path, manager, ffmpeg):
    from tests.test_library import _write_wav

    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    clean = bgm_dir / "ok.wav"
    _write_wav(clean)

    result = manager.clean_tainted({"paths": [str(clean)]})

    assert result["cleaned"] == 0
    assert result["results"][0]["ok"] is False
    assert clean.is_file()


def test_clean_tainted_missing_file(tmp_path, manager):
    result = manager.clean_tainted({"paths": [str(tmp_path / "不存在.m4a")]})
    assert result["cleaned"] == 0
    assert result["results"][0]["ok"] is False


def test_clean_tainted_requires_paths(manager):
    with pytest.raises(ValueError):
        manager.clean_tainted({"paths": []})
