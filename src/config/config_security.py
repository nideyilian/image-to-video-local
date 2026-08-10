#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
配置安全管理器
提供配置备份、恢复、加密和安全检查功能
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import logging
import os

# 尝试导入可选模块
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    yaml = None

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    Fernet = None

logger = logging.getLogger(__name__)

@dataclass
class BackupInfo:
    """备份信息"""
    backup_id: str
    timestamp: datetime
    file_path: Path
    checksum: str
    description: str = ""
    config_version: str = ""
    file_size: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'backup_id': self.backup_id,
            'timestamp': self.timestamp.isoformat(),
            'file_path': str(self.file_path),
            'checksum': self.checksum,
            'description': self.description,
            'config_version': self.config_version,
            'file_size': self.file_size
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BackupInfo':
        return cls(
            backup_id=data['backup_id'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            file_path=Path(data['file_path']),
            checksum=data['checksum'],
            description=data.get('description', ''),
            config_version=data.get('config_version', ''),
            file_size=data.get('file_size', 0)
        )

class ConfigSecurityManager:
    """配置安全管理器"""
    
    def __init__(self, config_dir: Path, backup_dir: Optional[Path] = None):
        self.config_dir = Path(config_dir)
        self.backup_dir = backup_dir or (self.config_dir / 'backups')
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        # 备份索引文件
        self.backup_index_file = self.backup_dir / 'backup_index.json'
        self.backup_info: List[BackupInfo] = []
        
        # 安全设置
        self.max_backups = 50  # 最大备份数量
        self.backup_retention_days = 30  # 备份保留天数
        self.encryption_key: Optional[bytes] = None
        
        # 初始化
        self._load_backup_index()
        self._cleanup_old_backups()
    
    def enable_encryption(self, key: Optional[bytes] = None) -> Optional[bytes]:
        """启用配置加密"""
        if not CRYPTO_AVAILABLE:
            logger.warning("⚠️ 加密功能不可用：缺少 cryptography 模块")
            return None
            
        if key is None:
            key = Fernet.generate_key()
        
        self.encryption_key = key
        logger.info("✅ 配置加密已启用")
        return key
    
    def disable_encryption(self):
        """禁用配置加密"""
        self.encryption_key = None
        logger.info("🔓 配置加密已禁用")
    
    def create_backup(self, config_file: Path, description: str = "") -> BackupInfo:
        """创建配置备份"""
        try:
            if not config_file.exists():
                raise FileNotFoundError(f"配置文件不存在: {config_file}")
            
            # 生成备份ID
            timestamp = datetime.now()
            backup_id = f"backup_{timestamp.strftime('%Y%m%d_%H%M%S')}_{hashlib.md5(str(config_file).encode()).hexdigest()[:8]}"
            
            # 备份文件路径
            backup_filename = f"{backup_id}.yaml"
            if self.encryption_key:
                backup_filename += ".enc"
            backup_path = self.backup_dir / backup_filename
            
            # 读取原始配置
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 加密（如果启用）
            if self.encryption_key and CRYPTO_AVAILABLE:
                fernet = Fernet(self.encryption_key)
                encrypted_content = fernet.encrypt(content.encode('utf-8'))
                with open(backup_path, 'wb') as f:
                    f.write(encrypted_content)
            else:
                with open(backup_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            
            # 计算校验和
            checksum = self._calculate_checksum(config_file)
            
            # 创建备份信息
            backup_info = BackupInfo(
                backup_id=backup_id,
                timestamp=timestamp,
                file_path=backup_path,
                checksum=checksum,
                description=description,
                config_version=self._get_config_version(config_file),
                file_size=config_file.stat().st_size
            )
            
            # 添加到索引
            self.backup_info.append(backup_info)
            self._save_backup_index()
            
            # 清理旧备份
            self._cleanup_old_backups()
            
            logger.info(f"✅ 配置备份创建成功: {backup_id}")
            return backup_info
            
        except Exception as e:
            logger.error(f"❌ 创建配置备份失败: {e}")
            raise
    
    def restore_backup(self, backup_id: str, target_file: Path) -> bool:
        """恢复配置备份"""
        try:
            # 查找备份
            backup = self._find_backup(backup_id)
            if not backup:
                raise ValueError(f"备份不存在: {backup_id}")
            
            if not backup.file_path.exists():
                raise FileNotFoundError(f"备份文件不存在: {backup.file_path}")
            
            # 读取备份内容
            if self.encryption_key and backup.file_path.suffix == '.enc' and CRYPTO_AVAILABLE:
                # 解密备份
                with open(backup.file_path, 'rb') as f:
                    encrypted_content = f.read()
                
                fernet = Fernet(self.encryption_key)
                content = fernet.decrypt(encrypted_content).decode('utf-8')
            else:
                # 普通备份
                with open(backup.file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            
            # 创建目标文件的备份
            if target_file.exists():
                backup_desc = f"恢复前自动备份 (恢复: {backup_id})"
                self.create_backup(target_file, backup_desc)
            
            # 写入恢复的内容
            target_file.parent.mkdir(parents=True, exist_ok=True)
            with open(target_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"✅ 配置恢复成功: {backup_id} -> {target_file}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 配置恢复失败: {e}")
            return False
    
    def list_backups(self, limit: Optional[int] = None) -> List[BackupInfo]:
        """列出所有备份"""
        # 按时间倒序排列
        sorted_backups = sorted(self.backup_info, key=lambda x: x.timestamp, reverse=True)
        
        if limit:
            return sorted_backups[:limit]
        return sorted_backups
    
    def delete_backup(self, backup_id: str) -> bool:
        """删除指定备份"""
        try:
            backup = self._find_backup(backup_id)
            if not backup:
                logger.warning(f"备份不存在: {backup_id}")
                return False
            
            # 删除备份文件
            if backup.file_path.exists():
                backup.file_path.unlink()
            
            # 从索引中移除
            self.backup_info = [b for b in self.backup_info if b.backup_id != backup_id]
            self._save_backup_index()
            
            logger.info(f"✅ 备份删除成功: {backup_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 删除备份失败: {e}")
            return False
    
    def verify_backup_integrity(self, backup_id: str) -> bool:
        """验证备份完整性"""
        try:
            backup = self._find_backup(backup_id)
            if not backup:
                return False
            
            if not backup.file_path.exists():
                logger.error(f"备份文件丢失: {backup.file_path}")
                return False
            
            # 尝试读取和解析备份
            if self.encryption_key and backup.file_path.suffix == '.enc' and CRYPTO_AVAILABLE:
                with open(backup.file_path, 'rb') as f:
                    encrypted_content = f.read()
                fernet = Fernet(self.encryption_key)
                content = fernet.decrypt(encrypted_content).decode('utf-8')
            else:
                with open(backup.file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            
            # 尝试解析YAML或JSON
            if YAML_AVAILABLE:
                yaml.safe_load(content)
            else:
                json.loads(content)
            
            logger.info(f"✅ 备份完整性验证通过: {backup_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 备份完整性验证失败 {backup_id}: {e}")
            return False
    
    def get_backup_statistics(self) -> Dict[str, Any]:
        """获取备份统计信息"""
        if not self.backup_info:
            return {
                'total_backups': 0,
                'total_size': 0,
                'oldest_backup': None,
                'newest_backup': None,
                'encryption_enabled': self.encryption_key is not None
            }
        
        total_size = sum(b.file_size for b in self.backup_info)
        sorted_backups = sorted(self.backup_info, key=lambda x: x.timestamp)
        
        return {
            'total_backups': len(self.backup_info),
            'total_size': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'oldest_backup': sorted_backups[0].timestamp.isoformat(),
            'newest_backup': sorted_backups[-1].timestamp.isoformat(),
            'encryption_enabled': self.encryption_key is not None,
            'backup_dir': str(self.backup_dir)
        }
    
    def export_backup_list(self, export_path: Path):
        """导出备份列表"""
        try:
            backup_data = {
                'export_time': datetime.now().isoformat(),
                'statistics': self.get_backup_statistics(),
                'backups': [b.to_dict() for b in self.backup_info]
            }
            
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"✅ 备份列表导出成功: {export_path}")
            
        except Exception as e:
            logger.error(f"❌ 备份列表导出失败: {e}")
    
    def check_config_security(self, config_file: Path) -> Dict[str, Any]:
        """检查配置文件安全性"""
        security_report = {
            'file_exists': False,
            'file_permissions': None,
            'file_size': 0,
            'content_issues': [],
            'security_score': 0,
            'recommendations': []
        }
        
        try:
            if not config_file.exists():
                security_report['recommendations'].append("配置文件不存在，建议创建默认配置")
                return security_report
            
            security_report['file_exists'] = True
            stat_info = config_file.stat()
            security_report['file_size'] = stat_info.st_size
            security_report['file_permissions'] = oct(stat_info.st_mode)[-3:]
            
            # 读取配置内容
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 检查敏感信息
            sensitive_patterns = [
                ('password', '可能包含密码信息'),
                ('secret', '可能包含密钥信息'),
                ('token', '可能包含令牌信息'),
                ('api_key', '可能包含API密钥'),
                ('private_key', '可能包含私钥信息')
            ]
            
            for pattern, message in sensitive_patterns:
                if pattern.lower() in content.lower():
                    security_report['content_issues'].append(message)
            
            # 检查文件权限
            if os.name == 'nt':  # Windows
                # Windows权限检查相对简单
                if stat_info.st_mode & 0o077:  # 其他用户有读写权限
                    security_report['recommendations'].append("建议限制文件访问权限")
            else:  # Unix/Linux
                if stat_info.st_mode & 0o077:  # 其他用户有读写权限
                    security_report['recommendations'].append("建议使用 chmod 600 限制文件权限")
            
            # 计算安全分数
            score = 100
            score -= len(security_report['content_issues']) * 20  # 每个敏感信息问题扣20分
            score -= len(security_report['recommendations']) * 10  # 每个建议扣10分
            security_report['security_score'] = max(0, score)
            
            # 通用建议
            if not security_report['content_issues'] and not security_report['recommendations']:
                security_report['recommendations'].append("配置安全性良好")
            
            if not self.encryption_key:
                security_report['recommendations'].append("建议启用配置加密以提高安全性")
            
        except Exception as e:
            security_report['content_issues'].append(f"配置文件检查异常: {e}")
        
        return security_report
    
    def _find_backup(self, backup_id: str) -> Optional[BackupInfo]:
        """查找备份"""
        for backup in self.backup_info:
            if backup.backup_id == backup_id:
                return backup
        return None
    
    def _load_backup_index(self):
        """加载备份索引"""
        try:
            if self.backup_index_file.exists():
                with open(self.backup_index_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.backup_info = [BackupInfo.from_dict(item) for item in data.get('backups', [])]
                logger.info(f"✅ 加载备份索引: {len(self.backup_info)}个备份")
            else:
                self.backup_info = []
                
        except Exception as e:
            logger.error(f"❌ 加载备份索引失败: {e}")
            self.backup_info = []
    
    def _save_backup_index(self):
        """保存备份索引"""
        try:
            index_data = {
                'last_updated': datetime.now().isoformat(),
                'total_backups': len(self.backup_info),
                'backups': [backup.to_dict() for backup in self.backup_info]
            }
            
            with open(self.backup_index_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"❌ 保存备份索引失败: {e}")
    
    def _cleanup_old_backups(self):
        """清理旧备份"""
        try:
            # 按数量限制
            if len(self.backup_info) > self.max_backups:
                # 删除最老的备份
                sorted_backups = sorted(self.backup_info, key=lambda x: x.timestamp)
                to_delete = sorted_backups[:-self.max_backups]
                
                for backup in to_delete:
                    if backup.file_path.exists():
                        backup.file_path.unlink()
                    logger.info(f"🗑️ 删除过期备份: {backup.backup_id}")
                
                self.backup_info = sorted_backups[-self.max_backups:]
            
            # 按时间限制
            cutoff_date = datetime.now() - timedelta(days=self.backup_retention_days)
            valid_backups = []
            
            for backup in self.backup_info:
                if backup.timestamp < cutoff_date:
                    if backup.file_path.exists():
                        backup.file_path.unlink()
                    logger.info(f"🗑️ 删除过期备份: {backup.backup_id}")
                else:
                    valid_backups.append(backup)
            
            if len(valid_backups) != len(self.backup_info):
                self.backup_info = valid_backups
                self._save_backup_index()
                
        except Exception as e:
            logger.error(f"❌ 清理旧备份失败: {e}")
    
    def _calculate_checksum(self, file_path: Path) -> str:
        """计算文件校验和"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    def _get_config_version(self, config_file: Path) -> str:
        """获取配置版本"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                if config_file.suffix.lower() == '.yaml' and YAML_AVAILABLE:
                    data = yaml.safe_load(f)
                else:
                    data = json.load(f)
            
            return data.get('version', 'unknown')
            
        except Exception:
            return 'unknown'

def create_security_manager(config_dir: Path, backup_dir: Optional[Path] = None) -> ConfigSecurityManager:
    """创建配置安全管理器"""
    return ConfigSecurityManager(config_dir, backup_dir)