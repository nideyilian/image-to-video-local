#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
业务异常定义
根据项目规范：开发新功能时，需要确保功能是可选的，并且不能影响到其他无关功能
"""

class ImageToVideoError(Exception):
    """图片转视频基础异常类"""
    def __init__(self, message: str, error_code: str = None, details: dict = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

class ImageProcessingError(ImageToVideoError):
    """图片处理异常"""
    pass

class VideoGenerationError(ImageToVideoError):
    """视频生成异常"""
    pass

class TransitionError(ImageToVideoError):
    """转场效果异常"""
    pass

class ConfigurationError(ImageToVideoError):
    """配置错误异常"""
    pass

class ResourceNotFoundError(ImageToVideoError):
    """资源未找到异常"""
    pass

class MemoryError(ImageToVideoError):
    """内存不足异常"""
    pass

class FFmpegError(ImageToVideoError):
    """FFmpeg处理异常"""
    pass