#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
进度条组件
支持百分比显示、状态文本、取消操作等
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable
import threading
import time

class ProgressBar(ttk.Frame):
    """增强的进度条组件"""
    
    def __init__(self, parent, show_percentage=True, show_status=True, cancelable=False):
        super().__init__(parent)
        
        self.show_percentage = show_percentage
        self.show_status = show_status
        self.cancelable = cancelable
        
        # 变量
        self.progress_var = tk.DoubleVar(value=0)
        self.status_var = tk.StringVar(value="准备中...")
        self.percentage_var = tk.StringVar(value="0%")
        
        # 回调函数
        self.cancel_callback: Optional[Callable] = None
        
        # 状态
        self.is_running = False
        self.is_cancelled = False
        
        self._create_widgets()
    
    def _create_widgets(self):
        """创建界面组件"""
        self.grid_columnconfigure(0, weight=1)
        row = 0
        
        # 状态文本（如果启用）
        if self.show_status:
            self.status_label = ttk.Label(self, textvariable=self.status_var)
            self.status_label.grid(row=row, column=0, sticky="ew", padx=12, pady=(0, 8))
            row += 1
        
        # 进度条容器
        progress_frame = ttk.Frame(self)
        progress_frame.grid(row=row, column=0, sticky="ew", padx=12, pady=(0, 12))
        progress_frame.columnconfigure(0, weight=1)
        
        # 进度条
        self.progressbar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100,
            mode='determinate'
        )
        self.progressbar.grid(row=0, column=0, sticky="ew")
        
        # 百分比标签（如果启用）
        if self.show_percentage:
            self.percentage_label = ttk.Label(progress_frame, textvariable=self.percentage_var, width=6)
            self.percentage_label.grid(row=0, column=1, padx=(5, 0))
        
        # 取消按钮（如果启用）
        if self.cancelable:
            self.cancel_button = ttk.Button(
                progress_frame,
                text="取消",
                command=self._on_cancel,
                width=8
            )
            self.cancel_button.grid(row=0, column=2, padx=(5, 0))
    
    def _on_cancel(self):
        """取消按钮处理"""
        if self.cancel_callback:
            self.is_cancelled = True
            self.cancel_callback()
            self.set_status("正在取消...")
            if hasattr(self, 'cancel_button'):
                self.cancel_button.config(state="disabled")
    
    def start(self, status_text: str = "开始处理..."):
        """开始进度"""
        self.is_running = True
        self.is_cancelled = False
        self.set_progress(0)
        self.set_status(status_text)
        
        if hasattr(self, 'cancel_button'):
            self.cancel_button.config(state="normal")
    
    def set_progress(self, value: float):
        """设置进度值 (0-100)"""
        if self.is_cancelled:
            return
        
        value = max(0, min(100, value))
        self.progress_var.set(value)
        
        if self.show_percentage:
            self.percentage_var.set(f"{int(value)}%")
        
        # 强制刷新界面
        self.update_idletasks()
    
    def set_status(self, status_text: str):
        """设置状态文本"""
        if self.show_status:
            self.status_var.set(status_text)
        self.update_idletasks()
    
    def complete(self, status_text: str = "完成"):
        """完成进度"""
        self.set_progress(100)
        self.set_status(status_text)
        self.is_running = False
        
        if hasattr(self, 'cancel_button'):
            self.cancel_button.config(state="disabled")
    
    def error(self, error_text: str = "处理失败"):
        """错误状态"""
        self.set_status(f"❌ {error_text}")
        self.is_running = False
        
        if hasattr(self, 'cancel_button'):
            self.cancel_button.config(state="disabled")
    
    def reset(self):
        """重置进度条"""
        self.is_running = False
        self.is_cancelled = False
        self.set_progress(0)
        self.set_status("准备中...")
        
        if hasattr(self, 'cancel_button'):
            self.cancel_button.config(state="normal")
    
    def set_indeterminate(self, active: bool = True):
        """设置为不确定进度模式"""
        if active:
            self.progressbar.config(mode='indeterminate')
            self.progressbar.start(10)  # 动画速度
            if self.show_percentage:
                self.percentage_var.set("...")
        else:
            self.progressbar.stop()
            self.progressbar.config(mode='determinate')
    
    def set_cancel_callback(self, callback: Callable):
        """设置取消回调函数"""
        self.cancel_callback = callback
    
    def is_processing(self) -> bool:
        """检查是否正在处理"""
        return self.is_running and not self.is_cancelled
    
    def was_cancelled(self) -> bool:
        """检查是否被取消"""
        return self.is_cancelled

