#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""桌面端（TypeScript）与引擎端（Python）之间的配置契约一致性检查。

同一个事实在两个地方各写了一份，谁也不检查谁：

    Python 侧                                   TypeScript 侧
    src/engine/config.py:build_default_config()  desktop/src/constants.ts:FALLBACK_CONFIG
    src/utils/transition_constants.py            desktop/src/constants.ts:TRANSITIONS
    src/engine/config.py:DEFAULT_VIDEO_EFFECTS   desktop/src/constants.ts:VIDEO_EFFECTS

一侧新增字段或效果、另一侧忘记同步时不会报错：参数会被 normalize 静默丢弃，
或前端出现一个后端根本不认识的选项。这里把这种漂移变成一条会失败的测试。

只做比对，不修改任何一侧的定义。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.engine.config import (
    DEFAULT_RESOLUTION_PRESETS,
    DEFAULT_VIDEO_EFFECTS,
    IMAGE_SELECTION_MODES,
    build_default_config,
)
from src.utils.transition_constants import GUI_TRANSITIONS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TS_CONSTANTS_PATH = PROJECT_ROOT / "desktop" / "src" / "constants.ts"
TS_INSPECTOR_PATH = PROJECT_ROOT / "desktop" / "src" / "components" / "Inspector.tsx"


@pytest.fixture(scope="module")
def ts_source() -> str:
    if not TS_CONSTANTS_PATH.is_file():
        pytest.skip(f"未找到前端常量文件：{TS_CONSTANTS_PATH}")
    return TS_CONSTANTS_PATH.read_text(encoding="utf-8")


def _ts_string_array(source: str, name: str) -> list[str]:
    """从 `export const NAME = [ ... ];` 中取出字符串字面量（保持原顺序）。"""
    match = re.search(rf"export const {name}\s*(?::[^=]+)?=\s*\[(.*?)\]", source, re.S)
    if not match:
        raise AssertionError(f"desktop/src/constants.ts 中找不到数组 {name}")
    return re.findall(r'"([^"]+)"', match.group(1))


def _ts_object_keys(source: str, name: str) -> set[str]:
    """从 `export const NAME: Type = { ... };` 中取出顶层键名。"""
    match = re.search(rf"export const {name}\s*(?::[^=]+)?=\s*\{{(.*?)^\}};", source, re.S | re.M)
    if not match:
        raise AssertionError(f"desktop/src/constants.ts 中找不到对象 {name}")
    return set(re.findall(r"^\s*([A-Za-z_]\w*)\s*:", match.group(1), re.M))


def test_default_config_keys_match_frontend(ts_source: str) -> None:
    """默认配置的字段名两侧必须完全一致。"""
    python_keys = set(build_default_config().keys())
    ts_keys = _ts_object_keys(ts_source, "FALLBACK_CONFIG")

    assert ts_keys, "未能从 FALLBACK_CONFIG 解析出任何字段，检查解析规则是否失效"

    only_python = sorted(python_keys - ts_keys)
    only_ts = sorted(ts_keys - python_keys)

    assert not only_python and not only_ts, (
        "默认配置字段不一致：\n"
        f"  仅 Python 有：{only_python}\n"
        f"  仅前端有：{only_ts}\n"
        "请在 src/engine/config.py:build_default_config() 与 "
        "desktop/src/constants.ts:FALLBACK_CONFIG 之间同步。"
    )


def test_transition_enum_matches_frontend(ts_source: str) -> None:
    """转场列表必须一致且顺序相同（顺序影响“第一个选项”的默认值）。"""
    ts_transitions = _ts_string_array(ts_source, "TRANSITIONS")

    assert ts_transitions, "未能从 TRANSITIONS 解析出任何条目，检查解析规则是否失效"
    assert GUI_TRANSITIONS == ts_transitions, (
        "转场列表不一致：\n"
        f"  仅 Python 有：{sorted(set(GUI_TRANSITIONS) - set(ts_transitions))}\n"
        f"  仅前端有：{sorted(set(ts_transitions) - set(GUI_TRANSITIONS))}\n"
        f"  顺序是否一致：{GUI_TRANSITIONS == ts_transitions}\n"
        "请同步 src/utils/transition_constants.py:GUI_TRANSITIONS 与 "
        "desktop/src/constants.ts:TRANSITIONS。"
    )


def test_video_effect_enum_matches_frontend(ts_source: str) -> None:
    """画面特效列表必须一致且顺序相同。"""
    ts_effects = _ts_string_array(ts_source, "VIDEO_EFFECTS")

    assert ts_effects, "未能从 VIDEO_EFFECTS 解析出任何条目，检查解析规则是否失效"
    assert DEFAULT_VIDEO_EFFECTS == ts_effects, (
        "画面特效列表不一致：\n"
        f"  仅 Python 有：{sorted(set(DEFAULT_VIDEO_EFFECTS) - set(ts_effects))}\n"
        f"  仅前端有：{sorted(set(ts_effects) - set(DEFAULT_VIDEO_EFFECTS))}\n"
        "请同步 src/engine/config.py:DEFAULT_VIDEO_EFFECTS 与 "
        "desktop/src/constants.ts:VIDEO_EFFECTS。"
    )


