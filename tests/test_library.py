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


def test_remove_sends_file_to_trash(tmp_path, manager, monkeypatch):
    """删除素材应走回收站组件，而非直接 unlink。"""
    import src.engine.library as library_module

    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()
    target = watermark_dir / "logo.png"
    target.write_bytes(b"png-bytes")

    calls: list[str] = []

    class Recorder:
        @staticmethod
        def send2trash(path: str):
            calls.append(path)

    monkeypatch.setattr(library_module, "_send2trash", Recorder())

    result = manager.remove({
        "kind": "watermark",
        "path": str(target),
        "watermark_dir": str(watermark_dir),
    })
    assert result["removed"] is True
    # 走的是回收站组件，而不是直接删除文件
    assert calls == [str(target)]
    assert target.exists()


def test_delete_folder_sends_to_trash(tmp_path, manager, monkeypatch):
    """删除空文件夹也应走回收站组件。"""
    import src.engine.library as library_module

    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()
    folder = watermark_dir / "空文件夹"
    folder.mkdir()

    calls: list[str] = []

    class Recorder:
        @staticmethod
        def send2trash(path: str):
            calls.append(path)

    monkeypatch.setattr(library_module, "_send2trash", Recorder())

    manager.delete_folder({"kind": "watermark", "folder": "空文件夹", "watermark_dir": str(watermark_dir)})
    assert calls == [str(folder)]
    assert folder.exists()


def test_remove_batch_routes_to_trash(tmp_path, manager, monkeypatch):
    """批量删除一次处理多个文件，且都走回收站组件。"""
    import src.engine.library as library_module

    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()
    targets = [watermark_dir / f"{index}.png" for index in range(3)]
    for target in targets:
        target.write_bytes(b"png")

    calls: list[str] = []

    class Recorder:
        @staticmethod
        def send2trash(path: str):
            calls.append(path)

    monkeypatch.setattr(library_module, "_send2trash", Recorder())

    result = manager.remove_batch({
        "kind": "watermark",
        "paths": [str(target) for target in targets],
        "watermark_dir": str(watermark_dir),
    })
    assert [item["status"] for item in result["results"]] == ["removed", "removed", "removed"]
    assert calls == [str(target) for target in targets]
    assert all(target.exists() for target in targets)


def test_rename_item_keeps_extension(tmp_path, manager):
    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()
    target = watermark_dir / "旧名.mp4"
    target.write_bytes(b"video")

    result = manager.rename_item({
        "kind": "watermark",
        "path": str(target),
        "new_name": "新名字.wav",  # 扩展名会被强制改回 .mp4
        "watermark_dir": str(watermark_dir),
    })
    assert result["name"] == "新名字.mp4"
    assert (watermark_dir / "新名字.mp4").is_file()
    assert not target.exists()

    # 无扩展名时自动补原扩展名
    result = manager.rename_item({
        "kind": "watermark",
        "path": str(watermark_dir / "新名字.mp4"),
        "new_name": "最终名",
        "watermark_dir": str(watermark_dir),
    })
    assert result["name"] == "最终名.mp4"
    assert (watermark_dir / "最终名.mp4").is_file()


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


