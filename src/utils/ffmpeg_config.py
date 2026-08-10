#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
FFmpeg配置模块 - 确保FFmpeg在后台静默运行
专为打包环境优化，避免命令行窗口弹出
"""

import os
import sys
import subprocess
import json
from pathlib import Path

class FFmpegConfig:
    """FFmpeg配置管理器"""
    
    def __init__(self):
        self.base_dir = self._get_base_dir()
        self.ffmpeg_exe = None
        self.startup_info = None
        
        # 初始化Windows静默运行配置
        self._setup_windows_silent_mode()
        
        # 查找并配置FFmpeg
        self._find_and_configure_ffmpeg()
    
    def _get_base_dir(self):
        """获取程序基础目录"""
        if getattr(sys, 'frozen', False):
            # 打包后的exe环境
            return Path(sys._MEIPASS)
        else:
            # 开发环境
            return Path(__file__).parent
    
    def _setup_windows_silent_mode(self):
        """设置Windows静默运行模式"""
        if sys.platform == 'win32':
            self.startup_info = subprocess.STARTUPINFO()
            self.startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.startup_info.wShowWindow = subprocess.SW_HIDE
            
            # 设置进程创建标志，防止弹出控制台窗口
            self.creation_flags = subprocess.CREATE_NO_WINDOW
        else:
            self.startup_info = None
            self.creation_flags = 0
    
    def _find_and_configure_ffmpeg(self):
        """查找并配置FFmpeg"""
        # 可能的FFmpeg路径
        ffmpeg_paths = [
            self.base_dir / "tools" / "ffmpeg" / "ffmpeg.exe",
            self.base_dir / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
            self.base_dir / "ffmpeg.exe",
            self.base_dir / "bin" / "ffmpeg.exe",
        ]
        
        # 查找FFmpeg可执行文件
        for path in ffmpeg_paths:
            if path.exists():
                self.ffmpeg_exe = str(path)
                print(f"✅ 找到FFmpeg: {self.ffmpeg_exe}")
                break
        
        if not self.ffmpeg_exe:
            # 尝试从系统PATH查找
            import shutil
            system_ffmpeg = shutil.which("ffmpeg")
            if system_ffmpeg:
                self.ffmpeg_exe = system_ffmpeg
                print(f"✅ 使用系统FFmpeg: {self.ffmpeg_exe}")
            else:
                print("⚠️ 未找到FFmpeg可执行文件")
        
        # 配置环境变量
        self._configure_environment()
    
    def _configure_environment(self):
        """配置FFmpeg环境变量"""
        if self.ffmpeg_exe:
            # 设置FFmpeg目录到PATH
            ffmpeg_dir = str(Path(self.ffmpeg_exe).parent)
            current_path = os.environ.get('PATH', '')
            if ffmpeg_dir not in current_path:
                os.environ['PATH'] = f"{ffmpeg_dir}{os.pathsep}{current_path}"
            
            # 设置MoviePy和imageio的FFmpeg路径
            os.environ['FFMPEG_BINARY'] = self.ffmpeg_exe
            os.environ['IMAGEIO_FFMPEG_EXE'] = self.ffmpeg_exe
            
            # 配置MoviePy
            try:
                import moviepy.config as mpconfig
                mpconfig.FFMPEG_BINARY = self.ffmpeg_exe
                print("✅ MoviePy FFmpeg配置完成")
            except ImportError:
                print("⚠️ MoviePy未安装，跳过配置")
            
            # 配置imageio
            try:
                import imageio
                imageio.plugins.ffmpeg.download()
                print("✅ ImageIO FFmpeg配置完成")
            except ImportError:
                print("⚠️ ImageIO未安装，跳过配置")
    
    def get_ffmpeg_command(self, *args):
        """获取FFmpeg命令，配置为静默运行"""
        if not self.ffmpeg_exe:
            raise RuntimeError("FFmpeg不可用")
        
        return [self.ffmpeg_exe] + list(args)
    
    def run_ffmpeg_command(self, *args, **kwargs):
        """运行FFmpeg命令（静默模式）"""
        cmd = self.get_ffmpeg_command(*args)
        
        # 设置静默运行参数
        run_kwargs = {
            'startupinfo': self.startup_info,
            'creationflags': self.creation_flags,
            'capture_output': kwargs.get('capture_output', True),
            'text': kwargs.get('text', True),
            'encoding': kwargs.get('encoding', 'utf-8'),
            'errors': 'ignore'
        }
        
        # 移除自定义参数
        for key in ['capture_output', 'text', 'encoding']:
            kwargs.pop(key, None)
        
        # 合并参数
        run_kwargs.update(kwargs)
        
        try:
            result = subprocess.run(cmd, **run_kwargs)
            return result
        except Exception as e:
            print(f"❌ FFmpeg命令执行失败: {str(e)}")
            raise
    
    def test_ffmpeg(self):
        """测试FFmpeg是否正常工作"""
        if not self.ffmpeg_exe:
            return False
        
        try:
            result = self.run_ffmpeg_command('-version')
            if result.returncode == 0:
                print("✅ FFmpeg测试通过")
                return True
            else:
                print(f"❌ FFmpeg测试失败: {result.stderr}")
                return False
        except Exception as e:
            print(f"❌ FFmpeg测试异常: {str(e)}")
            return False
    
    def save_config(self):
        """保存FFmpeg配置"""
        config = {
            'ffmpeg_exe': self.ffmpeg_exe,
            'base_dir': str(self.base_dir),
            'version': self.get_ffmpeg_version()
        }
        
        config_file = self.base_dir / "ffmpeg_config.json"
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print(f"✅ FFmpeg配置已保存: {config_file}")
        except Exception as e:
            print(f"⚠️ 保存FFmpeg配置失败: {str(e)}")
    
    def get_ffmpeg_version(self):
        """获取FFmpeg版本信息"""
        if not self.ffmpeg_exe:
            return "未知"
        
        try:
            result = self.run_ffmpeg_command('-version')
            if result.returncode == 0:
                # 解析版本信息
                lines = result.stdout.split('\n')
                for line in lines:
                    if line.startswith('ffmpeg version'):
                        return line.split()[2]
            return "无法获取"
        except:
            return "无法获取"

# 全局FFmpeg配置实例
_ffmpeg_config = None

def get_ffmpeg_config():
    """获取全局FFmpeg配置实例"""
    global _ffmpeg_config
    if _ffmpeg_config is None:
        _ffmpeg_config = FFmpegConfig()
    return _ffmpeg_config

def initialize_ffmpeg_config():
    """初始化FFmpeg配置"""
    config = get_ffmpeg_config()
    config.test_ffmpeg()
    config.save_config()
    return config

def get_ffmpeg_startup_info():
    """获取FFmpeg启动信息（用于subprocess调用）"""
    config = get_ffmpeg_config()
    return config.startup_info, config.creation_flags

def run_ffmpeg_silent(*args, **kwargs):
    """静默运行FFmpeg命令"""
    config = get_ffmpeg_config()
    return config.run_ffmpeg_command(*args, **kwargs)

if __name__ == "__main__":
    # 测试FFmpeg配置
    print("🔧 测试FFmpeg配置...")
    config = initialize_ffmpeg_config()
    
    if config.ffmpeg_exe:
        print(f"FFmpeg路径: {config.ffmpeg_exe}")
        print(f"FFmpeg版本: {config.get_ffmpeg_version()}")
        print("✅ FFmpeg配置测试完成")
    else:
        print("❌ FFmpeg配置失败")