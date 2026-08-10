#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
iOS 风格的浅色主题
参考 iOS Human Interface Guidelines
"""

import tkinter as tk
from tkinter import ttk


class IOSLightTheme:
    """iOS 浅色主题配置"""
    
    # 颜色方案 - Cinematic dark workspace palette
    COLORS = {
        # 背景色
        'bg_primary': '#070B12',
        'bg_secondary': '#0D1420',
        'bg_tertiary': '#0D1420',
        'bg_hover': '#132033',
        'bg_active': '#123A52',
        'bg_input': '#0D1420',
        
        # 文字色
        'text_primary': '#E6EDF7',
        'text_secondary': '#93A4BD',
        'text_tertiary': '#6E7F97',
        'text_disabled': '#4F647F',
        'text_highlight': '#ECF3FF',
        
        # 边框色
        'border': '#1E2A3A',
        'border_light': '#1A2636',
        'border_focus': '#38BDF8',
        
        # 强调色
        'accent': '#06B6D4',
        'accent_hover': '#22D3EE',
        'success': '#06B6D4',
        'warning': '#F59E0B',
        'error': '#EF4444',
        'info': '#38BDF8',
        
        # 按钮色
        'button_primary': '#06B6D4',
        'button_primary_hover': '#22D3EE',
        'button_secondary': '#0D1420',
        'button_secondary_hover': '#132033',
        
        # 进度条
        'progress_bg': '#1A2636',
        'progress_fill': '#38BDF8',
        
        # 分隔线
        'separator': '#1A2636',
    }
    
    # 字体配置
    FONTS = {
        'default': ('SF Pro Text', 10),      # iOS 默认字体（或 -apple-system）
        'title': ('SF Pro Display', 13, 'bold'),
        'subtitle': ('SF Pro Text', 11, 'bold'),
        'normal': ('SF Pro Text', 10),
        'small': ('SF Pro Text', 9),
    }
    
    # 如果没有SF Pro字体，使用系统默认字体
    FONTS_FALLBACK = {
        'default': ('Segoe UI', 10),
        'title': ('Segoe UI', 13, 'bold'),
        'subtitle': ('Segoe UI', 11, 'bold'),
        'normal': ('Segoe UI', 10),
        'small': ('Segoe UI', 9),
    }
    
    @classmethod
    def apply_theme(cls, root: tk.Tk):
        """应用iOS浅色主题到Tkinter窗口"""
        
        # 尝试使用SF Pro字体，如果不可用则使用备选
        try:
            test_font = tk.font.Font(family='SF Pro Text', size=10)
            fonts = cls.FONTS
        except:
            fonts = cls.FONTS_FALLBACK
        
        # 设置调色板
        root.tk_setPalette(
            background=cls.COLORS['bg_primary'],
            foreground=cls.COLORS['text_primary'],
            activeBackground=cls.COLORS['accent'],
            activeForeground='white',
            highlightBackground=cls.COLORS['border_focus'],
            highlightForeground=cls.COLORS['text_primary']
        )
        
        # 配置根窗口
        root.configure(bg=cls.COLORS['bg_primary'])
        root.option_add("*Font", fonts['default'])
        
        # 创建样式
        style = ttk.Style()
        style.theme_use("clam")
        
        # === 配置整体 ===
        style.configure(".",
            font=fonts['default'],
            background=cls.COLORS['bg_primary'],
            foreground=cls.COLORS['text_primary'],
            bordercolor=cls.COLORS['border'])
        
        # === 配置 Frame ===
        style.configure('TFrame',
            background=cls.COLORS['bg_primary'],
            relief='flat',
            borderwidth=0)
        
        style.configure('Card.TFrame',
            background=cls.COLORS['bg_secondary'],
            relief='flat',
            borderwidth=0)
        
        # === 配置 Label ===
        style.configure('TLabel',
            background=cls.COLORS['bg_primary'],
            foreground=cls.COLORS['text_primary'],
            font=fonts['default'])
        
        style.configure('Title.TLabel',
            foreground=cls.COLORS['text_primary'],
            font=fonts['title'])
        
        style.configure('Subtitle.TLabel',
            background=cls.COLORS['bg_primary'],
            foreground=cls.COLORS['text_primary'],
            font=fonts['subtitle'])
        
        style.configure('Status.TLabel',
            background=cls.COLORS['bg_primary'],
            foreground=cls.COLORS['text_secondary'],
            font=fonts['default'],
            padding=(4, 4))
        
        # === 配置 Button ===
        style.configure('TButton',
            background=cls.COLORS['button_secondary'],
            foreground=cls.COLORS['text_primary'],
            borderwidth=1,
            bordercolor=cls.COLORS['border'],
            relief='flat',
            padding=(12, 6),
            font=fonts['default'])
        
        style.map('TButton',
            background=[
                ('active', cls.COLORS['button_secondary_hover']),
                ('pressed', cls.COLORS['bg_hover']),
                ('disabled', cls.COLORS['bg_secondary'])
            ],
            foreground=[
                ('disabled', cls.COLORS['text_disabled'])
            ])
        
        # 主按钮
        style.configure('Primary.TButton',
            background=cls.COLORS['button_primary'],
            foreground='white',
            borderwidth=0,
            relief='flat')
        
        style.map('Primary.TButton',
            background=[
                ('active', cls.COLORS['button_primary_hover']),
                ('pressed', '#0040A0'),
                ('disabled', cls.COLORS['bg_secondary'])
            ],
            foreground=[
                ('disabled', cls.COLORS['text_disabled'])
            ])
        
        # 成功按钮
        style.configure('Success.TButton',
            background=cls.COLORS['success'],
            foreground='white',
            borderwidth=0,
            relief='flat')
        
        style.map('Success.TButton',
            background=[
                ('active', '#28A745'),
                ('pressed', '#1E7E34'),
                ('disabled', cls.COLORS['bg_secondary'])
            ],
            foreground=[
                ('disabled', cls.COLORS['text_disabled'])
            ])
        
        # === 配置 Entry ===
        style.configure('TEntry',
            fieldbackground=cls.COLORS['bg_input'],
            background=cls.COLORS['bg_input'],
            foreground=cls.COLORS['text_primary'],
            bordercolor=cls.COLORS['border'],
            borderwidth=1,
            relief='solid',
            insertcolor=cls.COLORS['accent'],
            padding=6)
        
        style.map('TEntry',
            bordercolor=[
                ('focus', cls.COLORS['border_focus']),
                ('!focus', cls.COLORS['border'])
            ])
        
        # === 配置 Combobox ===
        style.configure('TCombobox',
            fieldbackground=cls.COLORS['bg_input'],
            background=cls.COLORS['bg_input'],
            foreground=cls.COLORS['text_primary'],
            selectbackground=cls.COLORS['accent'],
            selectforeground='white',
            bordercolor=cls.COLORS['border'],
            borderwidth=1,
            relief='solid',
            padding=6)
        
        style.map('TCombobox',
            fieldbackground=[
                ('readonly', cls.COLORS['bg_input'])
            ],
            bordercolor=[
                ('focus', cls.COLORS['border_focus']),
                ('!focus', cls.COLORS['border'])
            ])
        
        # 下拉箭头
        style.configure('TCombobox.downarrow',
            background=cls.COLORS['bg_input'],
            foreground=cls.COLORS['text_secondary'])
        
        style.map('TCombobox.downarrow',
            background=[
                ('active', cls.COLORS['accent'])
            ],
            foreground=[
                ('active', 'white')
            ])
        
        # === 配置 Spinbox ===
        style.configure('TSpinbox',
            fieldbackground=cls.COLORS['bg_input'],
            background=cls.COLORS['bg_input'],
            foreground=cls.COLORS['text_primary'],
            bordercolor=cls.COLORS['border'],
            borderwidth=1,
            relief='solid',
            padding=6)
        
        style.map('TSpinbox',
            bordercolor=[
                ('focus', cls.COLORS['border_focus']),
                ('!focus', cls.COLORS['border'])
            ])
        
        # === 配置 Checkbutton ===
        style.configure('TCheckbutton',
            background=cls.COLORS['bg_primary'],
            foreground=cls.COLORS['text_primary'],
            font=fonts['default'],
            indicatorsize=16)
        
        style.map('TCheckbutton',
            background=[
                ('active', cls.COLORS['bg_primary'])
            ],
            indicatorbackground=[
                ('selected', cls.COLORS['accent']),
                ('!selected', cls.COLORS['bg_input'])
            ])
        
        # === 配置 Radiobutton ===
        style.configure('TRadiobutton',
            background=cls.COLORS['bg_primary'],
            foreground=cls.COLORS['text_primary'],
            font=fonts['default'])
        
        # === 配置 Notebook (标签页) ===
        style.configure('TNotebook',
            background=cls.COLORS['bg_primary'],
            borderwidth=0)
        
        style.configure('TNotebook.Tab',
            background=cls.COLORS['bg_secondary'],
            foreground=cls.COLORS['text_secondary'],
            padding=[16, 8],
            borderwidth=0)
        
        style.map('TNotebook.Tab',
            background=[
                ('selected', cls.COLORS['bg_primary']),
                ('active', cls.COLORS['bg_hover'])
            ],
            foreground=[
                ('selected', cls.COLORS['accent']),
                ('active', cls.COLORS['text_primary'])
            ])
        
        # === 配置 Progressbar ===
        style.configure('TProgressbar',
            background=cls.COLORS['progress_fill'],
            troughcolor=cls.COLORS['progress_bg'],
            borderwidth=0,
            thickness=8)
        
        # === 配置 Separator ===
        style.configure('TSeparator',
            background=cls.COLORS['separator'])
        
        # === 配置 LabelFrame ===
        style.configure('TLabelframe',
            background=cls.COLORS['bg_primary'],
            borderwidth=0,
            relief='flat')
        
        style.configure('TLabelframe.Label',
            background=cls.COLORS['bg_primary'],
            foreground=cls.COLORS['text_primary'],
            font=fonts['subtitle'],
            padding=(0, 4))
        
        # === 配置 Scrollbar ===
        style.configure('TScrollbar',
            background=cls.COLORS['bg_secondary'],
            troughcolor=cls.COLORS['bg_primary'],
            bordercolor=cls.COLORS['border'],
            arrowcolor=cls.COLORS['text_secondary'],
            relief='flat')
        
        style.map('TScrollbar',
            background=[
                ('active', cls.COLORS['accent'])
            ],
            arrowcolor=[
                ('active', 'white')
            ])
        
        return style
    
    @staticmethod
    def create_primary_button(parent, text, command, **kwargs):
        """创建iOS风格主按钮"""
        btn = ttk.Button(parent, text=text, command=command, 
                        style="Primary.TButton", **kwargs)
        return btn
    
    @staticmethod
    def create_secondary_button(parent, text, command, **kwargs):
        """创建iOS风格次要按钮"""
        btn = ttk.Button(parent, text=text, command=command, 
                        style="TButton", **kwargs)
        return btn
    
    @staticmethod
    def create_success_button(parent, text, command, **kwargs):
        """创建iOS风格成功按钮"""
        btn = ttk.Button(parent, text=text, command=command, 
                        style="Success.TButton", **kwargs)
        return btn


def apply_ios_light_theme(root: tk.Tk):
    """应用iOS浅色主题（便捷函数）"""
    return IOSLightTheme.apply_theme(root)

