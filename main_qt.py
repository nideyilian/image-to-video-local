#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Qt 入口（渐进迁移）
当前默认入口，仅保留 Qt 界面链路。
"""

import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(CURRENT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


def _run_bridge_worker_from_args(argv):
    """打包后子进程入口：避免再次拉起 Qt 主窗口。"""
    if "--qt-bridge-worker" not in argv:
        return -1
    try:
        from gui_qt.tk_bridge_runner import main as bridge_main
    except Exception as exc:
        print(f"[ERROR] Qt bridge worker 启动失败: {exc}")
        return 2
    # 传递给桥接器的参数只保留其自身需要的项
    filtered = [argv[0]]
    for i, token in enumerate(argv[1:], start=1):
        if token == "--qt-bridge-worker":
            continue
        filtered.append(argv[i])
    old_argv = sys.argv
    try:
        sys.argv = filtered
        return int(bridge_main())
    finally:
        sys.argv = old_argv


def main() -> int:
    worker_code = _run_bridge_worker_from_args(sys.argv)
    if worker_code >= 0:
        return worker_code
    try:
        from gui_qt import run_qt_app
    except Exception as exc:
        print(f"[ERROR] Qt GUI 启动失败: {exc}")
        print("[HINT] 请先安装依赖: pip install PySide6")
        return 1
    return run_qt_app()


if __name__ == "__main__":
    sys.exit(main())
