#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Turbo 加速器模块
提供图片处理和视频生成的性能优化功能
集成并行处理、缓存优化和FFmpeg管道优化
"""

import os
import time
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache, wraps
import cv2
import numpy as np
from typing import List, Dict, Any, Optional, Callable
import psutil
import gc


class TurboAccelerator:
    """Turbo 加速器 - 性能优化核心"""
    
    def __init__(self):
        self.enabled = False
        self.stats = {
            'start_time': time.time(),
            'images_processed': 0,
            'videos_created': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'memory_optimizations': 0
        }
        
        # 缓存配置
        self.image_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self.max_cache_size = 200  # 最大缓存图片数量
        self.cache_memory_limit = 800 * 1024 * 1024  # 800MB内存限制
        self.cache_bytes = 0
        self.cache_cleanup_interval = 5.0
        self.cache_cleanup_threshold = 85
        self._last_cache_cleanup = 0.0
        
        # 线程池配置
        self.max_workers = min(8, os.cpu_count() or 1)
        self.thread_pool = None
        
        # 性能监控
        self.performance_data = []
        
    def initialize(self) -> bool:
        """初始化 Turbo 加速器"""
        try:
            print("[INFO] 初始化 Turbo 加速器...")
            
            # 创建线程池
            self.thread_pool = ThreadPoolExecutor(max_workers=self.max_workers)
            
            # 系统优化
            self._optimize_system_settings()
            self._recalculate_cache_limits()
            
            self.enabled = True
            print("[OK] Turbo 加速器启用成功！")
            print(f"   - 并行处理线程: {self.max_workers}")
            print(f"   - 图片缓存容量: {self.max_cache_size}张")
            print(f"   - 内存限制: {self.cache_memory_limit // 1024 // 1024}MB")
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Turbo 加速器初始化失败: {str(e)}")
            self.enabled = False
            return False
    
    def _optimize_system_settings(self):
        """优化系统设置"""
        try:
            # OpenCV 线程优化
            cv2.setNumThreads(self.max_workers)
            
            # 内存管理优化
            gc.set_threshold(700, 10, 10)
            
            print("[OK] 系统设置优化完成")
            
        except Exception as e:
            print(f"[WARN] 系统设置优化警告: {str(e)}")

    def _recalculate_cache_limits(self):
        """根据可用内存动态调整缓存限制"""
        try:
            mem = psutil.virtual_memory()
            available = int(mem.available * 0.25)
            self.cache_memory_limit = max(256 * 1024 * 1024, min(available, 1024 * 1024 * 1024))
        except Exception:
            pass
    
    def cache_image(self, image_path: str, image: np.ndarray):
        """缓存图片"""
        if not self.enabled:
            return
            
        try:
            # 检查缓存大小限制
            if len(self.image_cache) >= self.max_cache_size:
                self._cleanup_cache()
            
            # 检查内存限制
            if self.cache_bytes > self.cache_memory_limit:
                self._cleanup_cache()
            
            # 缓存图片
            image_size = image.nbytes
            if image_path in self.image_cache:
                old = self.image_cache.pop(image_path)
                self.cache_bytes -= old.get('size', 0)

            self.image_cache[image_path] = {
                'image': image.copy(),
                'timestamp': time.time(),
                'access_count': 1,
                'size': image_size
            }
            self.cache_bytes += image_size
            self.image_cache.move_to_end(image_path)
            
        except Exception as e:
            print(f"[WARN] 图片缓存失败: {str(e)}")
    
    def get_cached_image(self, image_path: str) -> Optional[np.ndarray]:
        """获取缓存的图片"""
        if not self.enabled or image_path not in self.image_cache:
            self.stats['cache_misses'] += 1
            return None
        
        try:
            cache_entry = self.image_cache[image_path]
            cache_entry['access_count'] += 1
            cache_entry['timestamp'] = time.time()
            self.image_cache.move_to_end(image_path)
            
            self.stats['cache_hits'] += 1
            return cache_entry['image'].copy()
            
        except Exception as e:
            print(f"[WARN] 获取缓存图片失败: {str(e)}")
            self.stats['cache_misses'] += 1
            return None
    
    def _cleanup_cache(self):
        """清理缓存"""
        try:
            if not self.image_cache:
                return
            
            removed = 0
            while self.image_cache and (
                len(self.image_cache) > self.max_cache_size or self.cache_bytes > self.cache_memory_limit
            ):
                key, value = self.image_cache.popitem(last=False)
                self.cache_bytes -= value.get('size', 0)
                removed += 1
            print(f"[INFO] 缓存清理完成，移除 {removed} 项")
            
        except Exception as e:
            print(f"[WARN] 缓存清理失败: {str(e)}")

    def realtime_cleanup(self, force: bool = False):
        """实时缓存清理（轻量、带节流）"""
        if not self.enabled:
            return
        now = time.time()
        if not force and (now - self._last_cache_cleanup) < self.cache_cleanup_interval:
            return
        self._last_cache_cleanup = now
        try:
            self._recalculate_cache_limits()
            mem_percent = psutil.virtual_memory().percent
            need_cleanup = (
                force
                or mem_percent >= self.cache_cleanup_threshold
                or len(self.image_cache) > self.max_cache_size
                or self.cache_bytes > self.cache_memory_limit
            )
            if need_cleanup:
                self._cleanup_cache()
                if mem_percent >= self.cache_cleanup_threshold:
                    gc.collect()
                self.stats['memory_optimizations'] += 1
        except Exception as e:
            print(f"[WARN] 实时缓存清理失败: {str(e)}")
    
    def _get_cache_memory_usage(self) -> int:
        """获取缓存内存使用量"""
        return self.cache_bytes
    
    def parallel_image_processing(self, image_paths: List[str], 
                                processor_func: Callable, 
                                *args, **kwargs) -> List[Any]:
        """并行图片处理"""
        if not self.enabled or not self.thread_pool:
            # 回退到串行处理
            return [processor_func(path, *args, **kwargs) for path in image_paths]
        
        try:
            futures = []
            results = []
            
            # 提交任务到线程池
            for image_path in image_paths:
                future = self.thread_pool.submit(processor_func, image_path, *args, **kwargs)
                futures.append((future, image_path))
            
            # 收集结果
            for future, image_path in futures:
                try:
                    result = future.result(timeout=30)  # 30秒超时
                    results.append(result)
                    self.stats['images_processed'] += 1
                except Exception as e:
                    print(f"[WARN] 处理图片 {image_path} 失败: {str(e)}")
                    results.append(None)
            
            return results
            
        except Exception as e:
            print(f"[WARN] 并行处理失败，回退到串行: {str(e)}")
            return [processor_func(path, *args, **kwargs) for path in image_paths]
    
    def optimized_image_read(self, image_path: str) -> Optional[np.ndarray]:
        """优化的图片读取"""
        if not self.enabled:
            return cv2.imread(image_path)
        
        # 尝试从缓存获取
        cached_image = self.get_cached_image(image_path)
        if cached_image is not None:
            return cached_image
        
        # 读取图片
        try:
            # 使用numpy方法处理中文路径
            if not os.path.exists(image_path):
                return None
                
            img_array = np.fromfile(image_path, dtype=np.uint8)
            image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            
            if image is not None:
                # 缓存图片
                self.cache_image(image_path, image)
                
            return image
            
        except Exception as e:
            print(f"[WARN] 优化读取失败，使用标准方法: {str(e)}")
            return cv2.imread(image_path)
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        runtime = time.time() - self.stats['start_time']
        cache_total = self.stats['cache_hits'] + self.stats['cache_misses']
        hit_rate = (self.stats['cache_hits'] / cache_total * 100) if cache_total > 0 else 0
        
        return {
            'enabled': self.enabled,
            'runtime_hours': runtime / 3600,
            'images_processed': self.stats['images_processed'],
            'videos_created': self.stats['videos_created'],
            'cache_hit_rate': f"{hit_rate:.1f}%",
            'cache_size': len(self.image_cache),
            'cache_memory_mb': self._get_cache_memory_usage() / 1024 / 1024,
            'thread_pool_workers': self.max_workers,
            'memory_optimizations': self.stats['memory_optimizations'],
            'system_memory_percent': psutil.virtual_memory().percent,
            'system_cpu_percent': psutil.cpu_percent()
        }
    
    def force_memory_optimization(self):
        """强制内存优化"""
        try:
            # 清理缓存
            self._cleanup_cache()
            
            # 强制垃圾回收
            collected = gc.collect()
            
            self.stats['memory_optimizations'] += 1
            print(f"🧹 内存优化完成，回收 {collected} 个对象")
            
        except Exception as e:
            print(f"⚠️ 内存优化失败: {str(e)}")
    
    def cleanup(self):
        """清理资源"""
        try:
            print("🧹 清理 Turbo 加速器资源...")
            
            # 关闭线程池
            if self.thread_pool:
                self.thread_pool.shutdown(wait=True)
                self.thread_pool = None
            
            # 清理缓存
            self.image_cache.clear()
            
            # 重置状态
            self.enabled = False
            
            print("✅ Turbo 加速器资源清理完成")
            
        except Exception as e:
            print(f"⚠️ Turbo 清理失败: {str(e)}")


# 全局实例
_turbo_accelerator = None

def get_turbo_accelerator() -> TurboAccelerator:
    """获取 Turbo 加速器实例"""
    global _turbo_accelerator
    if _turbo_accelerator is None:
        _turbo_accelerator = TurboAccelerator()
    return _turbo_accelerator

def initialize_turbo() -> bool:
    """初始化 Turbo 加速器"""
    accelerator = get_turbo_accelerator()
    return accelerator.initialize()

def cleanup_turbo():
    """清理 Turbo 加速器"""
    global _turbo_accelerator
    if _turbo_accelerator:
        _turbo_accelerator.cleanup()
        _turbo_accelerator = None

def turbo_performance_decorator(func):
    """Turbo 性能装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        accelerator = get_turbo_accelerator()
        
        if not accelerator.enabled:
            return func(*args, **kwargs)
        
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            print(f"⚠️ Turbo 加速函数执行失败: {str(e)}")
            raise
        finally:
            elapsed = time.time() - start_time
            accelerator.performance_data.append({
                'function': func.__name__,
                'duration': elapsed,
                'timestamp': start_time
            })
    
    return wrapper