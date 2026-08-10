#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
数据模型定义
支持类型检查和数据验证
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union
from pathlib import Path
from enum import Enum
from utils.transition_constants import TransitionEffect as TransitionType

class VideoFormat(Enum):
    """视频格式枚举"""
    MP4 = "mp4"
    AVI = "avi"
    MOV = "mov"
    MKV = "mkv"

@dataclass
class VideoSettings:
    """视频设置数据模型"""
    fps: int = 30
    duration: float = 3.0
    transition_duration: float = 1.0
    bitrate: str = "5000k"
    resolution: str = "1920x1080"
    format: VideoFormat = VideoFormat.MP4
    codec: str = "libx264"
    
    def __post_init__(self):
        """数据验证"""
        if self.fps <= 0 or self.fps > 120:
            raise ValueError("FPS必须在1-120之间")
        if self.duration <= 0:
            raise ValueError("持续时间必须大于0")
        if self.transition_duration < 0:
            raise ValueError("转场时间不能小于0")

@dataclass
class ImageInfo:
    """图片信息数据模型"""
    path: Path
    width: int
    height: int
    format: str
    size_bytes: int
    
    @property
    def aspect_ratio(self) -> float:
        """宽高比"""
        return self.width / self.height if self.height > 0 else 1.0

@dataclass
class TransitionSettings:
    """转场设置数据模型"""
    type: TransitionType = TransitionType.FADE
    duration: float = 1.0
    enabled: bool = True
    parameters: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AudioSettings:
    """音频设置数据模型"""
    enabled: bool = False
    background_music_path: Optional[Path] = None
    volume: float = 0.5
    loop: bool = True
    fade_in: float = 0.0
    fade_out: float = 0.0
    
    def __post_init__(self):
        """数据验证"""
        if not 0.0 <= self.volume <= 1.0:
            raise ValueError("音量必须在0.0-1.0之间")

@dataclass
class WatermarkSettings:
    """水印设置数据模型"""
    enabled: bool = False
    image_path: Optional[Path] = None
    position: str = "bottom-right"  # top-left, top-right, bottom-left, bottom-right, center
    opacity: float = 0.8
    scale: float = 0.1
    
    def __post_init__(self):
        """数据验证"""
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError("透明度必须在0.0-1.0之间")
        if not 0.0 < self.scale <= 1.0:
            raise ValueError("缩放比例必须在0.0-1.0之间")

@dataclass
class ProcessingOptions:
    """处理选项数据模型"""
    video_settings: VideoSettings = field(default_factory=VideoSettings)
    transition_settings: TransitionSettings = field(default_factory=TransitionSettings)
    audio_settings: AudioSettings = field(default_factory=AudioSettings)
    watermark_settings: WatermarkSettings = field(default_factory=WatermarkSettings)
    output_path: Optional[Path] = None
    temp_dir: Optional[Path] = None
    enable_optimization: bool = True
    parallel_processing: bool = True
    max_workers: int = 4

@dataclass
class ProcessingResult:
    """处理结果数据模型"""
    success: bool
    output_path: Optional[Path] = None
    error_message: Optional[str] = None
    processing_time: float = 0.0
    stats: Dict[str, Any] = field(default_factory=dict)
