#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
异步图片加载器 - 高优先级优化实施
实现并行图片预取、智能缓存和批量处理优化
"""

import asyncio
import threading
import time
import os
from typing import List, Dict, Any, Optional, Callable, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import cv2
from collections import OrderedDict, deque
from dataclasses import dataclass

@dataclass
class LoadTask:
    """加载任务"""
    path: str
    priority: int = 0
    callback: Optional[Callable] = None
    timestamp: float = 0
    
    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = time.time()

class ImageCache:
    """智能图片缓存"""
    
    def __init__(self, max_size: int = 200, max_memory_mb: int = 500):
        self.max_size = max_size
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.cache = OrderedDict()
        self.memory_usage = 0
        self.access_count = {}
        self.access_time = {}
        self.lock = threading.RLock()
        
        # 统计信息
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'total_loaded': 0
        }
    
    def get(self, key: str) -> Optional[np.ndarray]:
        """获取缓存的图片"""
        with self.lock:
            if key in self.cache:
                # 更新访问信息
                self.access_count[key] = self.access_count.get(key, 0) + 1
                self.access_time[key] = time.time()
                
                # 移到最后（LRU）
                self.cache.move_to_end(key)
                
                self.stats['hits'] += 1
                return self.cache[key].copy()  # 返回副本避免修改原始数据
            
            self.stats['misses'] += 1
            return None
    
    def put(self, key: str, image: np.ndarray):
        """添加图片到缓存"""
        with self.lock:
            if key in self.cache:
                # 更新现有项
                old_size = self.cache[key].nbytes
                self.memory_usage -= old_size
            
            # 检查内存限制
            image_size = image.nbytes
            while (self.memory_usage + image_size > self.max_memory_bytes or 
                   len(self.cache) >= self.max_size):
                if not self.cache:
                    break
                self._evict_one()
            
            # 添加新项
            self.cache[key] = image.copy()
            self.memory_usage += image_size
            self.access_count[key] = 1
            self.access_time[key] = time.time()
            self.stats['total_loaded'] += 1
    
    def _evict_one(self):
        """驱逐一个缓存项"""
        if not self.cache:
            return
        
        # 使用LFU + LRU混合策略
        # 优先驱逐访问次数少且时间久的项
        min_score = float('inf')
        evict_key = None
        current_time = time.time()
        
        for key in self.cache:
            access_freq = self.access_count.get(key, 1)
            time_since_access = current_time - self.access_time.get(key, current_time)
            
            # 计算驱逐分数（越小越容易被驱逐）
            score = access_freq / (1 + time_since_access / 3600)  # 按小时衰减
            
            if score < min_score:
                min_score = score
                evict_key = key
        
        if evict_key:
            evicted_image = self.cache.pop(evict_key)
            self.memory_usage -= evicted_image.nbytes
            self.access_count.pop(evict_key, None)
            self.access_time.pop(evict_key, None)
            self.stats['evictions'] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self.lock:
            total_requests = self.stats['hits'] + self.stats['misses']
            hit_rate = (self.stats['hits'] / total_requests * 100) if total_requests > 0 else 0
            
            return {
                'cache_size': len(self.cache),
                'max_size': self.max_size,
                'memory_usage_mb': self.memory_usage / (1024 * 1024),
                'max_memory_mb': self.max_memory_bytes / (1024 * 1024),
                'hit_rate': f"{hit_rate:.1f}%",
                **self.stats
            }
    
    def clear(self):
        """清空缓存"""
        with self.lock:
            self.cache.clear()
            self.memory_usage = 0
            self.access_count.clear()
            self.access_time.clear()

class AsyncImageLoader:
    """异步图片加载器"""
    
    def __init__(self, max_workers: int = 8, cache_size: int = 200, cache_memory_mb: int = 500):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.cache = ImageCache(cache_size, cache_memory_mb)
        
        # 任务队列和预取队列
        self.task_queue = asyncio.Queue()
        self.prefetch_queue = deque()
        
        # 加载统计
        self.stats = {
            'total_loaded': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'load_time_total': 0.0,
            'parallel_loads': 0
        }
        
        # 预取线程
        self.prefetch_thread = threading.Thread(target=self._prefetch_worker, daemon=True)
        self.prefetch_thread.start()
        
        print(f"🚀 异步图片加载器已启动 (工作线程: {max_workers})")
    
    def load_image_sync(self, path: str) -> Optional[np.ndarray]:
        """同步加载单张图片"""
        # 首先检查缓存
        cached_image = self.cache.get(path)
        if cached_image is not None:
            self.stats['cache_hits'] += 1
            return cached_image
        
        self.stats['cache_misses'] += 1
        
        # 从磁盘加载
        start_time = time.time()
        image = self._load_image_from_disk(path)
        load_time = time.time() - start_time
        
        if image is not None:
            # 添加到缓存
            self.cache.put(path, image)
            
            # 更新统计
            self.stats['total_loaded'] += 1
            self.stats['load_time_total'] += load_time
            
            return image
        
        return None
    
    async def load_image_async(self, path: str) -> Optional[np.ndarray]:
        """异步加载单张图片"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self.load_image_sync, path)
    
    async def load_images_batch(self, paths: List[str], 
                               progress_callback: Optional[Callable] = None) -> List[Optional[np.ndarray]]:
        """异步批量加载图片"""
        if not paths:
            return []
        
        start_time = time.time()
        
        # 检查缓存中已有的图片
        cached_results = {}
        uncached_paths = []
        
        for path in paths:
            cached_image = self.cache.get(path)
            if cached_image is not None:
                cached_results[path] = cached_image
                self.stats['cache_hits'] += 1
            else:
                uncached_paths.append(path)
                self.stats['cache_misses'] += 1
        
        # 并行加载未缓存的图片
        if uncached_paths:
            self.stats['parallel_loads'] += 1
            
            # 创建加载任务
            loop = asyncio.get_event_loop()
            tasks = [
                loop.run_in_executor(self.executor, self._load_image_from_disk, path)
                for path in uncached_paths
            ]
            
            # 等待所有任务完成，同时更新进度
            loaded_images = []
            completed = 0
            
            for task in asyncio.as_completed(tasks):
                image = await task
                loaded_images.append(image)
                completed += 1
                
                # 更新进度
                if progress_callback:
                    progress = (len(cached_results) + completed) / len(paths) * 100
                    progress_callback(progress)
            
            # 将加载的图片添加到缓存
            for path, image in zip(uncached_paths, loaded_images):
                if image is not None:
                    self.cache.put(path, image)
                    cached_results[path] = image
        
        # 按原始顺序返回结果
        results = []
        for path in paths:
            results.append(cached_results.get(path))
        
        # 更新统计
        load_time = time.time() - start_time
        self.stats['load_time_total'] += load_time
        self.stats['total_loaded'] += len([r for r in results if r is not None])
        
        return results
    
    def _load_image_from_disk(self, path: str) -> Optional[np.ndarray]:
        """从磁盘加载图片"""
        try:
            # 检查文件是否存在
            if not os.path.exists(path):
                return None
            
            # 使用支持中文路径的读取方法
            try:
                from turbo_image_processor import imread_unicode
                image = imread_unicode(path)
            except ImportError:
                # 备用方法
                image = cv2.imread(path)
            
            return image
            
        except Exception as e:
            print(f"加载图片失败 {path}: {str(e)}")
            return None
    
    def prefetch_images(self, paths: List[str], priority: int = 0):
        """预取图片到缓存"""
        for path in paths:
            if self.cache.get(path) is None:  # 只预取未缓存的图片
                task = LoadTask(path=path, priority=priority)
                self.prefetch_queue.append(task)
    
    def _prefetch_worker(self):
        """预取工作线程"""
        while True:
            try:
                if self.prefetch_queue:
                    # 按优先级排序
                    tasks = list(self.prefetch_queue)
                    tasks.sort(key=lambda t: (-t.priority, t.timestamp))
                    self.prefetch_queue.clear()
                    
                    # 预取前几个高优先级任务
                    for task in tasks[:5]:  # 限制并发预取数量
                        if self.cache.get(task.path) is None:
                            image = self._load_image_from_disk(task.path)
                            if image is not None:
                                self.cache.put(task.path, image)
                                if task.callback:
                                    task.callback(task.path, image)
                
                time.sleep(0.1)  # 避免过度占用CPU
                
            except Exception as e:
                print(f"预取工作线程异常: {str(e)}")
                time.sleep(1)
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计信息"""
        cache_stats = self.cache.get_stats()
        
        avg_load_time = (
            self.stats['load_time_total'] / self.stats['total_loaded']
            if self.stats['total_loaded'] > 0 else 0
        )
        
        return {
            'loader_stats': {
                'total_loaded': self.stats['total_loaded'],
                'parallel_loads': self.stats['parallel_loads'],
                'avg_load_time_ms': avg_load_time * 1000,
                'images_per_second': 1 / avg_load_time if avg_load_time > 0 else 0,
                'prefetch_queue_size': len(self.prefetch_queue)
            },
            'cache_stats': cache_stats
        }
    
    def optimize_cache(self):
        """优化缓存"""
        # 清理访问频率低的缓存项
        current_time = time.time()
        to_remove = []
        
        with self.cache.lock:
            for key in self.cache.cache:
                last_access = self.cache.access_time.get(key, 0)
                if current_time - last_access > 3600:  # 1小时未访问
                    access_count = self.cache.access_count.get(key, 0)
                    if access_count < 2:  # 访问次数少
                        to_remove.append(key)
            
            for key in to_remove:
                if key in self.cache.cache:
                    evicted_image = self.cache.cache.pop(key)
                    self.cache.memory_usage -= evicted_image.nbytes
                    self.cache.access_count.pop(key, None)
                    self.cache.access_time.pop(key, None)
                    self.cache.stats['evictions'] += 1
        
        print(f"🧹 缓存优化完成，清理了 {len(to_remove)} 个低频访问项")
    
    def cleanup(self):
        """清理加载器"""
        print("🧹 清理异步图片加载器...")
        
        # 清空预取队列
        self.prefetch_queue.clear()
        
        # 清空缓存
        self.cache.clear()
        
        # 关闭线程池
        self.executor.shutdown(wait=True)
        
        print("✅ 异步图片加载器清理完成")

# 全局加载器实例
_global_image_loader = None
_loader_lock = threading.Lock()

def get_image_loader() -> AsyncImageLoader:
    """获取全局图片加载器实例"""
    global _global_image_loader
    with _loader_lock:
        if _global_image_loader is None:
            _global_image_loader = AsyncImageLoader()
        return _global_image_loader

def cleanup_image_loader():
    """清理全局图片加载器"""
    global _global_image_loader
    with _loader_lock:
        if _global_image_loader:
            _global_image_loader.cleanup()
            _global_image_loader = None

if __name__ == "__main__":
    # 测试代码
    import asyncio
    
    async def test_async_loader():
        loader = get_image_loader()
        
        # 创建测试图片路径
        test_paths = [f"test_image_{i}.jpg" for i in range(10)]
        
        # 测试批量加载
        print("开始批量加载测试...")
        start_time = time.time()
        
        def progress_callback(progress):
            print(f"加载进度: {progress:.1f}%")
        
        results = await loader.load_images_batch(test_paths, progress_callback)
        
        load_time = time.time() - start_time
        print(f"批量加载完成，耗时: {load_time:.2f}秒")
        
        # 显示统计信息
        stats = loader.get_performance_stats()
        print("性能统计:", stats)
    
    # 运行测试
    # asyncio.run(test_async_loader())
