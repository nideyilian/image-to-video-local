#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
异步处理模块 - 优化多线程和异步处理
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Any, List, Optional, Dict
from dataclasses import dataclass
from enum import Enum
import queue
import logging

logger = logging.getLogger(__name__)

class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class Task:
    """任务数据类"""
    id: str
    func: Callable
    args: tuple
    kwargs: dict
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[Exception] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    progress: float = 0.0

class ProgressCallback:
    """进度回调管理器"""
    
    def __init__(self, callback: Optional[Callable[[float, str], None]] = None):
        self.callback = callback
        self.total_steps = 100
        self.current_step = 0
        self.message = ""
        self.lock = threading.RLock()
    
    def set_total_steps(self, total: int):
        """设置总步数"""
        with self.lock:
            self.total_steps = max(1, total)
    
    def update(self, step: int, message: str = ""):
        """更新进度"""
        with self.lock:
            self.current_step = min(step, self.total_steps)
            self.message = message
            progress = (self.current_step / self.total_steps) * 100
            
            if self.callback:
                try:
                    self.callback(progress, message)
                except Exception as e:
                    print(f"进度回调错误: {str(e)}")
    
    def increment(self, message: str = ""):
        """递增进度"""
        with self.lock:
            self.update(self.current_step + 1, message)
    
    def complete(self, message: str = "完成"):
        """标记为完成"""
        self.update(self.total_steps, message)

class AsyncTaskManager:
    """异步任务管理器"""
    
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.tasks: Dict[str, Task] = {}
        self.task_queue = queue.Queue()
        self.lock = threading.RLock()
        self.shutdown = False
    
    def submit_task(self, task_id: str, func: Callable, *args, **kwargs) -> Task:
        """提交任务"""
        with self.lock:
            task = Task(
                id=task_id,
                func=func,
                args=args,
                kwargs=kwargs
            )
            self.tasks[task_id] = task
            
            # 提交到线程池
            future = self.executor.submit(self._execute_task, task)
            task.future = future
            
            return task
    
    def _execute_task(self, task: Task) -> Any:
        """执行任务"""
        task.status = TaskStatus.RUNNING
        task.start_time = time.time()
        
        try:
            result = task.func(*task.args, **task.kwargs)
            task.result = result
            task.status = TaskStatus.COMPLETED
            return result
        except Exception as e:
            task.error = e
            task.status = TaskStatus.FAILED
            raise
        finally:
            task.end_time = time.time()
    
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """获取任务状态"""
        with self.lock:
            task = self.tasks.get(task_id)
            return task.status if task else None
    
    def get_task_result(self, task_id: str) -> Any:
        """获取任务结果"""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                raise ValueError(f"任务 {task_id} 不存在")
            
            if task.status == TaskStatus.COMPLETED:
                return task.result
            elif task.status == TaskStatus.FAILED:
                raise task.error
            else:
                raise RuntimeError(f"任务 {task_id} 尚未完成")
    
    def wait_for_task(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """等待任务完成"""
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"任务 {task_id} 不存在")
        
        try:
            return task.future.result(timeout=timeout)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = e
            raise
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            
            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                return False
            
            cancelled = task.future.cancel()
            if cancelled:
                task.status = TaskStatus.CANCELLED
            
            return cancelled
    
    def get_all_tasks(self) -> Dict[str, Task]:
        """获取所有任务"""
        with self.lock:
            return self.tasks.copy()
    
    def cleanup_completed_tasks(self):
        """清理已完成的任务"""
        with self.lock:
            completed_tasks = [
                task_id for task_id, task in self.tasks.items()
                if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]
            ]
            
            for task_id in completed_tasks:
                del self.tasks[task_id]
    
    def shutdown_executor(self, wait: bool = True):
        """关闭执行器"""
        self.shutdown = True
        self.executor.shutdown(wait=wait)

class BatchProcessor:
    """批量处理器"""
    
    def __init__(self, max_workers: int = 4):
        self.task_manager = AsyncTaskManager(max_workers)
        self.progress_callback = None
    
    def set_progress_callback(self, callback: Callable[[float, str], None]):
        """设置进度回调"""
        self.progress_callback = callback
    
    def process_batch(self, items: List[Any], processor_func: Callable, 
                     batch_size: int = 10) -> List[Any]:
        """批量处理项目"""
        results = []
        total_items = len(items)
        
        # 创建进度管理器
        progress = ProgressCallback(self.progress_callback)
        progress.set_total_steps(total_items)
        
        # 分批处理
        for i in range(0, total_items, batch_size):
            batch = items[i:i + batch_size]
            batch_results = self._process_batch_chunk(batch, processor_func, progress)
            results.extend(batch_results)
        
        progress.complete("批量处理完成")
        return results
    
    def _process_batch_chunk(self, batch: List[Any], processor_func: Callable,
                           progress: ProgressCallback) -> List[Any]:
        """处理批次块"""
        futures = []
        
        # 提交批次任务
        for i, item in enumerate(batch):
            task_id = f"batch_item_{id(item)}_{i}"
            task = self.task_manager.submit_task(task_id, processor_func, item)
            futures.append((task_id, task.future))
        
        # 收集结果
        results = []
        for task_id, future in futures:
            try:
                result = future.result()
                results.append(result)
                progress.increment(f"处理完成: {task_id}")
            except Exception as e:
                print(f"批次项目处理失败 {task_id}: {str(e)}")
                results.append(None)
        
        return results
    
    def shutdown(self):
        """关闭批量处理器"""
        self.task_manager.shutdown_executor()

