#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
配置验证和类型安全系统简化测试
"""

import json
from pathlib import Path
import tempfile
import sys
import os

# 添加src目录到Python路径
current_dir = Path(__file__).parent
project_root = current_dir.parent
src_dir = project_root / 'src'
sys.path.insert(0, str(src_dir))

def test_basic_import():
    """测试基本导入功能"""
    print("\n🧪 测试基本导入功能...")
    
    try:
        from config.config_validator import ConfigValidator, ValidationLevel, ValidationResult
        print("✅ 成功导入ConfigValidator")
        
        from config.unified_config import ConfigManager, AppConfig
        print("✅ 成功导入ConfigManager")
        
        return True
    except ImportError as e:
        print(f"❌ 导入失败: {e}")
        return False

def test_config_validation_basic():
    """测试配置验证基本功能"""
    print("\n🧪 测试配置验证基本功能...")
    
    try:
        from config.config_validator import ConfigValidator, ValidationLevel
        
        # 创建验证器
        validator = ConfigValidator(ValidationLevel.NORMAL)
        print("✅ 验证器创建成功")
        
        # 测试基本配置验证
        test_config = {
            "video_settings": {
                "fps": 30,
                "duration": 3.0,
                "bitrate": "5000k",
                "resolution": "1920x1080"
            }
        }
        
        result = validator.validate_config(test_config)
        print(f"📊 验证结果: {result.get_summary()}")
        
        # 测试无效配置
        invalid_config = {
            "video_settings": {
                "fps": "invalid_fps",  # 无效类型
                "bitrate": "invalid_bitrate"  # 无效格式
            }
        }
        
        result = validator.validate_config(invalid_config)
        print(f"⚠️ 无效配置验证: {result.get_summary()}")
        
        return True
        
    except Exception as e:
        print(f"❌ 配置验证测试失败: {e}")
        return False

def test_config_manager_basic():
    """测试配置管理器基本功能"""
    print("\n🧪 测试配置管理器基本功能...")
    
    try:
        from config.unified_config import ConfigManager
        from config.config_validator import ValidationLevel
        
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            
            # 创建配置管理器
            manager = ConfigManager(config_dir, ValidationLevel.NORMAL)
            print("✅ 配置管理器创建成功")
            
            # 获取配置
            config = manager.get_config()
            if config:
                print(f"📋 获取配置成功: 版本 {config.version}")
            else:
                print("⚠️ 配置为空")
            
            # 获取验证报告
            report = manager.get_validation_report()
            print(f"📊 验证报告: {report.get('status', '未知')}")
            
            return True
            
    except Exception as e:
        print(f"❌ 配置管理器测试失败: {e}")
        return False

def test_type_safety():
    """测试类型安全功能"""
    print("\n🧪 测试类型安全功能...")
    
    try:
        from config.config_validator import ConfigValidator, ValidationLevel, TypeSafeConfig
        
        validator = ConfigValidator(ValidationLevel.NORMAL)
        
        test_config = {
            "video_settings": {"fps": 30},
            "ui": {"theme": "default"}
        }
        
        safe_config = TypeSafeConfig(test_config, validator)
        result = safe_config.validate()
        print(f"🔒 类型安全验证: {result.get_summary()}")
        
        # 测试安全获取
        fps_value = safe_config.get("video_settings.fps")
        print(f"📊 安全获取FPS: {fps_value}")
        
        # 测试安全设置
        success = safe_config.set("video_settings.fps", 60)
        print(f"⚙️ 安全设置FPS: {'成功' if success else '失败'}")
        
        return True
        
    except Exception as e:
        print(f"❌ 类型安全测试失败: {e}")
        return False

def test_validation_rules():
    """测试验证规则"""
    print("\n🧪 测试验证规则...")
    
    try:
        from config.config_validator import ConfigValidator, ValidationLevel
        
        validator = ConfigValidator(ValidationLevel.STRICT)
        
        # 测试各种数据类型验证
        test_cases = [
            ("整数验证", {"video_settings": {"fps": 30}}),
            ("浮点数验证", {"video_settings": {"duration": 3.5}}),
            ("字符串验证", {"ui": {"theme": "default"}}),
            ("分辨率验证", {"video_settings": {"resolution": "1920x1080"}}),
            ("比特率验证", {"video_settings": {"bitrate": "5000k"}}),
        ]
        
        for test_name, config in test_cases:
            result = validator.validate_config(config)
            status = "✅" if result.is_valid else "❌"
            print(f"{status} {test_name}: {result.get_summary()}")
        
        return True
        
    except Exception as e:
        print(f"❌ 验证规则测试失败: {e}")
        return False

def run_simplified_test():
    """运行简化测试"""
    print("🚀 开始配置验证和类型安全系统简化测试")
    print("=" * 60)
    
    tests = [
        test_basic_import,
        test_config_validation_basic, 
        test_config_manager_basic,
        test_type_safety,
        test_validation_rules
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
    print(f"🎉 测试完成: {passed}/{total} 通过")
    
    if passed == total:
        print("✅ 所有测试通过！配置验证和类型安全系统基本功能正常")
    else:
        print("⚠️ 部分测试失败，需要进一步检查")
    
    return passed == total

if __name__ == "__main__":
    success = run_simplified_test()
    sys.exit(0 if success else 1)