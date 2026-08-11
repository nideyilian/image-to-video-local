#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
FFmpeg静默运行器 - 确保FFmpeg在后台运行，不弹出控制台窗口
专为EXE打包优化，解决FFmpeg窗口弹出问题
"""

import os
import sys
import subprocess
from typing import Optional, List, Any

from .ffmpeg_runtime import resolve_ffmpeg_path

class FFmpegSilentRunner:
    """FFmpeg静默运行器"""
    
    def __init__(self):
        self.startupinfo = None
        self.creationflags = 0
        
        # Windows平台配置
        if sys.platform == "win32":
            self.startupinfo = subprocess.STARTUPINFO()
            self.startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.startupinfo.wShowWindow = subprocess.SW_HIDE
            self.creationflags = subprocess.CREATE_NO_WINDOW
    
    def run_command(self, cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
        """
        静默运行命令
        
        Args:
            cmd: 命令列表
            **kwargs: 其他subprocess.run参数
            
        Returns:
            subprocess.CompletedProcess对象
        """
        # 添加静默参数
        if sys.platform == "win32":
            kwargs.setdefault('startupinfo', self.startupinfo)
            kwargs.setdefault('creationflags', self.creationflags)
        
        # 默认捕获输出
        kwargs.setdefault('capture_output', True)
        kwargs.setdefault('text', True)
        
        return subprocess.run(cmd, **kwargs)
    
    def run_popen(self, cmd: List[str], **kwargs) -> subprocess.Popen:
        """
        静默启动Popen进程
        
        Args:
            cmd: 命令列表
            **kwargs: 其他subprocess.Popen参数
            
        Returns:
            subprocess.Popen对象
        """
        # 添加静默参数
        if sys.platform == "win32":
            kwargs.setdefault('startupinfo', self.startupinfo)
            kwargs.setdefault('creationflags', self.creationflags)
        
        return subprocess.Popen(cmd, **kwargs)
    
    def find_ffmpeg(self) -> Optional[str]:
        """
        静默查找FFmpeg路径
        
        Returns:
            FFmpeg路径或None
        """
        return resolve_ffmpeg_path()
    
    def test_ffmpeg(self, ffmpeg_path: str) -> bool:
        """
        静默测试FFmpeg是否可用
        
        Args:
            ffmpeg_path: FFmpeg路径
            
        Returns:
            是否可用
        """
        try:
            result = self.run_command([ffmpeg_path, '-version'])
            return result.returncode == 0
        except:
            return False

# 全局静默运行器实例
_global_silent_runner = None

def get_silent_runner() -> FFmpegSilentRunner:
    """获取全局静默运行器实例"""
    global _global_silent_runner
    if _global_silent_runner is None:
        _global_silent_runner = FFmpegSilentRunner()
    return _global_silent_runner

def run_ffmpeg_silent(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    """
    静默运行FFmpeg命令的便捷函数
    
    Args:
        cmd: FFmpeg命令列表
        **kwargs: 其他subprocess.run参数
        
    Returns:
        subprocess.CompletedProcess对象
    """
    runner = get_silent_runner()
    return runner.run_command(cmd, **kwargs)

def popen_ffmpeg_silent(cmd: List[str], **kwargs) -> subprocess.Popen:
    """
    静默启动FFmpeg Popen进程的便捷函数
    
    Args:
        cmd: FFmpeg命令列表
        **kwargs: 其他subprocess.Popen参数
        
    Returns:
        subprocess.Popen对象
    """
    runner = get_silent_runner()
    return runner.run_popen(cmd, **kwargs)

def find_ffmpeg_silent() -> Optional[str]:
    """
    静默查找FFmpeg路径的便捷函数
    
    Returns:
        FFmpeg路径或None
    """
    runner = get_silent_runner()
    return runner.find_ffmpeg()

# 为了向后兼容，提供一个配置函数
def configure_subprocess_for_exe():
    """
    为EXE环境配置subprocess参数
    返回可用于subprocess调用的参数字典
    """
    config = {}
    
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        
        config['startupinfo'] = startupinfo
        config['creationflags'] = subprocess.CREATE_NO_WINDOW
    
    return config

if __name__ == "__main__":
    # 测试代码
    print("🔧 FFmpeg静默运行器测试")
    print("=" * 40)
    
    runner = get_silent_runner()
    
    # 测试查找FFmpeg
    ffmpeg_path = runner.find_ffmpeg()
    if ffmpeg_path:
        print(f"✅ 找到FFmpeg: {ffmpeg_path}")
        
        # 测试FFmpeg
        if runner.test_ffmpeg(ffmpeg_path):
            print("✅ FFmpeg测试通过")
        else:
            print("❌ FFmpeg测试失败")
    else:
        print("❌ 未找到FFmpeg")
    
    # 测试配置
    config = configure_subprocess_for_exe()
    print(f"📋 EXE配置: {list(config.keys())}")
    
    print("=" * 40)
