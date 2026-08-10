#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
配置常量模块 - 统一管理所有常量和配置
"""

# 转场效果类型定义
TRANSITION_TYPES = [
    "淡入淡出",     # 基本淡入淡出
    "左右滑动",     # 水平方向滑动
    "上下滑动",     # 垂直方向滑动
    "交叉溶解",     # 两张图片交叉溶解
    "缩放过渡",     # 缩放效果
    "方块过渡",     # 方块形状过渡
    "圆形扩展",     # 圆形扩展效果
    "交错效果",     # 交错线条效果
    "像素化",       # 像素化过渡
    "旋转变换",     # 旋转变换效果
    "百叶窗垂直",   # 垂直百叶窗效果
    "棋盘格",       # 棋盘格过渡
    "流水扩散",     # 从一点向外扩散
    "颜色混合",     # 颜色混合过渡
    "波浪",         # 波浪形状过渡
]

# 界面名称与实际效果名称的映射关系
UI_TO_EFFECT_MAP = {
    "淡入淡出": "淡入淡出",
    "左右滑动": "左右滑动",
    "上下滑动": "上下滑动",
    "交叉溶解": "交叉溶解",
    "缩放过渡": "缩放过渡",
    "方块过渡": "方块过渡",
    "圆形扩展": "圆形扩展",
    "百叶窗": "交错效果",       # 百叶窗效果映射到交错效果
    "像素化": "像素化",
    "旋转变换": "旋转变换",
    "垂直百叶窗": "百叶窗垂直",
    "棋盘格效果": "棋盘格",
    "水波扩散": "流水扩散",
    "颜色混合": "颜色混合",
    "波浪效果": "波浪"
}

# 默认启用的转场效果
DEFAULT_ENABLED_TRANSITIONS = [
    "淡入淡出", "左右滑动", "交叉溶解", 
    "缩放过渡", "圆形扩展", "交错效果"
]

# 视频处理默认参数
class VideoDefaults:
    FPS = 30
    DURATION = 3
    TRANSITION_DURATION = 1
    BITRATE = "5000k"
    RESOLUTION = "1920x1080"
    VIDEO_FORMAT = "mp4"
    CODEC = "libx264"

# 文件和目录配置
class PathConfig:
    TEMP_DIR = "temp"
    OUTPUT_DIR = "output"
    PRESETS_DIR = "presets"
    FFMPEG_DIR = "ffmpeg"
    
    # 支持的图片格式
    SUPPORTED_IMAGE_FORMATS = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp']
    
    # 支持的视频格式
    SUPPORTED_VIDEO_FORMATS = ['.mp4', '.avi', '.mov', '.mkv']
    
    # 支持的音频格式
    SUPPORTED_AUDIO_FORMATS = ['.mp3', '.wav', '.aac', '.flac']

# 界面配置
class UIConfig:
    WINDOW_TITLE = "图片转视频工具"
    WINDOW_SIZE = "1200x800"
    MIN_WINDOW_SIZE = (800, 600)
    
    # 控件尺寸
    BUTTON_WIDTH = 12
    ENTRY_WIDTH = 20
    LISTBOX_HEIGHT = 10
    
    # 颜色主题
    PRIMARY_COLOR = "#2196F3"
    SUCCESS_COLOR = "#4CAF50"
    WARNING_COLOR = "#FF9800"
    ERROR_COLOR = "#F44336"

# 性能配置
class PerformanceConfig:
    # 图片缓存配置
    IMAGE_CACHE_SIZE = 50  # 最大缓存图片数量
    
    # 线程池配置
    MAX_WORKER_THREADS = 4
    
    # 内存管理
    MEMORY_CLEANUP_INTERVAL = 100  # 每处理多少张图片后清理内存
    
    # 进度更新频率
    PROGRESS_UPDATE_INTERVAL = 0.1  # 秒

# 日志配置
class LogConfig:
    LOG_LEVEL = "INFO"
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_FILE = "video_processor.log"
    MAX_LOG_SIZE = 10 * 1024 * 1024  # 10MB
    BACKUP_COUNT = 5

# 错误消息
class ErrorMessages:
    INVALID_INPUT_DIR = "输入目录不存在或无效"
    INVALID_OUTPUT_DIR = "输出目录无效"
    NO_IMAGES_FOUND = "在输入目录中未找到支持的图片文件"
    INSUFFICIENT_IMAGES = "图片数量不足，至少需要2张图片"
    PROCESSING_ERROR = "视频处理过程中发生错误"
    MEMORY_ERROR = "内存不足，请减少图片数量或降低分辨率"
    DISK_SPACE_ERROR = "磁盘空间不足"
    PERMISSION_ERROR = "文件权限不足"

# 成功消息
class SuccessMessages:
    VIDEO_CREATED = "视频创建成功"
    BATCH_COMPLETED = "批量处理完成"
    SETTINGS_SAVED = "设置已保存"
    CACHE_CLEARED = "缓存已清理"

# 验证规则
class ValidationRules:
    MIN_FPS = 1
    MAX_FPS = 60
    MIN_DURATION = 0.1
    MAX_DURATION = 10.0
    MIN_TRANSITION_DURATION = 0.1
    MAX_TRANSITION_DURATION = 5.0
    MIN_BITRATE = 500
    MAX_BITRATE = 50000
    
    # 分辨率选项
    RESOLUTION_OPTIONS = [
        "1920x1080", "1280x720", "854x480", 
        "640x360", "3840x2160", "2560x1440"
    ]
    
    # 码率选项
    BITRATE_OPTIONS = [
        "1000k", "2000k", "3000k", "5000k", 
        "8000k", "10000k", "15000k", "20000k"
    ]

# 功能开关
class FeatureFlags:
    ENABLE_WATERMARK = True
    ENABLE_BACKGROUND_MUSIC = True
    ENABLE_BATCH_PROCESSING = True
    ENABLE_PREVIEW = False  # 预览功能暂时禁用
    ENABLE_GPU_ACCELERATION = False  # GPU加速暂时禁用
    ENABLE_ADVANCED_EFFECTS = True

# 调试配置
class DebugConfig:
    ENABLE_DEBUG_MODE = False
    SAVE_INTERMEDIATE_FRAMES = False
    VERBOSE_LOGGING = False
    PROFILE_PERFORMANCE = False

# 获取配置的便捷函数
def get_default_settings():
    """获取默认设置字典"""
    return {
        'fps': VideoDefaults.FPS,
        'duration': VideoDefaults.DURATION,
        'transition_duration': VideoDefaults.TRANSITION_DURATION,
        'bitrate': VideoDefaults.BITRATE,
        'resolution': VideoDefaults.RESOLUTION,
        'video_format': VideoDefaults.VIDEO_FORMAT,
        'enabled_transitions': DEFAULT_ENABLED_TRANSITIONS.copy()
    }

def get_supported_formats():
    """获取所有支持的文件格式"""
    return {
        'images': PathConfig.SUPPORTED_IMAGE_FORMATS,
        'videos': PathConfig.SUPPORTED_VIDEO_FORMATS,
        'audio': PathConfig.SUPPORTED_AUDIO_FORMATS
    }

def validate_settings(settings):
    """验证设置是否有效"""
    errors = []
    
    # 验证FPS
    if not (ValidationRules.MIN_FPS <= settings.get('fps', 0) <= ValidationRules.MAX_FPS):
        errors.append(f"FPS必须在{ValidationRules.MIN_FPS}-{ValidationRules.MAX_FPS}之间")
    
    # 验证时长
    if not (ValidationRules.MIN_DURATION <= settings.get('duration', 0) <= ValidationRules.MAX_DURATION):
        errors.append(f"图片显示时长必须在{ValidationRules.MIN_DURATION}-{ValidationRules.MAX_DURATION}秒之间")
    
    # 验证转场时长
    if not (ValidationRules.MIN_TRANSITION_DURATION <= settings.get('transition_duration', 0) <= ValidationRules.MAX_TRANSITION_DURATION):
        errors.append(f"转场时长必须在{ValidationRules.MIN_TRANSITION_DURATION}-{ValidationRules.MAX_TRANSITION_DURATION}秒之间")
    
    return errors

# 版本信息
VERSION = "2.0.0"
BUILD_DATE = "2025-08-15"
AUTHOR = "图片转视频工具开发团队"
