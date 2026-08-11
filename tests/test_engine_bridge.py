import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image

from src.engine.config import DEFAULT_VIDEO_EFFECTS, build_default_config, normalize_config, scan_images, validate_config
from src.engine.effect_preview import render_effect_frame, render_effect_preview
from src.engine.server import EngineServer
from src.utils.ffmpeg_runtime import configure_ffmpeg_environment, probe_ffmpeg
from src.utils.timeline import cycle_images_to_duration, timeline_slot_count


ROOT = Path(__file__).resolve().parents[1]


def test_default_config_keeps_legacy_dimensions():
    config = normalize_config(build_default_config())
    assert config["resolution_preset"] == "1280x720"
    assert config["width"] == 1280
    assert config["height"] == 720
    assert config["watermark_type"] == "视频"


def test_scan_images_is_recursive_and_naturally_sorted(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    for relative in ("image10.png", "image2.png", "nested/image1.png"):
        path = tmp_path / relative
        Image.new("RGB", (4, 4), "white").save(path)
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")

    assert [Path(path).name for path in scan_images(str(tmp_path))] == [
        "image2.png",
        "image10.png",
        "image1.png",
    ]


def test_validate_config_reports_missing_paths():
    errors = validate_config({}, check_files=False)
    assert "请输入输入目录" in errors
    assert "请输入输出目录" in errors


def test_validate_config_reports_invalid_bgm_directory(tmp_path):
    input_dir = tmp_path / "图片"
    output_dir = tmp_path / "输出"
    input_dir.mkdir()
    output_dir.mkdir()
    Image.new("RGB", (8, 8), "white").save(input_dir / "1.png")
    config = build_default_config()
    config.update({
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "use_bgm": True,
        "bgm_dir": str(tmp_path / "不存在的音乐目录"),
        "watermark_audio": "使用BGM",
    })

    assert "BGM目录不存在，请重新选择" in validate_config(config, check_files=True)


def test_fixed_total_duration_cycles_images():
    images = ["1.png", "2.png", "3.png", "4.png"]

    assert timeline_slot_count(1, 8) == 8
    assert cycle_images_to_duration(images, 1, 8) == images + images


def test_total_duration_must_match_whole_image_slots():
    config = build_default_config()
    config.update({"input_dir": "input", "output_dir": "output", "duration": 1.5, "total_duration": 8})

    errors = validate_config(config, check_files=False)

    assert "总时长必须是每图时长的整数倍（例如每图 1 秒、总时长 8 秒）" in errors


def test_engine_one_shot_health_protocol():
    request = json.dumps({"id": "health-1", "method": "health", "params": {}})
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", "src.engine.server", "--once", request],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    response = json.loads(result.stdout.strip())
    assert response["ok"] is True
    assert response["result"]["protocol"] == 1
    assert "render" in response["result"]["capabilities"]


def test_engine_pipe_preserves_unicode_image_paths(tmp_path):
    input_dir = tmp_path / "化妆技巧大图"
    input_dir.mkdir()
    image_path = input_dir / "示例图片.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    request = json.dumps(
        {"id": "scan-unicode", "method": "scan_images", "params": {"input_dir": str(input_dir)}},
        ensure_ascii=False,
    )
    env = os.environ.copy()
    env.pop("PYTHONIOENCODING", None)
    env.pop("PYTHONUTF8", None)
    result = subprocess.run(
        [sys.executable, "-m", "src.engine.server"],
        cwd=ROOT,
        env=env,
        input=(request + "\n").encode("utf-8"),
        capture_output=True,
        check=True,
    )
    response = json.loads(result.stdout.decode("utf-8"))

    assert response["ok"] is True
    assert response["result"]["count"] == 1
    assert response["result"]["images"][0]["path"] == str(image_path.resolve())


def test_ffmpeg_runtime_finds_and_probes_available_binary():
    ffmpeg_path = configure_ffmpeg_environment(ROOT)
    available, version = probe_ffmpeg(ffmpeg_path)

    assert ffmpeg_path
    assert Path(ffmpeg_path).is_file()
    assert available is True
    assert version and version.startswith("ffmpeg version")


def test_engine_snapshot_reports_real_ffmpeg():
    snapshot = EngineServer(ROOT)._system_snapshot({})

    assert snapshot["ffmpeg_available"] is True
    assert Path(snapshot["ffmpeg_path"]).is_file()


