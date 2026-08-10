#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
统一配置管理模块
"""

from .unified_config import (
    ConfigManager,
    AppConfig,
    ConfigPaths,
    UIConfig,
    PerformanceConfig,
    AdvancedConfig
)

from .config_validator import (
    ConfigValidator,
    ValidationLevel,
    ValidationResult,
    TypeSafeConfig,
    create_validator,
    validate_config_file
)

from .config_security import (
    ConfigSecurityManager,
    BackupInfo,
    create_security_manager
)

__all__ = [
    # 核心配置管理
    'ConfigManager',
    'AppConfig',
    'ConfigPaths',
    'UIConfig',
    'PerformanceConfig',
    'AdvancedConfig',
    
    # 配置验证
    'ConfigValidator',
    'ValidationLevel',
    'ValidationResult',
    'TypeSafeConfig',
    'create_validator',
    'validate_config_file',
    
    # 配置安全
    'ConfigSecurityManager',
    'BackupInfo',
    'create_security_manager'
]

from .unified_config import (
    AppConfig,
    ConfigPaths,
    UIConfig,
    PerformanceConfig,
    AdvancedConfig,
    ConfigManager
)

__version__ = "2.1.0"
__all__ = [
    'AppConfig',
    'ConfigPaths',
    'UIConfig', 
    'PerformanceConfig',
    'AdvancedConfig',
    'ConfigManager'
]
