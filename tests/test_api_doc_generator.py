#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
API文档生成器测试
"""

import unittest
import tempfile
import json
from pathlib import Path
import sys
import os

# 添加项目根目录到路径
project_root = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, project_root)

from src.docs.api_doc_generator import (
    CodeParser, DocumentationGenerator, generate_api_docs,
    DocModule, DocClass, DocMethod, DocParameter
)

class TestCodeParser(unittest.TestCase):
    """代码解析器测试"""
    
    def setUp(self):
        self.parser = CodeParser()
        
    def test_parse_simple_class(self):
        """测试解析简单类"""
        test_code = '''
class TestClass:
    """测试类"""
    
    def __init__(self, name: str):
        """初始化方法"""
        self.name = name
    
    def get_name(self) -> str:
        """获取名称"""
        return self.name
'''
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(test_code)
            temp_file = Path(f.name)
        
        try:
            # 解析文件
            module = self.parser.parse_file(temp_file)
            
            # 验证结果
            self.assertEqual(len(module.classes), 1)
            
            test_class = module.classes[0]
            self.assertEqual(test_class.name, "TestClass")
            self.assertEqual(test_class.description, "测试类")
            self.assertEqual(len(test_class.methods), 2)
            
            # 验证方法
            init_method = next(m for m in test_class.methods if m.name == "__init__")
            self.assertEqual(len(init_method.parameters), 1)
            self.assertEqual(init_method.parameters[0].name, "name")
            self.assertEqual(init_method.parameters[0].type_hint, "str")
            
        finally:
            temp_file.unlink()
    
    def test_parse_function_with_docstring(self):
        """测试解析带文档字符串的函数"""
        test_code = '''
def calculate_area(width: float, height: float) -> float:
    """
    计算矩形面积
    
    @param width: 宽度
    @param height: 高度
    @return: 面积值
    """
    return width * height
'''
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(test_code)
            temp_file = Path(f.name)
        
        try:
            module = self.parser.parse_file(temp_file)
            
            self.assertEqual(len(module.functions), 1)
            
            func = module.functions[0]
            self.assertEqual(func.name, "calculate_area")
            self.assertIn("计算矩形面积", func.description)
            self.assertEqual(len(func.parameters), 2)
            self.assertEqual(func.return_type, "float")
            
        finally:
            temp_file.unlink()

class TestDocumentationGenerator(unittest.TestCase):
    """文档生成器测试"""
    
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.generator = DocumentationGenerator(self.temp_dir)
        
        # 创建测试文件
        self.create_test_files()
    
    def tearDown(self):
        # 清理临时目录
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def create_test_files(self):
        """创建测试文件"""
        # 创建src目录
        src_dir = self.temp_dir / "src"
        src_dir.mkdir()
        
        # 创建测试模块
        test_module = src_dir / "test_module.py"
        test_module.write_text('''
"""测试模块"""

class Calculator:
    """计算器类"""
    
    def add(self, a: int, b: int) -> int:
        """加法运算"""
        return a + b
    
    def subtract(self, a: int, b: int) -> int:
        """减法运算"""
        return a - b

def helper_function():
    """辅助函数"""
    pass
''', encoding='utf-8')
    
    def test_scan_project(self):
        """测试项目扫描"""
        self.generator.scan_project()
        
        # 验证结果
        self.assertEqual(len(self.generator.modules), 1)
        
        module = self.generator.modules[0]
        self.assertEqual(module.name, "test_module")
        self.assertEqual(len(module.classes), 1)
        self.assertEqual(len(module.functions), 1)
        
        calculator_class = module.classes[0]
        self.assertEqual(calculator_class.name, "Calculator")
        self.assertEqual(len(calculator_class.methods), 2)
    
    def test_generate_markdown(self):
        """测试Markdown生成"""
        self.generator.scan_project()
        
        output_file = self.temp_dir / "docs" / "api.md"
        self.generator.generate_markdown(output_file)
        
        # 验证文件生成
        self.assertTrue(output_file.exists())
        
        # 验证内容
        content = output_file.read_text(encoding='utf-8')
        self.assertIn("# API 文档", content)
        self.assertIn("## test_module", content)
        self.assertIn("### Calculator", content)
        self.assertIn("add(", content)
    
    def test_generate_json(self):
        """测试JSON生成"""
        self.generator.scan_project()
        
        output_file = self.temp_dir / "docs" / "api.json"
        self.generator.generate_json(output_file)
        
        # 验证文件生成
        self.assertTrue(output_file.exists())
        
        # 验证JSON格式
        with open(output_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.assertIn("modules", data)
        self.assertEqual(len(data["modules"]), 1)
        
        module_data = data["modules"][0]
        self.assertEqual(module_data["name"], "test_module")
        self.assertEqual(len(module_data["classes"]), 1)

class TestIntegration(unittest.TestCase):
    """集成测试"""
    
    def test_generate_api_docs_integration(self):
        """测试完整的API文档生成流程"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 创建测试项目结构
            src_dir = temp_path / "src"
            src_dir.mkdir()
            
            # 创建测试文件
            test_file = src_dir / "example.py"
            test_file.write_text('''
"""示例模块"""

class ExampleClass:
    """示例类"""
    
    def example_method(self, param: str) -> bool:
        """示例方法"""
        return True
''', encoding='utf-8')
            
            # 生成文档
            result = generate_api_docs(
                project_root=str(temp_path),
                output_dir=str(temp_path / "docs" / "api"),
                formats=["markdown", "json"]
            )
            
            # 验证结果
            self.assertGreater(result["modules_count"], 0)
            self.assertGreater(result["total_classes"], 0)
            
            # 验证文件生成
            docs_dir = temp_path / "docs" / "api"
            self.assertTrue((docs_dir / "api.md").exists())
            self.assertTrue((docs_dir / "api.json").exists())

def run_api_doc_tests():
    """运行API文档生成器测试"""
    print("🧪 开始API文档生成器测试...")
    
    # 创建测试套件
    test_suite = unittest.TestSuite()
    
    # 添加测试用例
    test_suite.addTest(unittest.makeSuite(TestCodeParser))
    test_suite.addTest(unittest.makeSuite(TestDocumentationGenerator))
    test_suite.addTest(unittest.makeSuite(TestIntegration))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # 统计结果
    total_tests = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passed = total_tests - failures - errors
    
    print(f"\n📊 API文档生成器测试结果:")
    print(f"   总测试数: {total_tests}")
    print(f"   通过: {passed}")
    print(f"   失败: {failures}")
    print(f"   错误: {errors}")
    
    if failures + errors == 0:
        print("✅ 所有测试通过！API文档生成器功能正常")
    else:
        print("⚠️ 部分测试失败，需要检查API文档生成器")
    
    return failures + errors == 0

if __name__ == "__main__":
    success = run_api_doc_tests()
    sys.exit(0 if success else 1)