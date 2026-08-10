#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
统一图片处理器 - 整合所有图片处理功能
"""

from typing import List, Dict, Any, Optional
import logging
import numpy as np

logger = logging.getLogger(__name__)

class ImageProcessor:
    """统一的图片处理器"""
    
    def __init__(self, config_manager):
        self.config = config_manager
        
        # 延迟导入
        self._cache = None
        self._loader = None
    
    @property
    def cache(self):
        if self._cache is None:
            from ..optimization.cache.image_cache import ImageCache
            self._cache = ImageCache(self.config)
        return self._cache
    
    @property
    def loader(self):
        if self._loader is None:
            from ..optimization.async_processing.image_loader import AsyncImageLoader
            self._loader = AsyncImageLoader(self.config)
        return self._loader
    
    def process_images(self, image_paths, **options):
        """预处理图片列表 - 加载并调整尺寸"""
        from ..utils.opencv_silent import import_cv2_silent

        cv2 = import_cv2_silent()
        from pathlib import Path

        target_size = tuple(options.get("target_size", (1920, 1080)))
        processed = []

        for path in image_paths:
            try:
                img = cv2.imread(str(Path(path)))
                if img is None:
                    continue
                if img.shape[1] != target_size[0] or img.shape[0] != target_size[1]:
                    img = cv2.resize(img, target_size, interpolation=cv2.INTER_AREA)
                processed.append(img)
            except Exception as e:
                logger.warning(f"图片处理失败: {path} - {e}")
                continue

        return processed