def test_effect_library_custom_assets_roundtrip(tmp_path):
    """自定义演示图：设置后生效、清单持久化、可恢复默认、非图片被拒绝。"""
    from PIL import Image

    from src.engine.effect_preview import (
        effect_library_reset_assets,
        effect_library_set_asset,
        ensure_effect_library_assets,
    )

    effect_library_reset_assets()  # 保证测试起点干净

    custom = tmp_path / "我的演示图.png"
    Image.new("RGB", (96, 54), (10, 200, 120)).save(custom)

    assets = effect_library_set_asset({"which": "a", "path": str(custom)})
    assert assets["custom_a"] is True
    assert assets["custom_b"] is False
    assert Path(assets["source_a"]).is_file()
    assert Path(assets["source_a"]).stat().st_size == custom.stat().st_size  # 原样复制
    assert assets["user_path_a"] == str(custom.resolve())

    # 再次读取仍生效（清单持久化，临时目录清理后也能从原路径恢复）
    again = ensure_effect_library_assets()
    assert again["custom_a"] is True

    # 恢复默认
    reset = effect_library_reset_assets()
    assert reset["custom_a"] is False and reset["custom_b"] is False

    # 非图片文件被拒绝
    bad = tmp_path / "不是图片.txt"
    bad.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="不是有效的图片"):
        effect_library_set_asset({"which": "b", "path": str(bad)})

    with pytest.raises(ValueError, match="which"):
        effect_library_set_asset({"which": "x", "path": str(custom)})


def test_server_dispatches_custom_effect_assets(tmp_path):
    from PIL import Image

    server = EngineServer(ROOT)
    server._dispatch("effect_library_reset_assets", {})

    custom = tmp_path / "服务端演示图.png"
    Image.new("RGB", (64, 64), (200, 40, 60)).save(custom)

    assets = server._dispatch("effect_library_set_asset", {"which": "b", "path": str(custom)})
    assert assets["custom_b"] is True
    assert Path(assets["source_b"]).is_file()

    reset = server._dispatch("effect_library_reset_assets", {})
    assert reset["custom_a"] is False and reset["custom_b"] is False