def test_image_selection_modes_match_frontend() -> None:
    """「选图方式」下拉的选项必须与后端常量一致，否则选了新模式会被静默当成旧模式。"""
    if not TS_INSPECTOR_PATH.is_file():
        pytest.skip(f"未找到前端配置面板：{TS_INSPECTOR_PATH}")
    source = TS_INSPECTOR_PATH.read_text(encoding="utf-8")

    match = re.search(r'label="选图方式".*?<select[^>]*>(.*?)</select>', source, re.S)
    assert match, "未能从 Inspector.tsx 中定位「选图方式」下拉，检查解析规则是否失效"

    options = re.findall(r"<option>(.*?)</option>", match.group(1))
    assert options, "「选图方式」下拉里没有解析到任何选项"
    assert options == list(IMAGE_SELECTION_MODES), (
        "选图方式选项不一致：\n"
        f"  后端：{list(IMAGE_SELECTION_MODES)}\n"
        f"  前端：{options}\n"
        "请同步 src/engine/config.py:IMAGE_SELECTION_MODES 与 "
        "desktop/src/components/Inspector.tsx 的「选图方式」下拉。"
    )


def test_resolution_presets_match_frontend(ts_source: str) -> None:
    """分辨率预设必须一致。"""
    ts_presets = _ts_string_array(ts_source, "DEFAULT_RESOLUTION_PRESETS")

    assert ts_presets, "未能从 DEFAULT_RESOLUTION_PRESETS 解析出任何条目"
    assert list(DEFAULT_RESOLUTION_PRESETS) == ts_presets, (
        "分辨率预设不一致：\n"
        f"  Python: {list(DEFAULT_RESOLUTION_PRESETS)}\n"
        f"  前端:   {ts_presets}"
    )


RUST_DEFAULT_CONFIG_PATH = (
    PROJECT_ROOT / "desktop" / "src-tauri" / "src" / "engine" / "default_config.json"
)


def test_rust_engine_default_config_matches_python() -> None:
    """Rust 引擎内嵌的默认配置必须与 `build_default_config()` 逐字段一致。

    `default_config.json` 是由 Python 导出后内嵌进 Rust 的（`include_str!`），
    这样 Rust 侧不必手写 46 个字段。代价是两边可能漂移：Python 改了默认值而 JSON
    没重新导出时，Rust 接管 `default_config` 后前端拿到的默认参数会悄悄变样。
    """
    import json

    if not RUST_DEFAULT_CONFIG_PATH.is_file():
        pytest.skip(f"未找到 Rust 默认配置：{RUST_DEFAULT_CONFIG_PATH}")

    embedded = json.loads(RUST_DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    expected = build_default_config()
    assert embedded == expected, (
        "Rust 的 default_config.json 与 build_default_config() 不一致，请重新导出：\n"
        "  python -c \"import json; from src.engine.config import build_default_config as b; "
        "open('desktop/src-tauri/src/engine/default_config.json', 'w', encoding='utf-8', newline='\\n')"
        ".write(json.dumps(b(), ensure_ascii=False, indent=1) + '\\n')\""
    )


def test_effect_lists_match_core():
    """特效列表：前端下拉 / Python 默认 / Rust 目录三方必须完全一致。

    ⚠️ 这条是补漏：`缓慢拉远`/`右下平移`/`左上平移`/`缓慢推近` 内核早就实现了，
    但前端 `VIDEO_EFFECTS` 里没有 —— 用户在下拉里根本选不到。之前的
    `catalog_parity` 只核对「目录 ↔ 实现」，没核对「目录 ↔ 界面」，所以没能发现。
    """
    import re

    root = Path(__file__).resolve().parents[1]

    ts = (root / "desktop" / "src" / "constants.ts").read_text(encoding="utf-8")
    block = re.search(r"export const VIDEO_EFFECTS[^=]*=\s*\[(.*?)\]", ts, re.S)
    assert block, "找不到前端 VIDEO_EFFECTS"
    front = re.findall(r'"([^"]+)"', block.group(1))

    rs = (root / "desktop" / "src-tauri" / "src" / "render" / "catalog.rs").read_text(encoding="utf-8")
    core_block = re.search(r"pub const EFFECTS: &\[ItemSpec\] = &\[(.*?)\n\];", rs, re.S)
    assert core_block, "找不到 Rust catalog EFFECTS"
    core = re.findall(r'id: "([^"]+)"', core_block.group(1))

    from src.engine.config import DEFAULT_VIDEO_EFFECTS

    assert front == list(DEFAULT_VIDEO_EFFECTS), (
        "前端 VIDEO_EFFECTS 与 Python DEFAULT_VIDEO_EFFECTS 不一致：\n"
        f"  仅前端有：{sorted(set(front) - set(DEFAULT_VIDEO_EFFECTS))}\n"
        f"  仅 Python 有：{sorted(set(DEFAULT_VIDEO_EFFECTS) - set(front))}"
    )
    assert set(front) == set(core), (
        "前端 VIDEO_EFFECTS 与 Rust catalog 不一致（界面选不到内核已实现的特效）：\n"
        f"  仅前端有：{sorted(set(front) - set(core))}\n"
        f"  仅内核有：{sorted(set(core) - set(front))}"
    )
