#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
API文档自动生成器
解析代码并生成结构化的API文档
"""

import ast
import inspect
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Union
from dataclasses import dataclass, field
from datetime import datetime
import logging
import re

# 可选依赖
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    yaml = None

logger = logging.getLogger(__name__)

@dataclass
class DocParameter:
    """文档参数"""
    name: str
    type_hint: str = ""
    description: str = ""
    default_value: Any = None
    is_optional: bool = False

@dataclass 
class DocMethod:
    """文档方法"""
    name: str
    description: str = ""
    parameters: List[DocParameter] = field(default_factory=list)
    return_type: str = ""
    return_description: str = ""
    examples: List[str] = field(default_factory=list)
    raises: List[str] = field(default_factory=list)
    is_property: bool = False
    is_static: bool = False
    is_class_method: bool = False
    visibility: str = "public"  # public, private, protected

@dataclass
class DocClass:
    """文档类"""
    name: str
    description: str = ""
    module: str = ""
    inheritance: List[str] = field(default_factory=list)
    methods: List[DocMethod] = field(default_factory=list)
    properties: List[DocMethod] = field(default_factory=list)
    class_variables: List[DocParameter] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)

@dataclass
class DocModule:
    """文档模块"""
    name: str
    description: str = ""
    file_path: str = ""
    classes: List[DocClass] = field(default_factory=list)
    functions: List[DocMethod] = field(default_factory=list)
    constants: List[DocParameter] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)

class CodeParser:
    """代码解析器"""
    
    def __init__(self):
        self.current_module = ""
        
    def parse_file(self, file_path: Path) -> DocModule:
        """解析Python文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            module = DocModule(
                name=file_path.stem,
                file_path=str(file_path),
                description=self._extract_module_docstring(tree)
            )
            
            # 解析模块内容
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    doc_class = self._parse_class(node)
                    module.classes.append(doc_class)
                elif isinstance(node, ast.FunctionDef) and self._is_module_level_function(node, tree):
                    doc_function = self._parse_function(node)
                    module.functions.append(doc_function)
                elif isinstance(node, ast.Assign):
                    constants = self._parse_constants(node)
                    module.constants.extend(constants)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    imports = self._parse_imports(node)
                    module.imports.extend(imports)
            
            return module
            
        except Exception as e:
            logger.error(f"❌ 解析文件失败 {file_path}: {e}")
            return DocModule(name=file_path.stem, file_path=str(file_path))
    
    def _extract_module_docstring(self, tree: ast.AST) -> str:
        """提取模块文档字符串"""
        if (tree.body and 
            isinstance(tree.body[0], ast.Expr) and 
            isinstance(tree.body[0].value, ast.Str)):
            return tree.body[0].value.s
        elif (tree.body and 
              isinstance(tree.body[0], ast.Expr) and 
              isinstance(tree.body[0].value, ast.Constant) and 
              isinstance(tree.body[0].value.value, str)):
            return tree.body[0].value.value
        return ""
    
    def _parse_class(self, node: ast.ClassDef) -> DocClass:
        """解析类定义"""
        doc_class = DocClass(
            name=node.name,
            description=self._extract_docstring(node),
            inheritance=[self._get_name(base) for base in node.bases]
        )
        
        # 解析类方法和属性
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                method = self._parse_function(item, is_method=True)
                if method.name.startswith('_') and not method.name.startswith('__'):
                    method.visibility = "protected"
                elif method.name.startswith('__'):
                    method.visibility = "private"
                
                # 检查是否为属性装饰器
                if any(self._get_name(dec) == 'property' for dec in item.decorator_list):
                    method.is_property = True
                    doc_class.properties.append(method)
                else:
                    doc_class.methods.append(method)
            elif isinstance(item, ast.Assign):
                # 类变量
                variables = self._parse_constants(item)
                doc_class.class_variables.extend(variables)
        
        return doc_class
    
    def _parse_function(self, node: ast.FunctionDef, is_method: bool = False) -> DocMethod:
        """解析函数定义"""
        method = DocMethod(
            name=node.name,
            description=self._extract_docstring(node)
        )
        
        # 解析参数
        args = node.args
        defaults_offset = len(args.args) - len(args.defaults)
        
        for i, arg in enumerate(args.args):
            if is_method and i == 0 and arg.arg in ('self', 'cls'):
                continue  # 跳过self和cls参数
                
            param = DocParameter(
                name=arg.arg,
                type_hint=self._get_type_hint(arg.annotation) if arg.annotation else ""
            )
            
            # 设置默认值
            if i >= defaults_offset:
                default_index = i - defaults_offset
                if default_index < len(args.defaults):
                    param.default_value = self._get_default_value(args.defaults[default_index])
                    param.is_optional = True
            
            method.parameters.append(param)
        
        # 解析返回类型
        if node.returns:
            method.return_type = self._get_type_hint(node.returns)
        
        # 检查装饰器
        for decorator in node.decorator_list:
            decorator_name = self._get_name(decorator)
            if decorator_name == 'staticmethod':
                method.is_static = True
            elif decorator_name == 'classmethod':
                method.is_class_method = True
        
        # 解析文档字符串中的详细信息
        self._parse_docstring_details(method)
        
        return method
    
    def _parse_constants(self, node: ast.Assign) -> List[DocParameter]:
        """解析常量定义"""
        constants = []
        
        for target in node.targets:
            if isinstance(target, ast.Name):
                name = target.id
                if name.isupper():  # 假设大写变量为常量
                    constant = DocParameter(
                        name=name,
                        default_value=self._get_default_value(node.value)
                    )
                    constants.append(constant)
        
        return constants
    
    def _parse_imports(self, node: Union[ast.Import, ast.ImportFrom]) -> List[str]:
        """解析导入语句"""
        imports = []
        
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    imports.append(f"from {module} import *")
                else:
                    imports.append(f"from {module} import {alias.name}")
        
        return imports
    
    def _extract_docstring(self, node: ast.AST) -> str:
        """提取文档字符串"""
        if (hasattr(node, 'body') and node.body and 
            isinstance(node.body[0], ast.Expr)):
            expr = node.body[0]
            if isinstance(expr.value, ast.Str):
                return expr.value.s
            elif (isinstance(expr.value, ast.Constant) and 
                  isinstance(expr.value.value, str)):
                return expr.value.value
        return ""
    
    def _parse_docstring_details(self, method: DocMethod):
        """解析文档字符串中的详细信息"""
        if not method.description:
            return
            
        lines = method.description.split('\n')
        current_section = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # 检查参数部分
            param_match = re.match(r'@param\s+(\w+):\s*(.*)', line)
            if param_match:
                param_name, param_desc = param_match.groups()
                for param in method.parameters:
                    if param.name == param_name:
                        param.description = param_desc
                        break
                continue
            
            # 检查返回值部分
            return_match = re.match(r'@return:\s*(.*)', line)
            if return_match:
                method.return_description = return_match.group(1)
                continue
            
            # 检查异常部分
            raises_match = re.match(r'@raises?\s+(\w+):\s*(.*)', line)
            if raises_match:
                exception_type, exception_desc = raises_match.groups()
                method.raises.append(f"{exception_type}: {exception_desc}")
                continue
    
    def _get_name(self, node: ast.AST) -> str:
        """获取AST节点名称"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Constant):
            return str(node.value)
        return ""
    
    def _get_type_hint(self, node: ast.AST) -> str:
        """获取类型提示"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Subscript):
            value = self._get_type_hint(node.value)
            slice_value = self._get_type_hint(node.slice)
            return f"{value}[{slice_value}]"
        elif isinstance(node, ast.Constant):
            return str(node.value)
        return ""
    
    def _get_default_value(self, node: ast.AST) -> Any:
        """获取默认值"""
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        return None
    
    def _is_module_level_function(self, func_node: ast.FunctionDef, tree: ast.AST) -> bool:
        """检查是否为模块级函数"""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if item is func_node:
                        return False
        return True

