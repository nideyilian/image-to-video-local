#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Cursor 风格的栅格化设计系统
参考网页 Bootstrap Grid System
"""

from tkinter import ttk
from .cursor_theme import CursorTheme


class GridSystem:
    """栅格系统配置"""
    
    # 栅格列数
    COLUMNS = 12
    
    # 基础间距单位（8px）
    SPACING_UNIT = 8
    
    # 标准间距
    SPACING = {
        'xs': SPACING_UNIT * 1,      # 8px - 超小
        'sm': SPACING_UNIT * 1.5,    # 12px - 小
        'md': SPACING_UNIT * 2,      # 16px - 中
        'lg': SPACING_UNIT * 3,      # 24px - 大
        'xl': SPACING_UNIT * 4,      # 32px - 超大
        'xxl': SPACING_UNIT * 5,     # 40px - 巨大
    }
    
    # 标准组件高度
    HEIGHTS = {
        'input': 32,        # 输入框、下拉框
        'button': 32,       # 按钮
        'button_lg': 40,    # 大按钮
        'label': 20,        # 标签
        'title': 28,        # 标题
    }
    
    # 标准组件宽度
    WIDTHS = {
        'xs': 60,          # 超小（如：序号）
        'sm': 80,          # 小（如：浏览按钮）
        'md': 120,         # 中（如：下拉框）
        'lg': 200,         # 大（如：输入框）
        'xl': 300,         # 超大
        'full': -1,        # 填充剩余空间
    }
    
    # 标准标签宽度
    LABEL_WIDTH = 80


class FormRow(ttk.Frame):
    """标准表单行组件"""
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, style='TFrame', **kwargs)
        self.columnconfigure(1, weight=1)  # 输入区域自动扩展
        self._row = 0
    
    def add_field(self, label_text, widget, label_width=None, widget_config=None):
        """
        添加表单字段
        
        Args:
            label_text: 标签文字
            widget: 输入控件类型（Entry, Combobox, Button等）
            label_width: 标签宽度（默认使用标准宽度）
            widget_config: 控件配置字典
        
        Returns:
            创建的控件实例
        """
        if label_width is None:
            label_width = GridSystem.LABEL_WIDTH
        
        if widget_config is None:
            widget_config = {}
        
        # 创建标签
        label = ttk.Label(self, text=label_text, width=label_width//7)  # 大约7px per char
        label.grid(row=self._row, column=0, sticky='w', 
                  padx=(0, GridSystem.SPACING['md']), 
                  pady=GridSystem.SPACING['xs'])
        
        # 创建控件
        if callable(widget):
            control = widget(self, **widget_config)
            control.grid(row=self._row, column=1, sticky='ew',
                        padx=(0, GridSystem.SPACING['md']),
                        pady=GridSystem.SPACING['xs'])
        else:
            # 如果是已创建的控件
            widget.grid(row=self._row, column=1, sticky='ew',
                       padx=(0, GridSystem.SPACING['md']),
                       pady=GridSystem.SPACING['xs'])
            control = widget
        
        self._row += 1
        return control
    
    def add_field_with_button(self, label_text, entry_var, button_text, button_command, 
                              label_width=None, button_width=None):
        """
        添加带按钮的字段（如：文件路径 + 浏览按钮）
        
        Args:
            label_text: 标签文字
            entry_var: 输入框变量
            button_text: 按钮文字
            button_command: 按钮命令
            label_width: 标签宽度
            button_width: 按钮宽度
        
        Returns:
            (entry, button) 元组
        """
        if label_width is None:
            label_width = GridSystem.LABEL_WIDTH
        if button_width is None:
            button_width = GridSystem.WIDTHS['sm']
        
        # 创建标签
        label = ttk.Label(self, text=label_text, width=label_width//7)
        label.grid(row=self._row, column=0, sticky='w',
                  padx=(0, GridSystem.SPACING['md']),
                  pady=GridSystem.SPACING['xs'])
        
        # 创建容器（输入框 + 按钮）
        container = ttk.Frame(self, style='TFrame')
        container.grid(row=self._row, column=1, sticky='ew',
                      padx=(0, GridSystem.SPACING['md']),
                      pady=GridSystem.SPACING['xs'])
        container.columnconfigure(0, weight=1)
        
        # 输入框
        entry = ttk.Entry(container, textvariable=entry_var)
        entry.grid(row=0, column=0, sticky='ew',
                  padx=(0, GridSystem.SPACING['sm']))
        
        # 按钮
        button = ttk.Button(container, text=button_text, command=button_command,
                           width=button_width//7)
        button.grid(row=0, column=1, sticky='e')
        
        self._row += 1
        return entry, button


class GridRow(ttk.Frame):
    """栅格行组件 - 支持12列布局"""
    
    def __init__(self, parent, columns=12, **kwargs):
        super().__init__(parent, style='TFrame', **kwargs)
        self.columns = columns
        
        # 配置所有列权重相等
        for i in range(columns):
            self.columnconfigure(i, weight=1, uniform='col')
    
    def add_widget(self, widget, col_start, col_span=1, sticky='ew', padx=None, pady=None):
        """
        添加组件到栅格
        
        Args:
            widget: 要添加的组件
            col_start: 起始列（0-11）
            col_span: 跨越列数（默认1）
            sticky: 对齐方式
            padx: 水平边距
            pady: 垂直边距
        
        Returns:
            添加的组件
        """
        if padx is None:
            padx = (GridSystem.SPACING['sm'], GridSystem.SPACING['sm'])
        if pady is None:
            pady = (GridSystem.SPACING['xs'], GridSystem.SPACING['xs'])
        
        widget.grid(row=0, column=col_start, columnspan=col_span,
                   sticky=sticky, padx=padx, pady=pady)
        return widget


class FieldGroup(ttk.Frame):
    """字段组 - 用于水平排列多个字段"""
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, style='TFrame', **kwargs)
        self._col = 0
        # 为了兼容性，添加frame属性指向自己
        self.frame = self
    
    def add_field(self, label_text, widget, widget_config=None, label_width=None):
        """
        添加字段
        
        Args:
            label_text: 标签文字
            widget: 控件类型或实例
            widget_config: 控件配置
            label_width: 标签宽度（字符数）
        
        Returns:
            创建的控件
        """
        if widget_config is None:
            widget_config = {}
        if label_width is None:
            label_width = len(label_text) + 2
        
        # 标签
        label = ttk.Label(self, text=label_text, width=label_width)
        label.grid(row=0, column=self._col, sticky='w',
                  padx=(0 if self._col == 0 else GridSystem.SPACING['lg'], 
                        GridSystem.SPACING['xs']))
        self._col += 1
        
        # 控件
        if callable(widget):
            control = widget(self, **widget_config)
        else:
            control = widget
        
        control.grid(row=0, column=self._col, sticky='w',
                    padx=(0, GridSystem.SPACING['md']))
        self._col += 1
        
        return control
    
    def add_spacer(self, width=None):
        """添加空白间隔"""
        if width is None:
            width = GridSystem.SPACING['lg']
        
        spacer = ttk.Frame(self, width=width, style='TFrame')
        spacer.grid(row=0, column=self._col, sticky='ew')
        self._col += 1


class StandardButton:
    """标准按钮创建器"""
    
    @staticmethod
    def create(parent, text, command, style='secondary', icon=None, width=None):
        """
        创建标准按钮
        
        Args:
            parent: 父容器
            text: 按钮文字
            command: 回调函数
            style: 样式（primary/secondary/success）
            icon: 图标（Emoji）
            width: 宽度（字符数）
        
        Returns:
            按钮实例
        """
        if icon:
            text = f"{icon} {text}"
        
        if style == 'primary':
            btn = CursorTheme.create_primary_button(parent, text, command)
        elif style == 'success':
            btn = CursorTheme.create_success_button(parent, text, command)
        else:
            btn = ttk.Button(parent, text=text, command=command)
        
        if width:
            btn.configure(width=width)
        
        return btn


class ButtonGroup(ttk.Frame):
    """按钮组 - 水平排列的按钮"""
    
    def __init__(self, parent, align='left', **kwargs):
        """
        Args:
            parent: 父容器
            align: 对齐方式（left/right/center）
        """
        super().__init__(parent, style='TFrame', **kwargs)
        self.align = align
        self._buttons = []
        self._col = 0
        self._left_spacer = None
        self._right_spacer = None
        
        if self.align in ('right', 'center'):
            self._left_spacer = ttk.Frame(self, style='TFrame')
            self._left_spacer.grid(row=0, column=0, sticky="ew")
            self.columnconfigure(0, weight=1)
            self._col = 1
        
        if self.align == 'center':
            self._right_spacer = ttk.Frame(self, style='TFrame')
            self._right_spacer.grid(row=0, column=2, sticky="ew")
            self.columnconfigure(2, weight=1)
    
    def add_button(self, text, command, style='secondary', icon=None, width=None):
        """添加按钮"""
        btn = StandardButton.create(self, text, command, style, icon, width)
        btn.grid(row=0, column=self._col, sticky="w", padx=(0, GridSystem.SPACING['sm']))
        self._col += 1
        
        if self.align == 'center' and self._right_spacer:
            self._right_spacer.grid(row=0, column=self._col, sticky="ew")
            self.columnconfigure(self._col, weight=1)
        
        self._buttons.append(btn)
        return btn
    
    def add_spacer(self):
        """添加弹性空间（用于分隔左右按钮）"""
        spacer = ttk.Frame(self, style='TFrame')
        spacer.grid(row=0, column=self._col, sticky="ew")
        self.columnconfigure(self._col, weight=1)
        self._col += 1


def create_labeled_input(parent, label_text, variable, width=None):
    """
    快速创建 标签+输入框 组合
    
    Returns:
        container, entry
    """
    container = ttk.Frame(parent, style='TFrame')
    
    container.grid_columnconfigure(1, weight=1)
    
    label = ttk.Label(container, text=label_text)
    label.grid(row=0, column=0, sticky="w", padx=(0, GridSystem.SPACING['xs']))
    
    entry = ttk.Entry(container, textvariable=variable, width=width)
    entry.grid(row=0, column=1, sticky="ew")
    
    return container, entry


def create_labeled_combobox(parent, label_text, variable, values, width=None):
    """
    快速创建 标签+下拉框 组合
    
    Returns:
        container, combobox
    """
    container = ttk.Frame(parent, style='TFrame')
    
    label = ttk.Label(container, text=label_text)
    label.grid(row=0, column=0, sticky="w", padx=(0, GridSystem.SPACING['xs']))
    
    combo = ttk.Combobox(container, textvariable=variable, values=values,
                         width=width, state='readonly')
    combo.grid(row=0, column=1, sticky="w")
    
    return container, combo


def create_labeled_spinbox(parent, label_text, variable, from_, to, increment=1, width=None):
    """
    快速创建 标签+数字选择框 组合
    
    Returns:
        container, spinbox
    """
    container = ttk.Frame(parent, style='TFrame')
    
    label = ttk.Label(container, text=label_text)
    label.grid(row=0, column=0, sticky="w", padx=(0, GridSystem.SPACING['xs']))
    
    spinbox = ttk.Spinbox(container, textvariable=variable,
                          from_=from_, to=to, increment=increment, width=width)
    spinbox.grid(row=0, column=1, sticky="w")
    
    return container, spinbox

