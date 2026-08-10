# -*- coding: utf-8 -*-
"""
优化模块
提供性能加速和优化功能
"""

from .turbo_accelerator import (
    TurboAccelerator,
    get_turbo_accelerator,
    initialize_turbo,
    cleanup_turbo,
    turbo_performance_decorator
)

__all__ = [
    'TurboAccelerator',
    'get_turbo_accelerator', 
    'initialize_turbo',
    'cleanup_turbo',
    'turbo_performance_decorator'
]