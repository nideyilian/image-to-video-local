#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
独立配置验证测试
不依赖复杂的导入结构
"""

import json
from pathlib import Path
import tempfile
import sys
import os
from typing import Dict, Any, List, Optional

def test_standalone_validation():
    """测试独立配置验证"""
    print("🧪 测试独立配置验证...")
    
    # 基本验证规则
    validation_rules = {
        "fps": {"type": "int", "min": 1, "max": 120, "default": 30},
        "duration": {"type": "float", "min": 0.1, "max": 60.0, "default": 3.0},
        "bitrate": {"type": "string", "pattern": r"^\d+[kKmM]?$", "default": "5000k"},
        "resolution": {"type": "string", "pattern": r"^\d+x\d+$", "default": "1920x1080"},
        "theme": {"type": "string", "choices": ["default", "dark", "light"], "default": "default"}
    }
    
    def validate_value(value, rule):
        """简单的值验证"""
        try:
            if rule["type"] == "int":
                val = int(value)
                if val < rule.get("min", float('-inf')) or val > rule.get("max", float('inf')):
                    return False, f"值超出范围: {rule.get('min', 'N/A')} - {rule.get('max', 'N/A')}"
                return True, val
            elif rule["type"] == "float":
                val = float(value)
                if val < rule.get("min", float('-inf')) or val > rule.get("max", float('inf')):
                    return False, f"值超出范围: {rule.get('min', 'N/A')} - {rule.get('max', 'N/A')}"
                return True, val
            elif rule["type"] == "string":
                val = str(value)
                if "choices" in rule and val not in rule["choices"]:
                    return False, f"值不在允许选择中: {rule['choices']}"
                if "pattern" in rule:
                    import re
                    if not re.match(rule["pattern"], val):
                        return False, "格式不正确"
                return True, val
            return True, value
        except Exception as e:
            return False, str(e)
    
    # 测试用例
    test_cases = [
        ("fps", 30, True),
        ("fps", "invalid", False),
        ("fps", 150, False),
        ("duration", 3.5, True),
        ("duration", "invalid", False),
        ("bitrate", "5000k", True),
        ("bitrate", "invalid_bitrate", False),
        ("resolution", "1920x1080", True),
        ("resolution", "invalid_resolution", False),
        ("theme", "dark", True),
        ("theme", "invalid_theme", False),
    ]
    
    passed = 0
    total = len(test_cases)
    
    for field, value, expected in test_cases:
        rule = validation_rules.get(field, {})
        is_valid, result = validate_value(value, rule)
        
        if is_valid == expected:
            print(f"✅ {field}={value}: {'通过' if is_valid else '失败'} (预期: {'通过' if expected else '失败'})")
            passed += 1
        else:
            print(f"❌ {field}={value}: {'通过' if is_valid else '失败'} (预期: {'通过' if expected else '失败'}) - {result}")
    
    print(f"📊 验证测试: {passed}/{total} 通过")
    return passed == total

def test_config_structure():
    """测试配置结构"""
    print("\n🧪 测试配置结构...")
    
    # 标准配置结构
    standard_config = {
        "version": "2.1.0",
        "video_settings": {
            "fps": 30,
            "duration": 3.0,
            "bitrate": "5000k",
            "resolution": "1920x1080",
            "codec": "libx264"
        },
        "ui": {
            "theme": "default",
            "window_size": "1200x800"
        },
        "performance": {
            "image_cache_size": 100,
            "video_max_workers": 4
        }
    }
    
    def validate_structure(config, required_fields):
        """验证配置结构"""
        errors = []
        
        for field_path in required_fields:
            keys = field_path.split('.')
            current = config
            
            for key in keys:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    errors.append(f"缺少必需字段: {field_path}")
                    break
        
        return len(errors) == 0, errors
    
    required_fields = [
        "version",
        "video_settings.fps",
        "video_settings.duration",
        "ui.theme",
        "performance.image_cache_size"
    ]
    
    is_valid, errors = validate_structure(standard_config, required_fields)
    
    if is_valid:
        print("✅ 配置结构验证通过")
    else:
        print(f"❌ 配置结构验证失败: {errors}")
    
    return is_valid

def test_config_file_operations():
    """测试配置文件操作"""
    print("\n🧪 测试配置文件操作...")
    
    test_config = {
        "version": "2.1.0",
        "video_settings": {"fps": 30, "duration": 3.0},
        "test_timestamp": "2025-09-04T12:00:00"
    }
    
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "test_config.json"
            
            # 保存配置
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(test_config, f, indent=2, ensure_ascii=False)
            print("✅ 配置保存成功")
            
            # 读取配置
            with open(config_file, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
            
            if loaded_config == test_config:
                print("✅ 配置读取成功")
                return True
            else:
                print("❌ 配置内容不匹配")
                return False
                
    except Exception as e:
        print(f"❌ 配置文件操作失败: {e}")
        return False

def test_type_safety():
    """测试基本类型安全"""
    print("\n🧪 测试基本类型安全...")
    
    class TypeSafeDict:
        def __init__(self, data, type_definitions):
            self._data = data
            self._types = type_definitions
            
        def get(self, key, default=None):
            return self._data.get(key, default)
            
        def set(self, key, value):
            if key in self._types:
                expected_type = self._types[key]
                if isinstance(value, expected_type):
                    self._data[key] = value
                    return True
                else:
                    print(f"类型错误: {key} 期望 {expected_type.__name__}，得到 {type(value).__name__}")
                    return False
            else:
                self._data[key] = value
                return True
    
    # 测试类型安全字典
    type_defs = {
        "fps": int,
        "duration": float,
        "theme": str
    }
    
    safe_dict = TypeSafeDict({"fps": 30, "duration": 3.0, "theme": "default"}, type_defs)
    
    # 测试类型安全操作
    tests = [
        ("fps", 60, True),  # 正确类型
        ("fps", "invalid", False),  # 错误类型
        ("duration", 5.5, True),  # 正确类型
        ("duration", "invalid", False),  # 错误类型
        ("theme", "dark", True),  # 正确类型
        ("theme", 123, False),  # 错误类型
    ]
    
    passed = 0
    for key, value, expected in tests:
        result = safe_dict.set(key, value)
        if result == expected:
            status = "✅" if result else "⚠️"
            print(f"{status} 设置 {key}={value}: {'成功' if result else '失败'}")
            passed += 1
        else:
            print(f"❌ 设置 {key}={value}: 预期 {'成功' if expected else '失败'}，实际 {'成功' if result else '失败'}")
    
    print(f"📊 类型安全测试: {passed}/{len(tests)} 通过")
    return passed == len(tests)

def run_standalone_tests():
    """运行独立测试"""
    print("🚀 开始配置验证和类型安全系统独立测试")
    print("=" * 60)
    
    tests = [
        test_standalone_validation,
        test_config_structure,
        test_config_file_operations,
        test_type_safety
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ 测试异常: {e}")
    
    print("\n" + "=" * 60)
    print(f"🎉 独立测试完成: {passed}/{total} 通过")
    
    if passed == total:
        print("✅ 所有独立测试通过！配置验证基本逻辑正常")
        print("📋 测试覆盖:")
        print("   - 基本数据类型验证 (整数、浮点数、字符串)")
        print("   - 值范围和选择验证")
        print("   - 配置结构完整性检查")
        print("   - 配置文件读写操作")
        print("   - 基本类型安全机制")
    else:
        print("⚠️ 部分独立测试失败，需要进一步检查")
    
    return passed == total

if __name__ == "__main__":
    success = run_standalone_tests()
    sys.exit(0 if success else 1)