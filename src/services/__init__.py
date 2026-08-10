#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
服务层模块 - 业务逻辑处理
"""

__version__ = "1.0.0"
__all__ = [
    'ImageProcessingService',
    'VideoGenerationService'
]


def __getattr__(name):
    """Keep desktop imports compatible without loading GUI-oriented services eagerly."""
    if name == "ImageProcessingService":
        from .image_service import ImageProcessingService
        return ImageProcessingService
    if name == "VideoGenerationService":
        from .video_service import VideoGenerationService
        return VideoGenerationService
    raise AttributeError(name)
