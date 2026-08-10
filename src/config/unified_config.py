#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
统一配置管理系统
根据开发规范：新功能需要支持配置持久化，并提供清晰的用户界面控件
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field
import logging
from datetime import datetime

# 尝试导入yaml，如果不可用则使用json
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    yaml = None

try:
    from ..models import VideoSettings, TransitionSettings, AudioSettings, WatermarkSettings
    from ..exceptions import ConfigurationError
except ImportError:
    # 兼容把 src 加入 PYTHONPATH 后以顶层包 `config` 导入的场景。
    from models import VideoSettings, TransitionSettings, AudioSettings, WatermarkSettings
    from exceptions import ConfigurationError
from .config_validator import ConfigValidator, ValidationLevel, TypeSafeConfig, create_validator

logger = logging.getLogger(__name__)

@dataclass
class ConfigPaths:
    """配置路径设置"""
    temp_dir: str = "output/temp"
    output_dir: str = "output/videos"
    ffmpeg_path: str = "tools/ffmpeg/bin/ffmpeg.exe"
    presets_dir: str = "config/presets"

@dataclass
class UIConfig:
    """UI配置"""
    window_title: str = "图片转视频工具 v2.1"
    window_size: str = "1200x800"
    min_window_size: List[int] = field(default_factory=lambda: [800, 600])
    theme: str = "default"
    language: str = "zh_CN"
    auto_save_interval: int = 300  # 秒

@dataclass
class PerformanceConfig:
    """性能配置"""
    enable_optimization: bool = True
    image_cache_size: int = 100
    image_cache_memory_mb: int = 500
    video_max_workers: int = 4
    enable_system_monitoring: bool = True
    monitoring_interval: float = 10.0
    auto_optimization: bool = True
    parallel_processing: bool = True

@dataclass
class AdvancedConfig:
    """高级配置"""
    debug_mode: bool = False
    log_level: str = "INFO"
    backup_configs: bool = True
    enable_telemetry: bool = False
    max_log_files: int = 10
    log_max_size_mb: int = 10

@dataclass
class AppConfig:
    """应用程序完整配置"""
    version: str = "2.1.0"
    
    # 核心配置
    video_settings: VideoSettings = field(default_factory=VideoSettings)
    transition_settings: TransitionSettings = field(default_factory=TransitionSettings)
    audio_settings: AudioSettings = field(default_factory=AudioSettings)
    watermark_settings: WatermarkSettings = field(default_factory=WatermarkSettings)
    
    # 系统配置
    paths: ConfigPaths = field(default_factory=ConfigPaths)
    ui: UIConfig = field(default_factory=UIConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)
    
    # 用户特定配置
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    
    # 元数据
    last_modified: datetime = field(default_factory=datetime.now)
    config_source: str = "default"

