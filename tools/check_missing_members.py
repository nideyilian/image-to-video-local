# -*- coding: utf-8 -*-
"""扫描界面类里「被引用但已不存在」的 self 属性/方法。

写法与 tools/check_undefined_names.py 同源，但检查的是**类属性**：
把类里所有 ``def name``、``self.name = ...``、``name = ...``（类级）收集为已定义，
再找出所有 ``self.name`` 读取但从未定义的名字 —— 正是"精简代码时删了方法、
忘了改引用"这类只在运行到那一刻才暴露的问题。
"""
from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

TARGET = Path(sys.argv[1] if len(sys.argv) > 1 else r"src/gui/main_window.py")
CLASS_NAME = sys.argv[2] if len(sys.argv) > 2 else "ImageToVideoTab"

tree = ast.parse(io.open(TARGET, encoding="utf-8").read())
target = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == CLASS_NAME), None)
if target is None:
    raise SystemExit(f"未找到类 {CLASS_NAME}")

defined: set[str] = set()
for node in target.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        defined.add(node.name)
    elif isinstance(node, ast.Assign):
        for t in node.targets:
            for x in ast.walk(t):
                if isinstance(x, ast.Name):
                    defined.add(x.id)
# 类体内所有 self.x = ... 与 setattr(self, "x", ...) 都算已定义
for node in ast.walk(target):
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                defined.add(t.attr)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "setattr":
        if len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and node.args[0].id == "self":
            if isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                defined.add(node.args[1].value)

missing: dict[str, list[int]] = {}
for node in ast.walk(target):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        name = node.attr
        if name in defined:
            continue
        # getattr(self, "x", 默认值) 形式的读取不算问题
        missing.setdefault(name, []).append(node.lineno)

if not missing:
    print(f"{TARGET.name} 的 {CLASS_NAME}：没有缺失引用")
else:
    print(f"{TARGET.name} 的 {CLASS_NAME} 里被引用但未定义的名字：")
    for name, lines in sorted(missing.items(), key=lambda item: item[1][0]):
        head = ", ".join(str(line) for line in lines[:6])
        more = f" …共 {len(lines)} 处" if len(lines) > 6 else ""
        print(f"  self.{name:<28} 行 {head}{more}")
