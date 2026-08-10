#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
自定义异常模块 - 定义业务异常类型
"""

from .business_exceptions import (
    ImageToVideoError,
    ImageProcessingError,
    VideoGenerationError,
    TransitionError,
    ConfigurationError,
    ResourceNotFoundError,
    MemoryError,
    FFmpegError
)

__version__ = "1.0.0"
__all__ = [
    'ImageToVideoError',
    'ImageProcessingError', 
    'VideoGenerationError',
    'TransitionError',
    'ConfigurationError',
    'ResourceNotFoundError',
    'MemoryError',
    'FFmpegError'
]