#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CLI：mp4/mov box 级“去假轨”——删除 text/章节轨及其 chap 引用（无损）。

实现位于 src/engine/mp4_strip.py（桌面版素材库「体检清洗」与
tools/clean_fake_tracks.py 共用同一实现，避免逻辑漂移）。

用法：
    python tools/mp4_strip_taint.py <输入.mp4> <输出.mp4> [轨道序号...]

示例（删除序号为 2 的假字幕轨）：
    python tools/mp4_strip_taint.py in.mp4 out.mp4 2
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.engine.mp4_strip import strip_tainted_tracks  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: python tools/mp4_strip_taint.py <输入.mp4> <输出.mp4> [轨道序号...]")
        return 1
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    indexes = {int(value) for value in sys.argv[3:]} if len(sys.argv) > 3 else {2}
    ok, message = strip_tainted_tracks(source, indexes, target)
    print(("成功: " if ok else "失败: ") + message)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
