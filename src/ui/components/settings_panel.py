#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
设置面板组件
根据开发规范：新功能需要支持配置持久化，并提供清晰的用户界面控件
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Dict, Any, Callable, Optional
from pathlib import Path

from ...config import ConfigManager, AppConfig
from ...models import VideoSettings, TransitionType

PADDING = 8
PADDING_LG = 12

class SettingsPanel(ttk.Frame):
    """设置面板组件"""
    
    def __init__(self, parent, config_manager: Optional[ConfigManager] = None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.change_callbacks: Dict[str, Callable] = {}
        
        # 配置变量
        self.fps_var = tk.IntVar(value=30)
        self.duration_var = tk.DoubleVar(value=3.0)
        self.resolution_var = tk.StringVar(value="1920x1080")
        self.bitrate_var = tk.StringVar(value="5000k")
        self.transition_var = tk.StringVar(value="淡入淡出")
        self.output_dir_var = tk.StringVar(value="output/videos")
        
        self._create_widgets()
        self._load_config()
    
    def _create_widgets(self):
        """创建界面控件"""
        # 主标题
        title_label = ttk.Label(self, text="视频设置", font=("Microsoft YaHei", 12, "bold"))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, PADDING_LG), sticky="w")
        
        # 视频基础设置
        self._create_video_settings()
        
        # 输出设置
        self._create_output_settings()
        
        # 转场设置
        self._create_transition_settings()
        
        # 高级设置
        self._create_advanced_settings()
        
        # 操作按钮
        self._create_action_buttons()
        
        # 配置网格权重
        self.columnconfigure(1, weight=1)
    
    def _create_video_settings(self):
        """创建视频设置区域"""
        # 分组框
        video_frame = ttk.LabelFrame(self, text="视频参数", padding=str(PADDING_LG))
        video_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=PADDING)
        video_frame.columnconfigure(1, weight=1)
        
        # FPS设置
        ttk.Label(video_frame, text="帧率 (FPS):").grid(row=0, column=0, sticky="w", pady=PADDING)
        fps_frame = ttk.Frame(video_frame)
        fps_frame.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        fps_frame.columnconfigure(0, weight=1)
        
        fps_scale = ttk.Scale(fps_frame, from_=10, to=60, variable=self.fps_var, 
                             orient="horizontal", command=self._on_fps_change)
        fps_scale.grid(row=0, column=0, sticky="ew")
        
        self.fps_label = ttk.Label(fps_frame, text="30")
        self.fps_label.grid(row=0, column=1, sticky="e", padx=(8, 0))
        
        # 持续时间设置
        ttk.Label(video_frame, text="图片持续时间 (秒):").grid(row=1, column=0, sticky="w", pady=PADDING)
        duration_frame = ttk.Frame(video_frame)
        duration_frame.grid(row=1, column=1, sticky="ew", padx=(10, 0))
        duration_frame.columnconfigure(0, weight=1)
        
        duration_scale = ttk.Scale(duration_frame, from_=0.5, to=10.0, variable=self.duration_var,
                                  orient="horizontal", command=self._on_duration_change)
        duration_scale.grid(row=0, column=0, sticky="ew")
        
        self.duration_label = ttk.Label(duration_frame, text="3.0")
        self.duration_label.grid(row=0, column=1, sticky="e", padx=(8, 0))
        
        # 分辨率设置
        ttk.Label(video_frame, text="分辨率:").grid(row=2, column=0, sticky="w", pady=PADDING)
        resolution_combo = ttk.Combobox(video_frame, textvariable=self.resolution_var,
                                       values=["1920x1080", "1280x720", "854x480", "640x360"],
                                       width=15)
        resolution_combo.grid(row=2, column=1, sticky="w", padx=(10, 0))
        resolution_combo.bind("<<ComboboxSelected>>", self._on_resolution_change)
        
        # 码率设置
        ttk.Label(video_frame, text="码率:").grid(row=3, column=0, sticky="w", pady=PADDING)
        bitrate_combo = ttk.Combobox(video_frame, textvariable=self.bitrate_var,
                                    values=["1000k", "2000k", "3000k", "5000k", "8000k", "10000k"],
                                    width=15)
        bitrate_combo.grid(row=3, column=1, sticky="w", padx=(10, 0))
        bitrate_combo.bind("<<ComboboxSelected>>", self._on_bitrate_change)
    
    def _create_output_settings(self):
        """创建输出设置区域"""
        output_frame = ttk.LabelFrame(self, text="输出设置", padding=str(PADDING_LG))
        output_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=PADDING)
        output_frame.columnconfigure(1, weight=1)
        
        # 输出目录
        ttk.Label(output_frame, text="输出目录:").grid(row=0, column=0, sticky="w", pady=PADDING)
        
        dir_frame = ttk.Frame(output_frame)
        dir_frame.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        dir_frame.columnconfigure(0, weight=1)
        
        self.output_dir_entry = ttk.Entry(dir_frame, textvariable=self.output_dir_var)
        self.output_dir_entry.grid(row=0, column=0, sticky="ew")
        
        ttk.Button(dir_frame, text="浏览...", command=self._browse_output_dir,
                  width=8).grid(row=0, column=1, padx=(5, 0))
    
    def _create_transition_settings(self):
        """创建转场设置区域"""
        transition_frame = ttk.LabelFrame(self, text="转场效果", padding=str(PADDING_LG))
        transition_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=PADDING)
        transition_frame.columnconfigure(1, weight=1)
        
        # 转场类型
        ttk.Label(transition_frame, text="转场效果:").grid(row=0, column=0, sticky="w", pady=PADDING)
        
        transition_values = [t.value for t in TransitionType]
        transition_combo = ttk.Combobox(transition_frame, textvariable=self.transition_var,
                                       values=transition_values, width=20)
        transition_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))
        transition_combo.bind("<<ComboboxSelected>>", self._on_transition_change)
    
    def _create_advanced_settings(self):
        """创建高级设置区域"""
        advanced_frame = ttk.LabelFrame(self, text="高级选项", padding=str(PADDING_LG))
        advanced_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=PADDING)
        
        # 性能优化选项
        self.enable_optimization_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(advanced_frame, text="启用性能优化", 
                       variable=self.enable_optimization_var,
                       command=self._on_optimization_change).grid(row=0, column=0, sticky="w")
        
        # 并行处理选项
        self.parallel_processing_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(advanced_frame, text="启用并行处理",
                       variable=self.parallel_processing_var,
                       command=self._on_parallel_change).grid(row=1, column=0, sticky="w")
    
    def _create_action_buttons(self):
        """创建操作按钮"""
        button_frame = ttk.Frame(self)
        button_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        
        ttk.Button(button_frame, text="保存设置", command=self.save_config).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Button(button_frame, text="重置默认", command=self.reset_to_defaults).grid(row=0, column=1, sticky="w", padx=(0, 8))
        ttk.Button(button_frame, text="导入配置", command=self.import_config).grid(row=0, column=2, sticky="w", padx=(0, 8))
        ttk.Button(button_frame, text="导出配置", command=self.export_config).grid(row=0, column=3, sticky="w")
    
    def _load_config(self):
        """加载配置"""
        if not self.config_manager:
            return
        
        try:
            config = self.config_manager.get_config()
            
            # 视频设置
            self.fps_var.set(config.video_settings.fps)
            self.duration_var.set(config.video_settings.duration)
            self.resolution_var.set(config.video_settings.resolution)
            self.bitrate_var.set(config.video_settings.bitrate)
            
            # 输出设置
            self.output_dir_var.set(config.paths.output_dir)
            
            # 转场设置
            self.transition_var.set(config.transition_settings.type.value)
            
            # 高级设置
            self.enable_optimization_var.set(config.performance.enable_optimization)
            self.parallel_processing_var.set(config.performance.parallel_processing)
            
            # 更新标签
            self._update_labels()
            
        except Exception as e:
            messagebox.showerror("配置加载错误", f"加载配置时出错: {e}")
    
    def _update_labels(self):
        """更新显示标签"""
        self.fps_label.config(text=str(int(self.fps_var.get())))
        self.duration_label.config(text=f"{self.duration_var.get():.1f}")
    
    # 事件处理方法
    def _on_fps_change(self, value):
        """FPS变更处理"""
        fps = int(float(value))
        self.fps_var.set(fps)
        self.fps_label.config(text=str(fps))
        self._trigger_change("fps", fps)
    
    def _on_duration_change(self, value):
        """持续时间变更处理"""
        duration = round(float(value), 1)
        self.duration_var.set(duration)
        self.duration_label.config(text=f"{duration:.1f}")
        self._trigger_change("duration", duration)
    
    def _on_resolution_change(self, event):
        """分辨率变更处理"""
        self._trigger_change("resolution", self.resolution_var.get())
    
    def _on_bitrate_change(self, event):
        """码率变更处理"""
        self._trigger_change("bitrate", self.bitrate_var.get())
    
    def _on_transition_change(self, event):
        """转场变更处理"""
        self._trigger_change("transition", self.transition_var.get())
    
    def _on_optimization_change(self):
        """优化选项变更处理"""
        self._trigger_change("optimization", self.enable_optimization_var.get())
    
    def _on_parallel_change(self):
        """并行处理变更处理"""
        self._trigger_change("parallel", self.parallel_processing_var.get())
    
    def _browse_output_dir(self):
        """浏览输出目录"""
        current_dir = self.output_dir_var.get() or "."
        new_dir = filedialog.askdirectory(
            title="选择输出目录",
            initialdir=current_dir
        )
        
        if new_dir:
            self.output_dir_var.set(new_dir)
            self._trigger_change("output_dir", new_dir)
    
    def _trigger_change(self, setting: str, value: Any):
        """触发变更回调"""
        if setting in self.change_callbacks:
            try:
                self.change_callbacks[setting](value)
            except Exception as e:
                print(f"设置变更回调错误 {setting}: {e}")
    
    # 公共API
    def add_change_callback(self, setting: str, callback: Callable):
        """添加设置变更回调"""
        self.change_callbacks[setting] = callback
    
    def get_current_settings(self) -> Dict[str, Any]:
        """获取当前设置"""
        return {
            "fps": self.fps_var.get(),
            "duration": self.duration_var.get(),
            "resolution": self.resolution_var.get(),
            "bitrate": self.bitrate_var.get(),
            "transition": self.transition_var.get(),
            "output_dir": self.output_dir_var.get(),
            "optimization": self.enable_optimization_var.get(),
            "parallel": self.parallel_processing_var.get()
        }
    
    def save_config(self):
        """保存配置"""
        if not self.config_manager:
            messagebox.showwarning("警告", "配置管理器未初始化")
            return
        
        try:
            # 更新配置
            config = self.config_manager.get_config()
            
            # 更新视频设置
            config.video_settings.fps = self.fps_var.get()
            config.video_settings.duration = self.duration_var.get()
            config.video_settings.resolution = self.resolution_var.get()
            config.video_settings.bitrate = self.bitrate_var.get()
            
            # 更新路径设置
            config.paths.output_dir = self.output_dir_var.get()
            
            # 更新性能设置
            config.performance.enable_optimization = self.enable_optimization_var.get()
            config.performance.parallel_processing = self.parallel_processing_var.get()
            
            # 保存配置
            self.config_manager.save_user_config()
            
            messagebox.showinfo("成功", "配置已保存")
            
        except Exception as e:
            messagebox.showerror("保存错误", f"保存配置时出错: {e}")
    
    def reset_to_defaults(self):
        """重置为默认设置"""
        if messagebox.askyesno("确认", "确定要重置为默认设置吗？"):
            try:
                if self.config_manager:
                    self.config_manager.reset_to_defaults()
                
                # 重新加载界面
                self._load_config()
                
                messagebox.showinfo("成功", "已重置为默认设置")
                
            except Exception as e:
                messagebox.showerror("重置错误", f"重置设置时出错: {e}")
    
    def import_config(self):
        """导入配置"""
        file_path = filedialog.askopenfilename(
            title="导入配置文件",
            filetypes=[("YAML files", "*.yaml"), ("All files", "*.*")]
        )
        
        if file_path and self.config_manager:
            try:
                self.config_manager.import_config(Path(file_path))
                self._load_config()
                messagebox.showinfo("成功", "配置已导入")
                
            except Exception as e:
                messagebox.showerror("导入错误", f"导入配置时出错: {e}")
    
    def export_config(self):
        """导出配置"""
        file_path = filedialog.asksaveasfilename(
            title="导出配置文件",
            defaultextension=".yaml",
            filetypes=[("YAML files", "*.yaml"), ("All files", "*.*")]
        )
        
        if file_path and self.config_manager:
            try:
                self.config_manager.export_config(Path(file_path))
                messagebox.showinfo("成功", "配置已导出")
                
            except Exception as e:
                messagebox.showerror("导出错误", f"导出配置时出错: {e}")