class MultiStageProgressBar(ttk.Frame):
    """多阶段进度条"""
    
    def __init__(self, parent, stages: list, show_current_stage=True):
        super().__init__(parent)
        
        self.stages = stages
        self.current_stage = 0
        self.stage_progress = 0
        self.show_current_stage = show_current_stage
        
        # 变量
        self.overall_progress_var = tk.DoubleVar(value=0)
        self.stage_progress_var = tk.DoubleVar(value=0)
        self.current_stage_var = tk.StringVar(value=stages[0] if stages else "")
        
        self._create_widgets()
    
    def _create_widgets(self):
        """创建界面组件"""
        self.grid_columnconfigure(0, weight=1)
        # 当前阶段标签
        if self.show_current_stage:
            self.stage_label = ttk.Label(self, textvariable=self.current_stage_var)
            self.stage_label.grid(row=0, column=0, sticky="ew", padx=12, pady=(0, 8))
        
        # 阶段进度条
        stage_frame = ttk.Frame(self)
        stage_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        stage_frame.columnconfigure(0, weight=1)
        
        ttk.Label(stage_frame, text="当前阶段:").grid(row=0, column=0, sticky="w")
        
        self.stage_progressbar = ttk.Progressbar(
            stage_frame,
            variable=self.stage_progress_var,
            maximum=100,
            mode='determinate',
            length=200
        )
        self.stage_progressbar.grid(row=0, column=1, sticky="ew", padx=(10, 5))
        
        self.stage_percentage_label = ttk.Label(stage_frame, text="0%", width=6)
        self.stage_percentage_label.grid(row=0, column=2)
        
        # 总体进度条
        overall_frame = ttk.Frame(self)
        overall_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        overall_frame.columnconfigure(0, weight=1)
        
        ttk.Label(overall_frame, text="总体进度:").grid(row=0, column=0, sticky="w")
        
        self.overall_progressbar = ttk.Progressbar(
            overall_frame,
            variable=self.overall_progress_var,
            maximum=100,
            mode='determinate',
            length=200
        )
        self.overall_progressbar.grid(row=0, column=1, sticky="ew", padx=(10, 5))
        
        self.overall_percentage_label = ttk.Label(overall_frame, text="0%", width=6)
        self.overall_percentage_label.grid(row=0, column=2)
    
    def set_stage(self, stage_index: int, stage_progress: float = 0):
        """设置当前阶段"""
        if 0 <= stage_index < len(self.stages):
            self.current_stage = stage_index
            self.current_stage_var.set(self.stages[stage_index])
            self.set_stage_progress(stage_progress)
    
    def set_stage_progress(self, progress: float):
        """设置当前阶段的进度"""
        progress = max(0, min(100, progress))
        self.stage_progress = progress
        self.stage_progress_var.set(progress)
        self.stage_percentage_label.config(text=f"{int(progress)}%")
        
        # 计算总体进度
        overall_progress = (self.current_stage / len(self.stages)) * 100
        overall_progress += (progress / len(self.stages))
        
        self.overall_progress_var.set(overall_progress)
        self.overall_percentage_label.config(text=f"{int(overall_progress)}%")
        
        self.update_idletasks()
    
    def next_stage(self, stage_progress: float = 0):
        """进入下一阶段"""
        if self.current_stage < len(self.stages) - 1:
            self.set_stage(self.current_stage + 1, stage_progress)
    
    def complete(self):
        """完成所有阶段"""
        self.set_stage(len(self.stages) - 1, 100)
        self.current_stage_var.set("完成")
    
    def reset(self):
        """重置进度"""
        self.set_stage(0, 0)