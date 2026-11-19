# -*- coding: utf-8 -*-
"""对比 Rust 与 Python 的编码器/容器决策。

用法：
    python tools/render_codec_parity_rs.py <rust.json>

rust.json 由 `ITV_CODEC_PARITY=1 cargo test parity_dump_codec -- --nocapture`
的 `CODEC_PARITY=` 行导出。本脚本用同一批输入跑 `src/render/codec.py`，逐项比对。
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.render import codec as cd  # noqa: E402


PATHS = ["a.mp4", "b.MKV", "c.mov", "d.avi", "e.webm", "f.ts", "no_ext", "g.MP4"]
SELECTED = ["XVID", "H264", "MJPG", "mp4v", "不存在的编码器"]


def python_side() -> dict:
    out = {}
    for path in PATHS:
        out[f"ext|{path}"] = cd.get_output_extension(path)
        out[f"temp|{path}"] = cd.build_temp_output_path(path, "_tmp")
        out[f"muxer|{path}"] = cd.get_ffmpeg_muxer_for_output(path)
        out[f"acod|{path}"] = cd.get_container_compatible_acodec(path)
        for selected in SELECTED:
            ctx = cd.CodecContext(codec_provider=lambda s=selected: s)
            out[f"vcodec|{path}|{selected}"] = cd.get_ffmpeg_vcodec(ctx)
            out[f"strict|{path}|{selected}"] = cd.get_strict_ffmpeg_vcodec_for_output(path, ctx)
    for path in ["a.mp4", "b.MKV", "d.avi"]:
        for preferred in (None, "libx264", "libxvid"):
            out[f"cands|{path}|{preferred!r}"] = cd.get_container_compatible_vcodecs(
                path, preferred
            )
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    with open(sys.argv[1], encoding="utf-8") as handle:
        rust = json.load(handle)
    py = python_side()

    # Rust 用 Option 的 Debug 形态（None / Some("x")），Python 那边是 None / 'x'
    normalized = {}
    for key, value in rust.items():
        if key.startswith("cands|"):
            normalized[key] = value
        else:
            normalized[key] = value
    py_norm = {}
    for key, value in py.items():
        if key.startswith("cands|"):
            py_norm[key] = list(value)
            continue
        py_norm[key] = value

    # 键名里的 preferred 表示法对齐：Python 侧 (None, 'libx264') → Rust 侧 (None, Some("libx264"))
    def canon(key: str) -> str:
        return (
            key.replace("(None,", "(None,")
            .replace("'libx264'", 'Some("libx264")')
            .replace("'libxvid'", 'Some("libxvid")')
        )

    py_norm = {canon(k): v for k, v in py_norm.items()}

    only_rust = sorted(set(normalized) - set(py_norm))
    only_py = sorted(set(py_norm) - set(normalized))
    diffs = []
    for key in sorted(set(normalized) & set(py_norm)):
        if normalized[key] != py_norm[key]:
            diffs.append((key, normalized[key], py_norm[key]))

    print(f"用例数 rust={len(normalized)} py={len(py_norm)}")
    if only_rust:
        print("仅 Rust 有:", only_rust[:8])
    if only_py:
        print("仅 Python 有:", only_py[:8])
    if diffs:
        print(f"不一致 {len(diffs)} 项：")
        for key, rs, py_val in diffs[:20]:
            print(f"  {key}\n    rust={rs!r}\n    py  ={py_val!r}")
        return 1
    print("RESULT: IDENTICAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())