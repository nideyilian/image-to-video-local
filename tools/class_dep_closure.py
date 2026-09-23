# -*- coding: utf-8 -*-
"""列出某个类里指定方法的 self.* 依赖闭包（含行号、行数）。

用于规划"把渲染内核从界面类里抽出来"时的模块边界：
每次改动后行号都会漂，靠这个工具重新定位，不要相信记忆里的行号。

用法:
    python tools/class_dep_closure.py <file> <ClassName> <method> [<method> ...]
    python tools/class_dep_closure.py src/gui/main_window.py ImageToVideoTab create_video add_audio_with_ffmpeg

输出按源码顺序排列，形如:
    行号  行数  方法名  <- 它依赖的同类方法
"""
import ast
import io
import sys


def analyze(path: str, class_name: str, targets: list[str]) -> int:
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name]
    if not classes:
        print("找不到类 %s" % class_name, file=sys.stderr)
        return 2
    methods = {n.name: n for n in classes[0].body if isinstance(n, ast.FunctionDef)}

    def self_attrs(node):
        out = set()
        for x in ast.walk(node):
            if (isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name)
                    and x.value.id == "self"):
                out.add(x.attr)
        return out

    missing = [t for t in targets if t not in methods]
    if missing:
        print("警告：类中不存在 %s" % ", ".join(missing), file=sys.stderr)

    seen, stack, order = set(), list(targets), []
    while stack:
        name = stack.pop()
        if name in seen or name not in methods:
            continue
        seen.add(name)
        order.append(name)
        for a in self_attrs(methods[name]):
            if a in methods and a not in seen:
                stack.append(a)

    rows = []
    for name in order:
        n = methods[name]
        rows.append((name, n.lineno, n.end_lineno - n.lineno + 1,
                     sorted(a for a in self_attrs(n) if a in methods)))
    rows.sort(key=lambda r: r[1])

    print("闭包方法数: %d   总行数: %d" % (len(rows), sum(r[2] for r in rows)))
    print()
    for name, ln, length, deps in rows:
        print("%5d %4d  %-44s <- %s" % (ln, length, name,
                                        ", ".join(deps) if deps else "(leaf)"))
    return 0


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    return analyze(sys.argv[1], sys.argv[2], sys.argv[3:])


if __name__ == "__main__":
    raise SystemExit(main())
