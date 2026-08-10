#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
高级内存管理器 - 高优先级优化实施
实现对象池、智能垃圾回收和内存监控
"""

import gc
import sys
import time
import threading
import weakref
import psutil
import numpy as np
import cv2
from typing import Dict, Any, Optional, List, Callable
from collections import defaultdict, deque
from dataclasses import dataclass

@dataclass
class MemoryStats:
    """内存统计信息"""
    total_allocated: int = 0
    total_freed: int = 0
    current_usage: int = 0
    peak_usage: int = 0
    gc_collections: int = 0
    pool_hits: int = 0
    pool_misses: int = 0

class ObjectPool:
    """通用对象池"""
    
    def __init__(self, factory_func: Callable, max_size: int = 50):
        self.factory_func = factory_func
        self.max_size = max_size
        self.pool = deque()
        self.in_use = set()
        self.lock = threading.RLock()
        self.stats = {'hits': 0, 'misses': 0, 'created': 0}
    
    def acquire(self, *args, **kwargs):
        """获取对象"""
        with self.lock:
            if self.pool:
                obj = self.pool.popleft()
                self.in_use.add(id(obj))
                self.stats['hits'] += 1
                return obj
            else:
                obj = self.factory_func(*args, **kwargs)
                self.in_use.add(id(obj))
                self.stats['misses'] += 1
                self.stats['created'] += 1
                return obj
    
    def release(self, obj):
        """释放对象"""
        with self.lock:
            obj_id = id(obj)
            if obj_id in self.in_use:
                self.in_use.remove(obj_id)
                if len(self.pool) < self.max_size:
                    # 重置对象状态
                    self._reset_object(obj)
                    self.pool.append(obj)
                else:
                    # 池已满，直接丢弃
                    del obj
    
    def _reset_object(self, obj):
        """重置对象状态"""
        if isinstance(obj, np.ndarray):
            obj.fill(0)  # 清零数组
        # 可以根据对象类型添加更多重置逻辑
    
    def get_stats(self) -> Dict[str, int]:
        """获取池统计信息"""
        with self.lock:
            return {
                'pool_size': len(self.pool),
                'in_use': len(self.in_use),
                'max_size': self.max_size,
                **self.stats
            }

class AdvancedMemoryManager:
    """高级内存管理器"""
    
    def __init__(self, max_memory_mb: int = 1000):
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.stats = MemoryStats()
        self.pools = {}
        self.weak_refs = weakref.WeakValueDictionary()
        self.memory_pressure_callbacks = []
        self.lock = threading.RLock()
        
        # 创建常用对象池
        self._create_standard_pools()
        
        # 启动内存监控线程
        self.monitor_thread = threading.Thread(target=self._memory_monitor, daemon=True)
        self.monitor_thread.start()
        
        print("🧠 高级内存管理器已启动")
    
    def _create_standard_pools(self):
        """创建标准对象池"""
        # 图片缓冲区池
        self.pools['image_small'] = ObjectPool(
            lambda: np.zeros((480, 640, 3), dtype=np.uint8), max_size=20
        )
        self.pools['image_medium'] = ObjectPool(
            lambda: np.zeros((720, 1280, 3), dtype=np.uint8), max_size=15
        )
        self.pools['image_large'] = ObjectPool(
            lambda: np.zeros((1080, 1920, 3), dtype=np.uint8), max_size=10
        )
        
        # 临时数组池
        self.pools['temp_arrays'] = ObjectPool(
            lambda size: np.zeros(size, dtype=np.uint8), max_size=30
        )
    
    def allocate_image_buffer(self, height: int, width: int, channels: int = 3) -> np.ndarray:
        """分配图片缓冲区"""
        size = height * width * channels
        
        # 根据大小选择合适的池
        if size <= 480 * 640 * 3:
            pool_key = 'image_small'
        elif size <= 720 * 1280 * 3:
            pool_key = 'image_medium'
        elif size <= 1080 * 1920 * 3:
            pool_key = 'image_large'
        else:
            # 超大图片，直接分配
            return np.zeros((height, width, channels), dtype=np.uint8)
        
        buffer = self.pools[pool_key].acquire()
        
        # 如果尺寸不匹配，重新调整
        if buffer.shape != (height, width, channels):
            buffer = cv2.resize(buffer, (width, height))
            if channels == 3 and len(buffer.shape) == 2:
                buffer = cv2.cvtColor(buffer, cv2.COLOR_GRAY2BGR)
        
        self.stats.total_allocated += buffer.nbytes
        self.stats.current_usage += buffer.nbytes
        self.stats.peak_usage = max(self.stats.peak_usage, self.stats.current_usage)
        
        return buffer
    
    def release_image_buffer(self, buffer: np.ndarray):
        """释放图片缓冲区"""
        if buffer is None:
            return
        
        size = buffer.nbytes
        
        # 根据大小选择合适的池
        if size <= 480 * 640 * 3:
            pool_key = 'image_small'
        elif size <= 720 * 1280 * 3:
            pool_key = 'image_medium'
        elif size <= 1080 * 1920 * 3:
            pool_key = 'image_large'
        else:
            # 超大图片，直接释放
            del buffer
            return
        
        self.pools[pool_key].release(buffer)
        self.stats.total_freed += size
        self.stats.current_usage -= size
    
    def smart_gc(self, force: bool = False):
        """智能垃圾回收"""
        if force or self._should_trigger_gc():
            # 清理OpenCV缓存
            cv2.destroyAllWindows()
            
            # 清理PIL缓存
            try:
                from PIL import Image
                if hasattr(Image, '_getdecoder'):
                    Image._getdecoder.cache_clear()
            except:
                pass
            
            # 执行垃圾回收
            collected = gc.collect()
            self.stats.gc_collections += 1
            
            print(f"🧹 智能垃圾回收: 回收了 {collected} 个对象")
            return collected
        
        return 0
    
    def _should_trigger_gc(self) -> bool:
        """判断是否应该触发垃圾回收"""
        # 获取当前内存使用情况
        process = psutil.Process()
        memory_info = process.memory_info()
        
        # 如果内存使用超过阈值，触发GC
        if memory_info.rss > self.max_memory_bytes * 0.8:
            return True
        
        # 如果分配的内存远大于释放的内存，触发GC
        if self.stats.total_allocated - self.stats.total_freed > self.max_memory_bytes * 0.5:
            return True
        
        return False
    
    def _memory_monitor(self):
        """内存监控线程"""
        while True:
            try:
                process = psutil.Process()
                memory_info = process.memory_info()
                
                # 检查内存压力
                if memory_info.rss > self.max_memory_bytes * 0.9:
                    print("⚠️ 内存压力过高，执行紧急清理")
                    self._handle_memory_pressure()
                
                # 定期智能垃圾回收
                if self._should_trigger_gc():
                    self.smart_gc()
                
                time.sleep(5)  # 每5秒检查一次
                
            except Exception as e:
                print(f"内存监控异常: {str(e)}")
                time.sleep(10)
    
    def _handle_memory_pressure(self):
        """处理内存压力"""
        # 清空所有对象池
        for pool in self.pools.values():
            with pool.lock:
                pool.pool.clear()
        
        # 执行强制垃圾回收
        self.smart_gc(force=True)
        
        # 调用注册的回调函数
        for callback in self.memory_pressure_callbacks:
            try:
                callback()
            except Exception as e:
                print(f"内存压力回调失败: {str(e)}")
    
    def register_memory_pressure_callback(self, callback: Callable):
        """注册内存压力回调"""
        self.memory_pressure_callbacks.append(callback)
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """获取内存统计信息"""
        process = psutil.Process()
        memory_info = process.memory_info()
        
        pool_stats = {}
        for name, pool in self.pools.items():
            pool_stats[name] = pool.get_stats()
        
        return {
            'memory_manager': {
                'total_allocated_mb': self.stats.total_allocated / (1024 * 1024),
                'total_freed_mb': self.stats.total_freed / (1024 * 1024),
                'current_usage_mb': self.stats.current_usage / (1024 * 1024),
                'peak_usage_mb': self.stats.peak_usage / (1024 * 1024),
                'gc_collections': self.stats.gc_collections,
            },
            'system_memory': {
                'process_rss_mb': memory_info.rss / (1024 * 1024),
                'process_vms_mb': memory_info.vms / (1024 * 1024),
                'system_available_mb': psutil.virtual_memory().available / (1024 * 1024),
                'system_percent': psutil.virtual_memory().percent,
            },
            'object_pools': pool_stats
        }
    
    def optimize_memory(self):
        """执行内存优化"""
        print("🔧 执行内存优化...")
        
        # 清理对象池
        cleared_objects = 0
        for pool in self.pools.values():
            with pool.lock:
                cleared_objects += len(pool.pool)
                pool.pool.clear()
        
        # 强制垃圾回收
        collected = self.smart_gc(force=True)
        
        print(f"✅ 内存优化完成: 清理了 {cleared_objects} 个池对象, 回收了 {collected} 个Python对象")
        
        return {
            'cleared_pool_objects': cleared_objects,
            'collected_objects': collected
        }
    
    def cleanup(self):
        """清理内存管理器"""
        print("🧹 清理高级内存管理器...")
        
        # 清理所有对象池
        for pool in self.pools.values():
            with pool.lock:
                pool.pool.clear()
                pool.in_use.clear()
        
        # 最终垃圾回收
        self.smart_gc(force=True)
        
        print("✅ 高级内存管理器清理完成")

# 全局内存管理器实例
_global_memory_manager = None
_manager_lock = threading.Lock()

def get_memory_manager() -> AdvancedMemoryManager:
    """获取全局内存管理器实例"""
    global _global_memory_manager
    with _manager_lock:
        if _global_memory_manager is None:
            _global_memory_manager = AdvancedMemoryManager()
        return _global_memory_manager

def cleanup_memory_manager():
    """清理全局内存管理器"""
    global _global_memory_manager
    with _manager_lock:
        if _global_memory_manager:
            _global_memory_manager.cleanup()
            _global_memory_manager = None

if __name__ == "__main__":
    # 测试代码
    manager = get_memory_manager()
    
    # 测试图片缓冲区分配
    buffer1 = manager.allocate_image_buffer(480, 640, 3)
    buffer2 = manager.allocate_image_buffer(1080, 1920, 3)
    
    print("内存统计:", manager.get_memory_stats())
    
    # 释放缓冲区
    manager.release_image_buffer(buffer1)
    manager.release_image_buffer(buffer2)
    
    # 执行优化
    manager.optimize_memory()
    
    print("优化后内存统计:", manager.get_memory_stats())