class DocumentationGenerator:
    """文档生成器"""
    
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.parser = CodeParser()
        self.modules: List[DocModule] = []
        
    def scan_project(self, include_patterns: List[str] = None, exclude_patterns: List[str] = None):
        """扫描项目文件"""
        include_patterns = include_patterns or ["**/*.py"]
        exclude_patterns = exclude_patterns or ["**/__pycache__/**", "**/.*/**"]
        
        logger.info("🔍 开始扫描项目文件...")
        
        python_files = []
        for pattern in include_patterns:
            python_files.extend(self.project_root.glob(pattern))
        
        # 过滤排除的文件
        filtered_files = []
        for file_path in python_files:
            should_exclude = False
            for exclude_pattern in exclude_patterns:
                if file_path.match(exclude_pattern):
                    should_exclude = True
                    break
            if not should_exclude:
                filtered_files.append(file_path)
        
        logger.info(f"📁 找到 {len(filtered_files)} 个Python文件")
        
        # 解析文件
        for file_path in filtered_files:
            try:
                module = self.parser.parse_file(file_path)
                if module.classes or module.functions:  # 只包含有内容的模块
                    self.modules.append(module)
                    logger.debug(f"✅ 解析完成: {file_path}")
            except Exception as e:
                logger.error(f"❌ 解析失败 {file_path}: {e}")
        
        logger.info(f"📚 成功解析 {len(self.modules)} 个模块")
    
    def generate_markdown(self, output_path: Path):
        """生成Markdown格式文档"""
        logger.info("📝 生成Markdown API文档...")
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# API 文档\n\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("## 目录\n\n")
            
            # 生成目录
            for module in sorted(self.modules, key=lambda m: m.name):
                f.write(f"- [{module.name}](#{module.name.replace('.', '').replace('_', '')})\n")
                for cls in module.classes:
                    f.write(f"  - [{cls.name}](#{cls.name.lower()})\n")
            
            f.write("\n")
            
            # 生成详细文档
            for module in sorted(self.modules, key=lambda m: m.name):
                self._write_module_markdown(f, module)
        
        logger.info(f"✅ Markdown文档已生成: {output_path}")
    
    def generate_html(self, output_path: Path):
        """生成HTML格式文档"""
        logger.info("🌐 生成HTML API文档...")
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        html_content = self._generate_html_content()
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"✅ HTML文档已生成: {output_path}")
    
    def generate_json(self, output_path: Path):
        """生成JSON格式文档"""
        logger.info("📋 生成JSON API文档...")
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        doc_data = {
            "generation_time": datetime.now().isoformat(),
            "project_root": str(self.project_root),
            "modules": []
        }
        
        for module in self.modules:
            module_data = {
                "name": module.name,
                "description": module.description,
                "file_path": module.file_path,
                "classes": [],
                "functions": [],
                "constants": []
            }
            
            # 转换类
            for cls in module.classes:
                class_data = {
                    "name": cls.name,
                    "description": cls.description,
                    "inheritance": cls.inheritance,
                    "methods": [],
                    "properties": []
                }
                
                for method in cls.methods:
                    method_data = self._method_to_dict(method)
                    class_data["methods"].append(method_data)
                
                for prop in cls.properties:
                    prop_data = self._method_to_dict(prop)
                    class_data["properties"].append(prop_data)
                
                module_data["classes"].append(class_data)
            
            # 转换函数
            for func in module.functions:
                func_data = self._method_to_dict(func)
                module_data["functions"].append(func_data)
            
            # 转换常量
            for const in module.constants:
                const_data = {
                    "name": const.name,
                    "type": const.type_hint,
                    "default_value": const.default_value
                }
                module_data["constants"].append(const_data)
            
            doc_data["modules"].append(module_data)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(doc_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✅ JSON文档已生成: {output_path}")
    
    def _method_to_dict(self, method: DocMethod) -> Dict[str, Any]:
        """将方法转换为字典"""
        return {
            "name": method.name,
            "description": method.description,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type_hint,
                    "description": p.description,
                    "default_value": p.default_value,
                    "is_optional": p.is_optional
                }
                for p in method.parameters
            ],
            "return_type": method.return_type,
            "return_description": method.return_description,
            "raises": method.raises,
            "is_property": method.is_property,
            "is_static": method.is_static,
            "is_class_method": method.is_class_method,
            "visibility": method.visibility
        }
    
    def _write_module_markdown(self, f, module: DocModule):
        """写入模块的Markdown文档"""
        f.write(f"## {module.name}\n\n")
        if module.description:
            f.write(f"{module.description}\n\n")
        
        f.write(f"**文件路径**: `{module.file_path}`\n\n")
        
        # 模块常量
        if module.constants:
            f.write("### 常量\n\n")
            for const in module.constants:
                f.write(f"- **{const.name}**: {const.default_value}\n")
            f.write("\n")
        
        # 模块函数
        if module.functions:
            f.write("### 函数\n\n")
            for func in module.functions:
                self._write_method_markdown(f, func)
        
        # 模块类
        for cls in module.classes:
            f.write(f"### {cls.name}\n\n")
            if cls.description:
                f.write(f"{cls.description}\n\n")
            
            if cls.inheritance:
                f.write(f"**继承**: {', '.join(cls.inheritance)}\n\n")
            
            # 类方法
            if cls.methods:
                f.write("#### 方法\n\n")
                for method in cls.methods:
                    self._write_method_markdown(f, method)
            
            # 类属性
            if cls.properties:
                f.write("#### 属性\n\n")
                for prop in cls.properties:
                    self._write_method_markdown(f, prop)
        
        f.write("\n---\n\n")
    
    def _write_method_markdown(self, f, method: DocMethod):
        """写入方法的Markdown文档"""
        # 方法签名
        params = []
        for param in method.parameters:
            param_str = param.name
            if param.type_hint:
                param_str += f": {param.type_hint}"
            if param.default_value is not None:
                param_str += f" = {param.default_value}"
            params.append(param_str)
        
        signature = f"{method.name}({', '.join(params)})"
        if method.return_type:
            signature += f" -> {method.return_type}"
        
        f.write(f"#### {signature}\n\n")
        
        if method.description:
            f.write(f"{method.description}\n\n")
        
        # 参数描述
        if any(p.description for p in method.parameters):
            f.write("**参数**:\n")
            for param in method.parameters:
                if param.description:
                    f.write(f"- `{param.name}`: {param.description}\n")
            f.write("\n")
        
        # 返回值描述
        if method.return_description:
            f.write(f"**返回**: {method.return_description}\n\n")
        
        # 异常
        if method.raises:
            f.write("**异常**:\n")
            for exc in method.raises:
                f.write(f"- {exc}\n")
            f.write("\n")
    
    def _generate_html_content(self) -> str:
        """生成HTML内容"""
        html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API 文档</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; margin: 0; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { border-bottom: 2px solid #eee; padding-bottom: 20px; margin-bottom: 30px; }
        .module { margin-bottom: 40px; }
        .class { margin-bottom: 30px; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }
        .method { margin-bottom: 20px; padding: 15px; background: #f9f9f9; border-radius: 5px; }
        .signature { font-family: 'Courier New', monospace; background: #f0f0f0; padding: 10px; border-radius: 3px; }
        .nav { position: fixed; left: 20px; top: 20px; width: 250px; background: #f5f5f5; padding: 15px; border-radius: 8px; max-height: 80vh; overflow-y: auto; }
        .content { margin-left: 300px; }
        h1, h2, h3, h4 { color: #333; }
        .param { margin: 5px 0; }
        .return { color: #666; font-style: italic; }
    </style>
</head>
<body>
    <div class="nav">
        <h3>目录</h3>
        <ul>"""
        
        # 生成导航
        for module in sorted(self.modules, key=lambda m: m.name):
            html += f'<li><a href="#{module.name}">{module.name}</a><ul>'
            for cls in module.classes:
                html += f'<li><a href="#{cls.name}">{cls.name}</a></li>'
            html += '</ul></li>'
        
        html += """</ul>
    </div>
    <div class="content">
        <div class="container">
            <div class="header">
                <h1>API 文档</h1>
                <p>生成时间: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + """</p>
            </div>"""
        
        # 生成模块内容
        for module in sorted(self.modules, key=lambda m: m.name):
            html += f'<div class="module" id="{module.name}">'
            html += f'<h2>{module.name}</h2>'
            if module.description:
                html += f'<p>{module.description}</p>'
            
            for cls in module.classes:
                html += f'<div class="class" id="{cls.name}">'
                html += f'<h3>{cls.name}</h3>'
                if cls.description:
                    html += f'<p>{cls.description}</p>'
                
                for method in cls.methods:
                    html += self._method_to_html(method)
                
                html += '</div>'
            
            html += '</div>'
        
        html += """
        </div>
    </div>
</body>
</html>"""
        
        return html
    
    def _method_to_html(self, method: DocMethod) -> str:
        """将方法转换为HTML"""
        params = []
        for param in method.parameters:
            param_str = param.name
            if param.type_hint:
                param_str += f": {param.type_hint}"
            if param.default_value is not None:
                param_str += f" = {param.default_value}"
            params.append(param_str)
        
        signature = f"{method.name}({', '.join(params)})"
        if method.return_type:
            signature += f" -> {method.return_type}"
        
        html = f'<div class="method">'
        html += f'<div class="signature">{signature}</div>'
        
        if method.description:
            html += f'<p>{method.description}</p>'
        
        if any(p.description for p in method.parameters):
            html += '<strong>参数:</strong><ul>'
            for param in method.parameters:
                if param.description:
                    html += f'<li><code>{param.name}</code>: {param.description}</li>'
            html += '</ul>'
        
        if method.return_description:
            html += f'<div class="return"><strong>返回:</strong> {method.return_description}</div>'
        
        html += '</div>'
        return html

def generate_api_docs(project_root: str, output_dir: str = "docs/api", formats: List[str] = None):
    """生成API文档的主函数"""
    formats = formats or ["markdown", "html", "json"]
    
    logger.info("🚀 开始API文档自动生成")
    
    # 创建文档生成器
    generator = DocumentationGenerator(Path(project_root))
    
    # 扫描项目
    generator.scan_project(
        include_patterns=["src/**/*.py", "*.py"],
        exclude_patterns=["**/__pycache__/**", "**/.*/**", "**/tests/**", "**/test_*.py"]
    )
    
    # 创建输出目录
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 生成不同格式的文档
    if "markdown" in formats:
        generator.generate_markdown(output_path / "api.md")
    
    if "html" in formats:
        generator.generate_html(output_path / "api.html")
    
    if "json" in formats:
        generator.generate_json(output_path / "api.json")
    
    logger.info("✅ API文档生成完成")
    
    return {
        "modules_count": len(generator.modules),
        "total_classes": sum(len(m.classes) for m in generator.modules),
        "total_functions": sum(len(m.functions) for m in generator.modules),
        "output_directory": str(output_path)
    }

if __name__ == "__main__":
    import sys
    
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # 获取项目根目录
    project_root = sys.argv[1] if len(sys.argv) > 1 else "."
    
    # 生成文档
    result = generate_api_docs(project_root)
    print(f"📊 生成统计: {result}")