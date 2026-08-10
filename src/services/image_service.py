#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
图片处理服务
提供统一的图片处理接口，支持批量处理和缓存
"""

import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import cv2
import numpy as np
from PIL import Image

from ..models import ImageInfo, ProcessingOptions
from ..exceptions import ImageProcessingError, ResourceNotFoundError

logger = logging.getLogger(__name__)


class ImageProcessingService:
    """图片处理服务"""

    def __init__(self, cache_enabled: bool = True, max_cache_size: int = 100):
        self.cache_enabled = cache_enabled
        self.max_cache_size = max_cache_size
        self._info_cache: Dict[str, ImageInfo] = {}

    @property
    def _accelerator(self):
        """延迟获取 TurboAccelerator 实例（避免循环导入）"""
        try:
            from ..optimization.turbo_accelerator import get_turbo_accelerator
            return get_turbo_accelerator()
        except Exception:
            return None

    def get_image_info(self, image_path: Path) -> ImageInfo:
        """获取图片信息

        Args:
            image_path: 图片路径

        Returns:
            ImageInfo: 图片信息对象

        Raises:
            ResourceNotFoundError: 图片文件不存在
            ImageProcessingError: 图片信息获取失败
        """
        if not image_path.exists():
            raise ResourceNotFoundError(f"图片文件不存在: {image_path}")

        cache_key = str(image_path)
        if cache_key in self._info_cache:
            return self._info_cache[cache_key]

        try:
            with Image.open(image_path) as img:
                width, height = img.size
                format_name = img.format or 'UNKNOWN'

            size_bytes = image_path.stat().st_size

            info = ImageInfo(
                path=image_path,
                width=width,
                height=height,
                format=format_name,
                size_bytes=size_bytes
            )

            if self.cache_enabled and len(self._info_cache) < self.max_cache_size:
                self._info_cache[cache_key] = info

            return info

        except Exception as e:
            raise ImageProcessingError(f"获取图片信息失败: {e}")

    def load_image(self, image_path: Path, target_size: Optional[tuple] = None) -> np.ndarray:
        """加载图片为numpy数组

        优先使用 TurboAccelerator 缓存（LRU + 内存限制），
        避免与加速器层重复维护两份图片缓存。

        Args:
            image_path: 图片路径
            target_size: 目标尺寸 (width, height)，None表示保持原始尺寸

        Returns:
            np.ndarray: 图片数组 (BGR格式)

        Raises:
            ResourceNotFoundError: 图片文件不存在
            ImageProcessingError: 图片加载失败
        """
        if not image_path.exists():
            raise ResourceNotFoundError(f"图片文件不存在: {image_path}")

        try:
            # 优先从 TurboAccelerator 缓存获取原始图片
            img = None
            acc = self._accelerator
            if acc and acc.enabled:
                cached = acc.get_cached_image(str(image_path))
                if cached is not None:
                    img = cached

            # 缓存未命中，直接读取
            if img is None:
                img = cv2.imread(str(image_path))
                if img is None:
                    raise ImageProcessingError(f"无法加载图片: {image_path}")

                # 写入 TurboAccelerator 缓存
                if acc and acc.enabled:
                    acc.cache_image(str(image_path), img)

            # 调整尺寸
            if target_size:
                h, w = img.shape[:2]
                if w != target_size[0] or h != target_size[1]:
                    img = cv2.resize(img, target_size, interpolation=cv2.INTER_LANCZOS4)

            return img

        except ImageProcessingError:
            raise
        except Exception as e:
            raise ImageProcessingError(f"图片加载失败: {e}")

    def batch_load_images(
        self,
        image_paths: List[Path],
        target_size: Optional[tuple] = None,
        max_workers: int = 4
    ) -> List[np.ndarray]:
        """批量并行加载图片

        使用 ThreadPoolExecutor 替代 asyncio，与项目中其他模块的并发模型保持一致。

        Args:
            image_paths: 图片路径列表
            target_size: 目标尺寸
            max_workers: 最大并发数

        Returns:
            List[np.ndarray]: 图片数组列表（失败项为 None）
        """
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(self.load_image, path, target_size): path
                for path in image_paths
            }
            for future in as_completed(future_map):
                try:
                    results.append(future.result())
                except Exception as e:
                    logger.error(f"加载图片失败 {future_map[future]}: {e}")
                    results.append(None)
        return results

    def resize_image(
        self,
        image: np.ndarray,
        target_size: tuple,
        keep_aspect_ratio: bool = True
    ) -> np.ndarray:
        """调整图片尺寸

        Args:
            image: 输入图片
            target_size: 目标尺寸 (width, height)
            keep_aspect_ratio: 是否保持宽高比

        Returns:
            np.ndarray: 调整后的图片
        """
        if not keep_aspect_ratio:
            return cv2.resize(image, target_size, interpolation=cv2.INTER_LANCZOS4)

        h, w = image.shape[:2]
        target_w, target_h = target_size

        scale = min(target_w / w, target_h / h)
        new_w = int(w * scale)
        new_h = int(h * scale)

        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

        canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        y_offset = (target_h - new_h) // 2
        x_offset = (target_w - new_w) // 2
        canvas[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized

        return canvas

    def clear_cache(self):
        """清理所有缓存（含 TurboAccelerator）"""
        self._info_cache.clear()
        try:
            acc = self._accelerator
            if acc and acc.enabled:
                acc.image_cache.clear()
                acc.cache_bytes = 0
        except Exception:
            pass
        logger.info("图片缓存已清理")

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        stats = {
            'info_cache_size': len(self._info_cache),
            'max_cache_size': self.max_cache_size,
            'cache_enabled': self.cache_enabled
        }
        try:
            acc = self._accelerator
            if acc and acc.enabled:
                stats['image_cache_size'] = len(acc.image_cache)
                stats['cache_memory_mb'] = round(acc.cache_bytes / 1024 / 1024, 1)
            else:
                stats['image_cache_size'] = 0
        except Exception:
            stats['image_cache_size'] = 0
        return stats