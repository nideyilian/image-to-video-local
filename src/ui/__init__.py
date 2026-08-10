#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
用户界面模块
组件化UI架构，降低GUI复杂度
"""

from .components.settings_panel import SettingsPanel
from .components.progress_bar import ProgressBar
from .components.file_browser import FileBrowser
from .widgets.image_preview import ImagePreview
from .dialogs.about_dialog import AboutDialog

__version__ = "2.1.0"
__all__ = [
    'SettingsPanel',
    'ProgressBar', 
    'FileBrowser',
    'ImagePreview',
    'AboutDialog'
]