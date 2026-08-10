#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
API文档自动生成工具
提供命令行接口和配置管理
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass, asdict

from .api_doc_generator import generate_api_docs

@dataclass
class DocConfig:
    """文档生成配置"""
    project_root: str = "."
    output_dir: str = "docs/api"
    formats: List[str] = None
    include_patterns: List[str] = None
    exclude_patterns: List[str] = None
    
    def __post_init__(self):
        if self.formats is None:
            self.formats = ["markdown", "html", "json"]
        if self.include_patterns is None:
            self.include_patterns = ["src/**/*.py", "*.py"]
        if self.exclude_patterns is None:
            self.exclude_patterns = [
                "**/__pycache__/**", 
                "**/.*/**", 
                "**/tests/**", 
                "**/test_*.py"
            ]

class DocGeneratorCLI:
    """文档生成器命令行工具"""
    
    def __init__(self):
        self.config = DocConfig()
        
    def parse_args(self) -> argparse.Namespace:
        """解析命令行参数"""
        parser = argparse.ArgumentParser(
            description="API文档自动生成工具",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
示例:
  python -m src.docs.doc_tool --project . --output docs/api --formats markdown html
  python -m src.docs.doc_tool --config config/doc_config.json
  python -m src.docs.doc_tool --quick
            """
        )
        
        parser.add_argument(
            "--project", "-p",
            default=".",
            help="项目根目录 (默认: 当前目录)"
        )
        
        parser.add_argument(
            "--output", "-o", 
            default="docs/api",
            help="输出目录 (默认: docs/api)"
        )
        
        parser.add_argument(
            "--formats", "-f",
            nargs="+",
            choices=["markdown", "html", "json"],
            default=["markdown", "html"],
            help="生成格式 (默认: markdown html)"
        )
        
        parser.add_argument(
            "--include", "-i",
            nargs="+",
            help="包含的文件模式"
        )
        
        parser.add_argument(
            "--exclude", "-e", 
            nargs="+",
            help="排除的文件模式"
        )
        
        parser.add_argument(
            "--config", "-c",
            help="配置文件路径"
        )
        
        parser.add_argument(
            "--quick", "-q",
            action="store_true",
            help="快速模式，使用默认配置"
        )
        
        parser.add_argument(
            "--verbose", "-v",
            action="store_true", 
            help="详细输出"
        )
        
        parser.add_argument(
            "--save-config",
            help="保存当前配置到文件"
        )
        
        return parser.parse_args()
    
    def load_config(self, config_path: str) -> DocConfig:
        """加载配置文件"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            return DocConfig(**config_data)
            
        except Exception as e:
            logging.error(f"❌ 加载配置文件失败 {config_path}: {e}")
            return DocConfig()
    
    def save_config(self, config: DocConfig, config_path: str):
        """保存配置文件"""
        try:
            config_data = asdict(config)
            
            Path(config_path).parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            
            logging.info(f"✅ 配置已保存到: {config_path}")
            
        except Exception as e:
            logging.error(f"❌ 保存配置文件失败: {e}")
    
    def run(self):
        """运行文档生成工具"""
        args = self.parse_args()
        
        # 设置日志级别
        log_level = logging.DEBUG if args.verbose else logging.INFO
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        
        # 加载配置
        if args.config:
            self.config = self.load_config(args.config)
        
        # 更新配置参数
        if args.project:
            self.config.project_root = args.project
        if args.output:
            self.config.output_dir = args.output
        if args.formats:
            self.config.formats = args.formats
        if args.include:
            self.config.include_patterns = args.include
        if args.exclude:
            self.config.exclude_patterns = args.exclude
        
        # 保存配置
        if args.save_config:
            self.save_config(self.config, args.save_config)
        
        # 显示配置
        logging.info("📋 使用配置:")
        logging.info(f"   项目根目录: {self.config.project_root}")
        logging.info(f"   输出目录: {self.config.output_dir}")
        logging.info(f"   生成格式: {', '.join(self.config.formats)}")
        
        # 生成文档
        try:
            result = generate_api_docs(
                project_root=self.config.project_root,
                output_dir=self.config.output_dir,
                formats=self.config.formats
            )
            
            # 显示结果
            logging.info("🎉 文档生成成功!")
            logging.info(f"📊 统计信息:")
            logging.info(f"   模块数量: {result['modules_count']}")
            logging.info(f"   类数量: {result['total_classes']}")
            logging.info(f"   函数数量: {result['total_functions']}")
            logging.info(f"   输出目录: {result['output_directory']}")
            
            return True
            
        except Exception as e:
            logging.error(f"❌ 文档生成失败: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            return False

def main():
    """主函数"""
    cli = DocGeneratorCLI()
    success = cli.run()
    exit(0 if success else 1)

if __name__ == "__main__":
    main()