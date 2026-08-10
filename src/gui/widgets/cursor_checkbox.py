#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Cursor 风格的自定义复选框组件
使用 ✅ 表示选中状态
"""

import tkinter as tk
from tkinter import ttk


class CursorCheckbox(ttk.Frame):
    """
    Cursor 风格的复选框
    选中时显示 ✅，未选中时显示 ☐
    """
    
    def __init__(self, parent, text="", variable=None, command=None, **kwargs):
        super().__init__(parent, **kwargs)
        
        # 内部变量
        if variable is None:
            self._variable = tk.BooleanVar()
        else:
            self._variable = variable
        
        self._command = command
        self._text = text
        
        # 配置框架
        self.configure(style='TFrame', cursor='hand2')
        
        # 创建内部容器
        self.grid_columnconfigure(0, weight=1)
        container = ttk.Frame(self, style='TFrame')
        container.grid(row=0, column=0, sticky="ew")
        container.grid_columnconfigure(1, weight=1)
        
        # 复选框图标标签（固定宽度避免位移）
        self._icon_label = ttk.Label(
            container,
            text="☐",
            font=('Segoe UI', 14),
            style='TLabel',
            cursor='hand2',
            width=2  # 固定宽度，避免图标切换时位移
        )
        self._icon_label.grid(row=0, column=0, sticky="w", padx=(0, 4))
        
        # 文本标签
        self._text_label = ttk.Label(
            container,
            text=text,
            style='TLabel',
            cursor='hand2'
        )
        self._text_label.grid(row=0, column=1, sticky="w")
        
        # 绑定点击事件
        self._icon_label.bind('<Button-1>', self._on_click)
        self._text_label.bind('<Button-1>', self._on_click)
        self.bind('<Button-1>', self._on_click)
        
        # 监听变量变化
        self._variable.trace_add('write', self._on_variable_change)
        
        # 初始化显示
        self._update_display()
    
    def _on_click(self, event=None):
        """点击事件处理"""
        # 切换状态
        current = self._variable.get()
        self._variable.set(not current)
        
        # 执行回调
        if self._command:
            self._command()
    
    def _on_variable_change(self, *args):
        """变量变化时更新显示"""
        self._update_display()
    
    def _update_display(self):
        """更新显示状态"""
        is_checked = self._variable.get()
        
        if is_checked:
            # iOS风格：使用对勾符号（更小更统一）
            self._icon_label.configure(text="☑", foreground="#34C759")
        else:
            # 未选中：空心方框
            self._icon_label.configure(text="☐", foreground="#8E8E93")
    
    def get(self):
        """获取当前值"""
        return self._variable.get()
    
    def set(self, value):
        """设置值"""
        self._variable.set(value)
    
    def configure_text(self, text):
        """配置文本"""
        self._text = text
        self._text_label.configure(text=text)
    
    def configure_variable(self, variable):
        """配置变量"""
        # 移除旧的trace
        if hasattr(self, '_trace_id'):
            self._variable.trace_remove('write', self._trace_id)
        
        self._variable = variable
        self._trace_id = self._variable.trace_add('write', self._on_variable_change)
        self._update_display()


# 兼容性包装函数
def create_cursor_checkbox(parent, text="", variable=None, **kwargs):
    """
    创建Cursor风格复选框的便捷函数
    
    用法：
    var = tk.BooleanVar()
    checkbox = create_cursor_checkbox(parent, text="保持比例", variable=var)
    checkbox.grid()
    """
    return CursorCheckbox(parent, text=text, variable=variable, **kwargs)

