#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
图形用户界面模块 - 精简版
"""

# 导入主窗口
try:
    from .main_window import MultiTabApp
except ImportError:
    MultiTabApp = None

__version__ = "3.0.0"
__all__ = ['MultiTabApp']
