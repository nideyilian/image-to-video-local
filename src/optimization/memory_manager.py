#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
内存管理模块 - 优化内存使用和缓存管理
"""

import gc
import os
import sys
import time
import threading
from collections import OrderedDict
from typing import Optional, Any, Dict, List
import cv2
import numpy as np
from ..config.constants import PerformanceConfig

class ImageCache:
    """图片缓存管理器 - 使用LRU策略"""
    
    def __init__(self, max_size: int = PerformanceConfig.IMAGE_CACHE_SIZE):
        self.max_size = max_size
        self.cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self.lock = threading.RLock()
        self.hit_count = 0
        self.miss_count = 0
    
    def get(self, image_path: str) -> Optional[np.ndarray]:
        """获取缓存的图片，如果不存在则加载"""
        with self.lock:
            if image_path in self.cache:
                # 移动到末尾（最近使用）
                self.cache.move_to_end(image_path)
                self.hit_count += 1
                return self.cache[image_path].copy()  # 返回副本避免修改原始数据
            
            # 缓存未命中，加载图片
            self.miss_count += 1
            image = self._load_image(image_path)
            if image is not None:
                self._add_to_cache(image_path, image)
            return image
    
    def _load_image(self, image_path: str) -> Optional[np.ndarray]:
        """加载图片文件"""
        try:
            if not os.path.exists(image_path):
                return None
            
            image = cv2.imread(image_path)
            if image is None:
                print(f"警告: 无法加载图片 {image_path}")
                return None
            
            return image
        except Exception as e:
            print(f"加载图片失败 {image_path}: {str(e)}")
            return None
    
    def _add_to_cache(self, image_path: str, image: np.ndarray):
        """添加图片到缓存"""
        with self.lock:
            # 如果缓存已满，移除最少使用的项
            while len(self.cache) >= self.max_size:
                oldest_path, oldest_image = self.cache.popitem(last=False)
                del oldest_image  # 显式删除图片数据
            
            # 添加新图片
            self.cache[image_path] = image.copy()
    
    def clear(self):
        """清空缓存"""
        with self.lock:
            for image in self.cache.values():
                del image
            self.cache.clear()
            gc.collect()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self.lock:
            total_requests = self.hit_count + self.miss_count
            hit_rate = (self.hit_count / total_requests * 100) if total_requests > 0 else 0
            
            return {
                'cache_size': len(self.cache),
                'max_size': self.max_size,
                'hit_count': self.hit_count,
                'miss_count': self.miss_count,
                'hit_rate': f"{hit_rate:.1f}%",
                'memory_usage_mb': self._estimate_memory_usage()
            }
    
    def _estimate_memory_usage(self) -> float:
        """估算缓存内存使用量（MB）"""
        total_bytes = 0
        for image in self.cache.values():
            if image is not None:
                total_bytes += image.nbytes
        return total_bytes / (1024 * 1024)

class MemoryMonitor:
    """内存监控器"""
    
    def __init__(self):
        self.start_memory = self._get_memory_usage()
        self.peak_memory = self.start_memory
        self.last_cleanup = time.time()
    
    def _get_memory_usage(self) -> float:
        """获取当前内存使用量（MB）"""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / (1024 * 1024)
        except ImportError:
            # 如果没有psutil，使用简单的估算
            return sys.getsizeof(gc.get_objects()) / (1024 * 1024)
    
    def update(self):
        """更新内存监控信息"""
        current_memory = self._get_memory_usage()
        if current_memory > self.peak_memory:
            self.peak_memory = current_memory
        
        # 如果内存使用过高，触发清理
        if current_memory > self.start_memory * 2:  # 内存使用超过启动时的2倍
            self.cleanup_if_needed()
    
    def cleanup_if_needed(self):
        """根据需要清理内存"""
        current_time = time.time()
        if current_time - self.last_cleanup > 30:  # 至少间隔30秒
            self.force_cleanup()
            self.last_cleanup = current_time
    
    def force_cleanup(self):
        """强制清理内存"""
        # 清理numpy数组
        for obj in gc.get_objects():
            if isinstance(obj, np.ndarray):
                try:
                    del obj
                except:
                    pass
        
        # 运行垃圾回收
        collected = gc.collect()
        print(f"内存清理完成，回收了 {collected} 个对象")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取内存统计信息"""
        current_memory = self._get_memory_usage()
        return {
            'current_memory_mb': f"{current_memory:.1f}",
            'peak_memory_mb': f"{self.peak_memory:.1f}",
            'start_memory_mb': f"{self.start_memory:.1f}",
            'memory_increase_mb': f"{current_memory - self.start_memory:.1f}"
        }

