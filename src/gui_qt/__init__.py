#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
PySide6 GUI 模块（渐进迁移版本）

注意：PySide6 是重量级桌面依赖，引擎 worker（Tk 管线）不应加载它。
因此 run_qt_app 采用惰性导入，仅当真正启动 Qt 界面时才引入 PySide6。
"""


def run_qt_app(*args, **kwargs):
    from .app import run_qt_app as _run_qt_app

    return _run_qt_app(*args, **kwargs)


__all__ = ["run_qt_app"]