def _write_fake_draft(draft_dir: Path, name: str, payload: dict) -> None:
    import json

    draft_dir.mkdir(parents=True, exist_ok=True)
    (draft_dir / "draft_content.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_jianying_scan_collects_draft_materials(tmp_path):
    """剪映草稿扫描：新旧格式兼容、按路径去重、跳过缺失文件、照片单独归类。"""
    import json
    import wave

    from src.engine.jianying import jianying_scan

    draft_root = tmp_path / "com.lveditor.draft"
    media = tmp_path / "media"
    media.mkdir()

    # 真实音频（wav）与占位视频/图片（扫描只校验存在性与扩展名）
    audio_a = media / "第一首歌.wav"
    with wave.open(str(audio_a), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * 800)
    audio_b = media / "第二首歌.mp3"
    audio_b.write_bytes(b"ID3")
    video = media / "素材视频.mp4"
    video.write_bytes(b"fake")
    photo = media / "封面照片.png"
    photo.write_bytes(b"fake")
    effect_clip = media / "特效资源.mp4"
    effect_clip.write_bytes(b"fake")
    transition_img = media / "转场序列图.png"
    transition_img.write_bytes(b"fake")

    # 新版草稿：materials.videos / materials.audios / effects / transitions
    _write_fake_draft(draft_root / "我的草稿", "我的草稿", {
        "name": "我的草稿",
        "materials": {
            "audios": [
                {"path": str(audio_a), "type": "music", "material_name": "第一首歌"},
                {"path": str(audio_b), "type": "sound"},
                {"path": str(media / "已删除.mp3"), "type": "music"},  # 文件不存在，跳过
            ],
            "videos": [
                {"path": str(video), "type": "video"},
                {"path": str(photo), "type": "photo"},
            ],
            "effects": [
                {"path": str(effect_clip), "type": "video_effect", "name": "特效"},
                {"id": "cloud-template-001", "name": "云端特效"},  # 无本地文件，跳过
            ],
            "transitions": [
                {"path": str(transition_img), "type": "transition", "name": "转场"},
            ],
        },
        "tracks": [],
    })

    # 旧版草稿：materials_audios / materials_videos
    old_draft = draft_root / "旧草稿"
    old_draft.mkdir(parents=True)
    (old_draft / "draft_info.json").write_text(json.dumps({
        "name": "旧草稿",
        "materials_audios": [{"path": str(audio_a)}],  # 与新版草稿重复，应去重
        "materials_videos": [{"path": str(video)}],
    }, ensure_ascii=False), encoding="utf-8")

    # 无 JSON 的目录应被忽略
    (draft_root / "无清单草稿").mkdir()

    result = jianying_scan({"draft_root": str(draft_root)})

    assert len(result["drafts"]) == 2
    assert [d["name"] for d in result["drafts"]] == ["我的草稿", "旧草稿"]

    audio_paths = {entry["path"] for entry in result["audios"]}
    assert audio_paths == {str(audio_a.resolve()), str(audio_b.resolve())}  # 缺失文件跳过、跨草稿去重

    assert [entry["path"] for entry in result["videos"]] == [str(video.resolve())]
    assert [entry["path"] for entry in result["images"]] == [str(photo.resolve())]
    assert [entry["path"] for entry in result["effects"]] == [str(effect_clip.resolve())]
    assert [entry["path"] for entry in result["transitions"]] == [str(transition_img.resolve())]

    draft_a = next(d for d in result["drafts"] if d["name"] == "我的草稿")
    assert draft_a["counts"] == {"audio": 2, "video": 1, "image": 1, "effect": 1, "transition": 1}


def test_jianying_scan_rejects_missing_root(tmp_path):
    from src.engine.jianying import jianying_scan

    with pytest.raises(ValueError, match="未找到剪映草稿目录"):
        jianying_scan({"draft_root": str(tmp_path / "不存在")})


def test_jianying_cache_scan_collects_downloaded_assets(tmp_path):
    """剪映内置资源缓存扫描：按体积过滤、名称从清单 JSON 解析、跨目录去重。"""
    import json

    from src.engine.jianying import jianying_cache_scan

    cache = tmp_path / "Cache"
    (cache / "music").mkdir(parents=True)
    (cache / "effect").mkdir(parents=True)

    # 内置 BGM：音频 + 同名清单（读取真实名称）
    song = cache / "music" / "abc123.mp3"
    song.write_bytes(b"\x00" * (300 * 1024))
    (cache / "music" / "abc123.json").write_text(json.dumps({"name": "内置歌曲名"}, ensure_ascii=False), encoding="utf-8")

    # 小体积音频（音效碎片/图标类）应被过滤
    tiny = cache / "music" / "tiny.mp3"
    tiny.write_bytes(b"\x00" * (10 * 1024))

    # 内置特效/转场视频资源
    effect_video = cache / "effect" / "fx9876.mp4"
    effect_video.write_bytes(b"\x00" * (80 * 1024))

    # 非媒体文件忽略
    (cache / "music" / "notes.txt").write_text("x", encoding="utf-8")

    result = jianying_cache_scan({"cache_root": str(cache)})
    assert [entry["path"] for entry in result["audios"]] == [str(song.resolve())]
    assert result["audios"][0]["name"] == "内置歌曲名"  # 从清单 JSON 解析
    assert [entry["path"] for entry in result["videos"]] == [str(effect_video.resolve())]
    assert result["audios"][0]["draft"] == "内置缓存"
    assert result["scanned_files"] >= 4
    assert result["truncated"] is False


def test_jianying_cache_scan_rejects_missing_root(tmp_path):
    from src.engine.jianying import jianying_cache_scan

    with pytest.raises(ValueError, match="未找到剪映内置资源缓存目录"):
        jianying_cache_scan({"cache_root": str(tmp_path / "不存在")})


def test_server_dispatches_jianying_cache_scan(tmp_path):
    import json

    server = EngineServer(ROOT)

    cache = tmp_path / "Cache"
    (cache / "music").mkdir(parents=True)
    song = cache / "music" / "srv001.m4a"
    song.write_bytes(b"\x00" * (300 * 1024))
    (cache / "music" / "srv001.json").write_text(json.dumps({"name": "服务端内置曲"}, ensure_ascii=False), encoding="utf-8")

    result = server._dispatch("jianying_cache_scan", {"cache_root": str(cache)})
    assert len(result["audios"]) == 1
    assert result["audios"][0]["name"] == "服务端内置曲"


def test_server_dispatches_jianying_scan(tmp_path):
    import json

    server = EngineServer(ROOT)

    media = tmp_path / "media"
    media.mkdir()
    audio = media / "服务端歌曲.wav"
    audio.write_bytes(b"wav")

    draft_root = tmp_path / "com.lveditor.draft"
    (draft_root / "草稿").mkdir(parents=True)
    (draft_root / "草稿" / "draft_content.json").write_text(json.dumps({
        "materials": {"audios": [{"path": str(audio)}], "videos": []},
    }, ensure_ascii=False), encoding="utf-8")

    result = server._dispatch("jianying_scan", {"draft_root": str(draft_root)})
    assert len(result["audios"]) == 1
    assert result["audios"][0]["path"] == str(audio.resolve())


def _make_transparent_mov(tmp_path, size: int = 40, frames: int = 3) -> Path:
    """生成一个「品红方块 + 其余全透明」的 qtrle MOV（OpenCV 解码会丢 alpha）。"""
    import subprocess
    import sys

    from PIL import Image, ImageDraw

    ffmpeg_path = configure_ffmpeg_environment(ROOT)
    if not ffmpeg_path:
        pytest.skip("需要 ffmpeg")
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir(exist_ok=True)
    for index in range(frames):
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle([5, 5, 25, 25], fill=(255, 0, 200, 255))
        image.save(frames_dir / f"{index:02d}.png")
    mov = tmp_path / "transparent.mov"
    startupinfo = None
    creationflags = 0
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y", "-framerate", "10",
         "-i", str(frames_dir / "%02d.png"), "-c:v", "qtrle", str(mov)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    if result.returncode != 0 or not mov.is_file():
        pytest.skip("ffmpeg 无法生成透明视频")
    return mov


def test_read_video_frames_rgba_preserves_alpha(tmp_path):
    """FFmpeg RGBA 解码保留透明通道（OpenCV VideoCapture 会丢弃）。"""
    from src.utils.ffmpeg_runtime import configure_ffmpeg_environment, read_video_frames_rgba

    ffmpeg_path = configure_ffmpeg_environment(ROOT)
    if not ffmpeg_path:
        pytest.skip("需要 ffmpeg")
    mov = _make_transparent_mov(tmp_path)

    frames = read_video_frames_rgba(ffmpeg_path, mov)
    assert frames is not None and len(frames) == 3
    frame = frames[1]
    assert frame.shape[2] == 4
    transparent = int((frame[:, :, 3] == 0).sum())
    opaque = int((frame[:, :, 3] == 255).sum())
    assert transparent > 0, "应存在透明像素"
    assert opaque > 0, "应存在不透明像素"

    # 不存在的文件 / 非视频返回 None
    assert read_video_frames_rgba(ffmpeg_path, tmp_path / "不存在.mov") is None


def test_preview_video_watermark_keeps_transparency(tmp_path):
    """透明视频水印预览：透明区域透出背景，方块区域按 alpha 叠加。"""
    import numpy as np
    from PIL import Image

    from src.engine.config import build_default_config
    from src.engine.effect_preview import render_effect_preview

    mov = _make_transparent_mov(tmp_path)
    base = tmp_path / "base.png"
    Image.new("RGB", (192, 108), (40, 44, 50)).save(base)

    config = build_default_config()
    config.update({
        "use_watermark": True,
        "watermark_path": str(mov),
        "watermark_position": "中心",
        "watermark_match_method": "循环",
        "watermark_size_mode": "固定比例",
        "watermark_scale": 40,
        "watermark_blend_mode": "正常",
    })
    result = render_effect_preview({
        "path": str(base),
        "config": config,
        "time_sec": 0.5,
        "max_width": 192,
        "max_height": 108,
    })
    frame = np.asarray(Image.open(result["preview_path"]).convert("RGB"))
    h, w, _ = frame.shape
    center = frame[h // 2 - 2:h // 2 + 2, w // 2 - 2:w // 2 + 2]
    corner = frame[2:8, 2:8]
    center_red = center[:, :, 0].mean()
    corner_red = corner[:, :, 0].mean()
    # 中央方块区域应有品红叠加（红色通道明显高于背景），角落保持背景色
    assert center_red > corner_red + 40, f"中央未叠加水印: center={center_red:.1f} corner={corner_red:.1f}"
    assert corner_red < 80, "角落不应被水印污染（透明区域透出背景）"


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


def _ffmpeg_run(ffmpeg_path: str, args: list[str], timeout: int = 60):
    import subprocess
    import sys

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


def _make_test_video(tmp_path, name: str, codec: str) -> Path:
    """用 PIL 帧 + ffmpeg 生成一段测试视频（h264 mp4 / mpeg4 avi）。"""
    from PIL import Image

    ffmpeg_path = configure_ffmpeg_environment(ROOT)
    if not ffmpeg_path:
        pytest.skip("需要 ffmpeg")
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir(exist_ok=True)
    for index in range(4):
        Image.new("RGB", (64, 36), (60 + index * 40, 40, 90)).save(frames_dir / f"{index}.png")
    video = tmp_path / name
    result = _ffmpeg_run(ffmpeg_path, [
        ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
        "-framerate", "5", "-i", str(frames_dir / "%d.png"),
        "-c:v", codec, "-pix_fmt", "yuv420p",
        str(video),
    ])
    if result.returncode != 0 or not video.is_file():
        pytest.skip(f"ffmpeg 无法生成测试视频 {name}")
    return video


def test_library_preview_video_copies_playable_and_caches(tmp_path, manager):
    """浏览器可播放的 h264 mp4 直接拷贝为预览，且按内容缓存；缺失文件报错。"""
    video = _make_test_video(tmp_path, "片段.mp4", "libx264")

    result = manager.preview_video({"path": str(video)})
    preview = Path(result["preview_path"])
    assert preview.is_file() and preview.stat().st_size > 0
    assert "image-to-video-engine" in preview.parts
    assert "video-previews" in preview.parts
    assert result["transcoded"] is False
    assert preview.stat().st_size == video.stat().st_size  # 直接拷贝

    # 缓存命中：再次调用返回同一路径
    again = manager.preview_video({"path": str(video)})
    assert again["preview_path"] == result["preview_path"]

    # 缺失文件报错
    with pytest.raises(ValueError, match="视频文件不存在"):
        manager.preview_video({"path": str(tmp_path / "不存在的视频.mp4")})


def test_library_preview_video_transcodes_avi(tmp_path, manager):
    """浏览器不可播放的格式（mpeg4 avi）转码为 h264 mp4 预览。"""
    video = _make_test_video(tmp_path, "旧格式.avi", "mpeg4")

    result = manager.preview_video({"path": str(video)})
    assert result["transcoded"] is True
    preview = Path(result["preview_path"])
    assert preview.is_file() and preview.stat().st_size > 0
    assert preview.suffix == ".mp4"
    codec = manager._probe_video_codec(preview)
    assert codec == "h264"


def test_server_dispatches_library_preview_video(tmp_path):
    server = EngineServer(ROOT)
    video = _make_test_video(tmp_path, "服务端片段.mp4", "libx264")

    result = server._dispatch("library_preview_video", {"path": str(video)})
    assert Path(result["preview_path"]).is_file()
    assert "video-previews" in Path(result["preview_path"]).parts


# ---------- 素材元数据（标签 / 星标 / 备注） ----------


def _make_watermark_image(directory: Path, name: str, color: str = "red", size: int = 16) -> Path:
    from PIL import Image

    path = directory / name
    Image.new("RGB", (size, size), color).save(path)
    return path


def _make_gradient_image(directory: Path, name: str, offset: int = 0) -> Path:
    """写一张对角渐变图：相邻像素亮度递增，dHash 有区分度。

    offset 改变像素值但不改变相邻像素的大小关系，用于构造「内容相似但文件不同」。
    """
    from PIL import Image

    path = directory / name
    size = 32
    pixels = []
    for y in range(size):
        for x in range(size):
            pixels.append((x + y + offset) % 256)
    image = Image.new("L", (size, size))
    image.putdata(pixels)
    image.save(path)
    return path


def test_set_metadata_updates_snapshot_fields(tmp_path, manager):
    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()
    _make_watermark_image(watermark_dir, "logo.png")

    result = manager.set_metadata({
        "kind": "watermark",
        "path": str(watermark_dir / "logo.png"),
        "watermark_dir": str(watermark_dir),
        "tags": ["品牌", " 品牌 ", "透明背景"],
        "starred": True,
        "note": "主视觉 logo",
    })
    assert result["tags"] == ["品牌", "透明背景"]  # 自动去重
    assert result["starred"] is True
    assert result["note"] == "主视觉 logo"

    snapshot = manager.snapshot({"watermark_dir": str(watermark_dir)})
    item = snapshot["watermark"][0]
    assert item["tags"] == ["品牌", "透明背景"]
    assert item["starred"] is True
    assert item["note"] == "主视觉 logo"


def test_set_metadata_partial_update_and_clear(tmp_path, manager):
    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()
    _make_watermark_image(watermark_dir, "logo.png")

    manager.set_metadata({
        "kind": "watermark",
        "path": str(watermark_dir / "logo.png"),
        "watermark_dir": str(watermark_dir),
        "tags": ["a", "b"],
        "starred": True,
        "note": "备注",
    })
    # 只更新 starred，其余字段保持不变
    manager.set_metadata({
        "kind": "watermark",
        "path": str(watermark_dir / "logo.png"),
        "watermark_dir": str(watermark_dir),
        "starred": False,
    })
    result = manager.set_metadata({
        "kind": "watermark",
        "path": str(watermark_dir / "logo.png"),
        "watermark_dir": str(watermark_dir),
        "tags": [],
        "note": "",
    })
    assert result["tags"] == []
    assert result["starred"] is False
    assert result["note"] == ""

    with pytest.raises(ValueError, match="没有需要更新的元数据字段"):
        manager.set_metadata({
            "kind": "watermark",
            "path": str(watermark_dir / "logo.png"),
            "watermark_dir": str(watermark_dir),
        })


def test_set_metadata_rejects_outside_path(tmp_path, manager):
    outside = _make_watermark_image(tmp_path, "外部.png")
    with pytest.raises(ValueError, match="只能编辑素材库内的素材"):
        manager.set_metadata({
            "kind": "watermark",
            "path": str(outside),
            "watermark_dir": str(tmp_path / "水印"),
            "tags": ["x"],
        })


def test_get_tags_aggregates_counts(tmp_path, manager):
    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()
    first = _make_watermark_image(watermark_dir, "a.png", "red")
    second = _make_watermark_image(watermark_dir, "b.png", "blue")
    _make_watermark_image(watermark_dir, "c.png", "green")
    for path, tags in ((first, ["品牌", "方形"]), (second, ["品牌"]), (watermark_dir / "c.png", ["透明背景"])):
        manager.set_metadata({
            "kind": "watermark",
            "path": str(path),
            "watermark_dir": str(watermark_dir),
            "tags": tags,
        })

    result = manager.get_tags({"kind": "watermark", "watermark_dir": str(watermark_dir)})
    by_name = {tag["name"]: tag["count"] for tag in result["tags"]}
    assert by_name == {"品牌": 2, "方形": 1, "透明背景": 1}


# ---------- 重复 / 相似素材查找 ----------


def test_find_duplicates_watermark_exact_and_similar(tmp_path, manager):
    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()
    # 三张内容完全相同（精确去重）
    _make_watermark_image(watermark_dir, "相同1.png", "red", size=32)
    _make_watermark_image(watermark_dir, "相同2.png", "red", size=32)
    _make_watermark_image(watermark_dir, "相同3.png", "red", size=32)
    # 内容相似但像素不同的渐变图（dHash 相同）
    _make_gradient_image(watermark_dir, "渐变A.png", offset=0)
    _make_gradient_image(watermark_dir, "渐变B.png", offset=10)
    # 完全不同的图片（纯蓝，dHash 与渐变图差异大）
    _make_watermark_image(watermark_dir, "蓝色.png", "blue", size=32)

    result = manager.find_duplicates({"kind": "watermark", "watermark_dir": str(watermark_dir)})
    groups = result["groups"]
    assert result["scanned"] == 6
    assert len(groups) >= 2

    exact = next(group for group in groups if group["reason"] == "内容完全相同")
    assert exact["count"] == 3
    assert len(exact["duplicates"]) == 2
    assert exact["saved_bytes"] > 0
    assert exact["representative"]["name"] == "相同1.png"

    similar = next((group for group in groups if group["reason"] == "图片内容相似"), None)
    assert similar is not None
    names = {item["name"] for item in [similar["representative"]] + similar["duplicates"]}
    assert {"渐变A.png", "渐变B.png"}.issubset(names)


def test_find_duplicates_bgm_similar_versions(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    # 同一节奏（响度曲线一致）但振幅不同 → 指纹归一化后判为同曲
    _write_rhythm_wav(bgm_dir / "版本A.wav", [0.9, 0.3, 0.7])
    _write_rhythm_wav(bgm_dir / "版本B.wav", [0.45, 0.15, 0.35])
    _write_rhythm_wav(bgm_dir / "其他歌.wav", [0.2, 0.8, 0.4, 0.6])

    result = manager.find_duplicates({"kind": "bgm", "bgm_dir": str(bgm_dir)})
    assert result["scanned"] == 3
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["reason"] == "音频内容相似（同曲不同版本）"
    names = {item["name"] for item in [group["representative"]] + group["duplicates"]}
    assert {"版本A.wav", "版本B.wav"}.issubset(names)


# ---------- 批量重命名 ----------


def test_rename_batch_applies_pattern(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    paths = []
    for name in ("第一首.wav", "第二首.wav", "第三首.wav"):
        path = bgm_dir / name
        _write_wav(path)
        paths.append(str(path))

    result = manager.rename_batch({
        "kind": "bgm",
        "paths": paths,
        "bgm_dir": str(bgm_dir),
        "pattern": "专辑-{n}-{name}",
        "start_index": 1,
    })
    assert [item["status"] for item in result["results"]] == ["renamed", "renamed", "renamed"]
    assert [item["name"] for item in result["results"]] == ["专辑-01-第一首.wav", "专辑-02-第二首.wav", "专辑-03-第三首.wav"]
    for item in result["results"]:
        assert Path(item["path"]).is_file()

    # 序号补零宽度取总数位数与 2 的较大值（3 个 → 01/02/03）
    assert result["results"][0]["name"].startswith("专辑-01-")


def test_rename_batch_keeps_extension_and_rejects_collision(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    paths = []
    for name in ("a.wav", "b.wav", "c.wav"):
        path = bgm_dir / name
        _write_wav(path)
        paths.append(str(path))

    # 模板不含任何占位符 → 全部生成同名，后续失败
    result = manager.rename_batch({
        "kind": "bgm",
        "paths": paths,
        "bgm_dir": str(bgm_dir),
        "pattern": "同名",
    })
    assert result["results"][0]["status"] == "renamed"
    assert all(item["status"] == "failed" for item in result["results"][1:])
    assert "重名" in result["results"][1]["reason"]


# ---------- 智能文件夹 ----------


def test_smart_folders_roundtrip(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    folders = [
        {
            "id": "smart-1",
            "name": "长音频",
            "kind": "bgm",
            "conditions": [
                {"field": "duration", "op": "gt", "value": 60},
            ],
        },
        {
            "name": "带标签",
            "kind": "watermark",
            "conditions": [
                {"field": "tag", "op": "contains", "value": "品牌"},
                {"field": "starred", "op": "eq", "value": True},
            ],
        },
    ]
    saved = manager.smart_folders_save({"bgm_dir": str(bgm_dir), "folders": folders})
    assert len(saved["folders"]) == 2
    assert saved["folders"][0]["id"] == "smart-1"
    assert saved["folders"][1]["id"].startswith("smart-")  # 未传 id 自动生成

    listed = manager.smart_folders_list({"bgm_dir": str(bgm_dir)})
    assert len(listed["folders"]) == 2
    assert listed["folders"][0]["name"] == "长音频"
    assert Path(listed["path"]).is_file()


def test_smart_folders_rejects_bad_rules(tmp_path, manager):
    bgm_dir = tmp_path / "BGM"
    bgm_dir.mkdir()
    with pytest.raises(ValueError, match="不支持的"):
        manager.smart_folders_save({
            "bgm_dir": str(bgm_dir),
            "folders": [{
                "name": "坏规则",
                "kind": "bgm",
                "conditions": [{"field": "颜色", "op": "eq", "value": "红"}],
            }],
        })
    with pytest.raises(ValueError, match="名称不能为空"):
        manager.smart_folders_save({
            "bgm_dir": str(bgm_dir),
            "folders": [{"name": "  ", "kind": "bgm", "conditions": []}],
        })


# ---------- 服务端分发 ----------


def test_server_dispatches_new_library_methods(tmp_path):
    server = EngineServer(ROOT)
    watermark_dir = tmp_path / "水印"
    watermark_dir.mkdir()
    _make_watermark_image(watermark_dir, "logo.png")

    updated = server._dispatch("library_set_metadata", {
        "kind": "watermark",
        "path": str(watermark_dir / "logo.png"),
        "watermark_dir": str(watermark_dir),
        "tags": ["品牌"],
        "starred": True,
    })
    assert updated["tags"] == ["品牌"]
    assert updated["starred"] is True

    tags = server._dispatch("library_get_tags", {
        "kind": "watermark",
        "watermark_dir": str(watermark_dir),
    })
    assert tags["tags"] == [{"name": "品牌", "count": 1}]

    duplicates = server._dispatch("library_find_duplicates", {
        "kind": "watermark",
        "watermark_dir": str(watermark_dir),
    })
    assert duplicates["scanned"] == 1
    assert duplicates["groups"] == []

    renamed = server._dispatch("library_rename_batch", {
        "kind": "watermark",
        "paths": [str(watermark_dir / "logo.png")],
        "watermark_dir": str(watermark_dir),
        "pattern": "新版-{n}",
    })
    assert renamed["results"][0]["status"] == "renamed"
    assert renamed["results"][0]["name"] == "新版-01.png"

    saved = server._dispatch("library_smart_folders_save", {
        "bgm_dir": str(tmp_path / "BGM"),
        "folders": [{"name": "收藏", "kind": "watermark", "conditions": [{"field": "starred", "op": "eq", "value": True}]}],
    })
    listed = server._dispatch("library_smart_folders_list", {"bgm_dir": str(tmp_path / "BGM")})
    assert [folder["name"] for folder in listed["folders"]] == ["收藏"]
    assert saved["folders"][0]["name"] == "收藏"

    capabilities = server._dispatch("health", {})["capabilities"]
    assert "library-metadata" in capabilities
    assert "library-dedup" in capabilities
    assert "library-smart-folders" in capabilities
