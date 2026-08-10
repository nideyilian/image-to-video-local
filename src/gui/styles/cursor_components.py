#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
标准化的 UI 组件库
所有组件遵循统一的设计规范
"""

from tkinter import ttk
from .cursor_theme import CursorTheme
from .cursor_grid import GridSystem


class StandardInput:
    """标准输入框"""
    
    @staticmethod
    def create(parent, variable, width=None, **kwargs):
        """
        创建标准输入框
        
        Args:
            parent: 父容器
            variable: tk变量
            width: 宽度（字符数）
        """
        entry = ttk.Entry(parent, textvariable=variable, **kwargs)
        if width:
            entry.configure(width=width)
        return entry


class StandardCombobox:
    """标准下拉框"""
    
    @staticmethod
    def create(parent, variable, values, width=None, **kwargs):
        """创建标准下拉框"""
        combo = ttk.Combobox(parent, textvariable=variable, values=values,
                            state='readonly', **kwargs)
        if width is None:
            width = 12
        combo.configure(width=width)
        return combo


class StandardSpinbox:
    """标准数字选择框"""
    
    @staticmethod
    def create(parent, variable, from_=0, to=100, increment=1, width=None, **kwargs):
        """创建标准数字选择框"""
        spinbox = ttk.Spinbox(parent, textvariable=variable,
                             from_=from_, to=to, increment=increment, **kwargs)
        if width is None:
            width = 10
        spinbox.configure(width=width)
        return spinbox


class StandardLabel:
    """标准标签"""
    
    @staticmethod
    def create(parent, text, width=None, **kwargs):
        """创建标准标签"""
        label = ttk.Label(parent, text=text, **kwargs)
        if width:
            label.configure(width=width)
        return label


class ResolutionInput:
    """分辨率输入组件（宽 × 高）"""
    
    def __init__(self, parent, width_var, height_var):
        self.frame = ttk.Frame(parent, style='TFrame')
        
        # 宽度输入
        self.width_entry = ttk.Entry(self.frame, textvariable=width_var, width=7)
        self.width_entry.grid(row=0, column=0, sticky="w")
        
        # × 符号
        ttk.Label(self.frame, text="×").grid(row=0, column=1, sticky="w", padx=GridSystem.SPACING['xs'])
        
        # 高度输入
        self.height_entry = ttk.Entry(self.frame, textvariable=height_var, width=7)
        self.height_entry.grid(row=0, column=2, sticky="w")
    
    def pack(self, **kwargs):
        grid_kwargs = {k: v for k, v in kwargs.items() if k in ("padx", "pady")}
        grid_kwargs.setdefault("sticky", "w")
        self.frame.grid(**grid_kwargs)
    
    def grid(self, **kwargs):
        self.frame.grid(**kwargs)


class FilePathInput:
    """文件路径输入组件（输入框 + 浏览按钮）"""
    
    def __init__(self, parent, variable, button_text="浏览", button_command=None):
        self.frame = ttk.Frame(parent, style='TFrame')
        self.frame.columnconfigure(0, weight=1)
        
        # 输入框
        self.entry = ttk.Entry(self.frame, textvariable=variable)
        self.entry.grid(row=0, column=0, sticky='ew',
                       padx=(0, GridSystem.SPACING['sm']))
        
        # 浏览按钮
        self.button = ttk.Button(self.frame, text=button_text,
                                command=button_command,
                                width=GridSystem.WIDTHS['sm']//7)
        self.button.grid(row=0, column=1, sticky='e')
    
    def pack(self, **kwargs):
        grid_kwargs = {k: v for k, v in kwargs.items() if k in ("padx", "pady")}
        grid_kwargs.setdefault("sticky", "ew")
        self.frame.grid(**grid_kwargs)
    
    def grid(self, **kwargs):
        self.frame.grid(**kwargs)


class LabeledField:
    """带标签的字段（标签 + 控件）"""
    
    def __init__(self, parent, label_text, widget, label_width=None):
        """
        Args:
            parent: 父容器
            label_text: 标签文字
            widget: 控件实例
            label_width: 标签宽度（字符数）
        """
        self.frame = ttk.Frame(parent, style='TFrame')
        
        if label_width is None:
            label_width = max(len(label_text), 6)
        
        # 标签
        self.label = ttk.Label(self.frame, text=label_text, width=label_width)
        self.label.grid(row=0, column=0, sticky="w", padx=(0, GridSystem.SPACING['sm']))
        
        # 控件
        self.widget = widget
        widget.grid(row=0, column=1, sticky="w")
    
    def pack(self, **kwargs):
        grid_kwargs = {k: v for k, v in kwargs.items() if k in ("padx", "pady")}
        grid_kwargs.setdefault("sticky", "w")
        self.frame.grid(**grid_kwargs)
    
    def grid(self, **kwargs):
        self.frame.grid(**kwargs)


class ParameterRow(ttk.Frame):
    """参数行 - 水平排列多个参数"""
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, style='TFrame', **kwargs)
        self.items = []
        # 为了兼容性，添加frame属性指向自己
        self.frame = self
    
    def add_item(self, item_widget, padx=None):
        """添加项目"""
        if padx is None:
            padx = (0, GridSystem.SPACING['lg'])
        
        col = len(self.items)
        item_widget.grid(row=0, column=col, sticky="w", padx=padx)
        self.items.append(item_widget)
        return item_widget


class OptionsGroup:
    """选项组 - 多个复选框或单选框"""
    
    def __init__(self, parent, orientation='horizontal'):
        """
        Args:
            parent: 父容器
            orientation: 方向（horizontal/vertical）
        """
        self.frame = ttk.Frame(parent, style='TFrame')
        self.orientation = orientation
        self.options = []
    
    def add_checkbox(self, text, variable, command=None):
        """添加复选框"""
        from ..widgets.cursor_checkbox import CursorCheckbox
        
        cb = CursorCheckbox(self.frame, text=text, variable=variable, command=command)
        
        if self.orientation == 'horizontal':
            col = len(self.options)
            cb.grid(row=0, column=col, sticky="w", padx=(0, GridSystem.SPACING['md']))
        else:
            row = len(self.options)
            cb.grid(row=row, column=0, sticky="w", pady=GridSystem.SPACING['xs'])
        
        self.options.append(cb)
        return cb
    
    def pack(self, **kwargs):
        grid_kwargs = {k: v for k, v in kwargs.items() if k in ("padx", "pady")}
        grid_kwargs.setdefault("sticky", "w")
        self.frame.grid(**grid_kwargs)
    
    def grid(self, **kwargs):
        self.frame.grid(**kwargs)


class SectionDivider:
    """分区分隔线"""
    
    def __init__(self, parent):
        self.separator = ttk.Separator(parent, orient='horizontal')
    
    def pack(self, **kwargs):
        default_kwargs = {'sticky': 'ew', 'pady': GridSystem.SPACING['lg']}
        default_kwargs.update(kwargs)
        self.separator.grid(**default_kwargs)
    
    def grid(self, **kwargs):
        default_kwargs = {'sticky': 'ew', 'pady': GridSystem.SPACING['lg']}
        default_kwargs.update(kwargs)
        self.separator.grid(**default_kwargs)

