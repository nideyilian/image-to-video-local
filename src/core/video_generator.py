#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
统一视频生成器 - 整合所有视频生成功能
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

class VideoGenerator:
    """统一的视频生成器"""
    
    def __init__(self, config_manager, memory_manager, error_handler):
        self.config = config_manager
        self.memory = memory_manager
        self.error_handler = error_handler
        
        # 延迟导入避免循环依赖
        self._image_processor = None
        self._transition_engine = None
    
    @property
    def image_processor(self):
        if self._image_processor is None:
            from .image_processor import ImageProcessor
            self._image_processor = ImageProcessor(self.config)
        return self._image_processor
    
    @property
    def transition_engine(self):
        if self._transition_engine is None:
            from .transition_engine import TransitionEngine
            self._transition_engine = TransitionEngine(self.config)
        return self._transition_engine
    
    def generate_video(self, images: List[str], output_path: str, **options) -> bool:
        """
        统一的视频生成接口
        
        Args:
            images: 图片路径列表
            output_path: 输出视频路径
            **options: 生成选项
        
        Returns:
            bool: 生成是否成功
        """
        try:
            # 预处理图片
            processed_images = self.image_processor.process_images(images, **options)
            
            # 生成转场
            if options.get('enable_transitions', True):
                transition_frames = self.transition_engine.generate_transitions(
                    processed_images, **options
                )
            else:
                transition_frames = processed_images
            
            # 编码视频
            return self._encode_video(transition_frames, output_path, **options)
            
        except Exception as e:
            self.error_handler.handle_error(e, "视频生成")
            return False
    
    def _encode_video(self, frames, output_path: str, **options) -> bool:
        """编码视频为文件"""
        from ..utils.opencv_silent import import_cv2_silent

        cv2 = import_cv2_silent()
        from pathlib import Path

        if not frames or len(frames) == 0:
            return False

        fps = options.get("fps", 30)
        codec = options.get("codec", "mp4v")
        fourcc = cv2.VideoWriter_fourcc(*codec)
        h, w = frames[0].shape[:2]

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        writer = cv2.VideoWriter(str(output_path), fourcc, float(fps), (w, h))
        if not writer.isOpened():
            return False

        try:
            for frame in frames:
                writer.write(frame)
            return True
        finally:
            writer.release()
