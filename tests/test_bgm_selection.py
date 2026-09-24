"""BGM 选曲规则：顺序模式按视频序号轮转，随机模式每次重抽。

回归的 bug：批量导出时每个视频都用同一首 BGM ——
``select_bgm_file`` 恒返回候选里的第一首，视频序号从头到尾没参与选曲，
而隔壁「视频水印·文件夹模式」早就用 ``_current_video_index % len(files)`` 轮转了。
"""

import os
import random
import wave
from pathlib import Path

from src.render.audio import resolve_bgm_candidates, select_bgm_file
from src.render.context import RenderContext

ROOT = Path(__file__).resolve().parents[1]


def _write_wav(path: Path, seconds: float = 0.2) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * int(8000 * seconds))


def _ctx(**state) -> RenderContext:
    table = {
        "use_bgm": True,
        "watermark_audio": "使用BGM",
        "random_bgm": False,
        "loop_bgm": True,
        "bgm_volume": 0.5,
        "bgm_dir": "",
        "bgm_files": [],
        "_bgm_files": [],
        "_current_video_index": 0,
    }
    table.update(state)
    return RenderContext(read=lambda name, default=None: table.get(name, default))


def _names(paths) -> list[str]:
    return [os.path.basename(str(path)) for path in paths]


def _bgm_dir_with(tmp_path, *names: str) -> Path:
    folder = tmp_path / "BGM"
    folder.mkdir()
    for name in names:
        _write_wav(folder / name)
    return folder


def test_ordered_mode_cycles_bgm_by_video_index(tmp_path):
    """顺序模式：3 首候选 → 3 个视频各拿一首，不再全部是第一首。"""
    folder = _bgm_dir_with(tmp_path, "01-第一首.wav", "02-第二首.wav", "03-第三首.wav")
    state = {
        "use_bgm": True, "watermark_audio": "使用BGM", "random_bgm": False,
        "bgm_dir": str(folder), "_bgm_files": [],
    }
    ctx = RenderContext(read=lambda name, default=None: state.get(name, default))

    picked = []
    for index in range(3):
        state["_current_video_index"] = index
        picked.append(os.path.basename(select_bgm_file(ctx)))

    assert picked == ["01-第一首.wav", "02-第二首.wav", "03-第三首.wav"]


def test_ordered_mode_wraps_around_after_full_cycle(tmp_path):
    """顺序模式：视频数多于候选数时从头再来，而不是卡在第一首。"""
    folder = _bgm_dir_with(tmp_path, "a.wav", "b.wav")
    state = {
        "use_bgm": True, "watermark_audio": "使用BGM", "random_bgm": False,
        "bgm_dir": str(folder), "_bgm_files": [],
    }
    ctx = RenderContext(read=lambda name, default=None: state.get(name, default))

    picked = []
    for index in range(5):
        state["_current_video_index"] = index
        picked.append(os.path.basename(select_bgm_file(ctx)))

    assert picked == ["a.wav", "b.wav", "a.wav", "b.wav", "a.wav"]


def test_single_video_keeps_first_candidate(tmp_path):
    """单视频导出（序号缺失或为 0）仍取第一首，旧行为不回退。"""
    folder = _bgm_dir_with(tmp_path, "a.wav", "b.wav")
    for index in (0, None, "", "不是数字"):
        ctx = _ctx(bgm_dir=str(folder), _current_video_index=index)
        assert os.path.basename(select_bgm_file(ctx)) == "a.wav"


def test_ordered_mode_follows_library_selection_order(tmp_path):
    """顺序模式按素材库里的挑选顺序取，而不是按路径字母序重排。

    界面上「BGM 素材」是按挑选顺序列的，顺序模式的第一首必须与它一致，
    否则预览（用挑选顺序）与成片（曾用字母序）对不上。
    """
    folder = _bgm_dir_with(tmp_path)
    later = folder / "z-后挑的.wav"
    earlier = folder / "a-先挑的.wav"
    _write_wav(later)
    _write_wav(earlier)

    ctx = _ctx(_bgm_files=[str(later), str(earlier)])
    assert _names(resolve_bgm_candidates(ctx)) == ["z-后挑的.wav", "a-先挑的.wav"]
    assert os.path.basename(select_bgm_file(ctx)) == "z-后挑的.wav"


def test_random_mode_still_rerolls_for_same_video_index(tmp_path):
    """随机模式不受视频序号约束：同一个序号多次取也可能换歌。"""
    folder = _bgm_dir_with(tmp_path, "a.wav", "b.wav", "c.wav")
    ctx = _ctx(bgm_dir=str(folder), random_bgm=True, _current_video_index=0)

    random.seed(7)
    picked = {os.path.basename(select_bgm_file(ctx)) for _ in range(8)}

    assert picked <= {"a.wav", "b.wav", "c.wav"}
    assert len(picked) > 1


def test_postprocess_reuses_single_selection_rule():
    """后处理不得再自己写一套 BGM 选曲（防止两处规则走散）。"""
    source = (ROOT / "src" / "render" / "postprocess.py").read_text(encoding="utf-8")

    assert "select_bgm_file(ctx)" in source
    assert "bgm_files[0]" not in source
