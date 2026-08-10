#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
应用程序控制器 - 统一管理应用程序生命周期
"""

from pathlib import Path
from typing import Optional

class AppController:
    """应用程序控制器"""
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        
        # 核心服务
        self.config_manager = None
        self.memory_manager = None
        self.error_handler = None
        self.video_generator = None
        
        self._initialized = False
    
    def initialize(self) -> bool:
        """初始化应用程序"""
        if self._initialized:
            return True
        
        try:
            # 初始化配置管理器
            from ..config.unified_config import ConfigManager
            self.config_manager = ConfigManager(Path(self.project_root) / "config")
            
            # 初始化内存管理器
            from ..optimization.memory.manager import MemoryManager
            self.memory_manager = MemoryManager(self.config_manager)
            
            # 初始化错误处理器
            from ..utils.error_handler import ErrorHandler
            self.error_handler = ErrorHandler(self.config_manager)
            
            # 初始化视频生成器
            from .video_generator import VideoGenerator
            self.video_generator = VideoGenerator(
                self.config_manager,
                self.memory_manager,
                self.error_handler
            )
            
            self._initialized = True
            print("✅ 应用程序控制器初始化完成")
            return True
            
        except Exception as e:
            print(f"❌ 应用程序控制器初始化失败: {str(e)}")
            return False
    
    def create_main_window(self):
        """创建主窗口"""
        if not self._initialized:
            raise RuntimeError("应用程序控制器未初始化")
        
        from ..gui.main_window import MainWindow
        return MainWindow(self)
    
    def cleanup(self):
        """清理资源"""
        if self.memory_manager:
            self.memory_manager.cleanup()
        
        if self.error_handler:
            self.error_handler.cleanup()
        
        print("✅ 应用程序资源清理完成")