class VideoProcessingQueue:
    """视频处理队列"""
    
    def __init__(self, max_concurrent: int = 2):
        self.max_concurrent = max_concurrent
        self.processing_queue = queue.Queue()
        self.active_tasks = {}
        self.task_manager = AsyncTaskManager(max_concurrent)
        self.lock = threading.RLock()
        self.worker_thread = None
        self.running = False
    
    def start(self):
        """启动队列处理"""
        if self.running:
            return
        
        self.running = True
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()
    
    def stop(self):
        """停止队列处理"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        self.task_manager.shutdown_executor()
    
    def add_video_task(self, task_id: str, video_params: Dict[str, Any],
                      progress_callback: Optional[Callable] = None) -> str:
        """添加视频处理任务

        Args:
            task_id: 任务唯一标识
            video_params: 视频生成参数，支持两种格式：
                1. {'image_paths': [...], 'options': ProcessingOptions}
                2. {'image_paths': [...], 'output_path': ..., 'fps': ..., ...}
            progress_callback: 进度回调

        Returns:
            str: 任务ID
        """
        task_info = {
            'id': task_id,
            'params': video_params,
            'progress_callback': progress_callback,
            'timestamp': time.time()
        }
        
        self.processing_queue.put(task_info)
        return task_id
    
    def _process_queue(self):
        """处理队列中的任务"""
        while self.running:
            try:
                # 获取任务（超时1秒）
                task_info = self.processing_queue.get(timeout=1)
                
                # 检查并发限制
                with self.lock:
                    if len(self.active_tasks) >= self.max_concurrent:
                        # 重新放回队列
                        self.processing_queue.put(task_info)
                        time.sleep(0.1)
                        continue
                
                # 处理任务
                self._handle_video_task(task_info)
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"队列处理错误: {str(e)}")
    
    def _handle_video_task(self, task_info: Dict[str, Any]):
        """处理单个视频任务"""
        task_id = task_info['id']
        params = task_info['params']

        with self.lock:
            self.active_tasks[task_id] = task_info

        try:
            # 调用实际视频生成逻辑
            from ..services.video_service import VideoGenerationService
            from ..services.image_service import ImageProcessingService

            image_service = ImageProcessingService()
            video_service = VideoGenerationService(image_service)

            image_paths = params.get('image_paths', [])
            options = params.get('options')

            if not options:
                from ..models import ProcessingOptions
                options = ProcessingOptions(**{
                    k: v for k, v in params.items()
                    if k != 'image_paths'
                })

            result = video_service.generate_video(image_paths, options)
            
            if result.success:
                logger.info(f"视频任务完成: {task_id} -> {result.output_path}")
            else:
                logger.error(f"视频任务失败: {task_id} -> {result.error_message}")
            
            return result

        except Exception as e:
            logger.error(f"视频任务处理失败 {task_id}: {str(e)}")
        finally:
            with self.lock:
                self.active_tasks.pop(task_id, None)
    
    def get_queue_status(self) -> Dict[str, Any]:
        """获取队列状态"""
        with self.lock:
            return {
                'queue_size': self.processing_queue.qsize(),
                'active_tasks': len(self.active_tasks),
                'max_concurrent': self.max_concurrent,
                'running': self.running
            }

# 全局实例
_batch_processor = None
_video_queue = None

def get_batch_processor() -> BatchProcessor:
    """获取全局批量处理器"""
    global _batch_processor
    if _batch_processor is None:
        _batch_processor = BatchProcessor()
    return _batch_processor

def get_video_queue() -> VideoProcessingQueue:
    """获取全局视频处理队列"""
    global _video_queue
    if _video_queue is None:
        _video_queue = VideoProcessingQueue()
        _video_queue.start()
    return _video_queue

def shutdown_all_processors():
    """关闭所有处理器"""
    global _batch_processor, _video_queue
    
    if _batch_processor:
        _batch_processor.shutdown()
        _batch_processor = None
    
    if _video_queue:
        _video_queue.stop()
        _video_queue = None
