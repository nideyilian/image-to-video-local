#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
统一错误处理系统 - 高优先级优化实施
提供统一的异常处理、用户友好的错误信息和自动恢复机制
"""

import sys
import traceback
import logging
import threading
import time
from typing import Dict, Any, Optional, Callable, List
from functools import wraps
from enum import Enum
from dataclasses import dataclass
import tkinter as tk
from tkinter import messagebox

class ErrorSeverity(Enum):
    """错误严重程度"""
    INFO = "信息"
    WARNING = "警告"
    ERROR = "错误"
    CRITICAL = "严重错误"

class ErrorCategory(Enum):
    """错误分类"""
    FILE_IO = "文件操作"
    MEMORY = "内存管理"
    PROCESSING = "图片处理"
    VIDEO_ENCODING = "视频编码"
    NETWORK = "网络连接"
    SYSTEM = "系统错误"
    USER_INPUT = "用户输入"
    UNKNOWN = "未知错误"

@dataclass
class ErrorInfo:
    """错误信息"""
    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    user_message: str
    technical_details: str
    timestamp: float
    recovery_suggestions: List[str]
    auto_recovery: Optional[Callable] = None

class ErrorDatabase:
    """错误数据库 - 存储已知错误和解决方案"""
    
    def __init__(self):
        self.error_patterns = {
            # 文件操作错误
            "FileNotFoundError": ErrorInfo(
                category=ErrorCategory.FILE_IO,
                severity=ErrorSeverity.ERROR,
                message="文件未找到",
                user_message="找不到指定的文件，请检查文件路径是否正确",
                technical_details="",
                timestamp=0,
                recovery_suggestions=[
                    "检查文件路径是否正确",
                    "确认文件是否存在",
                    "检查文件权限"
                ]
            ),
            "PermissionError": ErrorInfo(
                category=ErrorCategory.FILE_IO,
                severity=ErrorSeverity.ERROR,
                message="权限不足",
                user_message="没有足够的权限访问文件，请以管理员身份运行程序",
                technical_details="",
                timestamp=0,
                recovery_suggestions=[
                    "以管理员身份运行程序",
                    "检查文件权限设置",
                    "确认文件未被其他程序占用"
                ]
            ),
            
            # 内存错误
            "MemoryError": ErrorInfo(
                category=ErrorCategory.MEMORY,
                severity=ErrorSeverity.CRITICAL,
                message="内存不足",
                user_message="系统内存不足，请关闭其他程序或减少处理的图片数量",
                technical_details="",
                timestamp=0,
                recovery_suggestions=[
                    "关闭其他占用内存的程序",
                    "减少同时处理的图片数量",
                    "降低输出视频分辨率",
                    "重启程序释放内存"
                ],
                auto_recovery=lambda: self._auto_memory_recovery()
            ),
            
            # 图片处理错误
            "cv2.error": ErrorInfo(
                category=ErrorCategory.PROCESSING,
                severity=ErrorSeverity.ERROR,
                message="图片处理失败",
                user_message="图片处理过程中出现错误，可能是图片格式不支持或文件损坏",
                technical_details="",
                timestamp=0,
                recovery_suggestions=[
                    "检查图片格式是否支持",
                    "尝试使用其他图片",
                    "检查图片文件是否完整"
                ]
            ),
            
            # 视频编码错误
            "FFmpegError": ErrorInfo(
                category=ErrorCategory.VIDEO_ENCODING,
                severity=ErrorSeverity.ERROR,
                message="视频编码失败",
                user_message="视频生成过程中出现错误，请检查输出路径和参数设置",
                technical_details="",
                timestamp=0,
                recovery_suggestions=[
                    "检查输出路径是否有写入权限",
                    "确认FFmpeg工具可用",
                    "尝试降低视频质量设置",
                    "检查磁盘空间是否充足"
                ]
            )
        }
    
    def _auto_memory_recovery(self):
        """自动内存恢复"""
        try:
            from advanced_memory_manager import get_memory_manager
            manager = get_memory_manager()
            manager.optimize_memory()
            return True
        except:
            import gc
            gc.collect()
            return False
    
    def get_error_info(self, exception: Exception) -> ErrorInfo:
        """根据异常获取错误信息"""
        exception_name = type(exception).__name__
        
        if exception_name in self.error_patterns:
            error_info = self.error_patterns[exception_name]
            # 更新技术细节和时间戳
            error_info.technical_details = str(exception)
            error_info.timestamp = time.time()
            return error_info
        
        # 未知错误
        return ErrorInfo(
            category=ErrorCategory.UNKNOWN,
            severity=ErrorSeverity.ERROR,
            message="未知错误",
            user_message=f"程序遇到了未知错误: {str(exception)}",
            technical_details=traceback.format_exc(),
            timestamp=time.time(),
            recovery_suggestions=[
                "重试操作",
                "重启程序",
                "联系技术支持"
            ]
        )

class UnifiedErrorHandler:
    """统一错误处理器"""
    
    def __init__(self):
        self.error_db = ErrorDatabase()
        self.error_history = []
        self.recovery_attempts = {}
        self.lock = threading.RLock()
        
        # 设置日志
        self._setup_logging()
        
        print("🛡️ 统一错误处理系统已启动")
    
    def _setup_logging(self):
        """设置日志系统"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('error_log.txt', encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def handle_error(self, exception: Exception, context: str = "", 
                    show_dialog: bool = True, attempt_recovery: bool = True) -> bool:
        """处理错误"""
        with self.lock:
            error_info = self.error_db.get_error_info(exception)
            
            # 记录错误
            self._log_error(error_info, context)
            
            # 添加到历史记录
            self.error_history.append({
                'error_info': error_info,
                'context': context,
                'timestamp': time.time()
            })
            
            # 尝试自动恢复
            recovery_success = False
            if attempt_recovery and error_info.auto_recovery:
                recovery_success = self._attempt_auto_recovery(error_info)
            
            # 显示用户对话框
            if show_dialog:
                self._show_error_dialog(error_info, recovery_success)
            
            return recovery_success
    
    def _log_error(self, error_info: ErrorInfo, context: str):
        """记录错误到日志"""
        log_message = f"[{error_info.category.value}] {error_info.message}"
        if context:
            log_message += f" (上下文: {context})"
        
        if error_info.severity == ErrorSeverity.CRITICAL:
            self.logger.critical(log_message)
        elif error_info.severity == ErrorSeverity.ERROR:
            self.logger.error(log_message)
        elif error_info.severity == ErrorSeverity.WARNING:
            self.logger.warning(log_message)
        else:
            self.logger.info(log_message)
        
        # 记录技术细节
        if error_info.technical_details:
            self.logger.debug(f"技术细节: {error_info.technical_details}")
    
    def _attempt_auto_recovery(self, error_info: ErrorInfo) -> bool:
        """尝试自动恢复"""
        if not error_info.auto_recovery:
            return False
        
        # 检查是否已经尝试过恢复
        error_key = f"{error_info.category.value}_{error_info.message}"
        if error_key in self.recovery_attempts:
            if self.recovery_attempts[error_key] >= 3:  # 最多尝试3次
                return False
        else:
            self.recovery_attempts[error_key] = 0
        
        try:
            self.recovery_attempts[error_key] += 1
            success = error_info.auto_recovery()
            
            if success:
                self.logger.info(f"自动恢复成功: {error_info.message}")
                # 重置尝试计数
                self.recovery_attempts[error_key] = 0
            else:
                self.logger.warning(f"自动恢复失败: {error_info.message}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"自动恢复过程中出错: {str(e)}")
            return False
    
    def _show_error_dialog(self, error_info: ErrorInfo, recovery_attempted: bool):
        """显示错误对话框"""
        try:
            title = f"{error_info.severity.value} - {error_info.category.value}"
            
            message = error_info.user_message
            
            if recovery_attempted:
                message += "\n\n✅ 已尝试自动恢复"
            
            if error_info.recovery_suggestions:
                message += "\n\n💡 建议解决方案:"
                for i, suggestion in enumerate(error_info.recovery_suggestions, 1):
                    message += f"\n{i}. {suggestion}"
            
            # 根据严重程度选择对话框类型
            if error_info.severity == ErrorSeverity.CRITICAL:
                messagebox.showerror(title, message)
            elif error_info.severity == ErrorSeverity.ERROR:
                messagebox.showerror(title, message)
            elif error_info.severity == ErrorSeverity.WARNING:
                messagebox.showwarning(title, message)
            else:
                messagebox.showinfo(title, message)
                
        except Exception as e:
            # 如果显示对话框失败，至少打印到控制台
            print(f"错误对话框显示失败: {str(e)}")
            print(f"原始错误: {error_info.user_message}")
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """获取错误统计信息"""
        with self.lock:
            if not self.error_history:
                return {'total_errors': 0}
            
            # 按类别统计
            category_counts = {}
            severity_counts = {}
            
            for record in self.error_history:
                error_info = record['error_info']
                
                category = error_info.category.value
                category_counts[category] = category_counts.get(category, 0) + 1
                
                severity = error_info.severity.value
                severity_counts[severity] = severity_counts.get(severity, 0) + 1
            
            return {
                'total_errors': len(self.error_history),
                'by_category': category_counts,
                'by_severity': severity_counts,
                'recent_errors': [
                    {
                        'category': record['error_info'].category.value,
                        'message': record['error_info'].message,
                        'timestamp': record['timestamp']
                    }
                    for record in self.error_history[-10:]  # 最近10个错误
                ]
            }

def handle_errors(error_message: str = "操作失败", 
                 show_dialog: bool = True, 
                 attempt_recovery: bool = True,
                 return_on_error: Any = None):
    """错误处理装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                handler = get_error_handler()
                context = f"函数: {func.__name__}, 参数: {args[:2]}..."  # 避免记录敏感信息
                
                recovery_success = handler.handle_error(
                    e, context, show_dialog, attempt_recovery
                )
                
                if recovery_success:
                    # 如果恢复成功，重试一次
                    try:
                        return func(*args, **kwargs)
                    except Exception as retry_e:
                        # 重试失败，返回默认值
                        handler.handle_error(retry_e, f"{context} (重试)", False, False)
                        return return_on_error
                else:
                    return return_on_error
        
        return wrapper
    return decorator

# 全局错误处理器实例
_global_error_handler = None
_handler_lock = threading.Lock()

def get_error_handler() -> UnifiedErrorHandler:
    """获取全局错误处理器实例"""
    global _global_error_handler
    with _handler_lock:
        if _global_error_handler is None:
            _global_error_handler = UnifiedErrorHandler()
        return _global_error_handler

def cleanup_error_handler():
    """清理错误处理器"""
    global _global_error_handler
    with _handler_lock:
        if _global_error_handler:
            _global_error_handler = None

if __name__ == "__main__":
    # 测试代码
    handler = get_error_handler()
    
    # 测试文件错误
    try:
        with open("不存在的文件.txt", "r") as f:
            pass
    except Exception as e:
        handler.handle_error(e, "测试文件读取")
    
    # 测试装饰器
    @handle_errors("图片处理失败", return_on_error=None)
    def test_function():
        raise ValueError("测试错误")
    
    result = test_function()
    print(f"函数结果: {result}")
    
    # 显示统计信息
    stats = handler.get_error_statistics()
    print("错误统计:", stats)