class ConfigManager:
    """统一配置管理器"""
    
    def __init__(self, config_dir: Path, validation_level: ValidationLevel = ValidationLevel.NORMAL):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # 配置文件路径
        self.default_config_path = self.config_dir / "default.yaml"
        self.user_config_path = self.config_dir / "user.yaml"
        self.legacy_json_path = self.config_dir / "default_settings.json"
        self.legacy_user_path = self.config_dir / "user.yaml"
        
        # 当前配置
        self._config: Optional[AppConfig] = None
        self._config_watchers: List[callable] = []
        
        # 配置验证器
        self._validator = create_validator(validation_level)
        self._type_safe_config: Optional[TypeSafeConfig] = None
        
        # 初始化配置
        self._initialize_config()
    
    def _initialize_config(self):
        """初始化配置系统"""
        try:
            # 迁移旧配置（如果存在）
            self._migrate_legacy_config()
            
            # 加载配置
            self._config = self._load_merged_config()
            
            # 验证配置
            self._validate_config()
            
            # 创建类型安全配置包装器
            self._create_type_safe_config()
            
            logger.info("✅ 配置管理系统初始化成功")
            
        except Exception as e:
            logger.error(f"❌ 配置初始化失败: {e}")
            # 使用默认配置
            self._config = AppConfig()
    
    def _migrate_legacy_config(self):
        """迁移旧的配置格式"""
        try:
            # 检查是否存在旧的JSON配置
            if self.legacy_json_path.exists() and not self.default_config_path.exists():
                logger.info("🔄 检测到旧的JSON配置，开始迁移...")
                
                with open(self.legacy_json_path, 'r', encoding='utf-8') as f:
                    legacy_data = json.load(f)
                
                # 转换为新的配置格式
                migrated_config = self._convert_legacy_config(legacy_data)
                
                # 保存为新格式
                self._save_config_to_file(migrated_config, self.default_config_path)
                
                logger.info("✅ 配置迁移完成")
                
        except Exception as e:
            logger.warning(f"⚠️ 配置迁移失败: {e}")
    
    def _convert_legacy_config(self, legacy_data: Dict) -> AppConfig:
        """转换旧配置格式到新格式"""
        config = AppConfig()
        
        # 视频设置
        if 'video' in legacy_data:
            video_data = legacy_data['video']
            config.video_settings = VideoSettings(
                fps=video_data.get('fps', 30),
                duration=video_data.get('duration', 3.0),
                transition_duration=video_data.get('transition_duration', 1.0),
                bitrate=video_data.get('bitrate', '5000k'),
                resolution=video_data.get('resolution', '1920x1080'),
                codec=video_data.get('codec', 'libx264')
            )
        
        # 路径设置
        if 'paths' in legacy_data:
            path_data = legacy_data['paths']
            config.paths = ConfigPaths(
                temp_dir=path_data.get('temp_dir', 'output/temp'),
                output_dir=path_data.get('output_dir', 'output/videos'),
                ffmpeg_path=path_data.get('ffmpeg_path', 'tools/ffmpeg/bin/ffmpeg.exe'),
                presets_dir=path_data.get('presets_dir', 'config/presets')
            )
        
        # UI设置
        if 'ui' in legacy_data:
            ui_data = legacy_data['ui']
            config.ui = UIConfig(
                window_title=ui_data.get('window_title', '图片转视频工具 v2.1'),
                window_size=ui_data.get('window_size', '1200x800'),
                min_window_size=ui_data.get('min_window_size', [800, 600]),
                theme=ui_data.get('theme', 'default')
            )
        
        # 性能设置
        if 'performance' in legacy_data:
            perf_data = legacy_data['performance']
            config.performance = PerformanceConfig(
                enable_optimization=perf_data.get('enable_optimization', True),
                image_cache_size=perf_data.get('image_cache_size', 100),
                image_cache_memory_mb=perf_data.get('image_cache_memory_mb', 500),
                video_max_workers=perf_data.get('video_max_workers', 4),
                enable_system_monitoring=perf_data.get('enable_system_monitoring', True),
                monitoring_interval=perf_data.get('monitoring_interval', 10.0),
                auto_optimization=perf_data.get('auto_optimization', True)
            )
        
        # 高级设置
        if 'advanced' in legacy_data:
            adv_data = legacy_data['advanced']
            config.advanced = AdvancedConfig(
                debug_mode=adv_data.get('debug_mode', False),
                log_level=adv_data.get('log_level', 'INFO'),
                backup_configs=adv_data.get('backup_configs', True)
            )
        
        config.last_modified = datetime.now()
        config.config_source = "migrated"
        
        return config
    
    def _load_merged_config(self) -> AppConfig:
        """加载并合并配置"""
        # 从默认配置开始
        config = self._load_default_config()
        
        # 合并用户配置
        if self.user_config_path.exists():
            user_config = self._load_user_config()
            config = self._merge_configs(config, user_config)
        
        return config
    
    def _load_default_config(self) -> AppConfig:
        """加载默认配置"""
        if self.default_config_path.exists():
            return self._load_config_from_file(self.default_config_path)
        else:
            # 创建默认配置
            config = AppConfig()
            self._save_config_to_file(config, self.default_config_path)
            return config
    
    def _load_user_config(self) -> AppConfig:
        """加载用户配置"""
        return self._load_config_from_file(self.user_config_path)
    
    def _load_config_from_file(self, file_path: Path) -> AppConfig:
        """从文件加载配置"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                if file_path.suffix.lower() == '.yaml' and YAML_AVAILABLE:
                    data = yaml.safe_load(f)
                else:
                    # 使用JSON格式
                    data = json.load(f)
            
            if not data:
                return AppConfig()
            
            # 转换为AppConfig对象
            return self._dict_to_config(data)
            
        except Exception as e:
            logger.error(f"❌ 配置文件加载失败 {file_path}: {e}")
            return AppConfig()
    
    def _dict_to_config(self, data: Dict) -> AppConfig:
        """将字典转换为AppConfig对象"""
        config = AppConfig()
        
        # 基本信息
        config.version = data.get('version', '2.1.0')
        config.config_source = data.get('config_source', 'file')
        
        # 各个配置部分
        if 'video_settings' in data:
            config.video_settings = self._dict_to_video_settings(data['video_settings'])
        
        if 'paths' in data:
            config.paths = ConfigPaths(**data['paths'])
        
        if 'ui' in data:
            config.ui = UIConfig(**data['ui'])
        
        if 'performance' in data:
            config.performance = PerformanceConfig(**data['performance'])
        
        if 'advanced' in data:
            config.advanced = AdvancedConfig(**data['advanced'])
        
        config.user_preferences = data.get('user_preferences', {})
        
        return config
    
    def _dict_to_video_settings(self, data: Dict) -> VideoSettings:
        """将字典转换为VideoSettings对象"""
        return VideoSettings(
            fps=data.get('fps', 30),
            duration=data.get('duration', 3.0),
            transition_duration=data.get('transition_duration', 1.0),
            bitrate=data.get('bitrate', '5000k'),
            resolution=data.get('resolution', '1920x1080'),
            codec=data.get('codec', 'libx264')
        )
    
    def _merge_configs(self, base: AppConfig, override: AppConfig) -> AppConfig:
        """合并两个配置"""
        # 简化的合并逻辑，实际应该更复杂
        merged = AppConfig()
        
        # 合并各个配置部分
        merged.version = override.version or base.version
        merged.video_settings = override.video_settings or base.video_settings
        merged.paths = override.paths or base.paths
        merged.ui = override.ui or base.ui
        merged.performance = override.performance or base.performance
        merged.advanced = override.advanced or base.advanced
        
        # 合并用户偏好
        merged.user_preferences = {**base.user_preferences, **override.user_preferences}
        
        merged.last_modified = datetime.now()
        merged.config_source = "merged"
        
        return merged
    
    def _save_config_to_file(self, config: AppConfig, file_path: Path):
        """保存配置到文件"""
        try:
            data = self._config_to_dict(config)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                if YAML_AVAILABLE:
                    yaml.dump(data, f, default_flow_style=False, allow_unicode=True, indent=2)
                else:
                    # 使用JSON格式
                    json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"✅ 配置已保存到 {file_path}")
            
        except Exception as e:
            logger.error(f"❌ 配置保存失败 {file_path}: {e}")
            raise ConfigurationError(f"配置保存失败: {e}")

    # 公共API
    def get_config(self) -> AppConfig:
        """获取当前配置"""
        if not self._config:
            raise ConfigurationError("配置未初始化")
        return self._config
    
    def update_config(self, **kwargs):
        """更新配置"""
        if not self._config:
            raise ConfigurationError("配置未初始化")
        
        # 更新指定的配置项
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        
        self._config.last_modified = datetime.now()
        
        # 触发配置变更事件
        self._notify_config_change()
    
    def save_user_config(self):
        """保存用户配置"""
        if not self._config:
            raise ConfigurationError("配置未初始化")
        
        self._save_config_to_file(self._config, self.user_config_path)
    
    def reset_to_defaults(self):
        """重置为默认配置"""
        self._config = AppConfig()
        self._notify_config_change()
    
    def add_config_watcher(self, callback: callable):
        """添加配置变更监听器"""
        self._config_watchers.append(callback)
    
    def remove_config_watcher(self, callback: callable):
        """移除配置变更监听器"""
        if callback in self._config_watchers:
            self._config_watchers.remove(callback)
    
    def _notify_config_change(self):
        """通知配置变更"""
        for callback in self._config_watchers:
            try:
                callback(self._config)
            except Exception as e:
                logger.error(f"配置变更通知失败: {e}")
    
    def export_config(self, file_path: Path):
        """导出配置"""
        self._save_config_to_file(self._config, file_path)
    
    def import_config(self, file_path: Path):
        """导入配置"""
        imported_config = self._load_config_from_file(file_path)
        self._config = imported_config
        self._validate_config()
        self._create_type_safe_config()
        self._notify_config_change()
    
    def _validate_config(self):
        """验证当前配置"""
        if not self._config:
            return
            
        try:
            # 转换为字典进行验证
            config_dict = self._config_to_dict(self._config)
            
            # 执行验证
            result = self._validator.validate_config(config_dict)
            
            # 处理验证结果
            if result.is_valid:
                logger.info(f"✅ 配置验证通过: {result.get_summary()}")
            else:
                logger.warning(f"⚠️ 配置验证失败: {result.get_summary()}")
                
                # 打印详细错误
                for error in result.errors:
                    logger.error(f"配置错误: {error}")
                    
                for warning in result.warnings:
                    logger.warning(f"配置警告: {warning}")
            
            # 应用修复的值
            if result.fixed_values:
                logger.info(f"应用配置修复: {len(result.fixed_values)}个")
                self._config = self._dict_to_config(config_dict)
                
        except Exception as e:
            logger.error(f"配置验证异常: {e}")
    
    def _create_type_safe_config(self):
        """创建类型安全的配置包装器"""
        if self._config:
            config_dict = self._config_to_dict(self._config)
            self._type_safe_config = TypeSafeConfig(config_dict, self._validator)
            validation_result = self._type_safe_config.validate()
            
            if not validation_result.is_valid:
                logger.warning(f"类型安全配置创建警告: {validation_result.get_summary()}")
    
    def get_safe_config(self) -> Optional[TypeSafeConfig]:
        """获取类型安全的配置"""
        return self._type_safe_config
    
    def validate_field(self, field_path: str, value: Any) -> bool:
        """验证单个字段"""
        if not self._type_safe_config:
            return False
            
        return self._type_safe_config.set(field_path, value)
    
    def _config_to_dict(self, config: AppConfig) -> Dict[str, Any]:
        """将配置对象转换为字典"""
        result = {
            'version': config.version,
            'config_source': config.config_source,
            'last_modified': config.last_modified.isoformat(),
            'user_preferences': config.user_preferences
        }
        
        # 视频设置
        if config.video_settings:
            result['video_settings'] = {
                'fps': config.video_settings.fps,
                'duration': config.video_settings.duration,
                'transition_duration': config.video_settings.transition_duration,
                'bitrate': config.video_settings.bitrate,
                'resolution': config.video_settings.resolution,
                'codec': config.video_settings.codec
            }
        
        # 转场设置
        if config.transition_settings:
            result['transition_settings'] = {
                'enabled': config.transition_settings.enabled,
                'random_order': getattr(config.transition_settings, 'random_order', False)
            }
        
        # 音频设置
        if config.audio_settings:
            result['audio_settings'] = {
                'enabled': config.audio_settings.enabled,
                'volume': config.audio_settings.volume
            }
        
        # 水印设置
        if config.watermark_settings:
            result['watermark_settings'] = {
                'enabled': config.watermark_settings.enabled,
                'position': config.watermark_settings.position
            }
        
        # 路径设置
        if config.paths:
            result['paths'] = {
                'temp_dir': config.paths.temp_dir,
                'output_dir': config.paths.output_dir,
                'ffmpeg_path': config.paths.ffmpeg_path,
                'presets_dir': config.paths.presets_dir
            }
        
        # UI设置
        if config.ui:
            result['ui'] = {
                'window_title': config.ui.window_title,
                'window_size': config.ui.window_size,
                'min_window_size': config.ui.min_window_size,
                'theme': config.ui.theme,
                'language': getattr(config.ui, 'language', 'zh_CN'),
                'auto_save_interval': getattr(config.ui, 'auto_save_interval', 300)
            }
        
        # 性能设置
        if config.performance:
            result['performance'] = {
                'enable_optimization': config.performance.enable_optimization,
                'image_cache_size': config.performance.image_cache_size,
                'image_cache_memory_mb': config.performance.image_cache_memory_mb,
                'video_max_workers': config.performance.video_max_workers,
                'enable_system_monitoring': config.performance.enable_system_monitoring,
                'monitoring_interval': config.performance.monitoring_interval,
                'auto_optimization': config.performance.auto_optimization,
                'parallel_processing': getattr(config.performance, 'parallel_processing', True)
            }
        
        # 高级设置
        if config.advanced:
            result['advanced'] = {
                'debug_mode': config.advanced.debug_mode,
                'log_level': config.advanced.log_level,
                'backup_configs': config.advanced.backup_configs,
                'enable_telemetry': getattr(config.advanced, 'enable_telemetry', False),
                'max_log_files': getattr(config.advanced, 'max_log_files', 10),
                'log_max_size_mb': getattr(config.advanced, 'log_max_size_mb', 10)
            }
        
        return result
    
    def get_validation_report(self) -> Dict[str, Any]:
        """获取配置验证报告"""
        if not self._config:
            return {'status': 'no_config', 'message': '配置未加载'}
            
        config_dict = self._config_to_dict(self._config)
        result = self._validator.validate_config(config_dict)
        
        return {
            'status': 'valid' if result.is_valid else 'invalid',
            'summary': result.get_summary(),
            'errors': result.errors,
            'warnings': result.warnings,
            'fixes': result.fixed_values,
            'total_rules': len(self._validator.rules),
            'validation_time': datetime.now().isoformat()
        }
