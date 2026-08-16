"""素材库（BGM库 / 水印库 / 批量拆BGM 避重）测试。"""

import math
import wave
from pathlib import Path

import pytest

from src.engine.library import (
    LibraryManager,
    compute_audio_fingerprint,
    fingerprints_duplicate,
)
from src.engine.server import EngineServer
from src.utils.ffmpeg_runtime import configure_ffmpeg_environment

ROOT = Path(__file__).resolve().parents[1]


def _write_wav(path: Path, seconds: int = 3, sample_rate: int = 8000, amplitude: float = 0.5):
    """写一个每秒响度一致的纯音 WAV，可用于构造不同响度曲线。"""
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        frames = bytearray()
        for index in range(seconds * sample_rate):
            value = int(32767 * amplitude * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames += value.to_bytes(2, "little", signed=True)
        output.writeframes(bytes(frames))


def _write_rhythm_wav(path: Path, pattern: list[float], seconds_per_segment: int = 1, sample_rate: int = 8000):
    """按 pattern 中的响度逐段写 WAV，用于构造不同的响度曲线。"""
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        frames = bytearray()
        for amplitude in pattern:
            for index in range(seconds_per_segment * sample_rate):
                value = int(32767 * amplitude * math.sin(2 * math.pi * 330 * index / sample_rate))
                frames += value.to_bytes(2, "little", signed=True)
        output.writeframes(bytes(frames))


@pytest.fixture()
def manager(tmp_path):
    ffmpeg_path = configure_ffmpeg_environment(ROOT)
    return LibraryManager(ROOT, ffmpeg_path, callback=lambda payload: None)


def test_default_dirs_use_chinese_library_folder():
    manager = LibraryManager(ROOT, None)
    dirs = manager.default_dirs()

    assert dirs["bgm_dir"].endswith("BGM")
    assert dirs["watermark_dir"].endswith("水印")
    assert "图转视频素材库" in dirs["library_root"]


def test_snapshot_lists_only_supported_files(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    watermark_dir = tmp_path / "水印"
    bgm_dir.mkdir()
    watermark_dir.mkdir()
    _write_wav(bgm_dir / "歌.wav")
    (bgm_dir / "说明.txt").write_text("x", encoding="utf-8")
    from PIL import Image

    Image.new("RGB", (8, 8), "white").save(watermark_dir / "logo.png")

    snapshot = manager.snapshot({"bgm_dir": str(bgm_dir), "watermark_dir": str(watermark_dir)})

    assert [item["name"] for item in snapshot["bgm"]] == ["歌.wav"]
    assert [item["name"] for item in snapshot["watermark"]] == ["logo.png"]
    assert snapshot["bgm"][0]["duration"] is not None
    assert snapshot["bgm"][0]["size_bytes"] > 0


def test_import_watermark_dedupes_exact_files(tmp_path, manager):
    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()
    from PIL import Image

    source = tmp_path / "logo.png"
    Image.new("RGB", (16, 16), "red").save(source)

    first = manager.import_files({
        "kind": "watermark",
        "paths": [str(source)],
        "watermark_dir": str(watermark_dir),
    })
    second = manager.import_files({
        "kind": "watermark",
        "paths": [str(source)],
        "watermark_dir": str(watermark_dir),
    })

    assert first["results"][0]["status"] == "imported"
    assert second["results"][0]["status"] == "duplicate"
    assert len(list(watermark_dir.glob("*.png"))) == 1


def test_import_bgm_dedupes_same_content_with_different_names(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    source_a = tmp_path / "原版.wav"
    source_b = tmp_path / "重命名版.wav"
    _write_rhythm_wav(source_a, [0.5, 0.2, 0.8])
    _write_rhythm_wav(source_b, [0.5, 0.2, 0.8])

    first = manager.import_files({
        "kind": "bgm",
        "paths": [str(source_a)],
        "bgm_dir": str(bgm_dir),
    })
    second = manager.import_files({
        "kind": "bgm",
        "paths": [str(source_b)],
        "bgm_dir": str(bgm_dir),
    })

    assert first["results"][0]["status"] == "imported"
    assert second["results"][0]["status"] == "duplicate"
    assert "原版.wav" in second["results"][0]["reason"]
    assert len(list(bgm_dir.glob("*.wav"))) == 1


def test_import_bgm_keeps_distinct_content(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    source_a = tmp_path / "安静的.wav"
    source_b = tmp_path / "活泼的.wav"
    _write_rhythm_wav(source_a, [0.2, 0.2, 0.2])
    _write_rhythm_wav(source_b, [0.9, 0.1, 0.9])

    results = manager.import_files({
        "kind": "bgm",
        "paths": [str(source_a), str(source_b)],
        "bgm_dir": str(bgm_dir),
    })["results"]

    assert {result["status"] for result in results} == {"imported"}
    assert len(list(bgm_dir.glob("*.wav"))) == 2


def test_fingerprints_duplicate_logic():
    first = [0.5, 0.2, 0.8, 0.4]
    re_encoded = [value * 1.3 for value in first]  # 响度整体放大 → 归一化后相同
    different = [0.9, 0.9, 0.9, 0.9]

    assert fingerprints_duplicate(first, 4.0, re_encoded, 4.0) is True
    assert fingerprints_duplicate(first, 4.0, first, 4.0) is True
    assert fingerprints_duplicate(first, 4.0, different, 4.0) is False
    assert fingerprints_duplicate(first, 4.0, first, 9.0) is False


def test_fingerprints_tolerate_one_second_shift():
    base = [0.3, 0.6, 0.9, 0.4, 0.2]
    shifted = [0.6, 0.9, 0.4, 0.2]

    assert fingerprints_duplicate(base, 5.0, shifted, 4.0) is True


def test_compute_fingerprint_via_ffmpeg(tmp_path, manager):
    audio = tmp_path / "指纹测试.wav"
    _write_rhythm_wav(audio, [0.5, 0.2, 0.8])

    fingerprint = compute_audio_fingerprint(manager.ffmpeg_path, audio)

    assert fingerprint is not None
    assert fingerprint["duration"] == pytest.approx(3.0, abs=1.0)
    assert len(fingerprint["signature"]) >= 2
    assert max(fingerprint["signature"]) > 0


def test_extract_bgm_from_video_and_dedupe(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    ffmpeg_path = manager.ffmpeg_path
    assert ffmpeg_path

    video = tmp_path / "成片.mp4"
    import subprocess

    result = subprocess.run(
        [
            ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=2",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(video),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr

    first = manager._extract_one(video, bgm_dir, bgm_dir, manager._ffprobe(), True)
    second = manager._extract_one(video, bgm_dir, bgm_dir, manager._ffprobe(), True)

    assert first["status"] == "saved"
    assert Path(first["path"]).is_file()
    assert Path(first["path"]).suffix == ".mp3"
    assert second["status"] == "duplicate"
    assert len(list(bgm_dir.glob("*.mp3"))) == 1


def test_extract_bgm_reports_video_without_audio(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    ffmpeg_path = manager.ffmpeg_path
    assert ffmpeg_path

    silent_video = tmp_path / "无音轨.mp4"
    import subprocess

    result = subprocess.run(
        [
            ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent_video),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr

    outcome = manager._extract_one(silent_video, bgm_dir, bgm_dir, manager._ffprobe(), True)

    assert outcome["status"] == "no_audio"
    assert len(list(bgm_dir.glob("*.mp3"))) == 0


def test_start_extract_emits_progress_and_done_events(tmp_path):
    ffmpeg_path = configure_ffmpeg_environment(ROOT)
    events: list[dict] = []
    manager = LibraryManager(ROOT, ffmpeg_path, callback=events.append)

    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    video = tmp_path / "带音乐.mp4"
    import subprocess

    result = subprocess.run(
        [
            ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=2",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=2",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(video),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr

    started = manager.start_extract({
        "paths": [str(video)],
        "bgm_dir": str(bgm_dir),
        "options": {"avoid_duplicates": True},
    })
    task_id = started["task_id"]

    import time

    for _ in range(120):
        if events and events[-1].get("event") == "library.extract.done":
            break
        time.sleep(0.1)

    done = next((event for event in events if event["event"] == "library.extract.done"), None)
    progress = [event for event in events if event["event"] == "library.extract.progress"]

    assert done is not None
    assert done["payload"]["task_id"] == task_id
    assert done["payload"]["summary"] == {"saved": 1, "duplicate": 0, "no_audio": 0, "failed": 0, "cancelled": 0, "total": 1}
    assert progress and progress[0]["payload"]["done"] == 1
    assert Path(done["payload"]["results"][0]["path"]).is_file()


def test_server_dispatches_library_methods(tmp_path):
    server = EngineServer(ROOT)
    snapshot = server._dispatch("library_snapshot", {
        "bgm_dir": str(tmp_path / "不存在"),
        "watermark_dir": str(tmp_path / "不存在2"),
    })

    assert snapshot["bgm"] == []
    assert snapshot["watermark"] == []
    assert "图转视频素材库" in snapshot["library_root"]

    dirs = server._dispatch("library_dirs", {})
    assert dirs["bgm_dir"].endswith("BGM")

    assert "library" in server._dispatch("health", {})["capabilities"]


def test_snapshot_reports_folder_tree_with_counts(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    watermark_dir = tmp_path / "水印"
    (bgm_dir / "流行" / "电音").mkdir(parents=True)
    (bgm_dir / "纯音乐").mkdir()
    (watermark_dir / "Logo").mkdir(parents=True)
    _write_wav(bgm_dir / "根目录.wav")
    _write_wav(bgm_dir / "流行" / "流行歌.wav")
    _write_wav(bgm_dir / "流行" / "电音" / "电音曲.wav")
    from PIL import Image

    Image.new("RGB", (8, 8), "white").save(watermark_dir / "Logo" / "logo.png")

    snapshot = manager.snapshot({"bgm_dir": str(bgm_dir), "watermark_dir": str(watermark_dir)})

    folders = {item["relative"]: item for item in snapshot["bgm_folders"]}
    assert set(folders) == {"流行", "流行/电音", "纯音乐"}
    assert folders["流行"]["count"] == 2  # 递归计数（含子文件夹）
    assert folders["流行/电音"]["count"] == 1
    assert folders["纯音乐"]["count"] == 0  # 空文件夹也出现在树中

    by_folder = {item["name"]: item["folder"] for item in snapshot["bgm"]}
    assert by_folder["根目录.wav"] == ""
    assert by_folder["流行歌.wav"] == "流行"
    assert by_folder["电音曲.wav"] == "流行/电音"

    assert snapshot["watermark_folders"][0]["relative"] == "Logo"


def test_import_into_subfolder_and_global_dedupe(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    source = tmp_path / "同一首歌.wav"
    _write_rhythm_wav(source, [0.5, 0.2, 0.8])

    first = manager.import_files({
        "kind": "bgm",
        "paths": [str(source)],
        "folder": "流行",
        "bgm_dir": str(bgm_dir),
    })
    second = manager.import_files({
        "kind": "bgm",
        "paths": [str(source)],
        "folder": "纯音乐",
        "bgm_dir": str(bgm_dir),
    })

    assert first["results"][0]["status"] == "imported"
    assert first["results"][0]["folder"] == "流行"
    assert (bgm_dir / "流行" / "同一首歌.wav").is_file()
    # 跨文件夹避重：不同文件夹也识别为重复
    assert second["results"][0]["status"] == "duplicate"
    assert "流行" in second["results"][0]["reason"]


def test_folder_crud_and_move(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    watermark_dir = tmp_path / "水印"
    bgm_dir.mkdir()
    watermark_dir.mkdir()
    from PIL import Image

    image = tmp_path / "logo.png"
    Image.new("RGB", (12, 12), "blue").save(image)
    imported = manager.import_files({
        "kind": "watermark",
        "paths": [str(image)],
        "folder": "A/B",
        "watermark_dir": str(watermark_dir),
    })["results"][0]
    assert imported["status"] == "imported"

    # 新建 + 重命名 + 删除
    manager.create_folder({"kind": "watermark", "folder": "空文件夹", "watermark_dir": str(watermark_dir)})
    renamed = manager.rename_folder({"kind": "watermark", "folder": "空文件夹", "new_name": "新名字", "watermark_dir": str(watermark_dir)})
    assert renamed["folder"] == "新名字"
    manager.delete_folder({"kind": "watermark", "folder": "新名字", "watermark_dir": str(watermark_dir)})

    # 非空文件夹不能删
    with pytest.raises(ValueError, match="不为空"):
        manager.delete_folder({"kind": "watermark", "folder": "A", "watermark_dir": str(watermark_dir)})

    # 移动到另一个文件夹（指纹索引随文件迁移）
    moved = manager.move({
        "kind": "watermark",
        "paths": [str(watermark_dir / "A" / "B" / "logo.png")],
        "folder": "成品",
        "watermark_dir": str(watermark_dir),
    })["results"][0]
    assert moved["status"] == "moved"
    assert (watermark_dir / "成品" / "logo.png").is_file()
    assert not (watermark_dir / "A" / "B" / "logo.png").exists()

    snapshot = manager.snapshot({"bgm_dir": str(bgm_dir), "watermark_dir": str(watermark_dir)})
    assert snapshot["watermark"][0]["folder"] == "成品"
    assert {item["relative"] for item in snapshot["watermark_folders"]} == {"A", "A/B", "成品"}


def test_move_into_folder_with_same_content_is_duplicate(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    watermark_dir = tmp_path / "水印"
    bgm_dir.mkdir()
    watermark_dir.mkdir()
    import shutil

    from PIL import Image

    image = tmp_path / "logo.png"
    Image.new("RGB", (12, 12), "blue").save(image)
    manager.import_files({"kind": "watermark", "paths": [str(image)], "watermark_dir": str(watermark_dir)})
    # 直接往目标文件夹放一份相同内容的文件（模拟库内已有的重复素材）
    target_folder = watermark_dir / "已有"
    target_folder.mkdir()
    shutil.copy2(image, target_folder / "旧副本.png")

    result = manager.move({
        "kind": "watermark",
        "paths": [str(watermark_dir / "logo.png")],
        "folder": "已有",
        "watermark_dir": str(watermark_dir),
    })["results"][0]

    assert result["status"] == "duplicate"
    assert (watermark_dir / "logo.png").is_file()


def test_extract_saves_into_subfolder(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    ffmpeg_path = manager.ffmpeg_path
    assert ffmpeg_path

    video = tmp_path / "带音乐.mp4"
    import subprocess

    result = subprocess.run(
        [
            ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=2",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=2",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(video),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr

    target = bgm_dir / "拆解"
    target.mkdir()
    outcome = manager._extract_one(video, bgm_dir, target, manager._ffprobe(), True)

    assert outcome["status"] == "saved"
    assert (target / "带音乐.mp3").is_file()
    assert not (bgm_dir / "带音乐.mp3").exists()


# ---------- 显式 BGM 素材（bgm_files） ----------

def test_default_config_has_bgm_files():
    from src.engine.config import build_default_config

    assert build_default_config()["bgm_files"] == []


def test_normalize_config_keeps_bgm_files_as_string_list():
    from src.engine.config import build_default_config, normalize_config

    normalized = normalize_config({**build_default_config(), "bgm_files": ["a.mp3", 123, None, "b.wav"]})
    assert normalized["bgm_files"] == ["a.mp3", "b.wav"]


def test_validate_bgm_files_reports_missing_file(tmp_path):
    from src.engine.config import build_default_config, validate_config_detailed

    config = build_default_config()
    config.update({
        "input_dir": str(tmp_path),
        "output_dir": str(tmp_path),
        "use_bgm": True,
        "bgm_dir": str(tmp_path / "不存在的目录"),
        "bgm_files": [str(tmp_path / "丢失.mp3")],
        "watermark_audio": "使用BGM",
    })
    (tmp_path / "图片").mkdir()
    from PIL import Image

    Image.new("RGB", (4, 4), "white").save(tmp_path / "图片" / "1.png")

    issues = validate_config_detailed(config, check_files=True)
    messages = [issue["message"] for issue in issues]

    assert any("选定的 BGM 素材不存在" in message for message in messages)
    # 已显式指定素材时不再要求 BGM 目录存在
    assert not any("BGM 目录" in message for message in messages)


def test_validate_bgm_files_skips_dir_check_when_valid(tmp_path):
    from src.engine.config import build_default_config, validate_config_detailed

    audio = tmp_path / "选中.wav"
    _write_wav(audio)
    config = build_default_config()
    config.update({
        "input_dir": str(tmp_path),
        "output_dir": str(tmp_path),
        "use_bgm": True,
        "bgm_dir": str(tmp_path / "不存在的目录"),
        "bgm_files": [str(audio)],
        "watermark_audio": "使用BGM",
    })
    from PIL import Image

    Image.new("RGB", (4, 4), "white").save(tmp_path / "1.png")

    issues = validate_config_detailed(config, check_files=True)
    messages = [issue["message"] for issue in issues]

    assert not any("BGM" in message for message in messages)


def test_preview_bgm_prefers_explicit_files(tmp_path):
    from src.engine.config import build_default_config

    bgm_dir = tmp_path / "背景音乐"
    bgm_dir.mkdir()
    _write_wav(bgm_dir / "目录里的.wav")
    explicit = tmp_path / "选定的.wav"
    _write_wav(explicit)

    config = build_default_config()
    config.update({
        "use_bgm": True,
        "bgm_dir": str(bgm_dir),
        "bgm_files": [str(explicit)],
        "watermark_audio": "使用BGM",
    })

    server = EngineServer(ROOT)
    result = server._preview_bgm({"config": config})

    assert result["enabled"] is True
    assert result["source"] == str(explicit.resolve())
    assert result["name"] == "选定的.wav"


# ---------- 水印库视频素材（mov/mp4） ----------

@pytest.fixture()
def sample_video(tmp_path):
    """用 ffmpeg 生成一个 1 秒的测试视频。"""
    ffmpeg_path = configure_ffmpeg_environment(ROOT)
    assert ffmpeg_path
    video = tmp_path / "动态水印.mov"
    import subprocess

    result = subprocess.run(
        [
            ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return video


def test_watermark_library_accepts_videos(tmp_path, manager, sample_video):
    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()

    result = manager.import_files({
        "kind": "watermark",
        "paths": [str(sample_video)],
        "watermark_dir": str(watermark_dir),
    })["results"][0]

    assert result["status"] == "imported"
    assert (watermark_dir / "动态水印.mov").is_file()

    snapshot = manager.snapshot({"bgm_dir": str(tmp_path / "BGM"), "watermark_dir": str(watermark_dir)})
    item = snapshot["watermark"][0]
    assert item["type"] == "video"
    assert item["duration"] is not None and item["duration"] > 0.5


def test_watermark_video_dedupes_by_hash(tmp_path, manager, sample_video):
    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()
    duplicate = tmp_path / "副本.mov"
    duplicate.write_bytes(sample_video.read_bytes())

    results = manager.import_files({
        "kind": "watermark",
        "paths": [str(sample_video), str(duplicate)],
        "watermark_dir": str(watermark_dir),
    })["results"]

    assert [result["status"] for result in results] == ["imported", "duplicate"]
    assert len(list(watermark_dir.glob("*.mov"))) == 1


def test_watermark_library_mixes_images_and_videos(tmp_path, manager, sample_video):
    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()
    from PIL import Image

    Image.new("RGB", (8, 8), "white").save(watermark_dir / "logo.png")
    manager.import_files({
        "kind": "watermark",
        "paths": [str(sample_video)],
        "watermark_dir": str(watermark_dir),
    })

    snapshot = manager.snapshot({"bgm_dir": str(tmp_path / "BGM"), "watermark_dir": str(watermark_dir)})
    types = {item["name"]: item["type"] for item in snapshot["watermark"]}

    assert types == {"logo.png": "image", "动态水印.mov": "video"}


def test_preview_thumbnail_extracts_video_frame(tmp_path, sample_video):
    server = EngineServer(ROOT)

    result = server._preview_thumbnail({"path": str(sample_video), "max_width": 240, "max_height": 240})

    assert result["kind"] == "video"
    assert Path(result["preview_path"]).is_file()
    assert result["preview_path"].endswith(".jpg")
    assert result["duration"] is not None and result["duration"] > 0.5
    assert result["width"] > 0 and result["height"] > 0


# ---------- 特效 / 转场素材库 ----------

def test_effect_library_assets_generates_demo_images():
    from src.engine.effect_preview import ensure_effect_library_assets

    assets = ensure_effect_library_assets()
    assert Path(assets["source_a"]).is_file()
    assert Path(assets["source_b"]).is_file()
    assert assets["source_a"] != assets["source_b"]


def test_effect_animation_renders_frame_sequence():
    from src.engine.effect_preview import render_effect_animation

    effect = render_effect_animation({"kind": "effect", "name": "镜头呼吸", "frames": 8})
    assert len(effect["frames"]) == 8
    assert all(Path(path).is_file() for path in effect["frames"])
    assert effect["kind"] == "effect"

    transition = render_effect_animation({"kind": "transition", "name": "左右滑动", "frames": 6})
    assert len(transition["frames"]) == 6
    assert all(Path(path).is_file() for path in transition["frames"])

    # 缓存命中：第二次调用返回相同帧文件
    again = render_effect_animation({"kind": "effect", "name": "镜头呼吸", "frames": 8})
    assert again["frames"] == effect["frames"]


def test_effect_animation_rejects_bad_input():
    from src.engine.effect_preview import render_effect_animation

    with pytest.raises(ValueError, match="effect 或 transition"):
        render_effect_animation({"kind": "bad", "name": "x"})
    with pytest.raises(ValueError, match="缺少效果名称"):
        render_effect_animation({"kind": "effect", "name": ""})


def test_server_dispatches_effect_animation():
    server = EngineServer(ROOT)

    assets = server._dispatch("effect_library_assets", {})
    assert Path(assets["source_a"]).is_file()

    animation = server._dispatch("effect_preview_animation", {"kind": "transition", "name": "百叶窗", "frames": 5})
    assert len(animation["frames"]) == 5
    assert all(Path(path).is_file() for path in animation["frames"])


def test_audio_cover_extracts_embedded_artwork(tmp_path):
    """内嵌封面的音频能提取出封面图并缓存；无封面音频返回 None。"""
    import subprocess
    import sys

    from PIL import Image

    from src.engine.library import _extract_audio_cover

    ffmpeg_path = configure_ffmpeg_environment(ROOT)
    if not ffmpeg_path:
        pytest.skip("需要 ffmpeg")

    cover = tmp_path / "cover.png"
    Image.new("RGB", (64, 64), (200, 40, 60)).save(cover)
    wav = tmp_path / "sound.wav"
    _write_wav(wav, seconds=1)

    startupinfo = None
    creationflags = 0
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = subprocess.CREATE_NO_WINDOW
    audio = tmp_path / "带封面.mp3"
    result = subprocess.run(
        [
            ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(cover), "-i", str(wav),
            "-map", "0:v:0", "-map", "1:a",
            "-c:v", "mjpeg", "-c:a", "libmp3lame", "-id3v2_version", "3",
            str(audio),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    if result.returncode != 0 or not audio.is_file():
        pytest.skip("ffmpeg 无法生成带封面音频")

    cover_path = _extract_audio_cover(ffmpeg_path, audio)
    assert cover_path is not None
    extracted = Path(cover_path)
    assert extracted.is_file() and extracted.stat().st_size > 0
    with Image.open(extracted) as image:
        image.verify()

    # 缓存命中：再次调用返回同一路径
    assert _extract_audio_cover(ffmpeg_path, audio) == cover_path

    # 无封面音频返回 None
    plain = tmp_path / "无封面.wav"
    _write_wav(plain, seconds=1)
    assert _extract_audio_cover(ffmpeg_path, plain) is None


def test_audio_cover_method_handles_missing_and_dispatch():
    server = EngineServer(ROOT)

    # 文件不存在时返回 None
    assert server._dispatch("library_audio_cover", {"path": str(ROOT / "不存在的音频.mp3")})["cover_path"] is None

    # 参数缺失时同样安全返回
    assert server.library.audio_cover({})["cover_path"] is None
