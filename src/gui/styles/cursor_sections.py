#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Cursor 风格的分区组件
使用分隔线而不是卡片背景
"""

from tkinter import ttk
from .cursor_theme import CursorTheme


def create_section(parent, title=None, **kwargs):
    """
    创建一个Cursor风格的分区
    
    Args:
        parent: 父容器
        title: 分区标题（可选）
        **kwargs: 传递给Frame的其他参数
    
    Returns:
        content_frame: 内容容器Frame
    """
    # 主容器
    section_container = ttk.Frame(parent, style='TFrame')
    section_container.grid_columnconfigure(0, weight=1)
    
    if title:
        # 标题行
        title_frame = ttk.Frame(section_container, style='TFrame')
        title_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        title_frame.grid_columnconfigure(1, weight=1)
        
        # 标题文字
        title_label = ttk.Label(
            title_frame,
            text=title,
            font=(CursorTheme.FONTS['subtitle'][0], 
                  CursorTheme.FONTS['subtitle'][1], 
                  'bold'),
            foreground=CursorTheme.COLORS['text_highlight'],
            style='TLabel'
        )
        title_label.grid(row=0, column=0, sticky="w")
        
        # 标题后的分隔线
        title_sep = ttk.Separator(title_frame, orient='horizontal')
        title_sep.grid(row=0, column=1, sticky="ew", padx=(12, 0))
    
    # 内容区域
    content_frame = ttk.Frame(section_container, style='TFrame', **kwargs)
    content_frame.grid(row=1 if title else 0, column=0, sticky="nsew", pady=(0, 0))
    section_container.grid_rowconfigure(1 if title else 0, weight=1)
    
    # 底部分隔线
    bottom_sep = ttk.Separator(section_container, orient='horizontal')
    bottom_sep.grid(row=2 if title else 1, column=0, sticky="ew", pady=(12, 0))
    
    return section_container, content_frame


def create_section_title(parent, title):
    """
    创建一个独立的分区标题
    
    Args:
        parent: 父容器
        title: 标题文字
    
    Returns:
        title_frame: 标题容器
    """
    title_frame = ttk.Frame(parent, style='TFrame')
    
    # 尝试获取主题颜色，如果失败则使用默认值
    try:
        from .ios_light_theme import IOSLightTheme as Theme
    except:
        try:
            from .cursor_theme import CursorTheme as Theme
        except:
            # 默认配置
            class Theme:
                FONTS = {'subtitle': ('Segoe UI', 11, 'bold')}
                COLORS = {'text_highlight': '#000000'}
    
    # 标题文字
    title_frame.grid_columnconfigure(1, weight=1)
    title_label = ttk.Label(
        title_frame,
        text=title,
        font=Theme.FONTS['subtitle'],
        style='Subtitle.TLabel'
    )
    title_label.grid(row=0, column=0, sticky="w", padx=(0, 12))
    
    # 分隔线
    sep = ttk.Separator(title_frame, orient='horizontal')
    sep.grid(row=0, column=1, sticky="ew")
    
    return title_frame