def test_bgm_preview_copies_supported_audio_to_asset_scope(tmp_path):
    bgm_dir = tmp_path / "背景音乐"
    bgm_dir.mkdir()
    audio = bgm_dir / "预览音乐.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * 800)
    config = build_default_config()
    config.update({
        "use_bgm": True,
        "bgm_dir": str(bgm_dir),
        "watermark_audio": "使用BGM",
    })

    result = EngineServer._preview_bgm({"config": config})

    assert result["enabled"] is True
    assert result["name"] == audio.name
    assert Path(result["preview_path"]).is_file()
    assert "image-to-video-engine" in Path(result["preview_path"]).parts


def test_all_configured_effects_use_legacy_renderer():
    yy, xx = np.mgrid[:54, :96]
    source = np.stack((xx * 2, yy * 4, (xx + yy) * 2), axis=-1).astype(np.uint8)

    for effect in DEFAULT_VIDEO_EFFECTS:
        result = render_effect_frame(source.copy(), effect, 0.23, 1.0, 100.0, 1.3)
        assert result.shape == source.shape, effect
        assert result.dtype == np.uint8, effect

    heartbeat = render_effect_frame(source.copy(), "心跳跃动", 0.2, 1.0, 100.0, 1.3)
    soul = render_effect_frame(source.copy(), "灵魂出窍", 0.2, 1.0, 100.0, 1.3)
    assert not np.array_equal(heartbeat, source)
    assert not np.array_equal(soul, source)


def test_effect_preview_endpoint_writes_output_frame(tmp_path):
    source = tmp_path / "特效源图.png"
    Image.effect_noise((160, 90), 80).convert("RGB").save(source)
    config = build_default_config()
    config.update({
        "use_video_effect": True,
        "video_effect_type": "灵魂出窍",
        "resolution_preset": "320x180",
        "width": 320,
        "height": 180,
    })

    result = render_effect_preview({"path": str(source), "config": config, "time_sec": 0.2})

    assert Path(result["preview_path"]).is_file()
    assert result["width"] == 320
    assert result["height"] == 180
    assert result["effect_type"] == "灵魂出窍"


def test_effect_preview_uses_enabled_random_effect_pool(tmp_path):
    source = tmp_path / "随机特效源图.png"
    Image.effect_noise((160, 90), 80).convert("RGB").save(source)
    config = build_default_config()
    config.update({
        "use_video_effect": True,
        "video_effect_type": "无特效",
        "random_video_effect": True,
        "enabled_video_effects": ["镜头呼吸"],
        "resolution_preset": "160x90",
    })

    result = render_effect_preview({"path": str(source), "config": config, "time_sec": 0.2})

    assert result["effect_type"] == "镜头呼吸"


def test_effect_preview_applies_enabled_image_watermark(tmp_path):
    source = tmp_path / "水印底图.png"
    watermark = tmp_path / "红色水印.png"
    Image.new("RGB", (160, 90), "black").save(source)
    Image.new("RGBA", (20, 20), (255, 0, 0, 255)).save(watermark)
    config = build_default_config()
    config.update({
        "use_transition": False,
        "use_video_effect": False,
        "use_watermark": False,
        "use_image_watermark": True,
        "watermark_layers": [{
            "enabled": True,
            "path": str(watermark),
            "position": "中心",
            "size_mode": "固定比例",
            "scale": 50,
            "blend_mode": "正常",
            "opacity": 1.0,
            "fixed": True,
            "folder_random_single": False,
        }],
        "resolution_preset": "160x90",
        "width": 160,
        "height": 90,
    })

    result = render_effect_preview({"path": str(source), "config": config, "time_sec": 0})
    preview = np.asarray(Image.open(result["preview_path"]).convert("RGB"))
    center = preview[45, 80]

    assert center[0] > 200
    assert center[1] < 30
    assert center[2] < 30


def test_effect_preview_uses_next_frame_during_transition(tmp_path):
    source = tmp_path / "转场前.png"
    next_source = tmp_path / "转场后.png"
    Image.new("RGB", (160, 90), "red").save(source)
    Image.new("RGB", (160, 90), "blue").save(next_source)
    config = build_default_config()
    config.update({
        "duration": 1.0,
        "fps": 30,
        "use_transition": True,
        "random_transition": False,
        "transition_type": "淡入淡出",
        "use_video_effect": False,
        "use_watermark": False,
        "use_image_watermark": False,
        "resolution_preset": "160x90",
        "width": 160,
        "height": 90,
    })

    result = render_effect_preview({
        "path": str(source),
        "next_path": str(next_source),
        "config": config,
        "time_sec": 0.9,
    })
    preview = np.asarray(Image.open(result["preview_path"]).convert("RGB"))

    assert result["transition_active"] is True
    assert result["transition_type"] == "淡入淡出"
    assert not np.array_equal(preview[45, 80], np.array([255, 0, 0], dtype=np.uint8))
