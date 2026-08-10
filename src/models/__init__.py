#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
数据模型层 - 定义业务数据结构
"""

from .data_models import (
    VideoFormat,
    TransitionType,
    VideoSettings,
    ImageInfo,
    TransitionSettings,
    AudioSettings,
    WatermarkSettings,
    ProcessingOptions,
    ProcessingResult
)

__version__ = "1.0.0"
__all__ = [
    'VideoFormat',
    'TransitionType',
    'VideoSettings',
    'ImageInfo',
    'TransitionSettings', 
    'AudioSettings',
    'WatermarkSettings',
    'ProcessingOptions',
    'ProcessingResult'
]