class ResourceManager:
    """资源管理器 - 统一管理缓存和内存"""
    
    def __init__(self):
        self.image_cache = ImageCache()
        self.memory_monitor = MemoryMonitor()
        self.cleanup_counter = 0
        self.lock = threading.RLock()
    
    def get_image(self, image_path: str) -> Optional[np.ndarray]:
        """获取图片（通过缓存）"""
        image = self.image_cache.get(image_path)
        
        # 更新内存监控
        self.memory_monitor.update()
        
        # 定期清理检查
        self.cleanup_counter += 1
        if self.cleanup_counter >= PerformanceConfig.MEMORY_CLEANUP_INTERVAL:
            self.cleanup_counter = 0
            self._periodic_cleanup()
        
        return image
    
    def _periodic_cleanup(self):
        """定期清理"""
        with self.lock:
            # 检查内存使用情况
            stats = self.memory_monitor.get_stats()
            current_memory = float(stats['current_memory_mb'])
            start_memory = float(stats['start_memory_mb'])
            
            # 如果内存使用增长过多，清理缓存
            if current_memory > start_memory * 1.5:
                print(f"内存使用过高 ({current_memory:.1f}MB)，清理图片缓存...")
                self.image_cache.clear()
                self.memory_monitor.force_cleanup()
    
    def clear_all(self):
        """清理所有资源"""
        with self.lock:
            self.image_cache.clear()
            self.memory_monitor.force_cleanup()
            self.cleanup_counter = 0
    
    def get_full_stats(self) -> Dict[str, Any]:
        """获取完整的资源统计信息"""
        return {
            'image_cache': self.image_cache.get_stats(),
            'memory': self.memory_monitor.get_stats(),
            'cleanup_counter': self.cleanup_counter
        }

# 全局资源管理器实例
_resource_manager = None

def get_resource_manager() -> ResourceManager:
    """获取全局资源管理器实例"""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = ResourceManager()
    return _resource_manager

def cleanup_resources():
    """清理所有资源"""
    global _resource_manager
    if _resource_manager is not None:
        _resource_manager.clear_all()

def get_cached_image(image_path: str) -> Optional[np.ndarray]:
    """获取缓存的图片（便捷函数）"""
    return get_resource_manager().get_image(image_path)

def print_resource_stats():
    """打印资源使用统计"""
    stats = get_resource_manager().get_full_stats()
    
    print("\n=== 资源使用统计 ===")
    print(f"图片缓存: {stats['image_cache']['cache_size']}/{stats['image_cache']['max_size']}")
    print(f"缓存命中率: {stats['image_cache']['hit_rate']}")
    print(f"缓存内存使用: {stats['image_cache']['memory_usage_mb']:.1f}MB")
    print(f"当前内存: {stats['memory']['current_memory_mb']}MB")
    print(f"峰值内存: {stats['memory']['peak_memory_mb']}MB")
    print(f"内存增长: {stats['memory']['memory_increase_mb']}MB")
    print("==================\n")

# 上下文管理器用于自动资源清理
class ResourceContext:
    """资源上下文管理器"""
    
    def __enter__(self):
        return get_resource_manager()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            # 发生异常时强制清理
            cleanup_resources()
        return False

# 装饰器用于自动内存管理
def with_memory_management(func):
    """内存管理装饰器"""
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            # 函数执行完成后检查内存
            get_resource_manager().memory_monitor.update()
            return result
        except MemoryError:
            print("内存不足，正在清理资源...")
            cleanup_resources()
            raise
        except Exception as e:
            # 其他异常也清理资源
            cleanup_resources()
            raise
    return wrapper
