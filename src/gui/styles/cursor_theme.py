#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Cursor 风格的现代化深色主题
参考 Cursor IDE 的设计规范
"""

import tkinter as tk
from tkinter import ttk

class CursorTheme:
    """Cursor 风格主题配置"""
    
    # 颜色方案 - 完全参考 Cursor IDE
    COLORS = {
        # 背景色
        'bg_primary': '#1e1e1e',      # 主背景
        'bg_secondary': '#252526',    # 次级背景（卡片）
        'bg_tertiary': '#2d2d30',     # 第三级背景
        'bg_hover': '#2a2d2e',        # 悬停背景
        'bg_active': '#094771',       # 激活背景
        'bg_input': '#313131',        # 输入框背景（更接近Cursor）
        
        # 文字色
        'text_primary': '#cccccc',    # 主文字
        'text_secondary': '#969696',  # 次级文字
        'text_disabled': '#6e6e6e',   # 禁用文字
        'text_highlight': '#ffffff',  # 高亮文字
        
        # 边框色
        'border': '#3e3e42',          # 边框
        'border_focus': '#007acc',    # 焦点边框
        
        # 强调色
        'accent': '#007acc',          # 主强调色（蓝色）
        'accent_hover': '#1c97ea',    # 强调色悬停
        'success': '#89d185',         # 成功（绿色）
        'warning': '#cca700',         # 警告（黄色）
        'error': '#f48771',           # 错误（红色）
        'info': '#75beff',            # 信息（浅蓝）
        
        # 按钮色
        'button_primary': '#0e639c',  # 主按钮
        'button_primary_hover': '#1177bb',
        'button_secondary': '#3c3c3c',
        'button_secondary_hover': '#505050',
        
        # 进度条
        'progress_bg': '#252526',
        'progress_fill': '#007acc',
    }
    
    # 字体配置
    FONTS = {
        'default': ('微软雅黑', 9),
        'title': ('微软雅黑', 11, 'bold'),
        'subtitle': ('微软雅黑', 10),
        'small': ('微软雅黑', 8),
        'code': ('Consolas', 9),
    }
    
    # 尺寸配置
    SIZES = {
        'padding_small': 4,
        'padding_medium': 8,
        'padding_large': 12,
        'border_radius': 4,
        'button_height': 28,
        'input_height': 26,
    }
    
    @classmethod
    def configure_style(cls, root):
        """配置全局样式"""
        style = ttk.Style()
        
        # 设置主题基础
        style.theme_use('clam')
        
        # === 配置根窗口 ===
        root.configure(bg=cls.COLORS['bg_primary'])
        
        # === 配置 Frame ===
        style.configure('TFrame', 
            background=cls.COLORS['bg_primary'])
        
        style.configure('Card.TFrame',
            background=cls.COLORS['bg_secondary'],
            relief='flat',
            borderwidth=1)
        
        # === 配置 Label ===
        style.configure('TLabel',
            background=cls.COLORS['bg_primary'],
            foreground=cls.COLORS['text_primary'],
            font=cls.FONTS['default'])
        
        style.configure('Title.TLabel',
            foreground=cls.COLORS['text_highlight'],
            font=cls.FONTS['title'])
        
        style.configure('Subtitle.TLabel',
            foreground=cls.COLORS['text_secondary'],
            font=cls.FONTS['subtitle'])
        
        # === 配置 Button ===
        style.configure('TButton',
            background=cls.COLORS['button_secondary'],
            foreground=cls.COLORS['text_primary'],
            borderwidth=1,
            relief='flat',
            font=cls.FONTS['default'],
            padding=(12, 6))
        
        style.map('TButton',
            background=[
                ('active', cls.COLORS['button_secondary_hover']),
                ('pressed', cls.COLORS['bg_active'])
            ],
            foreground=[
                ('disabled', cls.COLORS['text_disabled'])
            ])
        
        # 主按钮样式
        style.configure('Primary.TButton',
            background=cls.COLORS['button_primary'],
            foreground=cls.COLORS['text_highlight'])
        
        style.map('Primary.TButton',
            background=[
                ('active', cls.COLORS['button_primary_hover']),
                ('pressed', cls.COLORS['accent'])
            ])
        
        # 成功按钮
        style.configure('Success.TButton',
            background=cls.COLORS['success'],
            foreground='#000000')
        
        # === 配置 Entry ===
        style.configure('TEntry',
            fieldbackground=cls.COLORS['bg_input'],
            foreground=cls.COLORS['text_primary'],
            borderwidth=1,
            relief='flat',
            insertcolor=cls.COLORS['text_primary'])
        
        # === 配置 Combobox ===
        style.configure('TCombobox',
            fieldbackground=cls.COLORS['bg_input'],
            background=cls.COLORS['bg_input'],
            foreground=cls.COLORS['text_primary'],
            arrowcolor=cls.COLORS['text_primary'],
            borderwidth=1,
            relief='flat')
        
        style.map('TCombobox',
            fieldbackground=[('readonly', cls.COLORS['bg_input'])],
            selectbackground=[('readonly', cls.COLORS['bg_active'])],
            selectforeground=[('readonly', cls.COLORS['text_highlight'])])
        
        # === 配置 Checkbutton ===
        style.configure('TCheckbutton',
            background=cls.COLORS['bg_primary'],
            foreground=cls.COLORS['text_primary'],
            font=cls.FONTS['default'],
            indicatorsize=16,
            indicatorbackground=cls.COLORS['bg_input'],
            indicatorforeground=cls.COLORS['text_primary'])
        
        style.map('TCheckbutton',
            background=[('active', cls.COLORS['bg_primary'])],
            foreground=[('active', cls.COLORS['text_primary'])],
            indicatorbackground=[
                ('selected', cls.COLORS['accent']),
                ('!selected', cls.COLORS['bg_input'])
            ])
        
        # === 配置 Radiobutton ===
        style.configure('TRadiobutton',
            background=cls.COLORS['bg_primary'],
            foreground=cls.COLORS['text_primary'],
            font=cls.FONTS['default'])
        
        # === 配置 Notebook (标签页) ===
        style.configure('TNotebook',
            background=cls.COLORS['bg_primary'],
            borderwidth=0)
        
        style.configure('TNotebook.Tab',
            background=cls.COLORS['bg_secondary'],
            foreground=cls.COLORS['text_secondary'],
            padding=(12, 6),
            borderwidth=0)
        
        style.map('TNotebook.Tab',
            background=[
                ('selected', cls.COLORS['bg_primary']),
                ('active', cls.COLORS['bg_hover'])
            ],
            foreground=[
                ('selected', cls.COLORS['text_highlight']),
                ('active', cls.COLORS['text_primary'])
            ])
        
        # === 配置 Progressbar ===
        style.configure('TProgressbar',
            background=cls.COLORS['progress_fill'],
            troughcolor=cls.COLORS['progress_bg'],
            borderwidth=0,
            thickness=8)
        
        # === 配置状态栏 ===
        style.configure('Status.TLabel',
            background=cls.COLORS['bg_primary'],
            foreground=cls.COLORS['text_secondary'],
            font=cls.FONTS['default'],
            padding=(4, 4))
        
        # === 配置 LabelFrame（扁平式） ===
        style.configure('TLabelframe',
            background=cls.COLORS['bg_primary'],
            borderwidth=0,
            relief='flat')
        
        style.configure('TLabelframe.Label',
            background=cls.COLORS['bg_primary'],
            foreground=cls.COLORS['text_highlight'],
            font=cls.FONTS['subtitle'],
            padding=(0, 4))
        
        # === 配置 Separator（分隔线） ===
        style.configure('TSeparator',
            background=cls.COLORS['border'])
        
        # === 配置 Separator ===
        style.configure('TSeparator',
            background=cls.COLORS['border'])
        
        # === 配置 Scrollbar ===
        style.configure('TScrollbar',
            background=cls.COLORS['bg_secondary'],
            troughcolor=cls.COLORS['bg_primary'],
            borderwidth=0,
            arrowcolor=cls.COLORS['text_secondary'])
        
        style.map('TScrollbar',
            background=[('active', cls.COLORS['bg_hover'])])
        
        # === 配置 Scale ===
        style.configure('TScale',
            background=cls.COLORS['bg_primary'],
            troughcolor=cls.COLORS['bg_input'],
            borderwidth=0,
            sliderthickness=16)
        
        return style
    
    @classmethod
    def create_card_frame(cls, parent, **kwargs):
        """创建卡片式框架"""
        frame = ttk.Frame(parent, style='Card.TFrame', **kwargs)
        return frame
    
    @classmethod
    def create_section_title(cls, parent, text, **kwargs):
        """创建章节标题"""
        label = ttk.Label(parent, text=text, style='Title.TLabel', **kwargs)
        return label
    
    @classmethod
    def create_primary_button(cls, parent, text, command=None, **kwargs):
        """创建主按钮"""
        button = ttk.Button(parent, text=text, command=command, 
                          style='Primary.TButton', **kwargs)
        return button
    
    @classmethod
    def create_success_button(cls, parent, text, command=None, **kwargs):
        """创建成功按钮"""
        button = ttk.Button(parent, text=text, command=command,
                          style='Success.TButton', **kwargs)
        return button


def apply_cursor_theme(root):
    """应用 Cursor 主题到窗口"""
    return CursorTheme.configure_style(root)

