#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
配置验证和类型安全系统
提供严格的配置验证、类型检查和安全性保障
"""

import re
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple, Type
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class ValidationLevel(Enum):
    """验证级别"""
    STRICT = "strict"      # 严格验证，任何错误都失败
    NORMAL = "normal"      # 正常验证，尝试修复
    LENIENT = "lenient"    # 宽松验证，仅警告

class ValidationResult:
    """验证结果"""
    
    def __init__(self):
        self.is_valid = True
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.fixed_values: Dict[str, Any] = {}
        
    def add_error(self, message: str):
        """添加错误"""
        self.errors.append(message)
        self.is_valid = False
        
    def add_warning(self, message: str):
        """添加警告"""
        self.warnings.append(message)
        
    def add_fix(self, key: str, old_value: Any, new_value: Any):
        """添加修复"""
        self.fixed_values[key] = {
            'old': old_value,
            'new': new_value
        }
        
    def get_summary(self) -> str:
        """获取验证摘要"""
        summary = []
        if self.is_valid:
            summary.append("✅ 配置验证通过")
        else:
            summary.append("❌ 配置验证失败")
            
        if self.errors:
            summary.append(f"错误: {len(self.errors)}个")
        if self.warnings:
            summary.append(f"警告: {len(self.warnings)}个")
        if self.fixed_values:
            summary.append(f"修复: {len(self.fixed_values)}个")
            
        return " | ".join(summary)

@dataclass
class ValidationRule:
    """验证规则"""
    field_path: str                    # 字段路径，如 "video.fps"
    validator_type: str                # 验证器类型
    required: bool = True              # 是否必需
    default_value: Any = None          # 默认值
    constraints: Dict[str, Any] = field(default_factory=dict)  # 约束条件
    custom_validator: Optional[callable] = None  # 自定义验证器
    description: str = ""              # 描述

class ConfigValidator:
    """配置验证器"""
    
    def __init__(self, validation_level: ValidationLevel = ValidationLevel.NORMAL):
        self.validation_level = validation_level
        self.rules: Dict[str, ValidationRule] = {}
        self._setup_default_rules()
        
    def _setup_default_rules(self):
        """设置默认验证规则"""
        
        # 视频设置验证规则
        self.add_rule("video_settings.fps", "integer", 
                     constraints={"min": 1, "max": 120}, 
                     default_value=30,
                     description="视频帧率")
        
        self.add_rule("video_settings.duration", "float",
                     constraints={"min": 0.1, "max": 60.0},
                     default_value=3.0,
                     description="图片显示时长")
        
        self.add_rule("video_settings.transition_duration", "float",
                     constraints={"min": 0.0, "max": 5.0},
                     default_value=1.0,
                     description="转场时长")
        
        self.add_rule("video_settings.bitrate", "bitrate",
                     default_value="5000k",
                     description="视频比特率")
        
        self.add_rule("video_settings.resolution", "resolution",
                     default_value="1920x1080",
                     description="视频分辨率")
        
        self.add_rule("video_settings.codec", "string",
                     constraints={"choices": ["libx264", "libx265", "mpeg4", "libvpx"]},
                     default_value="libx264",
                     description="视频编码器")
        
        # 转场设置验证规则
        self.add_rule("transition_settings.enabled", "list",
                     constraints={"item_type": "string"},
                     default_value=["淡入淡出", "左右滑动"],
                     description="启用的转场效果")
        
        # 音频设置验证规则
        self.add_rule("audio_settings.enabled", "boolean",
                     default_value=False,
                     description="是否启用音频")
        
        self.add_rule("audio_settings.volume", "float",
                     constraints={"min": 0.0, "max": 2.0},
                     default_value=1.0,
                     description="音频音量")
        
        # 水印设置验证规则
        self.add_rule("watermark_settings.enabled", "boolean",
                     default_value=False,
                     description="是否启用水印")
        
        self.add_rule("watermark_settings.position", "string",
                     constraints={"choices": ["左上", "右上", "左下", "右下", "中心"]},
                     default_value="右下",
                     description="水印位置")
        
        # 路径设置验证规则
        self.add_rule("paths.temp_dir", "path",
                     default_value="output/temp",
                     description="临时目录")
        
        self.add_rule("paths.output_dir", "path",
                     default_value="output/videos",
                     description="输出目录")
        
        self.add_rule("paths.ffmpeg_path", "file_path",
                     default_value="tools/ffmpeg/bin/ffmpeg.exe",
                     description="FFmpeg路径")
        
        # UI设置验证规则
        self.add_rule("ui.window_size", "window_size",
                     default_value="1200x800",
                     description="窗口大小")
        
        self.add_rule("ui.theme", "string",
                     constraints={"choices": ["default", "dark", "light"]},
                     default_value="default",
                     description="界面主题")
        
        self.add_rule("ui.language", "string",
                     constraints={"choices": ["zh_CN", "en_US"]},
                     default_value="zh_CN",
                     description="界面语言")
        
        # 性能设置验证规则
        self.add_rule("performance.image_cache_size", "integer",
                     constraints={"min": 10, "max": 1000},
                     default_value=100,
                     description="图片缓存大小")
        
        self.add_rule("performance.image_cache_memory_mb", "integer",
                     constraints={"min": 50, "max": 2048},
                     default_value=500,
                     description="图片缓存内存限制")
        
        self.add_rule("performance.video_max_workers", "integer",
                     constraints={"min": 1, "max": 16},
                     default_value=4,
                     description="视频处理最大线程数")
        
        # 高级设置验证规则
        self.add_rule("advanced.log_level", "string",
                     constraints={"choices": ["DEBUG", "INFO", "WARNING", "ERROR"]},
                     default_value="INFO",
                     description="日志级别")
        
        self.add_rule("advanced.max_log_files", "integer",
                     constraints={"min": 1, "max": 50},
                     default_value=10,
                     description="最大日志文件数")
        
    def add_rule(self, field_path: str, validator_type: str, **kwargs):
        """添加验证规则"""
        rule = ValidationRule(
            field_path=field_path,
            validator_type=validator_type,
            **kwargs
        )
        self.rules[field_path] = rule
        
    def validate_config(self, config_data: Dict[str, Any]) -> ValidationResult:
        """验证完整配置"""
        result = ValidationResult()
        
        try:
            # 验证所有规则
            for field_path, rule in self.rules.items():
                self._validate_field(config_data, field_path, rule, result)
            
            # 检查未知字段
            self._check_unknown_fields(config_data, result)
            
            logger.info(f"配置验证完成: {result.get_summary()}")
            
        except Exception as e:
            result.add_error(f"验证过程发生异常: {e}")
            logger.error(f"配置验证异常: {e}")
            
        return result
    
    def _validate_field(self, config_data: Dict, field_path: str, rule: ValidationRule, result: ValidationResult):
        """验证单个字段"""
        try:
            # 获取字段值
            value = self._get_nested_value(config_data, field_path)
            
            # 检查必需字段
            if value is None:
                if rule.required:
                    if rule.default_value is not None:
                        # 使用默认值
                        self._set_nested_value(config_data, field_path, rule.default_value)
                        result.add_fix(field_path, None, rule.default_value)
                        value = rule.default_value
                    else:
                        result.add_error(f"必需字段缺失: {field_path}")
                        return
                else:
                    return  # 可选字段为空，跳过验证
            
            # 类型和值验证
            validated_value = self._validate_value(value, rule, result)
            
            # 如果值被修改，更新配置
            if validated_value != value:
                self._set_nested_value(config_data, field_path, validated_value)
                result.add_fix(field_path, value, validated_value)
                
        except Exception as e:
            result.add_error(f"字段 {field_path} 验证失败: {e}")
    
    def _validate_value(self, value: Any, rule: ValidationRule, result: ValidationResult) -> Any:
        """验证值"""
        validator_method = getattr(self, f"_validate_{rule.validator_type}", None)
        if validator_method:
            return validator_method(value, rule, result)
        else:
            result.add_warning(f"未知验证器类型: {rule.validator_type}")
            return value
    
    def _validate_integer(self, value: Any, rule: ValidationRule, result: ValidationResult) -> int:
        """验证整数"""
        try:
            int_value = int(value)
            
            # 范围检查
            if "min" in rule.constraints and int_value < rule.constraints["min"]:
                int_value = rule.constraints["min"]
                result.add_warning(f"值 {value} 小于最小值 {rule.constraints['min']}，已修正")
                
            if "max" in rule.constraints and int_value > rule.constraints["max"]:
                int_value = rule.constraints["max"]
                result.add_warning(f"值 {value} 大于最大值 {rule.constraints['max']}，已修正")
                
            return int_value
            
        except (ValueError, TypeError):
            result.add_error(f"无法转换为整数: {value}")
            return rule.default_value or 0
    
    def _validate_float(self, value: Any, rule: ValidationRule, result: ValidationResult) -> float:
        """验证浮点数"""
        try:
            float_value = float(value)
            
            # 范围检查
            if "min" in rule.constraints and float_value < rule.constraints["min"]:
                float_value = rule.constraints["min"]
                result.add_warning(f"值 {value} 小于最小值 {rule.constraints['min']}，已修正")
                
            if "max" in rule.constraints and float_value > rule.constraints["max"]:
                float_value = rule.constraints["max"]
                result.add_warning(f"值 {value} 大于最大值 {rule.constraints['max']}，已修正")
                
            return float_value
            
        except (ValueError, TypeError):
            result.add_error(f"无法转换为浮点数: {value}")
            return rule.default_value or 0.0
    
    def _validate_boolean(self, value: Any, rule: ValidationRule, result: ValidationResult) -> bool:
        """验证布尔值"""
        if isinstance(value, bool):
            return value
        elif isinstance(value, str):
            if value.lower() in ['true', '1', 'yes', 'on']:
                return True
            elif value.lower() in ['false', '0', 'no', 'off']:
                return False
        elif isinstance(value, (int, float)):
            return bool(value)
            
        result.add_error(f"无法转换为布尔值: {value}")
        return rule.default_value or False
    
    def _validate_string(self, value: Any, rule: ValidationRule, result: ValidationResult) -> str:
        """验证字符串"""
        str_value = str(value)
        
        # 选择限制
        if "choices" in rule.constraints:
            if str_value not in rule.constraints["choices"]:
                result.add_warning(f"值 '{str_value}' 不在允许的选择中，使用默认值")
                return rule.default_value or ""
                
        # 长度限制
        if "min_length" in rule.constraints and len(str_value) < rule.constraints["min_length"]:
            result.add_error(f"字符串长度不足: {len(str_value)} < {rule.constraints['min_length']}")
            
        if "max_length" in rule.constraints and len(str_value) > rule.constraints["max_length"]:
            result.add_error(f"字符串长度超限: {len(str_value)} > {rule.constraints['max_length']}")
            
        return str_value
    
    def _validate_list(self, value: Any, rule: ValidationRule, result: ValidationResult) -> List:
        """验证列表"""
        if not isinstance(value, list):
            try:
                list_value = list(value)
            except (TypeError, ValueError):
                result.add_error(f"无法转换为列表: {value}")
                return rule.default_value or []
        else:
            list_value = value
            
        # 项目类型检查
        if "item_type" in rule.constraints:
            item_type = rule.constraints["item_type"]
            cleaned_list = []
            for item in list_value:
                if item_type == "string":
                    cleaned_list.append(str(item))
                elif item_type == "integer":
                    try:
                        cleaned_list.append(int(item))
                    except (ValueError, TypeError):
                        result.add_warning(f"列表项无法转换为整数: {item}")
                # 添加更多类型支持...
                else:
                    cleaned_list.append(item)
            list_value = cleaned_list
            
        return list_value
    
    def _validate_path(self, value: Any, rule: ValidationRule, result: ValidationResult) -> str:
        """验证路径"""
        path_str = str(value)
        path_obj = Path(path_str)
        
        # 创建目录（如果不存在）
        try:
            if not path_obj.exists():
                path_obj.mkdir(parents=True, exist_ok=True)
                result.add_warning(f"创建目录: {path_str}")
        except Exception as e:
            result.add_warning(f"无法创建目录 {path_str}: {e}")
            
        return path_str
    
    def _validate_file_path(self, value: Any, rule: ValidationRule, result: ValidationResult) -> str:
        """验证文件路径"""
        file_path = str(value)
        
        # 检查文件是否存在
        if not Path(file_path).exists():
            result.add_warning(f"文件不存在: {file_path}")
            
        return file_path
    
    def _validate_bitrate(self, value: Any, rule: ValidationRule, result: ValidationResult) -> str:
        """验证比特率"""
        bitrate_str = str(value)
        
        # 检查格式
        if not re.match(r'^\d+[kKmM]?$', bitrate_str):
            result.add_warning(f"比特率格式不正确: {bitrate_str}，使用默认值")
            return rule.default_value or "5000k"
            
        return bitrate_str
    
    def _validate_resolution(self, value: Any, rule: ValidationRule, result: ValidationResult) -> str:
        """验证分辨率"""
        resolution_str = str(value)
        
        # 检查格式
        if not re.match(r'^\d+x\d+$', resolution_str):
            result.add_warning(f"分辨率格式不正确: {resolution_str}，使用默认值")
            return rule.default_value or "1920x1080"
            
        # 检查常见分辨率
        width, height = map(int, resolution_str.split('x'))
        if width < 320 or height < 240:
            result.add_warning("分辨率过小，可能影响视频质量")
        elif width > 3840 or height > 2160:
            result.add_warning("分辨率过大，可能影响处理性能")
            
        return resolution_str
    
    def _validate_window_size(self, value: Any, rule: ValidationRule, result: ValidationResult) -> str:
        """验证窗口大小"""
        return self._validate_resolution(value, rule, result)
    
    def _get_nested_value(self, data: Dict, field_path: str) -> Any:
        """获取嵌套字段值"""
        keys = field_path.split('.')
        current = data
        
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
                
        return current
    
    def _set_nested_value(self, data: Dict, field_path: str, value: Any):
        """设置嵌套字段值"""
        keys = field_path.split('.')
        current = data
        
        # 导航到父级字典
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
            
        # 设置值
        current[keys[-1]] = value
    
    def _check_unknown_fields(self, config_data: Dict, result: ValidationResult):
        """检查未知字段"""
        # 这里可以实现检查配置中是否有未定义的字段
        # 暂时跳过，因为配置结构比较复杂
        pass

class TypeSafeConfig:
    """类型安全的配置包装器"""
    
    def __init__(self, config_data: Dict[str, Any], validator: ConfigValidator):
        self._data = config_data
        self._validator = validator
        self._validated = False
        
    def validate(self) -> ValidationResult:
        """验证配置"""
        result = self._validator.validate_config(self._data)
        self._validated = True
        return result
    
    def get(self, field_path: str, default: Any = None) -> Any:
        """安全获取配置值"""
        if not self._validated:
            raise RuntimeError("配置未验证，请先调用 validate() 方法")
            
        return self._validator._get_nested_value(self._data, field_path) or default
    
    def set(self, field_path: str, value: Any) -> bool:
        """安全设置配置值"""
        try:
            rule = self._validator.rules.get(field_path)
            if rule:
                result = ValidationResult()
                validated_value = self._validator._validate_value(value, rule, result)
                
                if result.is_valid:
                    self._validator._set_nested_value(self._data, field_path, validated_value)
                    return True
                else:
                    logger.warning(f"设置配置失败: {result.errors}")
                    return False
            else:
                # 没有验证规则，直接设置
                self._validator._set_nested_value(self._data, field_path, value)
                return True
                
        except Exception as e:
            logger.error(f"设置配置异常: {e}")
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self._data.copy()

def create_validator(level: ValidationLevel = ValidationLevel.NORMAL) -> ConfigValidator:
    """创建配置验证器"""
    return ConfigValidator(level)

def validate_config_file(config_path: Path, level: ValidationLevel = ValidationLevel.NORMAL) -> ValidationResult:
    """验证配置文件"""
    try:
        validator = create_validator(level)
        
        # 读取配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            if config_path.suffix.lower() == '.yaml':
                try:
                    import yaml
                    config_data = yaml.safe_load(f)
                except ImportError:
                    # 如果yaml模块不可用，尝试作为JSON读取
                    f.seek(0)
                    import json
                    config_data = json.load(f)
            else:
                import json
                config_data = json.load(f)
        
        # 验证配置
        return validator.validate_config(config_data)
        
    except Exception as e:
        result = ValidationResult()
        result.add_error(f"读取配置文件失败: {e}")
        return result