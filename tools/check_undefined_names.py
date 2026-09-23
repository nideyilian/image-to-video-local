# -*- coding: utf-8 -*-
"""精确扫描 src/render：只查"函数直接作用域"里未定义的全局名。"""
import ast, builtins, io, os

RD = r"D:\AAA\image-to-video\src\render"


def iter_direct(node):
    """遍历语句树，但不进入嵌套的函数/类/lambda。"""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.Lambda, ast.ClassDef)):
            continue
        yield child
        yield from iter_direct(child)


total = 0
for fn in sorted(os.listdir(RD)):
    if not fn.endswith(".py"):
        continue
    tree = ast.parse(io.open(os.path.join(RD, fn), encoding="utf-8").read())
    defined = set(dir(builtins))
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                for x in ast.walk(t):
                    if isinstance(x, ast.Name):
                        defined.add(x.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            defined.add(n.target.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                defined.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.For):  # 模块级 for 的循环变量
            for x in ast.walk(n.target):
                if isinstance(x, ast.Name):
                    defined.add(x.id)

    missing = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        local = {a.arg for a in list(node.args.args) + list(node.args.kwonlyargs)}
        if node.args.vararg:
            local.add(node.args.vararg.arg)
        if node.args.kwarg:
            local.add(node.args.kwarg.arg)
        for sub in iter_direct(node):
            if isinstance(sub, ast.Assign):
                for t in sub.targets:
                    for x in ast.walk(t):
                        if isinstance(x, ast.Name):
                            local.add(x.id)
            elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
                local.add(sub.target.id)
            elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                for a in sub.names:
                    local.add(a.asname or a.name.split(".")[0])
            elif isinstance(sub, ast.For):
                for x in ast.walk(sub.target):
                    if isinstance(x, ast.Name):
                        local.add(x.id)
            elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                pass
        # 第二遍：收集直接作用域的 Load
        for sub in iter_direct(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                if sub.id not in local and sub.id not in defined:
                    missing.setdefault(sub.id, node.lineno)
    if missing:
        total += len(missing)
        print("%-16s %s" % (fn, missing))
print("合计:", total)
