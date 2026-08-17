#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import random
import threading
import tkinter as tk
import customtkinter as ctk
from tkinter import ttk, filedialog
from tkinter import messagebox as tk_messagebox
from tkinter import simpledialog as tk_simpledialog
from ..utils.opencv_silent import import_cv2_silent
from ..utils.ffmpeg_runtime import configure_ffmpeg_environment, probe_ffmpeg, resolve_ffprobe_path
cv2 = import_cv2_silent()
configure_ffmpeg_environment(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
from pathlib import Path
# 修复moviepy导入问题
# from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip, CompositeVideoClip
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.audio.AudioClip import CompositeAudioClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
import time
import logging
import subprocess
import shutil
import json  # 导入json模块用于配置保存和加载
import uuid  # 导入uuid模块用于生成唯一ID
import traceback
import base64
from typing import Dict
import re

# 导入转场引擎
from ..core.transition_engine import TurboTransitionEngine, get_turbo_transition_engine
from ..utils.transition_constants import (
    GUI_TRANSITIONS, 
    ALL_TRANSITIONS, 
    DEFAULT_ENABLED_TRANSITIONS,
    TRANSITION_DESCRIPTIONS
)
from ..utils.timeline import cycle_images_to_duration, timeline_slot_count

# 导入主题和对话框
from .styles.ios_light_theme import apply_ios_light_theme, IOSLightTheme
from .styles.cursor_dialogs import CursorMessageBox, CursorInputDialog
from .styles.cursor_sections import create_section, create_section_title
from .styles.cursor_grid import (
    GridSystem, FormRow, FieldGroup, ButtonGroup, GridRow
)
from .styles.cursor_components import (
    FilePathInput, ResolutionInput, ParameterRow, OptionsGroup
)
from .widgets.cursor_checkbox import CursorCheckbox

# 创建兼容的对话框别名
messagebox = CursorMessageBox
simpledialog = CursorInputDialog

# 使用iOS主题别名
CursorTheme = IOSLightTheme

# UI 设计规范常量
SPACING = {
    "xxs": 4,
    "xs": 8,
    "sm": 12,
    "md": 16,
    "lg": 24,
    "xl": 32,
    "xxl": 48,
}


class ThemeManager:
    """CustomTkinter 主题管理器"""

    def __init__(self):
        self.colors: Dict[str, Dict[str, str]] = {
            "light": {
                # Cinematic dark workspace (reference style)
                "bg": "#070B12",
                "frame": "#0D1420",
                "sidebar": "#0B111B",
                "header": "#0B111B",
                "text_primary": "#E6EDF7",
                "text_secondary": "#93A4BD",
                "text_tertiary": "#6E7F97",
                "border": "#1E2A3A",
                "divider": "#1A2636",
                "hover": "#132033",
                "active": "#123A52",
                "shadow": "#08101A",
            },
            "dark": {
                "bg": "#060A11",
                "frame": "#0B121D",
                "sidebar": "#090F18",
                "header": "#090F18",
                "text_primary": "#ECF3FF",
                "text_secondary": "#9AAAC1",
                "text_tertiary": "#72839B",
                "border": "#223045",
                "divider": "#1B2739",
                "hover": "#16243A",
                "active": "#144B6A",
                "shadow": "#070D16",
            },
        }
        self.semantic = {
            "primary": "#06B6D4",  # cyan accent
            "success": "#06B6D4",  # keep primary/success visually unified
            "warning": "#F59E0B",
            "danger": "#EF4444",
            "info": "#38BDF8",
        }
        self.mode = "light"

    def set_mode(self, mode: str):
        self.mode = "dark" if mode.lower() == "dark" else "light"

    def get(self, key: str) -> str:
        return self.colors[self.mode][key]

    def sidebar_text(self) -> str:
        return "#ecf0f1"

    def primary(self) -> str:
        return self.semantic["primary"]

    def primary_hover(self) -> str:
        return "#22D3EE"

    def success(self) -> str:
        return self.semantic["success"]

    def success_hover(self) -> str:
        return "#0EA5C6"


_UI_FONTS: Dict[str, ctk.CTkFont] = {}


def ensure_ui_fonts() -> Dict[str, ctk.CTkFont]:
    """确保在 root 创建后初始化字体"""
    if _UI_FONTS:
        return _UI_FONTS

    family = "Segoe UI"
    _UI_FONTS.update({
        "h1": ctk.CTkFont(family=family, size=28, weight="bold"),
        "h2": ctk.CTkFont(family=family, size=19, weight="bold"),
        "h3": ctk.CTkFont(family=family, size=18, weight="bold"),
        "body": ctk.CTkFont(family=family, size=14),
        "small": ctk.CTkFont(family=family, size=11),
        "micro": ctk.CTkFont(family=family, size=10),
    })
    return _UI_FONTS

# 使用新的转场效果列表
TRANSITION_TYPES = GUI_TRANSITIONS
UI_TO_EFFECT_MAP = {name: name for name in GUI_TRANSITIONS}  # 一对一映射

# 单图视频特效选项
VIDEO_EFFECTS = [
    "无特效",
    "心跳跳动",
    "反复缩放",
    "轻微摇摆",
    "左右晃动",
    "上下浮动",
    "镜头呼吸",
    "脉冲放大",
    "旋转摆动",
    # 新增：无限循环复合特效（20个）
    "旋转呼吸",
    "摇摆推拉",
    "圆周漂移",
    "螺旋摆动",
    "双轴呼吸",
    "心跳摇摆",
    "波浪平移",
    "8字漂移",
    "径向脉冲旋转",
    "镜头抖动呼吸",
    "反向双旋",
    "呼吸变焦扫光",
    "旋摆模糊脉冲",
    "透视呼吸摆动",
    "涡旋推拉",
    "变焦摇移",
    "旋转漂移闪动",
    "双频摆动",
    "环形巡航",
    "呼吸鱼眼旋摆",
    "水波扭曲",
    "漩涡旋转",
    "鱼眼镜头",
    "故障抖动",
    "镜像扫光",
    "呼吸模糊",
    "径向拉伸",
    "边缘闪烁",
    "透视俯仰",
    "滚动快门",
    "灵魂出窍",
]

# 禁用MoviePy的默认日志输出
logging.getLogger('moviepy').setLevel(logging.ERROR)

# 自定义MoviePy进度条
class CustomProgressBar:
    def __init__(self, update_status_func, prefix=""):
        self.update_status_func = update_status_func
        self.prefix = prefix
        self.last_percent = 0
        self.start_time = time.time()
    
    def __call__(self, t, remaining, total):
        percent_done = int((t / total) * 100)
        # 只有当百分比变化较大时才更新状态，避免过多更新
        if percent_done - self.last_percent >= 5:
            elapsed = time.time() - self.start_time
            remaining_time = (elapsed / t) * (total - t) if t > 0 else 0
            message = f"{self.prefix}进度: {percent_done}% (剩余约{int(remaining_time)}秒)"
            self.update_status_func(message)
            self.last_percent = percent_done

# 新增：多标签页应用类
class MultiTabApp:
    def __init__(self, root):
        # 设置窗口不置顶
        root.attributes('-topmost', False)
        self.root = root
        self.root.title("图转视频极速版")
        self.root.geometry("1200x840")
        self.root.minsize(1200, 600)
        self.root.resizable(True, True)
        
        # 字体系统（需要 root 已创建）
        self.fonts = ensure_ui_fonts()

        # 主题管理
        self.theme = ThemeManager()
        self.theme.set_mode(ctk.get_appearance_mode())
        self._apply_ttk_theme()
        self.root.configure(fg_color=self.theme.get("bg"))
        
        # 多标签页配置文件路径
        self.tabs_config_file = os.path.join(os.getcwd(), "img2video_tabs_config.json")
        
        # 主布局：标题 + 顶部工具条 + 内容区（紧凑全平铺）
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(2, weight=1)

        self.app_title = ctk.CTkLabel(
            self.root,
            text="图转视频极速版",
            font=self.fonts["h2"],
            text_color=self.theme.get("text_primary")
        )
        self.app_title.grid(row=0, column=0, sticky="ew", padx=SPACING["md"], pady=(SPACING["xs"], 4))
        
        # 状态栏（顶部显示）
        self.status_text = tk.StringVar(value="✓ 就绪")
        self.current_tab_name = tk.StringVar(value="标签页 1")

        # 顶部工具条（紧凑）
        self.top_nav = ctk.CTkFrame(
            self.root,
            fg_color=self.theme.get("header"),
            corner_radius=14,
            border_width=1,
            border_color=self.theme.get("border")
        )
        self.top_nav.grid(row=1, column=0, sticky="ew", padx=SPACING["md"], pady=(4, SPACING["xs"]))
        for i in range(10):
            self.top_nav.grid_columnconfigure(i, weight=0)
        self.top_nav.grid_columnconfigure(8, weight=1)
        
        self.theme_button = ctk.CTkButton(
            self.top_nav,
            text="切换深色",
            width=118,
            height=36,
            corner_radius=10,
            fg_color=self.theme.primary(),
            hover_color=self.theme.primary_hover(),
            text_color="#ffffff",
            command=self.toggle_theme
        )
        self.theme_button.grid(row=0, column=0, padx=(SPACING["sm"], SPACING["xs"]), pady=SPACING["xs"])
        
        self.batch_button = ctk.CTkButton(
            self.top_nav,
            text="批量处理",
            width=118,
            height=36,
            corner_radius=10,
            fg_color=self.theme.success(),
            hover_color=self.theme.success_hover(),
            text_color="#ffffff",
            command=self.batch_process
        )
        self.batch_button.grid(row=0, column=1, padx=SPACING["xs"], pady=SPACING["xs"])
        
        self.open_button = ctk.CTkButton(
            self.top_nav,
            text="打开输出",
            width=108,
            height=36,
            corner_radius=10,
            fg_color=self.theme.get("frame"),
            border_width=1,
            border_color=self.theme.primary(),
            text_color=self.theme.primary(),
            hover_color=self.theme.get("hover"),
            command=self.open_current_output_dir
        )
        self.open_button.grid(row=0, column=2, padx=SPACING["xs"], pady=SPACING["xs"])
        
        self.save_button = ctk.CTkButton(
            self.top_nav,
            text="保存配置",
            width=108,
            height=36,
            corner_radius=10,
            fg_color=self.theme.get("frame"),
            border_width=1,
            border_color=self.theme.primary(),
            text_color=self.theme.primary(),
            hover_color=self.theme.get("hover"),
            command=self.save_current_config
        )
        self.save_button.grid(row=0, column=3, padx=SPACING["xs"], pady=SPACING["xs"])
        
        self.reload_button = ctk.CTkButton(
            self.top_nav,
            text="重载配置",
            width=108,
            height=36,
            corner_radius=10,
            fg_color=self.theme.get("frame"),
            border_width=1,
            border_color=self.theme.primary(),
            text_color=self.theme.primary(),
            hover_color=self.theme.get("hover"),
            command=self.reload_current_config
        )
        self.reload_button.grid(row=0, column=4, padx=SPACING["xs"], pady=SPACING["xs"])
        
        self.status_bar = ctk.CTkLabel(
            self.top_nav,
            textvariable=self.status_text,
            anchor="w",
            font=self.fonts["small"],
            text_color=self.theme.get("text_secondary"),
            fg_color=self.theme.get("frame"),
            corner_radius=10
        )
        self.status_bar.grid(row=0, column=5, padx=(SPACING["sm"], SPACING["sm"]), pady=SPACING["xs"], sticky="ew")
        self.top_nav.grid_columnconfigure(5, weight=1)
        
        self.perf_button = ctk.CTkButton(
            self.top_nav,
            text="性能统计",
            width=108,
            height=36,
            corner_radius=10,
            fg_color=self.theme.get("frame"),
            border_width=1,
            border_color=self.theme.primary(),
            text_color=self.theme.primary(),
            hover_color=self.theme.get("hover"),
            command=self.show_current_performance
        )
        self.perf_button.grid(row=0, column=6, padx=SPACING["xs"], pady=SPACING["xs"])
        
        self.memory_button = ctk.CTkButton(
            self.top_nav,
            text="内存优化",
            width=108,
            height=36,
            corner_radius=10,
            fg_color=self.theme.get("frame"),
            border_width=1,
            border_color=self.theme.primary(),
            text_color=self.theme.primary(),
            hover_color=self.theme.get("hover"),
            command=self.optimize_current_memory
        )
        self.memory_button.grid(row=0, column=7, padx=SPACING["xs"], pady=SPACING["xs"])

        # 多标签页控制移到标签页顶栏右侧（内容区内）
        
        self._sync_theme_button()
        
        # 内容区
        self.content_frame = ctk.CTkFrame(
            self.root,
            fg_color=self.theme.get("bg"),
            corner_radius=14,
            border_width=1,
            border_color=self.theme.get("border")
        )
        self.content_frame.grid(row=2, column=0, sticky="nsew", padx=SPACING["md"], pady=(0, SPACING["sm"]))
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(0, weight=1)

        # 创建标签页控件
        self.notebook = ttk.Notebook(self.content_frame)
        self.notebook.grid(row=0, column=0, sticky="nsew", padx=SPACING["sm"], pady=(6, 8))

        # 标签页操作区（覆盖在标签行右侧，不占内容宽度）
        self.tabs_controls = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.tabs_controls.place(relx=1.0, x=-SPACING["sm"], y=6, anchor="ne")

        self.tab_label = ctk.CTkLabel(self.tabs_controls, text="标签页:", font=self.fonts["small"])
        self.tab_label.grid(row=0, column=0, padx=(0, SPACING["xs"]), pady=0, sticky="e")
        self.tab_name_display = ctk.CTkEntry(self.tabs_controls, textvariable=self.current_tab_name, width=120, state="readonly")
        self.tab_name_display.grid(row=0, column=1, padx=(0, SPACING["xs"]), pady=0)
        self.tab_add_button = ctk.CTkButton(self.tabs_controls, text="+添加", width=70, height=28, command=self.add_tab)
        self.tab_add_button.grid(row=0, column=2, padx=(0, SPACING["xs"]), pady=0)
        self.tab_remove_button = ctk.CTkButton(self.tabs_controls, text="×移除", width=70, height=28, command=self.remove_current_tab)
        self.tab_remove_button.grid(row=0, column=3, padx=(0, 0), pady=0)
        
        # 保存所有标签页
        self.tabs = []
        
        # 批量处理相关变量
        self.batch_processing = False
        self.completed_tabs = 0
        self.processing_tabs_count = 0
        
        # 状态栏（Cursor 风格）
        self.status_text = tk.StringVar(value="✓ 就绪")
        # 状态栏已移动到顶部工具条
        
        # 尝试加载保存的标签页配置
        if os.path.exists(self.tabs_config_file):
            self.load_tabs_config()
        else:
            # 如果没有保存的配置，添加第一个标签页
            self.add_tab()
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _sync_theme_button(self):
        current_mode = ctk.get_appearance_mode()
        button_text = "切换浅色" if current_mode == "Dark" else "切换深色"
        self.theme_button.configure(text=button_text)

    def toggle_theme(self):
        current_mode = ctk.get_appearance_mode()
        new_mode = "Dark" if current_mode == "Light" else "Light"
        ctk.set_appearance_mode(new_mode)
        self.theme.set_mode(new_mode)
        self._apply_ttk_theme()
        self._apply_theme_to_layout()
        self._sync_theme_button()

    def _apply_ttk_theme(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        bg = self.theme.get("bg")
        fg = self.theme.get("text_primary")
        border = self.theme.get("border")
        entry_bg = self.theme.get("frame")
        accent = self.theme.primary()

        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TLabelframe", background=entry_bg, foreground=fg, bordercolor=border, relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=bg, foreground=self.theme.get("text_secondary"))
        style.configure("TButton", background=entry_bg, foreground=fg, bordercolor=border, relief="solid")
        style.map("TButton", background=[("active", self.theme.get("hover"))], foreground=[("active", fg)])
        style.configure("Primary.TButton", background=accent, foreground="#ffffff", bordercolor=accent)
        style.map("Primary.TButton", background=[("active", self.theme.primary_hover())])
        style.configure("Success.TButton", background=self.theme.success(), foreground="#ffffff", bordercolor=self.theme.success())
        style.map("Success.TButton", background=[("active", self.theme.success_hover())])
        style.configure("TEntry", fieldbackground=entry_bg, background=entry_bg, foreground=fg)
        style.configure("TCombobox", fieldbackground=entry_bg, background=entry_bg, foreground=fg)
        style.map("TCombobox", fieldbackground=[("readonly", entry_bg)], foreground=[("readonly", fg)])
        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure("TNotebook.Tab", background=entry_bg, foreground=self.theme.get("text_secondary"), padding=(12, 5))
        style.map("TNotebook.Tab", background=[("selected", self.theme.get("active"))], foreground=[("selected", accent)])
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("TRadiobutton", background=bg, foreground=fg)
        style.configure("TScale", background=bg, troughcolor=entry_bg)
        style.configure("Status.TLabel", background=entry_bg, foreground=self.theme.get("text_secondary"))
        style.configure("TProgressbar", background=self.theme.semantic["info"], troughcolor=self.theme.get("divider"), thickness=6)
        style.configure("TSeparator", background=self.theme.get("divider"))

    def _apply_theme_to_layout(self):
        self.root.configure(fg_color=self.theme.get("bg"))
        self.app_title.configure(text_color=self.theme.get("text_primary"))
        self.top_nav.configure(
            fg_color=self.theme.get("header"),
            border_color=self.theme.get("border")
        )
        self.theme_button.configure(
            fg_color=self.theme.primary(),
            hover_color=self.theme.primary_hover(),
            text_color="#ffffff"
        )
        self.batch_button.configure(
            fg_color=self.theme.success(),
            hover_color=self.theme.success_hover(),
            text_color="#ffffff"
        )
        self.open_button.configure(
            fg_color=self.theme.get("frame"),
            border_color=self.theme.primary(),
            text_color=self.theme.primary(),
            hover_color=self.theme.get("hover")
        )
        self.save_button.configure(
            fg_color=self.theme.get("frame"),
            border_color=self.theme.primary(),
            text_color=self.theme.primary(),
            hover_color=self.theme.get("hover")
        )
        self.reload_button.configure(
            fg_color=self.theme.get("frame"),
            border_color=self.theme.primary(),
            text_color=self.theme.primary(),
            hover_color=self.theme.get("hover")
        )
        self.perf_button.configure(
            fg_color=self.theme.get("frame"),
            border_color=self.theme.primary(),
            text_color=self.theme.primary(),
            hover_color=self.theme.get("hover")
        )
        self.memory_button.configure(
            fg_color=self.theme.get("frame"),
            border_color=self.theme.primary(),
            text_color=self.theme.primary(),
            hover_color=self.theme.get("hover")
        )
        self.content_frame.configure(
            fg_color=self.theme.get("bg"),
            border_color=self.theme.get("border")
        )
        self.status_bar.configure(
            text_color=self.theme.get("text_secondary"),
            fg_color=self.theme.get("frame")
        )
        if hasattr(self, "tab_label"):
            self.tab_label.configure(text_color=self.theme.get("text_secondary"))
    
    def add_tab(self, tab_config_file=None):
        """添加新标签页"""
        tab_id = str(uuid.uuid4())[:8]  # 生成唯一ID
        tab_name = f"标签页 {len(self.tabs) + 1}"
        
        # 创建标签页框架
        tab_frame = ttk.Frame(self.notebook)
        
        # 如果指定了配置文件，使用它创建标签页
        if tab_config_file and os.path.exists(tab_config_file):
            tab_app = ImageToVideoTab(
                tab_frame,
                self.tab_status_callback,
                config_file=tab_config_file,
                main_app=self,
                tab_name_var=self.current_tab_name
            )
        else:
            # 为新标签页创建唯一的配置文件名
            tab_config_file = os.path.join(os.getcwd(), f"img2video_config_{tab_id}.json")
            tab_app = ImageToVideoTab(
                tab_frame,
                self.tab_status_callback,
                config_file=tab_config_file,
                main_app=self,
                tab_name_var=self.current_tab_name
            )
        
        # 将标签页添加到notebook
        self.notebook.add(tab_frame, text=tab_name)
        
        # 保存标签页信息
        self.tabs.append({
            "id": tab_id,
            "name": tab_name,
            "frame": tab_frame,
            "app": tab_app,
            "config_file": tab_config_file,
            "completed": False
        })
        
        # 切换到新标签页
        self.notebook.select(len(self.tabs) - 1)
        self.current_tab_name.set(tab_name)
        
        # 保存标签页配置
        self.save_tabs_config()
        
        self.update_status(f"已添加{tab_name}")
        return tab_app
    
    def remove_current_tab(self):
        """移除当前选中的标签页"""
        if len(self.tabs) <= 1:
            messagebox.showwarning("警告", "至少需要保留一个标签页")
            return
        
        current_tab_index = self.notebook.index(self.notebook.select())
        
        # 检查是否有处理中的任务
        if self.tabs[current_tab_index]["app"].is_processing:
            if not messagebox.askyesno("警告", "当前标签页正在处理任务，确定要移除吗？"):
                return
        
        # 移除标签页
        self.notebook.forget(current_tab_index)
        removed_tab = self.tabs.pop(current_tab_index)
        
        # 更新剩余标签页的名称
        for i, tab in enumerate(self.tabs):
            tab["name"] = f"标签页 {i+1}"
            self.notebook.tab(i, text=tab["name"])
        
        # 保存标签页配置
        self.save_tabs_config()
        
        self.update_status(f"已移除{removed_tab['name']}")
    
    def save_tabs_config(self):
        """保存所有标签页的配置信息"""
        try:
            # 收集所有标签页的配置信息
            tabs_config = []
            for tab in self.tabs:
                # 保存标签页的配置到对应的文件
                tab["app"].save_config(show_message=False)
                
                # 收集标签页的基本信息
                tabs_config.append({
                    "id": tab["id"],
                    "name": tab["name"],
                    "config_file": tab["config_file"]
                })
            
            # 将标签页配置信息保存到主配置文件
            with open(self.tabs_config_file, 'w', encoding='utf-8') as f:
                json.dump(tabs_config, f, ensure_ascii=False, indent=4)
            
            self.update_status("已保存所有标签页配置")
        except Exception as e:
            self.update_status(f"保存标签页配置失败: {str(e)}")
    
    def load_tabs_config(self):
        """加载标签页配置"""
        try:
            # 从主配置文件加载标签页信息
            with open(self.tabs_config_file, 'r', encoding='utf-8') as f:
                tabs_config = json.load(f)
            
            # 根据配置信息创建标签页
            for tab_info in tabs_config:
                # 创建标签页
                self.add_tab(tab_info.get("config_file"))
            
            self.update_status("已加载保存的标签页配置")
        except Exception as e:
            # 如果加载失败，创建一个默认标签页
            self.update_status(f"加载标签页配置失败: {str(e)}")
            self.add_tab()
    
    def batch_process(self):
        """批量处理所有标签页"""
        # 检查是否有标签页
        if not self.tabs:
            messagebox.showwarning("警告", "没有可处理的标签页")
            return
        
        # 统计已配置的标签页
        configured_tabs = [tab for tab in self.tabs if tab["app"].input_dir.get()]
        
        if not configured_tabs:
            messagebox.showwarning("警告", "没有配置好的标签页，请先在每个标签页中设置输入目录")
            return
        
        # 询问用户是否确认批量处理
        if not messagebox.askyesno("确认", f"确定要批量处理 {len(configured_tabs)} 个标签页吗？"):
            return
        
        # 重置批量处理状态
        self.batch_processing = True
        self.completed_tabs = 0
        self.processing_tabs_count = len(configured_tabs)  # 修改：直接使用配置好的标签页数量
        
        # 重置所有标签页的完成状态和处理标志
        for tab in self.tabs:
            tab["completed"] = False
            # 确保任何正在进行的处理先停止
            if tab["app"].is_processing:
                tab["app"].is_processing = False
                # 等待一小段时间让线程停止
                time.sleep(0.5)
        
        self.update_status(f"准备批量处理 {self.processing_tabs_count} 个标签页")
        
        # 启动所有标签页的处理
        for tab in configured_tabs:
            # 确保标签页处于未处理状态
            tab["app"].is_processing = False
            # 设置批处理模式标志
            tab["app"].batch_mode = True
            # 设置父窗口更新状态回调
            tab["app"].parent_update_status = self.tab_status_callback
            # 启动处理
            tab["app"].start_processing()
        
        self.update_status(f"已启动批量处理 {self.processing_tabs_count} 个标签页")
    
    def tab_status_callback(self, message, tab_completed=False):
        """标签页状态回调函数"""
        self.update_status(message)
        
        # 如果标签页处理完成且在批处理模式下
        if tab_completed and self.batch_processing:
            self.completed_tabs += 1
            self.update_status(f"已完成 {self.completed_tabs}/{self.processing_tabs_count} 个标签页")
            
            # 检查是否所有标签页都已完成
            if self.completed_tabs >= self.processing_tabs_count:
                self.batch_processing = False
                self.root.after(500, self.show_batch_complete_dialog)  # 延迟显示完成对话框
    
    def show_batch_complete_dialog(self):
        """显示批处理完成对话框"""
        if messagebox.askyesno("批量处理完成", f"所有 {self.processing_tabs_count} 个标签页的处理任务已完成！\n是否打开输出目录？"):
            # 使用第一个标签页的输出目录
            if self.tabs and hasattr(self.tabs[0]["app"], "open_output_dir"):
                self.tabs[0]["app"].open_output_dir()
    
    def update_status(self, message):
        """更新状态栏信息"""
        self.status_text.set(message)
        if hasattr(self, "detail_info_var"):
            text = message.replace("\n", " ").strip()
            if len(text) > 40:
                text = text[:37] + "..."
            self.detail_info_var.set(f"状态: {text}")

    def _on_tab_changed(self, event=None):
        try:
            current_index = self.notebook.index(self.notebook.select())
            if current_index < len(self.tabs):
                self.current_tab_name.set(self.tabs[current_index]["name"])
        except Exception:
            pass

    def _get_current_tab_app(self):
        """获取当前标签页应用实例"""
        if not self.tabs:
            return None
        try:
            current_index = self.notebook.index(self.notebook.select())
            return self.tabs[current_index]["app"]
        except Exception:
            return None

    def open_current_output_dir(self):
        app = self._get_current_tab_app()
        if app and hasattr(app, "open_output_dir"):
            app.open_output_dir()

    def save_current_config(self):
        app = self._get_current_tab_app()
        if app and hasattr(app, "save_config"):
            app.save_config(True)

    def reload_current_config(self):
        app = self._get_current_tab_app()
        if app and hasattr(app, "reload_config"):
            app.reload_config()

    def show_current_performance(self):
        app = self._get_current_tab_app()
        if app and hasattr(app, "show_performance_stats"):
            app.show_performance_stats()

    def optimize_current_memory(self):
        app = self._get_current_tab_app()
        if app and hasattr(app, "optimize_memory"):
            app.optimize_memory()
    
    def on_closing(self):
        """窗口关闭事件处理"""
        # 检查是否有正在处理的标签页
        processing_tabs = [tab for tab in self.tabs if tab["app"].is_processing]
        
        if processing_tabs:
            if not messagebox.askyesno("警告", f"有 {len(processing_tabs)} 个标签页正在处理，关闭程序将中断处理。\n是否确定关闭？"):
                return
        
        # 保存所有标签页的配置
        self.save_tabs_config()
        
        # 关闭窗口
        self.root.destroy()
        


# 修改原来的 ImageToVideoApp 类为 ImageToVideoTab
class ImageToVideoTab:
    def __init__(self, parent, parent_update_status=None, config_file=None, main_app=None, tab_name_var=None):
        """初始化"""
        # 创建父容器的引用
        self.parent = parent
        self.parent_update_status = parent_update_status
        self.main_app = main_app
        
        # 批处理模式标志
        self.batch_mode = False
        
        # 设置subprocess启动信息
        self.startupinfo = None
        if os.name == 'nt':  # Windows平台
            self.startupinfo = subprocess.STARTUPINFO()
            self.startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.startupinfo.wShowWindow = 0  # SW_HIDE
        
        # 如果没有指定配置文件，使用默认路径
        if config_file is None:
            config_file = os.path.join(os.getcwd(), "img2video_config.json")
        
        # 配置文件路径
        self.config_file = config_file

        # 运行时能力缓存（阶段1：启动预检查）
        self._codec_probe_cache = {}
        self._runtime_probe = {}
        self._pipeline_log_file = os.path.join(os.getcwd(), "video_pipeline.log")
        
        # 检测ffmpeg是否可用
        self.ffmpeg_available = self.check_ffmpeg()
        
        # 样式已由主题统一管理，无需单独配置
        
        # 变量
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar(value=os.path.join(os.getcwd(), "output"))
        self.num_images = tk.IntVar(value=10)
        self.duration = tk.DoubleVar(value=2.0)
        self.total_duration = tk.DoubleVar(value=0.0)
        self.fps = tk.IntVar(value=30)
        self.video_count = tk.IntVar(value=1)
        self.video_format = tk.StringVar(value="avi")
        self.width = tk.IntVar(value=1280)
        self.height = tk.IntVar(value=720)
        self.resolution_presets = [
            "1280x720",
            "1920x1080",
            "2560x1440",
            "3840x2160",
            "1080x1920",
            "720x1280",
        ]
        self.resolution_preset_var = tk.StringVar(value="1280x720")
        self._resolution_comboboxes = []
        self.progress_var = tk.DoubleVar(value=0.0)
        self.overall_progress_var = tk.DoubleVar(value=0.0)
        self.status_text = tk.StringVar(value="准备就绪")
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.is_paused = False
        self.cancel_requested = False
        self._speed_start_time = None
        self._speed_processed = 0
        self.overall_total_videos = 0
        self.current_video_index = 0
        self._last_cache_cleanup = 0.0
        self._cache_cleanup_interval = 2.0
        self._progress_last_ui_ts = 0.0
        self._progress_last_percent = -1
        self._progress_ui_min_interval = 0.08
        self.tab_name_var = tab_name_var or tk.StringVar(value="标签页")
        
        # 新增：视频码率设置
        self.bitrate = tk.IntVar(value=5000)  # 默认5000kbps
        
        # 新增：水印设置
        self.use_watermark = tk.BooleanVar(value=False)
        self.watermark_path = tk.StringVar()
        self.watermark_type = tk.StringVar(value="视频")  # 仅保留视频水印
        self.watermark_position = tk.StringVar(value="右下")
        self.watermark_match_method = tk.StringVar(value="循环")  # 视频水印匹配方法
        self.watermark_audio = tk.StringVar(value="使用BGM")  # 控制使用BGM还是水印声音
        self.watermark_mode = tk.StringVar(value="单文件")  # 新增：水印模式，"单文件"或"文件夹"
        self.watermark_size_mode = tk.StringVar(value="自适应覆盖")  # 新增：水印大小模式
        self.watermark_scale = tk.DoubleVar(value=20.0)  # 水印缩放比例（百分比）
        self.watermark_blend_mode = tk.StringVar(value="正常")  # 新增：混合模式
        self.watermark_layers = []  # 多重水印图层配置
        self.watermark_layer_rows = []  # 多重水印UI行
        
        # 新增：等比缩放选项
        self.keep_aspect_ratio = tk.BooleanVar(value=True)
        
        # 新增：转场效果选项
        self.use_transition = tk.BooleanVar(value=True)
        self.transition_type = tk.StringVar(value="淡入淡出")
        self.random_transition = tk.BooleanVar(value=False)

        # 新增：单图视频特效
        self.use_video_effect = tk.BooleanVar(value=False)
        self.video_effect_type = tk.StringVar(value="镜头呼吸")
        self.random_video_effect = tk.BooleanVar(value=False)
        self.video_effect_intensity = tk.DoubleVar(value=100.0)  # 100=默认强度
        self.video_effect_speed = tk.DoubleVar(value=1.0)  # 1.0=默认速度
        self.effect_preview_time = tk.DoubleVar(value=1.0)  # 单图特效预览时间点（秒）
        self.effect_preview_label = None
        self._effect_preview_photo = None
        self._effect_preview_after_id = None
        self._effect_preview_source_frame = None
        self._effect_preview_started_at = 0.0
        self._effect_preview_start_offset = 0.0
        self._effect_preview_max_seconds = 4.0
        self._effect_preview_visible = True
        self._effect_preview_toggle_button = None
        self.enabled_video_effects = [e for e in VIDEO_EFFECTS if e != "无特效"]
        
        # 初始化转场引擎
        self.transition_engine = None
        self._init_transition_engine()
        
        # 可用的转场效果列表（用于随机选择）
        self.enabled_transitions = DEFAULT_ENABLED_TRANSITIONS.copy()
        
        # 新增：BGM设置
        self.use_bgm = tk.BooleanVar(value=False)
        self.bgm_dir = tk.StringVar()
        self.random_bgm = tk.BooleanVar(value=True)
        self.bgm_volume = tk.DoubleVar(value=0.5)  # 默认音量50%
        self.loop_bgm = tk.BooleanVar(value=True)
        
        # 新增：输出命名设置
        self.use_date_prefix = tk.BooleanVar(value=True)  # 使用日期前缀
        self.use_first_image_name = tk.BooleanVar(value=False)  # 使用第一张图片名称作为前缀
        self.custom_prefix = tk.StringVar(value="video")  # 自定义前缀
        
        # 新增：图片选择方式
        self.image_selection_mode = tk.StringVar(value="随机选择")  # 图片选择方式："随机选择" 或 "按名称排序"
        
        # 编码器选择
        self.codec_var = tk.StringVar(value="XVID")

        # 初始化运行时探测（仅启动时执行一次，后续复用缓存）
        self._initialize_runtime_probes()
        
        # Turbo 加速器
        self.turbo_accelerator = None
        self._initialize_turbo_accelerator()
        
        # 尝试加载保存的配置
        self.load_config()
        
        # 创建UI
        self.create_widgets()
        
        # 将加载的配置应用到UI
        self.apply_config_to_ui()
        
        # 启动后再允许自动高度调整，避免覆盖初始高度
        self.auto_resize_enabled = False
        def _enable_auto_resize():
            self.auto_resize_enabled = True
            self._auto_resize_parent()
        self.parent.after(200, _enable_auto_resize)
        
        # 运行时变量
        self.processing_thread = None
        self.is_processing = False
        
        # 显示ffmpeg状态
        if self.ffmpeg_available:
            self.update_status("FFmpeg可用，BGM功能已启用")
        else:
            self.update_status("警告：未检测到FFmpeg，BGM功能可能受限")
        matrix = self._runtime_probe.get("opencv_codec_matrix", {}) if isinstance(self._runtime_probe, dict) else {}
        if matrix:
            codec_text = ", ".join(f"{k}:{'Y' if v else 'N'}" for k, v in matrix.items())
            self.update_status(f"编码器预检查完成 -> {codec_text}")
    
    def on_closing(self):
        """窗口关闭事件处理"""
        self._stop_effect_preview_animation()
        # 如果正在处理视频，询问是否确定关闭
        if self.is_processing:
            if not messagebox.askyesno("警告", "正在处理视频，关闭程序将中断处理。\n是否确定关闭？"):
                return
            # 停止处理
            self.is_processing = False
        
        # 保存当前配置，不显示消息框
        self.save_config(show_message=False)
        
        # 关闭窗口
        self.parent.destroy()
    
    def save_config(self, show_message=False):
        """保存当前配置到文件"""
        try:
            self.sync_watermark_layers_from_ui()
            config = {
                "input_dir": self.input_dir.get(),
                "output_dir": self.output_dir.get(),
                "num_images": self.num_images.get(),
                "duration": self.duration.get(),
                "total_duration": self.total_duration.get(),
                "fps": self.fps.get(),
                "video_count": self.video_count.get(),
                "video_format": self.video_format.get(),
                "width": self.width.get(),
                "height": self.height.get(),
                "resolution_preset": self.resolution_preset_var.get(),
                "resolution_presets": self.resolution_presets,
                "keep_aspect_ratio": self.keep_aspect_ratio.get(),
                "use_transition": self.use_transition.get(),
                "transition_type": self.transition_type.get(),
                "random_transition": self.random_transition.get(),
                "enabled_transitions": self.get_enabled_transitions(),
                "use_video_effect": self.use_video_effect.get(),
                "video_effect_type": self.video_effect_type.get(),
                "random_video_effect": self.random_video_effect.get(),
                "enabled_video_effects": self.get_enabled_video_effects(),
                "video_effect_intensity": self.video_effect_intensity.get(),
                "video_effect_speed": self.video_effect_speed.get(),
                "effect_preview_time": self.effect_preview_time.get(),
                "use_bgm": self.use_bgm.get(),
                "bgm_dir": self.bgm_dir.get(),
                "random_bgm": self.random_bgm.get(),
                "bgm_volume": self.bgm_volume.get(),
                "loop_bgm": self.loop_bgm.get(),
                "codec": self.codec_var.get(),
                # 新增：水印设置
                "use_watermark": self.use_watermark.get(),
                "watermark_path": self.watermark_path.get(),
                "watermark_type": self.watermark_type.get(),
                "watermark_position": self.watermark_position.get(),
                "watermark_match_method": self.watermark_match_method.get(),
                "watermark_audio": self.watermark_audio.get(),
                "watermark_size_mode": self.watermark_size_mode.get(),
                "watermark_scale": self.watermark_scale.get(),
                "watermark_blend_mode": self.watermark_blend_mode.get(),
                "watermark_layers": self.watermark_layers,
                # 新增：输出命名设置
                "use_date_prefix": self.use_date_prefix.get(),
                "use_first_image_name": self.use_first_image_name.get(),
                "custom_prefix": self.custom_prefix.get(),
                # 新增：图片选择方式
                "image_selection_mode": self.image_selection_mode.get(),
                # 新增：视频码率设置
                "bitrate": self.bitrate.get()
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            
            self.update_status("配置已保存")
            # 只有当用户主动点击保存按钮且指定显示消息框时才显示对话框
            if show_message and not self.is_processing:  # 避免在处理过程中或程序关闭时显示对话框
                messagebox.showinfo("保存成功", f"配置已保存到:\n{self.config_file}")
        except Exception as e:
            self.update_status(f"保存配置失败: {str(e)}")
            if show_message:
                messagebox.showerror("保存失败", f"保存配置失败:\n{str(e)}")
    
    def load_config(self):
        """从文件加载配置"""
        if not os.path.exists(self.config_file):
            self.update_status("未找到配置文件，将使用默认设置")
            return
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 更新变量值
            for key, value in config.items():
                if key == "input_dir" and hasattr(self, "input_dir"):
                    self.input_dir.set(value)
                elif key == "output_dir" and hasattr(self, "output_dir"):
                    self.output_dir.set(value)
                elif key == "num_images" and hasattr(self, "num_images"):
                    self.num_images.set(value)
                elif key == "duration" and hasattr(self, "duration"):
                    self.duration.set(value)
                elif key == "total_duration" and hasattr(self, "total_duration"):
                    self.total_duration.set(value)
                elif key == "fps" and hasattr(self, "fps"):
                    self.fps.set(value)
                elif key == "video_count" and hasattr(self, "video_count"):
                    self.video_count.set(value)
                elif key == "video_format" and hasattr(self, "video_format"):
                    self.video_format.set(value)
                elif key == "width" and hasattr(self, "width"):
                    self.width.set(value)
                elif key == "height" and hasattr(self, "height"):
                    self.height.set(value)
                elif key == "resolution_presets":
                    if isinstance(value, list):
                        normalized = [self._normalize_resolution_text(v) for v in value]
                        normalized = [v for v in normalized if v]
                        if normalized:
                            self.resolution_presets = list(dict.fromkeys(normalized))
                elif key == "resolution_preset" and hasattr(self, "resolution_preset_var"):
                    normalized = self._normalize_resolution_text(value)
                    if normalized:
                        if normalized not in self.resolution_presets:
                            self.resolution_presets.append(normalized)
                        self.resolution_preset_var.set(normalized)
                        self._apply_resolution_preset(normalized)
                elif key == "keep_aspect_ratio" and hasattr(self, "keep_aspect_ratio"):
                    self.keep_aspect_ratio.set(value)
                elif key == "use_transition" and hasattr(self, "use_transition"):
                    self.use_transition.set(value)
                elif key == "transition_type" and hasattr(self, "transition_type"):
                    self.transition_type.set(value)
                elif key == "random_transition" and hasattr(self, "random_transition"):
                    self.random_transition.set(value)
                elif key == "enabled_transitions":
                    if isinstance(value, list):
                        # 仅保留合法转场名，避免旧配置污染
                        valid_transitions = [t for t in value if t in GUI_TRANSITIONS]
                        self.enabled_transitions = valid_transitions or DEFAULT_ENABLED_TRANSITIONS.copy()
                elif key == "use_video_effect" and hasattr(self, "use_video_effect"):
                    self.use_video_effect.set(value)
                elif key == "video_effect_type" and hasattr(self, "video_effect_type"):
                    self.video_effect_type.set(value)
                elif key == "random_video_effect" and hasattr(self, "random_video_effect"):
                    self.random_video_effect.set(value)
                elif key == "enabled_video_effects":
                    if isinstance(value, list):
                        valid_effects = [e for e in value if e in VIDEO_EFFECTS and e != "无特效"]
                        self.enabled_video_effects = valid_effects or [e for e in VIDEO_EFFECTS if e != "无特效"]
                elif key == "video_effect_intensity" and hasattr(self, "video_effect_intensity"):
                    self.video_effect_intensity.set(value)
                elif key == "video_effect_speed" and hasattr(self, "video_effect_speed"):
                    self.video_effect_speed.set(value)
                elif key == "effect_preview_time" and hasattr(self, "effect_preview_time"):
                    self.effect_preview_time.set(value)
                elif key == "use_bgm" and hasattr(self, "use_bgm"):
                    self.use_bgm.set(value)
                elif key == "bgm_dir" and hasattr(self, "bgm_dir"):
                    self.bgm_dir.set(value)
                elif key == "random_bgm" and hasattr(self, "random_bgm"):
                    self.random_bgm.set(value)
                elif key == "bgm_volume" and hasattr(self, "bgm_volume"):
                    self.bgm_volume.set(value)
                elif key == "loop_bgm" and hasattr(self, "loop_bgm"):
                    self.loop_bgm.set(value)
                elif key == "codec" and hasattr(self, "codec_var"):
                    self.codec_var.set(value)
                # 水印设置
                elif key == "use_watermark" and hasattr(self, "use_watermark"):
                    self.use_watermark.set(value)
                elif key == "watermark_path" and hasattr(self, "watermark_path"):
                    self.watermark_path.set(value)
                elif key == "watermark_type" and hasattr(self, "watermark_type"):
                    self.watermark_type.set(value)
                elif key == "watermark_position" and hasattr(self, "watermark_position"):
                    self.watermark_position.set(value)
                elif key == "watermark_match_method" and hasattr(self, "watermark_match_method"):
                    self.watermark_match_method.set(value)
                elif key == "watermark_audio" and hasattr(self, "watermark_audio"):
                    self.watermark_audio.set(value)
                elif key == "watermark_size_mode" and hasattr(self, "watermark_size_mode"):
                    self.watermark_size_mode.set(value)
                elif key == "watermark_scale" and hasattr(self, "watermark_scale"):
                    self.watermark_scale.set(value)
                elif key == "watermark_blend_mode" and hasattr(self, "watermark_blend_mode"):
                    self.watermark_blend_mode.set(value)
                elif key == "watermark_layers":
                    self.watermark_layers = value if isinstance(value, list) else []
                # 输出命名设置
                elif key == "use_date_prefix" and hasattr(self, "use_date_prefix"):
                    self.use_date_prefix.set(value)
                elif key == "use_first_image_name" and hasattr(self, "use_first_image_name"):
                    self.use_first_image_name.set(value)
                elif key == "custom_prefix" and hasattr(self, "custom_prefix"):
                    self.custom_prefix.set(value)
                # 新增：图片选择方式
                elif key == "image_selection_mode" and hasattr(self, "image_selection_mode"):
                    self.image_selection_mode.set(value)
                # 视频码率设置
                elif key == "bitrate" and hasattr(self, "bitrate"):
                    self.bitrate.set(value)
                
            self.update_status("已加载配置")
            if hasattr(self, "watermark_type"):
                self.watermark_type.set("视频")
            # 兼容旧配置（仅宽高），并统一同步到分辨率下拉
            self._sync_resolution_preset_from_dimensions()
        except Exception as e:
            self.update_status(f"加载配置失败: {str(e)}")
    
    def apply_config_to_ui(self):
        """在UI创建后应用配置到界面控件"""
        # 这个方法会在create_widgets后调用，确保下拉菜单等选项正确显示
        try:
            # 应用视频格式选择
            format_values = ["avi", "mp4", "mov"]
            if self.video_format.get() in format_values:
                # 查找并设置视频格式下拉菜单
                self.find_and_set_combobox_by_name(
                    self.parent, 
                    self.video_format.get(), 
                    format_values, 
                    ["视频格式", "格式", "format"]
                )
            else:
                # 如果配置中的值不在有效选项中，设置为默认值
                self.video_format.set("avi")
                self.find_and_set_combobox_by_name(
                    self.parent, 
                    "avi", 
                    format_values, 
                    ["视频格式", "格式", "format"]
                )
            
            # 应用编码器选择
            codec_values = ["XVID", "MJPG", "mp4v", "H264"]
            if self.codec_var.get() in codec_values:
                # 查找并设置编码器下拉菜单
                self.find_and_set_combobox_by_name(
                    self.parent, 
                    self.codec_var.get(), 
                    codec_values, 
                    ["编码器", "codec"]
                )
            else:
                # 如果配置中的值不在有效选项中，设置为默认值
                self.codec_var.set("XVID")
                self.find_and_set_combobox_by_name(
                    self.parent, 
                    "XVID", 
                    codec_values, 
                    ["编码器", "codec"]
                )
            
            # 应用转场效果类型选择
            if self.transition_type.get() in GUI_TRANSITIONS:
                # 查找并设置转场效果下拉菜单
                self.find_and_set_combobox_by_name(
                    self.parent, 
                    self.transition_type.get(), 
                    GUI_TRANSITIONS, 
                    ["转场效果", "转场", "transition"]
                )
            else:
                # 如果配置中的值不在有效选项中，设置为默认值
                self.transition_type.set("淡入淡出")
                self.find_and_set_combobox_by_name(
                    self.parent, 
                    "淡入淡出", 
                    GUI_TRANSITIONS, 
                    ["转场效果", "转场", "transition"]
                )

            # 应用单图特效选择
            if self.video_effect_type.get() in VIDEO_EFFECTS:
                self.find_and_set_combobox_by_name(
                    self.parent,
                    self.video_effect_type.get(),
                    VIDEO_EFFECTS,
                    ["单图特效", "特效", "effect"]
                )
            else:
                self.video_effect_type.set("镜头呼吸")
                self.find_and_set_combobox_by_name(
                    self.parent,
                    "镜头呼吸",
                    VIDEO_EFFECTS,
                    ["单图特效", "特效", "effect"]
                )

            # 同步分辨率下拉（兼容旧配置只保存宽高的情况）
            self._sync_resolution_preset_from_dimensions()
            
        except Exception as e:
            self.update_status(f"应用配置到UI时出错: {str(e)}")
        
        # 加载多重水印到主界面
        try:
            self._load_watermark_layers_to_ui()
        except Exception:
            pass
    
    def find_and_set_combobox_by_name(self, parent, value, values, possible_labels):
        """通过相邻标签名称查找并设置下拉框的值"""
        # 递归查找所有子组件
        for child in parent.winfo_children():
            if isinstance(child, ttk.Combobox) and value in child['values']:
                # 找到相匹配的下拉框，检查它是否有相邻的Label
                child_info = child.grid_info() if hasattr(child, 'grid_info') else None
                
                if child_info:
                    # 查找同一行的Label
                    for sibling in parent.winfo_children():
                        if isinstance(sibling, ttk.Label):
                            sibling_info = sibling.grid_info() if hasattr(sibling, 'grid_info') else None
                            if sibling_info and sibling_info['row'] == child_info['row']:
                                # 检查Label文本是否匹配可能的标签名
                                for label_text in possible_labels:
                                    if label_text in sibling['text']:
                                        # 设置下拉框值
                                        try:
                                            index = values.index(value)
                                            child.current(index)
                                            return True
                                        except Exception:
                                            pass
                                            pass
                
                # 如果没有找到匹配的Label，但下拉框值匹配，也尝试设置
                try:
                                            index = values.index(value)
                                            child.current(index)
                                            return True
                except Exception:
                    pass
            
            # 递归搜索子组件
            if len(child.winfo_children()) > 0:
                if self.find_and_set_combobox_by_name(child, value, values, possible_labels):
                    return True

    def _normalize_resolution_text(self, text):
        """标准化分辨率文本为 WxH。"""
        if text is None:
            return None
        match = re.match(r"^\s*(\d{2,5})\s*[xX×]\s*(\d{2,5})\s*$", str(text))
        if not match:
            return None
        w = int(match.group(1))
        h = int(match.group(2))
        if w <= 0 or h <= 0:
            return None
        return f"{w}x{h}"

    def _apply_resolution_preset(self, preset_text):
        """将预设分辨率写入 width/height。"""
        normalized = self._normalize_resolution_text(preset_text)
        if not normalized:
            return False
        w, h = normalized.split("x")
        try:
            self.width.set(int(w))
            self.height.set(int(h))
            self.resolution_preset_var.set(normalized)
            return True
        except Exception:
            return False

    def _sync_resolution_preset_from_dimensions(self):
        """根据当前宽高同步分辨率下拉值。"""
        try:
            current = f"{int(self.width.get())}x{int(self.height.get())}"
            if current not in self.resolution_presets:
                self.resolution_presets.append(current)
            self.resolution_preset_var.set(current)
            self._refresh_resolution_combobox_values()
        except Exception:
            pass

    def _refresh_resolution_combobox_values(self):
        """刷新所有分辨率下拉框的选项。"""
        for combo in list(self._resolution_comboboxes):
            try:
                combo.configure(values=self.resolution_presets)
            except Exception:
                continue

    def _on_resolution_selected(self, _event=None):
        """分辨率下拉选中事件。"""
        if self._apply_resolution_preset(self.resolution_preset_var.get()):
            self.update_status(f"分辨率已切换为 {self.resolution_preset_var.get()}")

    def _add_resolution_preset(self):
        """新增分辨率预设。"""
        user_input = simpledialog.askstring("新增分辨率预设", "请输入分辨率（例如 1920x1080）", parent=self.parent)
        normalized = self._normalize_resolution_text(user_input)
        if not normalized:
            if user_input not in (None, ""):
                messagebox.showwarning("格式错误", "请输入正确格式，例如 1920x1080")
            return
        if normalized not in self.resolution_presets:
            self.resolution_presets.append(normalized)
        self._refresh_resolution_combobox_values()
        self._apply_resolution_preset(normalized)
        self.update_status(f"已新增分辨率预设: {normalized}")

    def _remove_current_resolution_preset(self):
        """删除当前分辨率预设。"""
        current = self._normalize_resolution_text(self.resolution_preset_var.get())
        if not current or current not in self.resolution_presets:
            return
        if len(self.resolution_presets) <= 1:
            messagebox.showwarning("提示", "至少保留一个分辨率预设")
            return
        self.resolution_presets = [r for r in self.resolution_presets if r != current]
        fallback = self.resolution_presets[0]
        self._refresh_resolution_combobox_values()
        self._apply_resolution_preset(fallback)
        self.update_status(f"已删除分辨率预设: {current}")

    def _save_resolution_presets(self):
        """保存分辨率预设到配置文件。"""
        normalized = [self._normalize_resolution_text(v) for v in self.resolution_presets]
        normalized = [v for v in normalized if v]
        if not normalized:
            messagebox.showwarning("提示", "没有可保存的分辨率预设")
            return
        self.resolution_presets = list(dict.fromkeys(normalized))
        self._sync_resolution_preset_from_dimensions()
        self.save_config(show_message=False)
        self.update_status("分辨率预设已保存")
        messagebox.showinfo("保存成功", "分辨率预设已保存")
                
    def _show_transition_config_dialog(self):
        """显示转场效果配置对话框"""
        dialog = tk.Toplevel(self.parent)
        dialog.title("配置随机转场效果")
        dialog.geometry("780x640")
        dialog.transient(self.parent)
        dialog.grab_set()
        
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(2, weight=1)
        
        # 标题
        title_label = ttk.Label(dialog, text="选择随机转场时可用的效果", font=("Arial", 12, "bold"))
        title_label.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))
        
        # 说明
        info_label = ttk.Label(dialog, text="勾选的效果将在启用'随机效果'时被随机选择", foreground="gray")
        info_label.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 8))
        
        # 创建可滚动框架
        list_frame = ttk.Frame(dialog)
        list_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=8)
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)
        
        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 创建复选框变量字典
        checkbox_vars = {}
        group_vars = {}
        group_members = {}
        sync_lock = {"busy": False}

        # 分组展示转场效果，便于查找
        transition_groups = {
            "基础转场": ["淡入淡出", "左右滑动", "上下滑动", "交叉溶解", "缩放过渡", "圆形扩展"],
            "纹理与几何": ["百叶窗", "棋盘格", "像素化", "方块过渡", "对角擦除", "门式打开"],
            "动感冲击": ["旋转变换", "波浪", "颜色混合", "放大冲击", "缩小爆炸", "旋转放大", "弹性缩放", "3D翻转", "推入效果", "闪光过渡", "碎片飞散"],
            "高级水印转场": ["光晕扩散", "径向旋切", "漩涡扭曲", "菱形开幕", "镜头虚焦", "纵向拉幕", "横向拉幕", "液态融合", "流光擦拭", "时钟扫描"],
        }
        placed = set()
        group_layout = []
        for group_name, transitions in transition_groups.items():
            group_items = [t for t in transitions if t in GUI_TRANSITIONS and t not in placed]
            if group_items:
                group_layout.append((group_name, group_items))
                placed.update(group_items)

        # 兜底：展示未分类项
        remaining = [t for t in GUI_TRANSITIONS if t not in placed]
        if remaining:
            group_layout.append(("其他", remaining))

        scrollable_frame.grid_columnconfigure(0, weight=1)
        scrollable_frame.grid_columnconfigure(1, weight=1)

        def _set_group_items(group_name):
            if sync_lock["busy"]:
                return
            sync_lock["busy"] = True
            try:
                checked = bool(group_vars[group_name].get())
                for item in group_members.get(group_name, []):
                    checkbox_vars[item].set(checked)
            finally:
                sync_lock["busy"] = False

        def _refresh_group_state(group_name):
            if sync_lock["busy"]:
                return
            members = group_members.get(group_name, [])
            if not members:
                return
            sync_lock["busy"] = True
            try:
                all_checked = all(bool(checkbox_vars[item].get()) for item in members)
                group_vars[group_name].set(all_checked)
            finally:
                sync_lock["busy"] = False

        for idx, (group_name, group_items) in enumerate(group_layout):
            col = idx % 2
            row = idx // 2
            group_frame = ttk.LabelFrame(scrollable_frame)
            group_frame.grid(row=row, column=col, sticky="nsew", padx=8, pady=6)
            group_frame.grid_columnconfigure(0, weight=1)
            group_frame.grid_columnconfigure(1, weight=1)
            group_members[group_name] = group_items

            group_var = tk.BooleanVar(value=all(t in self.enabled_transitions for t in group_items))
            group_vars[group_name] = group_var
            CursorCheckbox(group_frame, text=f"【{group_name}】", variable=group_var).grid(
                row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 6)
            )

            for item_idx, transition in enumerate(group_items, start=1):
                var = tk.BooleanVar(value=transition in self.enabled_transitions)
                checkbox_vars[transition] = var
                row_frame = ttk.Frame(group_frame)
                row_frame.grid(row=item_idx, column=0, columnspan=2, sticky="ew", padx=12, pady=2)
                row_frame.grid_columnconfigure(1, weight=1)
                CursorCheckbox(row_frame, text=transition, variable=var).grid(row=0, column=0, sticky="w")
                if transition in TRANSITION_DESCRIPTIONS:
                    ttk.Label(
                        row_frame,
                        text=f"({TRANSITION_DESCRIPTIONS[transition]})",
                        foreground="gray",
                        font=("Arial", 9)
                    ).grid(row=0, column=1, sticky="w", padx=(6, 0))

                var.trace_add("write", lambda *_args, g=group_name: _refresh_group_state(g))

            group_var.trace_add("write", lambda *_args, g=group_name: _set_group_items(g))
        
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        
        # 快捷按钮框架
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 8))
        
        def select_all():
            for var in checkbox_vars.values():
                var.set(True)
        
        def select_none():
            for var in checkbox_vars.values():
                var.set(False)
        
        def select_default():
            for transition, var in checkbox_vars.items():
                var.set(transition in DEFAULT_ENABLED_TRANSITIONS)
        
        ttk.Button(button_frame, text="全选", command=select_all).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Button(button_frame, text="全不选", command=select_none).grid(row=0, column=1, sticky="w", padx=(0, 8))
        ttk.Button(button_frame, text="恢复默认", command=select_default).grid(row=0, column=2, sticky="w")
        
        # 保存和取消按钮
        action_frame = ttk.Frame(dialog)
        action_frame.grid(row=4, column=0, sticky="ew", padx=16, pady=(8, 16))
        action_frame.grid_columnconfigure(0, weight=1)
        
        def save_and_close():
            # 更新enabled_transitions
            self.enabled_transitions = [
                transition for transition, var in checkbox_vars.items() 
                if var.get()
            ]
            
            if not self.enabled_transitions:
                messagebox.showwarning("警告", "至少需要选择一个转场效果！")
                self.enabled_transitions = ["淡入淡出"]  # 确保至少有一个
            
            self.update_status(f"[OK] 已更新随机转场配置: {len(self.enabled_transitions)}个效果")
            dialog.destroy()
        
        def cancel():
            dialog.destroy()
        
        ttk.Button(action_frame, text="取消", command=cancel, width=15).grid(row=0, column=1, sticky="e", padx=(8, 0))
        ttk.Button(action_frame, text="保存", command=save_and_close, width=15).grid(row=0, column=2, sticky="e")
        
        # 居中到主窗口
        self._center_dialog_on_parent(dialog)

    def _show_video_effect_config_dialog(self):
        """显示随机特效配置对话框。"""
        dialog = tk.Toplevel(self.parent)
        dialog.title("配置随机特效")
        dialog.geometry("760x640")
        dialog.transient(self.parent)
        dialog.grab_set()

        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(2, weight=1)

        ttk.Label(dialog, text="选择随机特效时可用的效果", font=("Arial", 12, "bold")).grid(
            row=0, column=0, sticky="w", padx=16, pady=(16, 8)
        )
        ttk.Label(dialog, text="勾选后将在生成多个视频时按视频随机应用", foreground="gray").grid(
            row=1, column=0, sticky="w", padx=16, pady=(0, 8)
        )

        list_frame = ttk.Frame(dialog)
        list_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=8)
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)

        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))

        selectable_effects = [e for e in VIDEO_EFFECTS if e != "无特效"]
        checkbox_vars = {}
        group_vars = {}
        group_members = {}
        sync_lock = {"busy": False}
        current_pool = set(self.get_enabled_video_effects())
        effect_groups = {
            "基础单图特效": ["心跳跳动", "反复缩放", "轻微摇摆", "左右晃动", "上下浮动", "镜头呼吸", "脉冲放大", "旋转摆动"],
            "复合循环特效A": ["旋转呼吸", "摇摆推拉", "圆周漂移", "螺旋摆动", "双轴呼吸", "心跳摇摆", "波浪平移", "8字漂移", "径向脉冲旋转", "镜头抖动呼吸"],
            "复合循环特效B": ["反向双旋", "呼吸变焦扫光", "旋摆模糊脉冲", "透视呼吸摆动", "涡旋推拉", "变焦摇移", "旋转漂移闪动", "双频摆动", "环形巡航", "呼吸鱼眼旋摆"],
            "高级镜头风格": ["水波扭曲", "漩涡旋转", "鱼眼镜头", "故障抖动", "镜像扫光", "呼吸模糊", "径向拉伸", "边缘闪烁", "透视俯仰", "滚动快门"],
            "灵魂特效": ["灵魂出窍"],
        }
        placed = set()
        group_layout = []
        for group_name, effects in effect_groups.items():
            group_items = [e for e in effects if e in selectable_effects and e not in placed]
            if group_items:
                group_layout.append((group_name, group_items))
                placed.update(group_items)

        remaining_effects = [e for e in selectable_effects if e not in placed]
        if remaining_effects:
            group_layout.append(("其他", remaining_effects))

        scrollable_frame.grid_columnconfigure(0, weight=1)
        scrollable_frame.grid_columnconfigure(1, weight=1)

        def _set_group_items(group_name):
            if sync_lock["busy"]:
                return
            sync_lock["busy"] = True
            try:
                checked = bool(group_vars[group_name].get())
                for item in group_members.get(group_name, []):
                    checkbox_vars[item].set(checked)
            finally:
                sync_lock["busy"] = False

        def _refresh_group_state(group_name):
            if sync_lock["busy"]:
                return
            members = group_members.get(group_name, [])
            if not members:
                return
            sync_lock["busy"] = True
            try:
                all_checked = all(bool(checkbox_vars[item].get()) for item in members)
                group_vars[group_name].set(all_checked)
            finally:
                sync_lock["busy"] = False

        for idx, (group_name, group_items) in enumerate(group_layout):
            col = idx % 2
            row = idx // 2
            group_frame = ttk.LabelFrame(scrollable_frame)
            group_frame.grid(row=row, column=col, sticky="nsew", padx=8, pady=6)
            group_frame.grid_columnconfigure(0, weight=1)
            group_members[group_name] = group_items

            group_var = tk.BooleanVar(value=all(name in current_pool for name in group_items))
            group_vars[group_name] = group_var
            CursorCheckbox(group_frame, text=f"【{group_name}】", variable=group_var).grid(
                row=0, column=0, sticky="w", padx=8, pady=(4, 6)
            )

            for item_idx, effect_name in enumerate(group_items, start=1):
                var = tk.BooleanVar(value=effect_name in current_pool)
                checkbox_vars[effect_name] = var
                CursorCheckbox(group_frame, text=effect_name, variable=var).grid(
                    row=item_idx, column=0, sticky="w", padx=16, pady=2
                )
                var.trace_add("write", lambda *_args, g=group_name: _refresh_group_state(g))

            group_var.trace_add("write", lambda *_args, g=group_name: _set_group_items(g))

        # 快捷按钮：全选 / 全不选 / 恢复默认
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 8))
        default_effects = [e for e in VIDEO_EFFECTS if e != "无特效"]

        def select_all():
            for var in checkbox_vars.values():
                var.set(True)

        def select_none():
            for var in checkbox_vars.values():
                var.set(False)

        def select_default():
            for effect_name, var in checkbox_vars.items():
                var.set(effect_name in default_effects)

        ttk.Button(button_frame, text="全选", command=select_all).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Button(button_frame, text="全不选", command=select_none).grid(row=0, column=1, sticky="w", padx=(0, 8))
        ttk.Button(button_frame, text="恢复默认", command=select_default).grid(row=0, column=2, sticky="w")

        action_frame = ttk.Frame(dialog)
        action_frame.grid(row=4, column=0, sticky="ew", padx=16, pady=(8, 16))
        action_frame.grid_columnconfigure(0, weight=1)

        def save_and_close():
            selected_effects = [name for name, var in checkbox_vars.items() if var.get()]
            if not selected_effects:
                messagebox.showwarning("警告", "至少需要选择一个特效！")
                return
            self.enabled_video_effects = selected_effects
            self.update_status(f"[OK] 已更新随机特效配置: {len(selected_effects)}个效果")
            dialog.destroy()

        ttk.Button(action_frame, text="取消", command=dialog.destroy, width=15).grid(row=0, column=1, sticky="e", padx=(8, 0))
        ttk.Button(action_frame, text="保存", command=save_and_close, width=15).grid(row=0, column=2, sticky="e")

        self._center_dialog_on_parent(dialog)
    
    def check_ffmpeg(self):
        """检查ffmpeg是否可用"""
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            ffmpeg_path = configure_ffmpeg_environment(project_root)
            available, _version = probe_ffmpeg(ffmpeg_path)
            if available and ffmpeg_path:
                self.ffmpeg_executable = ffmpeg_path
                self.ffprobe_executable = resolve_ffprobe_path(project_root, ffmpeg_path)
                self.update_status(f"[OK] 使用FFmpeg: {ffmpeg_path}")
                return True
            self.update_status("[WARN] 未找到FFmpeg，某些功能可能不可用")
            return False
        except Exception as e:
            self.update_status(f"检测FFmpeg时出错: {str(e)}")
            return False

    def check_codec_availability(self, codec, force_recheck=False):
        """检查编码器是否可用"""
        if not force_recheck:
            cache = getattr(self, "_codec_probe_cache", {})
            if codec in cache:
                return cache[codec]

        # 创建临时视频写入器测试编码器
        try:
            # 尝试创建1帧的临时视频
            fourcc = cv2.VideoWriter_fourcc(*codec)
            temp_file = os.path.join(os.getcwd(), f"temp_{int(time.time())}.mp4")
            temp_writer = cv2.VideoWriter(temp_file, fourcc, 30, (640, 480))
            
            is_opened = temp_writer.isOpened()
            temp_writer.release()
            
            # 清理临时文件
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
                
            if hasattr(self, "_codec_probe_cache"):
                self._codec_probe_cache[codec] = is_opened
            return is_opened
        except Exception:
            if hasattr(self, "_codec_probe_cache"):
                self._codec_probe_cache[codec] = False
            return False

    def _initialize_runtime_probes(self):
        """启动阶段预检查（执行一次）：FFmpeg与OpenCV编码器矩阵。"""
        try:
            candidate_codecs = ("H264", "mp4v", "XVID", "MJPG")
            codec_matrix = {}
            for codec in candidate_codecs:
                codec_matrix[codec] = bool(self.check_codec_availability(codec))

            preferred_cv_codec = None
            for codec in ("mp4v", "XVID", "MJPG"):
                if codec_matrix.get(codec):
                    preferred_cv_codec = codec
                    break

            self._runtime_probe = {
                "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "ffmpeg_available": bool(self.ffmpeg_available),
                "opencv_codec_matrix": codec_matrix,
                "preferred_cv_codec": preferred_cv_codec,
            }
        except Exception:
            self._runtime_probe = {
                "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "ffmpeg_available": bool(getattr(self, "ffmpeg_available", False)),
                "opencv_codec_matrix": {},
                "preferred_cv_codec": None,
            }

    def normalize_path(self, path):
        """标准化路径，处理中文和特殊字符"""
        if path is None:
            return None
            
        # 确保路径使用正确的路径分隔符
        normalized = os.path.normpath(path)
        
        # 进行简单调试
        self.update_status(f"路径标准化: {path} -> {normalized}")
        
        # 如果是Windows系统，处理中文路径
        if sys.platform == 'win32':
            try:
                # 检查路径是否存在
                if not os.path.exists(normalized):
                    self.update_status(f"警告: 路径不存在 - {normalized}")
                    return normalized
                
                # 尝试获取短路径名（8.3格式）
                try:
                    import win32api
                    short_path = win32api.GetShortPathName(normalized)
                    self.update_status(f"转换为短路径: {normalized} -> {short_path}")
                    return short_path
                except Exception as e:
                    self.update_status(f"获取短路径时出错: {str(e)}")
            except Exception as e:
                self.update_status(f"路径存在检测出错: {str(e)}")
        
        return normalized
    
    def _init_transition_engine(self):
        """初始化转场引擎"""
        try:
            self.transition_engine = get_turbo_transition_engine()
            print("[OK] 转场引擎初始化成功")
        except Exception as e:
            print(f"[WARN] 转场引擎初始化失败: {e}")
            self.transition_engine = None
    
    def _initialize_turbo_accelerator(self):
        """初始化 Turbo 加速器"""
        try:
            # 尝试多种导入方式
            self.turbo_accelerator = None
            
            # 方法1：直接从模块导入
            try:
                from optimization.turbo_accelerator import TurboAccelerator
                self.turbo_accelerator = TurboAccelerator()
                if self.turbo_accelerator.initialize():
                    self.update_status("Turbo 加速器已启用")
                    return
                else:
                    self.update_status("Turbo 加速器初始化失败")
            except ImportError as e:
                print(f"Turbo加速器直接导入失败: {str(e)}")
            
            # 方法2：通过optimization模块导入
            try:
                from optimization import get_turbo_accelerator
                self.turbo_accelerator = get_turbo_accelerator()
                if self.turbo_accelerator and self.turbo_accelerator.enabled:
                    self.update_status("Turbo 加速器已启用")
                    return
            except Exception as e:
                print(f"Turbo加速器模块导入失败: {str(e)}")
            
            # 方法3：从主程序导入
            try:
                import main
                if hasattr(main, 'get_turbo_accelerator'):
                    self.turbo_accelerator = main.get_turbo_accelerator()
                    if self.turbo_accelerator and self.turbo_accelerator.enabled:
                        self.update_status("Turbo 加速器已启用")
                        return
            except Exception as e:
                print(f"Turbo加速器主程序导入失败: {str(e)}")
            
            # 如果所有方法都失败
            self.turbo_accelerator = None
            self.update_status("使用标准性能模式")
            
        except Exception as e:
            self.update_status(f"Turbo 加速器初始化失败: {str(e)}")
            self.turbo_accelerator = None
    
    def create_widgets(self):
        """创建UI组件 - Cursor风格"""
        # 主框架
        self.parent.grid_columnconfigure(0, weight=1)
        self.parent.grid_rowconfigure(0, weight=1)
        main_frame = ttk.Frame(self.parent)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=8)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(0, weight=1)
        self._main_frame = main_frame
        
        # 使用 Canvas 实现滚动，背景跟随主题卡片色
        canvas_bg = "#FFFFFF"
        try:
            if self.main_app and hasattr(self.main_app, "theme"):
                canvas_bg = self.main_app.theme.get("frame")
        except Exception:
            pass
        canvas = tk.Canvas(main_frame, 
                          bg=canvas_bg,
                          highlightthickness=0,
                          bd=0)
        scrollable_frame = ttk.Frame(canvas, style='TFrame')
        self._canvas = canvas
        self._scrollable_frame = scrollable_frame
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        # 让scrollable_frame宽度随canvas调整
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind('<Configure>', on_canvas_configure)
        
        # 启用鼠标滚轮滚动（仅在主滚动区激活，避免干扰下拉框弹出列表）
        def _on_mousewheel(event):
            # 下拉列表弹层/列表框优先处理滚轮
            try:
                px, py = self.parent.winfo_pointerx(), self.parent.winfo_pointery()
                hover_widget = self.parent.winfo_containing(px, py)
            except Exception:
                hover_widget = None

            for w in (hover_widget, self.parent.focus_get(), getattr(event, "widget", None)):
                if not w:
                    continue
                try:
                    widget_class = w.winfo_class()
                except Exception:
                    widget_class = ""
                widget_path = str(w).lower()
                if widget_class in ("Listbox", "TCombobox", "Combobox"):
                    return
                if "combobox" in widget_path or "popdown" in widget_path:
                    return

            delta = int(getattr(event, "delta", 0))
            if delta == 0:
                return
            canvas.yview_scroll(int(-1 * (delta / 120)), "units")
            return "break"

        def _bind_canvas_wheel(_event=None):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_canvas_wheel(_event=None):
            canvas.unbind_all("<MouseWheel>")

        # 鼠标进入主滚动区才接管滚轮，离开即释放
        canvas.bind("<Enter>", _bind_canvas_wheel)
        canvas.bind("<Leave>", _unbind_canvas_wheel)
        scrollable_frame.bind("<Enter>", _bind_canvas_wheel)
        scrollable_frame.bind("<Leave>", _unbind_canvas_wheel)
        
        canvas.grid(row=0, column=0, sticky="nsew")
        
        # 主网格容器
        scrollable_frame.grid_columnconfigure(0, weight=1)
        main_grid = ttk.Frame(scrollable_frame)
        main_grid.grid(row=0, column=0, sticky="nsew", padx=12, pady=10)
        
        # 定义栅格布局 - 总共12列
        for i in range(12):
            main_grid.columnconfigure(i, weight=1)
        
        # 行计数器
        row = 0

        # 严格按“界面全平铺布局-紧凑版”构建
        self._create_compact_layout(main_grid)
        return

    def _create_compact_layout(self, main_grid):
        """紧凑全平铺布局"""
        pad_x = GridSystem.SPACING["xs"]
        pad_y = GridSystem.SPACING["xs"]
        row = 0

        def add_section(title):
            nonlocal row
            frame = ttk.LabelFrame(main_grid, text=title)
            frame.grid(row=row, column=0, columnspan=12, sticky="ew", pady=(0, GridSystem.SPACING["xs"]))
            for i in range(12):
                frame.columnconfigure(i, weight=0)
            frame.columnconfigure(11, weight=1)
            row += 1
            return frame

        # 顶部：左侧参数栏 + 右侧预览窗口（按参考图重排）
        section_top = add_section("")
        section_top.columnconfigure(0, weight=0)
        section_top.columnconfigure(1, weight=1)

        left_panel = ttk.Frame(section_top)
        left_panel.grid(row=0, column=0, sticky="nsw", padx=(pad_x, pad_x), pady=pad_y)
        for i in range(6):
            left_panel.columnconfigure(i, weight=0)

        right_panel = ttk.Frame(section_top)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(pad_x, pad_x), pady=pad_y)
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(0, weight=1)

        # 左侧边栏：目录
        ttk.Label(left_panel, text="输入目录:").grid(row=0, column=0, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Entry(left_panel, textvariable=self.input_dir, width=32).grid(row=0, column=1, columnspan=4, sticky="ew", padx=(0, pad_x), pady=pad_y)
        ttk.Button(left_panel, text="浏览", command=self.browse_input_dir, width=6).grid(row=0, column=5, sticky="w", padx=(0, pad_x), pady=pad_y)

        ttk.Label(left_panel, text="输出:").grid(row=1, column=0, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Entry(left_panel, textvariable=self.output_dir, width=32).grid(row=1, column=1, columnspan=4, sticky="ew", padx=(0, pad_x), pady=pad_y)
        ttk.Button(left_panel, text="浏览", command=self.browse_output_dir, width=6).grid(row=1, column=5, sticky="w", padx=(0, pad_x), pady=pad_y)

        ttk.Separator(left_panel, orient=tk.HORIZONTAL).grid(row=2, column=0, columnspan=6, sticky="ew", pady=(4, 4))

        # 左侧边栏：视频参数
        ttk.Label(left_panel, text="图片数:").grid(row=3, column=0, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Spinbox(left_panel, from_=1, to=1000, textvariable=self.num_images, width=7).grid(row=3, column=1, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(left_panel, text="每图时长:").grid(row=3, column=2, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Spinbox(left_panel, from_=0.1, to=60.0, increment=0.1, textvariable=self.duration, width=7).grid(row=3, column=3, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(left_panel, text="FPS:").grid(row=3, column=4, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Spinbox(left_panel, from_=1, to=120, textvariable=self.fps, width=7).grid(row=3, column=5, sticky="w", padx=(0, pad_x), pady=pad_y)

        ttk.Label(left_panel, text="分辨率:").grid(row=4, column=0, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        res_frame = ttk.Frame(left_panel)
        res_frame.grid(row=4, column=1, columnspan=3, sticky="w", padx=(0, pad_x), pady=pad_y)
        res_combo = ttk.Combobox(
            res_frame,
            textvariable=self.resolution_preset_var,
            values=self.resolution_presets,
            width=10,
            state="readonly"
        )
        res_combo.grid(row=0, column=0, sticky="w")
        res_combo.bind("<<ComboboxSelected>>", self._on_resolution_selected)
        self._resolution_comboboxes.append(res_combo)
        ttk.Button(res_frame, text="+", command=self._add_resolution_preset, width=2).grid(row=0, column=1, sticky="w", padx=(GridSystem.SPACING["xs"], 0))
        ttk.Button(res_frame, text="-", command=self._remove_current_resolution_preset, width=2).grid(row=0, column=2, sticky="w", padx=(GridSystem.SPACING["xs"], 0))
        ttk.Button(res_frame, text="保存", command=self._save_resolution_presets, width=4).grid(row=0, column=3, sticky="w", padx=(GridSystem.SPACING["xs"], 0))
        CursorCheckbox(left_panel, text="保持比例", variable=self.keep_aspect_ratio).grid(row=4, column=4, columnspan=2, sticky="w", padx=(0, pad_x), pady=pad_y)

        ttk.Label(left_panel, text="格式:").grid(row=5, column=0, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Combobox(left_panel, textvariable=self.video_format, values=["avi", "mp4", "mov"], width=8, state="readonly").grid(
            row=5, column=1, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(left_panel, text="编码:").grid(row=5, column=2, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Combobox(left_panel, textvariable=self.codec_var, values=["XVID", "MJPG", "mp4v", "H264"], width=8, state="readonly").grid(
            row=5, column=3, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(left_panel, text="码率:").grid(row=5, column=4, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Spinbox(left_panel, from_=1000, to=50000, increment=1000, textvariable=self.bitrate, width=7).grid(
            row=5, column=5, sticky="w", padx=(0, pad_x), pady=pad_y)

        ttk.Label(left_panel, text="视频数:").grid(row=6, column=0, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Spinbox(left_panel, from_=1, to=1000000, textvariable=self.video_count, width=7).grid(row=6, column=1, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(left_panel, text="图片:").grid(row=6, column=2, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Combobox(left_panel, textvariable=self.image_selection_mode, values=["随机选择", "按名称排序"], width=10, state="readonly").grid(
            row=6, column=3, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(left_panel, text="总时长:").grid(row=6, column=4, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Spinbox(left_panel, from_=0.0, to=86400.0, increment=0.1, textvariable=self.total_duration, width=7).grid(
            row=6, column=5, sticky="w", padx=(0, pad_x), pady=pad_y)

        ttk.Separator(left_panel, orient=tk.HORIZONTAL).grid(row=7, column=0, columnspan=6, sticky="ew", pady=(4, 4))

        # 左侧边栏：特效
        CursorCheckbox(left_panel, text="启用特效", variable=self.use_video_effect).grid(row=8, column=0, sticky="w", padx=(pad_x, pad_x), pady=pad_y)
        CursorCheckbox(left_panel, text="随机特效", variable=self.random_video_effect).grid(row=8, column=1, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Button(left_panel, text="配置随机...", command=self._show_video_effect_config_dialog, width=10).grid(
            row=8, column=2, sticky="w", padx=(0, pad_x), pady=pad_y)

        ttk.Label(left_panel, text="特效:").grid(row=9, column=0, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Combobox(left_panel, textvariable=self.video_effect_type, values=VIDEO_EFFECTS, width=10, state="readonly").grid(
            row=9, column=1, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(left_panel, text="强度%:").grid(row=9, column=2, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Spinbox(left_panel, from_=1, to=9999, increment=5, textvariable=self.video_effect_intensity, width=7).grid(
            row=9, column=3, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(left_panel, text="速度:").grid(row=9, column=4, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Spinbox(left_panel, from_=0.01, to=9999, increment=0.1, textvariable=self.video_effect_speed, width=7).grid(
            row=9, column=5, sticky="w", padx=(0, pad_x), pady=pad_y)

        ttk.Label(left_panel, text="预览时间(s):").grid(row=10, column=0, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Spinbox(left_panel, from_=0.0, to=600.0, increment=0.1, textvariable=self.effect_preview_time, width=7).grid(
            row=10, column=1, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Button(left_panel, text="刷新预览", command=self.preview_single_effect_frame, width=10).grid(
            row=10, column=2, sticky="w", padx=(0, pad_x), pady=pad_y)
        self._effect_preview_toggle_button = ttk.Button(
            left_panel,
            text="收起预览",
            command=self._toggle_effect_preview_visibility,
            width=10
        )
        self._effect_preview_toggle_button.grid(row=10, column=3, sticky="w", padx=(0, pad_x), pady=pad_y)

        ttk.Separator(left_panel, orient=tk.HORIZONTAL).grid(row=11, column=0, columnspan=6, sticky="ew", pady=(4, 4))

        # 左侧边栏：转场与命名
        CursorCheckbox(left_panel, text="转场", variable=self.use_transition).grid(row=12, column=0, sticky="w", padx=(pad_x, pad_x), pady=pad_y)
        CursorCheckbox(left_panel, text="随机", variable=self.random_transition).grid(row=12, column=1, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(left_panel, text="效果:").grid(row=12, column=2, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Combobox(left_panel, textvariable=self.transition_type, values=GUI_TRANSITIONS, width=10, state="readonly").grid(
            row=12, column=3, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Button(left_panel, text="配置随机...", command=self._show_transition_config_dialog, width=10).grid(
            row=12, column=4, sticky="w", padx=(0, pad_x), pady=pad_y)

        CursorCheckbox(left_panel, text="日期前缀", variable=self.use_date_prefix).grid(row=13, column=0, sticky="w", padx=(pad_x, pad_x), pady=pad_y)
        CursorCheckbox(left_panel, text="用画图名", variable=self.use_first_image_name).grid(row=13, column=1, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(left_panel, text="前缀:").grid(row=13, column=2, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Entry(left_panel, textvariable=self.custom_prefix, width=12).grid(row=13, column=3, sticky="w", padx=(0, pad_x), pady=pad_y)

        # 右侧：预览窗口
        self.effect_preview_label = ttk.Label(
            right_panel,
            text="预览窗口",
            relief="solid",
            anchor="center",
            font=("Arial", 32, "bold"),
            foreground=self.main_app.theme.get("text_tertiary") if self.main_app and hasattr(self.main_app, "theme") else "#94A3B8"
        )
        self.effect_preview_label.grid(row=0, column=0, sticky="nsew", ipadx=230, ipady=145)
        self._set_effect_preview_visibility(True)

        # BGM与水印
        section5 = add_section("")
        for i in range(12):
            section5.columnconfigure(i, weight=0)
        section5.columnconfigure(4, weight=1)
        section5.columnconfigure(8, weight=1)

        # BGM 行
        CursorCheckbox(section5, text="BGM", variable=self.use_bgm).grid(row=0, column=0, sticky="w", padx=(pad_x, pad_x), pady=pad_y)
        CursorCheckbox(section5, text="随机", variable=self.random_bgm).grid(row=0, column=1, sticky="w", padx=(0, pad_x), pady=pad_y)
        CursorCheckbox(section5, text="循环", variable=self.loop_bgm).grid(row=0, column=9, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(section5, text="目录:", width=6).grid(row=0, column=2, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Entry(section5, textvariable=self.bgm_dir).grid(row=0, column=3, columnspan=2, sticky="ew", padx=(0, pad_x), pady=pad_y)
        ttk.Button(section5, text="浏览", command=self.browse_bgm_dir, width=6).grid(row=0, column=5, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(section5, text="音量%:", width=6).grid(row=0, column=6, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Scale(section5, from_=0.1, to=1.0, value=0.5, variable=self.bgm_volume, orient=tk.HORIZONTAL).grid(
            row=0, column=7, columnspan=2, sticky="ew", padx=(0, pad_x), pady=pad_y)

        # 水印路径行
        CursorCheckbox(section5, text="视频水印", variable=self.use_watermark).grid(row=1, column=0, sticky="w", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Label(section5, text="模式:", width=6).grid(row=1, column=1, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Combobox(section5, textvariable=self.watermark_mode, values=["单文件", "文件夹"], width=8, state="readonly").grid(
            row=1, column=2, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(section5, text="路径:", width=6).grid(row=1, column=3, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Entry(section5, textvariable=self.watermark_path).grid(row=1, column=4, columnspan=2, sticky="ew", padx=(0, pad_x), pady=pad_y)
        ttk.Button(section5, text="浏览", command=self.browse_watermark_file, width=6).grid(row=1, column=6, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(section5, text="(黑色背景avi用'滤色'模式)", foreground="gray").grid(
            row=1, column=7, columnspan=3, sticky="w", padx=(0, pad_x), pady=pad_y)

        # 水印参数行
        ttk.Label(section5, text="位置:", width=6).grid(row=2, column=0, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Combobox(section5, textvariable=self.watermark_position, values=["左上", "右上", "左下", "右下", "中心"], width=8, state="readonly").grid(
            row=2, column=1, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(section5, text="匹配:", width=6).grid(row=2, column=2, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Combobox(section5, textvariable=self.watermark_match_method, values=["循环", "拉伸", "单次"], width=8, state="readonly").grid(
            row=2, column=3, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(section5, text="声音:", width=6).grid(row=2, column=4, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Combobox(section5, textvariable=self.watermark_audio, values=["使用BGM", "使用水印", "两者混合", "静音"], width=10, state="readonly").grid(
            row=2, column=5, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(section5, text="大小模式:", width=7).grid(row=2, column=6, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Combobox(section5, textvariable=self.watermark_size_mode, values=["固定比例", "自适应覆盖", "完全覆盖"], width=10, state="readonly").grid(
            row=2, column=7, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(section5, text="缩放%:", width=6).grid(row=2, column=8, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Spinbox(section5, from_=5, to=100, increment=5, textvariable=self.watermark_scale, width=6).grid(
            row=2, column=9, sticky="w", padx=(0, pad_x), pady=pad_y)
        ttk.Label(section5, text="混合:", width=6).grid(row=2, column=10, sticky="e", padx=(pad_x, pad_x), pady=pad_y)
        ttk.Combobox(section5, textvariable=self.watermark_blend_mode,
                     values=["正常", "滤色", "叠加", "正片叠底", "变亮", "变暗", "相加"],
                     width=8, state="readonly").grid(row=2, column=11, sticky="w", padx=(0, pad_x), pady=pad_y)

        # 水印层参数
        section6 = add_section("")
        ttk.Button(section6, text="添加图层", command=self._add_watermark_layer_row, width=8).grid(
            row=0, column=0, sticky="w", padx=(pad_x, pad_x), pady=pad_y)
        self.watermark_layers_container = ttk.Frame(section6)
        self.watermark_layers_container.grid(row=1, column=0, columnspan=12, sticky="ew", padx=(pad_x, pad_x), pady=pad_y)
        section6.columnconfigure(11, weight=1)

        # 底部区域：开始处理 + 进度 + 性能/内存
        bottom = add_section("")
        self.start_button = ttk.Button(bottom, text="▶ 开始处理", command=self.start_processing, width=14, style="Success.TButton")
        self.start_button.grid(row=0, column=0, sticky="w", padx=(pad_x, pad_x), pady=pad_y)
        self.pause_button = ttk.Button(bottom, text="⏸ 暂停", command=self.toggle_pause, width=10)
        self.pause_button.grid(row=0, column=1, sticky="w", padx=(0, pad_x), pady=pad_y)
        self.cancel_button = ttk.Button(bottom, text="⏹ 取消", command=self.cancel_processing, width=10)
        self.cancel_button.grid(row=0, column=2, sticky="w", padx=(0, pad_x), pady=pad_y)

        ttk.Progressbar(bottom, orient=tk.HORIZONTAL, mode='determinate', variable=self.progress_var).grid(
            row=0, column=3, columnspan=6, sticky="ew", padx=(0, pad_x), pady=pad_y)
        self.progress_info_var = tk.StringVar(value="进度: 0%")
        ttk.Label(bottom, textvariable=self.progress_info_var).grid(
            row=0, column=9, sticky="e", padx=(0, pad_x), pady=pad_y)
        self.speed_info_var = tk.StringVar(value="速度: 0.0 张/秒")
        ttk.Label(bottom, textvariable=self.speed_info_var).grid(
            row=0, column=10, sticky="e", padx=(0, pad_x), pady=pad_y)
        self.detail_info_var = tk.StringVar(value="状态: 就绪")
        ttk.Label(bottom, textvariable=self.detail_info_var).grid(
            row=0, column=11, sticky="e", padx=(0, pad_x), pady=pad_y)
        ttk.Label(bottom, text="总进度").grid(
            row=1, column=0, sticky="w", padx=(pad_x, pad_x), pady=(0, pad_y))
        ttk.Progressbar(bottom, orient=tk.HORIZONTAL, mode='determinate', variable=self.overall_progress_var).grid(
            row=1, column=3, columnspan=6, sticky="ew", padx=(0, pad_x), pady=(0, pad_y))
        self.overall_progress_info_var = tk.StringVar(value="总进度: 0%")
        ttk.Label(bottom, textvariable=self.overall_progress_info_var).grid(
            row=1, column=9, sticky="e", padx=(0, pad_x), pady=(0, pad_y))
        bottom.columnconfigure(8, weight=1)

        # 绑定前缀选项变化事件
        def update_prefix_state(*args):
            pass
        self.use_date_prefix.trace_add("write", update_prefix_state)
        self.use_first_image_name.trace_add("write", update_prefix_state)
        # 仅使用紧凑布局，后续旧布局代码不再执行（避免控件重复创建导致引用错乱）
        return

    def _show_perf_memory(self):
        """性能/内存按钮统一入口"""
        try:
            self.show_performance_stats()
        except Exception:
            pass
        try:
            self.optimize_memory()
        except Exception:
            pass

        
        # ===== 目录设置 =====
        # 标题
        create_section_title(main_grid, "📁 目录设置").grid(
            row=row, column=0, columnspan=12, sticky="ew", 
            padx=0, pady=(0, GridSystem.SPACING['md'])
        )
        row += 1
        
        # 内容容器 - 使用 FormRow
        dirs_form = FormRow(main_grid)
        dirs_form.grid(row=row, column=0, columnspan=12, sticky="ew", 
                      padx=0, pady=(0, GridSystem.SPACING['lg']))
        
        # 输入目录
        dirs_form.add_field_with_button("输入目录", self.input_dir, "浏览", self.browse_input_dir)
        
        # 输出目录
        dirs_form.add_field_with_button("输出目录", self.output_dir, "浏览", self.browse_output_dir)
        
        row += 1
        
        # ===== 视频参数 =====
        # 标题
        create_section_title(main_grid, "⚙️ 视频参数").grid(
            row=row, column=0, columnspan=12, sticky="ew", 
            padx=0, pady=(0, GridSystem.SPACING['md'])
        )
        row += 1
        
        # 内容容器
        params_container = ttk.Frame(main_grid, style='TFrame')
        params_container.grid(row=row, column=0, columnspan=12, sticky="ew", 
                            padx=0, pady=(0, GridSystem.SPACING['lg']))
        
        # 使用标准表单布局而不是参数行，避免拥挤
        # 第一行：图片数量、持续时间、帧率
        row1_frame = ttk.Frame(params_container, style='TFrame')
        row1_frame.grid(row=0, column=0, sticky="ew", pady=(0, GridSystem.SPACING['sm']))
        row1_frame.grid_columnconfigure(7, weight=1)
        
        # 图片数量
        ttk.Label(row1_frame, text="图片数量").grid(row=0, column=0, sticky='w', padx=(0, 8))
        ttk.Spinbox(row1_frame, from_=1, to=1000, textvariable=self.num_images, width=12).grid(
            row=0, column=1, sticky='w', padx=(0, 24))
        
        # 持续时间
        ttk.Label(row1_frame, text="持续时间(秒)").grid(row=0, column=2, sticky='w', padx=(0, 8))
        ttk.Spinbox(row1_frame, from_=0.1, to=60.0, increment=0.1, textvariable=self.duration, width=12).grid(
            row=0, column=3, sticky='w', padx=(0, 24))
        
        # 帧率
        ttk.Label(row1_frame, text="帧率(FPS)").grid(row=0, column=4, sticky='w', padx=(0, 8))
        ttk.Spinbox(row1_frame, from_=1, to=120, textvariable=self.fps, width=12).grid(
            row=0, column=5, sticky='w', padx=(0, 24))
        
        # 分辨率
        ttk.Label(row1_frame, text="分辨率").grid(row=0, column=6, sticky='w', padx=(0, 8))
        res_container = ttk.Frame(row1_frame, style='TFrame')
        res_container.grid(row=0, column=7, sticky='w', padx=(0, 16))
        ttk.Entry(res_container, textvariable=self.width, width=8).grid(row=0, column=0, sticky="w")
        ttk.Label(res_container, text="×").grid(row=0, column=1, sticky="w", padx=GridSystem.SPACING['xs'])
        ttk.Entry(res_container, textvariable=self.height, width=8).grid(row=0, column=2, sticky="w")
        
        # 保持比例
        CursorCheckbox(row1_frame, text="保持比例", variable=self.keep_aspect_ratio).grid(
            row=0, column=8, sticky='w', padx=(8, 0))
        
        # 第二行：视频数量、格式、编码器、码率、图片选择
        row2_frame = ttk.Frame(params_container, style='TFrame')
        row2_frame.grid(row=1, column=0, sticky="ew", pady=(0, GridSystem.SPACING['sm']))
        
        # 视频数量
        ttk.Label(row2_frame, text="视频数量").grid(row=0, column=0, sticky='w', padx=(0, 8))
        ttk.Spinbox(row2_frame, from_=1, to=1000000, textvariable=self.video_count, width=12).grid(
            row=0, column=1, sticky='w', padx=(0, 24))
        
        # 格式
        ttk.Label(row2_frame, text="格式").grid(row=0, column=2, sticky='w', padx=(0, 8))
        ttk.Combobox(row2_frame, textvariable=self.video_format, values=["avi", "mp4", "mov"], 
                     width=10, state="readonly").grid(row=0, column=3, sticky='w', padx=(0, 24))
        
        # 编码器
        codec_values = ["XVID", "MJPG", "mp4v", "H264"]
        h264_available = self.check_codec_availability('avc1')
        ttk.Label(row2_frame, text="编码器").grid(row=0, column=4, sticky='w', padx=(0, 8))
        ttk.Combobox(row2_frame, textvariable=self.codec_var, values=codec_values,
                     width=10, state="readonly").grid(row=0, column=5, sticky='w', padx=(0, 24))
        
        # 码率
        ttk.Label(row2_frame, text="码率(kbps)").grid(row=0, column=6, sticky='w', padx=(0, 8))
        ttk.Spinbox(row2_frame, from_=1000, to=50000, increment=1000,
                    textvariable=self.bitrate, width=12).grid(row=0, column=7, sticky='w', padx=(0, 24))
        
        # 图片选择
        ttk.Label(row2_frame, text="图片选择").grid(row=0, column=8, sticky='w', padx=(0, 8))
        ttk.Combobox(row2_frame, textvariable=self.image_selection_mode,
                     values=["随机选择", "按名称排序"], width=14, state="readonly").grid(
                     row=0, column=9, sticky='w')

        # 第三行：单图视频特效
        row3_frame = ttk.Frame(params_container, style='TFrame')
        row3_frame.grid(row=2, column=0, sticky="ew", pady=(0, GridSystem.SPACING['sm']))

        CursorCheckbox(row3_frame, text="单图特效", variable=self.use_video_effect).grid(
            row=0, column=0, sticky='w', padx=(0, 8))
        ttk.Label(row3_frame, text="特效:").grid(row=0, column=1, sticky='w', padx=(0, 8))
        ttk.Combobox(
            row3_frame,
            textvariable=self.video_effect_type,
            values=VIDEO_EFFECTS,
            width=12,
            state="readonly"
        ).grid(row=0, column=2, sticky='w', padx=(0, 16))
        ttk.Label(row3_frame, text="强度(%)").grid(row=0, column=3, sticky='w', padx=(0, 8))
        ttk.Spinbox(
            row3_frame,
            from_=1, to=9999, increment=5,
            textvariable=self.video_effect_intensity,
            width=8
        ).grid(row=0, column=4, sticky='w', padx=(0, 16))
        ttk.Label(row3_frame, text="速度").grid(row=0, column=5, sticky='w', padx=(0, 8))
        ttk.Spinbox(
            row3_frame,
            from_=0.01, to=9999, increment=0.1,
            textvariable=self.video_effect_speed,
            width=6
        ).grid(row=0, column=6, sticky='w', padx=(0, 16))
        ttk.Label(row3_frame, text="仅在图片数量=1时生效").grid(row=0, column=7, sticky='w')

        # 单图特效预览面板（单帧）
        ttk.Label(row3_frame, text="预览时间(s)").grid(row=1, column=0, sticky='w', padx=(0, 8), pady=(8, 0))
        ttk.Spinbox(
            row3_frame,
            from_=0.0, to=600.0, increment=0.1,
            textvariable=self.effect_preview_time,
            width=8
        ).grid(row=1, column=1, sticky='w', padx=(0, 12), pady=(8, 0))
        ttk.Button(
            row3_frame,
            text="刷新预览",
            command=self.preview_single_effect_frame,
            width=10
        ).grid(row=1, column=2, sticky='w', padx=(0, 12), pady=(8, 0))
        self._effect_preview_toggle_button = ttk.Button(
            row3_frame,
            text="收起预览",
            command=self._toggle_effect_preview_visibility,
            width=10
        )
        self._effect_preview_toggle_button.grid(row=1, column=3, sticky='w', padx=(0, 12), pady=(8, 0))
        ttk.Label(row3_frame, text="").grid(row=1, column=4, columnspan=3, sticky='w', pady=(8, 0))

        self.effect_preview_label = ttk.Label(
            row3_frame,
            text="特效预览区域（点击“刷新预览”）",
            relief="solid",
            anchor="center",
            width=48
        )
        self.effect_preview_label.grid(row=2, column=0, columnspan=8, sticky='ew', pady=(8, 0))
        self._set_effect_preview_visibility(True)
        
        row += 1
        
        # ===== 转场效果和输出命名（并排） =====
        # 左侧：转场效果（占6列）
        # 标题
        create_section_title(main_grid, "🎬 转场效果").grid(row=row, column=0, columnspan=6, sticky="ew", padx=(0, 12), pady=(0, 12))
        
        # 右侧：输出命名标题（占6列）
        create_section_title(main_grid, "📝 输出命名").grid(row=row, column=6, columnspan=6, sticky="ew", padx=(12, 0), pady=(0, 12))
        
        row += 1
        
        # 左侧内容
        trans_frame = ttk.Frame(main_grid, style='TFrame')
        trans_frame.grid(row=row, column=0, columnspan=6, sticky="ew", padx=(0, 12), pady=(0, 16))
        
        # 转场效果内部布局
        CursorCheckbox(trans_frame, text="启用转场", variable=self.use_transition).grid(
            row=0, column=0, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        CursorCheckbox(trans_frame, text="随机效果", variable=self.random_transition).grid(
            row=0, column=1, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        ttk.Label(trans_frame, text="效果:").grid(
            row=0, column=2, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        # 使用新的转场效果列表（已扩展到13种）
        trans_combo = ttk.Combobox(trans_frame, textvariable=self.transition_type, values=GUI_TRANSITIONS, width=10, state="readonly")
        trans_combo.grid(
            row=0, column=3, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        # 添加配置效果按钮
        def open_transition_config():
            """打开转场效果配置对话框"""
            try:
                self._show_transition_config_dialog()
            except Exception as e:
                self.update_status(f"打开转场效果配置时出错: {str(e)}")
        
        ttk.Button(trans_frame, text="配置随机...", command=open_transition_config, width=10).grid(
            row=0, column=4, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        # 右侧内容
        naming_frame = ttk.Frame(main_grid, style='TFrame')
        naming_frame.grid(row=row, column=6, columnspan=6, sticky="ew", padx=(12, 0), pady=(0, 16))
        
        # 命名选项
        CursorCheckbox(naming_frame, text="日期前缀", variable=self.use_date_prefix).grid(
            row=0, column=0, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        CursorCheckbox(naming_frame, text="使用首图名称", variable=self.use_first_image_name).grid(
            row=0, column=1, columnspan=2, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        ttk.Label(naming_frame, text="自定义前缀:").grid(
            row=0, column=3, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        ttk.Entry(naming_frame, textvariable=self.custom_prefix, width=10).grid(
            row=0, column=4, columnspan=2, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        row += 1
        
        # ===== 背景音乐和水印设置（并排） =====
        # 左侧：背景音乐标题（占6列）
        create_section_title(main_grid, "🎵 背景音乐").grid(row=row, column=0, columnspan=6, sticky="ew", padx=(0, 12), pady=(0, 12))
        
        # 右侧：水印设置标题（占6列）
        create_section_title(main_grid, "🖼️ 水印设置").grid(row=row, column=6, columnspan=6, sticky="ew", padx=(12, 0), pady=(0, 12))
        
        row += 1
        
        # 左侧内容
        bgm_frame = ttk.Frame(main_grid, style='TFrame')
        bgm_frame.grid(row=row, column=0, columnspan=6, sticky="ew", padx=(0, 12), pady=(0, 16))
        
        # 背景音乐选项 - 第一行
        options_frame = ttk.Frame(bgm_frame)
        options_frame.grid(row=0, column=0, columnspan=6, sticky="ew", padx=GridSystem.SPACING['xs'], pady=0)
        options_frame.grid_columnconfigure(0, weight=0)
        options_frame.grid_columnconfigure(1, weight=0)
        
        CursorCheckbox(options_frame, text="启用BGM", variable=self.use_bgm).grid(
            row=0, column=0, sticky="w", padx=(0, GridSystem.SPACING['xs']), pady=GridSystem.SPACING['xs']
        )
        CursorCheckbox(options_frame, text="随机选择", variable=self.random_bgm).grid(
            row=0, column=1, sticky="w", padx=(0, GridSystem.SPACING['xs']), pady=GridSystem.SPACING['xs']
        )
        CursorCheckbox(options_frame, text="循环", variable=self.loop_bgm).grid(
            row=0, column=2, sticky="w", padx=(0, GridSystem.SPACING['xs']), pady=GridSystem.SPACING['xs']
        )
        
        # 音乐目录 - 第二行
        ttk.Label(bgm_frame, text="目录:").grid(
            row=1, column=0, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        ttk.Entry(bgm_frame, textvariable=self.bgm_dir).grid(
            row=1, column=1, columnspan=4, sticky="ew", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        ttk.Button(bgm_frame, text="浏览", width=4, command=self.browse_bgm_dir).grid(
            row=1, column=5, padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        # 音量控制 - 第三行
        ttk.Label(bgm_frame, text="音量:").grid(
            row=2, column=0, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        ttk.Scale(
            bgm_frame, from_=0.1, to=1.0, value=0.5, variable=self.bgm_volume, orient=tk.HORIZONTAL
        ).grid(row=2, column=1, columnspan=4, sticky="ew", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs'])
        volume_label = ttk.Label(bgm_frame, text=f"{int(self.bgm_volume.get() * 100)}%", width=4)
        volume_label.grid(row=2, column=5, padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs'])
        
        # 更新音量标签的函数
        def update_volume_label(*args):
            volume_percent = int(self.bgm_volume.get() * 100)
            volume_label.config(text=f"{volume_percent}%")
        
        # 绑定音量变化事件
        self.bgm_volume.trace_add("write", update_volume_label)
        
        bgm_frame.columnconfigure(1, weight=1)
        bgm_frame.columnconfigure(2, weight=1)
        bgm_frame.columnconfigure(3, weight=1)
        bgm_frame.columnconfigure(4, weight=1)
        
        # 右侧内容
        watermark_frame = ttk.Frame(main_grid, style='TFrame')
        watermark_frame.grid(row=row, column=6, columnspan=6, sticky="ew", padx=(12, 0), pady=(0, 16))
        
        # 启用水印复选框
        CursorCheckbox(watermark_frame, text="启用水印", variable=self.use_watermark).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        # 视频水印类型（固定）
        ttk.Label(watermark_frame, text="视频水印").grid(
            row=0, column=2, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        # 水印位置
        ttk.Label(watermark_frame, text="位置:").grid(
            row=0, column=4, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        position_combo = ttk.Combobox(watermark_frame, textvariable=self.watermark_position,
                                values=["左上", "右上", "左下", "右下", "中心"], width=5, state="readonly")
        position_combo.grid(
            row=0, column=5, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        # 水印模式（新增）
        ttk.Label(watermark_frame, text="模式:").grid(
            row=1, column=0, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        watermark_mode_combo = ttk.Combobox(watermark_frame, textvariable=self.watermark_mode,
                                        values=["单文件", "文件夹"], width=6, state="readonly")
        watermark_mode_combo.grid(
            row=1, column=1, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        # 水印文件/文件夹选择
        ttk.Label(watermark_frame, text="路径:").grid(
            row=1, column=2, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        ttk.Entry(watermark_frame, textvariable=self.watermark_path).grid(
            row=1, column=3, columnspan=2, sticky="ew", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        ttk.Button(watermark_frame, text="浏览", width=4, command=self.browse_watermark_file).grid(
            row=1, column=5, padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        # 水印匹配方式（用于视频水印）
        ttk.Label(watermark_frame, text="匹配:").grid(
            row=2, column=0, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        match_combo = ttk.Combobox(watermark_frame, textvariable=self.watermark_match_method,
                                values=["循环", "拉伸", "单次"], width=6, state="readonly")
        match_combo.grid(
            row=2, column=1, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        # 水印声音来源设置（用于视频水印）
        ttk.Label(watermark_frame, text="声音:").grid(
            row=2, column=3, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        audio_combo = ttk.Combobox(watermark_frame, textvariable=self.watermark_audio,
                                values=["使用BGM", "使用水印", "两者混合", "静音"], width=8, state="readonly")
        audio_combo.grid(
            row=2, column=4, columnspan=2, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        # 水印大小模式（新增）
        ttk.Label(watermark_frame, text="大小模式:").grid(
            row=3, column=0, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        size_mode_combo = ttk.Combobox(watermark_frame, textvariable=self.watermark_size_mode,
                                values=["固定比例", "自适应覆盖", "完全覆盖"], width=10, state="readonly")
        size_mode_combo.grid(
            row=3, column=1, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        # 水印缩放比例（用于固定比例模式）
        ttk.Label(watermark_frame, text="缩放(%):").grid(
            row=3, column=2, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        scale_spinbox = ttk.Spinbox(watermark_frame, textvariable=self.watermark_scale,
                                from_=5, to=100, increment=5, width=8)
        scale_spinbox.grid(
            row=3, column=3, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        # 水印混合模式（新增）
        ttk.Label(watermark_frame, text="混合模式:").grid(
            row=4, column=0, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        blend_mode_combo = ttk.Combobox(watermark_frame, textvariable=self.watermark_blend_mode,
                                values=["正常", "滤色", "叠加", "正片叠底", "变亮", "变暗", "相加"], 
                                width=10, state="readonly")
        blend_mode_combo.grid(
            row=4, column=1, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )
        
        # 混合模式说明标签
        blend_hint = ttk.Label(watermark_frame, text="提示: 黑色背景mov请用'滤色'模式", 
                              foreground="gray", font=("", 8))
        blend_hint.grid(
            row=4, column=2, columnspan=2, sticky="w", padx=GridSystem.SPACING['xs'], pady=GridSystem.SPACING['xs']
        )

        # 多重水印配置（内嵌主界面）
        ttk.Label(watermark_frame, text="多重水印:").grid(
            row=5, column=0, sticky="w", padx=GridSystem.SPACING['xs'], pady=(GridSystem.SPACING['sm'], GridSystem.SPACING['xs'])
        )
        ttk.Button(
            watermark_frame,
            text="添加图层",
            command=self._add_watermark_layer_row,
            width=8
        ).grid(
            row=5, column=1, sticky="w", padx=GridSystem.SPACING['xs'], pady=(GridSystem.SPACING['sm'], GridSystem.SPACING['xs'])
        )

        self.watermark_layers_container = ttk.Frame(watermark_frame)
        self.watermark_layers_container.grid(
            row=6, column=0, columnspan=6, sticky="ew", padx=GridSystem.SPACING['xs'], pady=(GridSystem.SPACING['xs'], GridSystem.SPACING['sm'])
        )
        
        # 配置网格权重
        watermark_frame.columnconfigure(1, weight=1)
        watermark_frame.columnconfigure(2, weight=1)
        watermark_frame.columnconfigure(4, weight=1)
        
        row += 1
        
        # ===== 进度条 =====
        progress_frame = ttk.Frame(main_grid)
        progress_frame.grid(row=row, column=0, columnspan=12, sticky="ew", padx=0, pady=(0, 12))
        
        progress_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(progress_frame, text="进度").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Progressbar(progress_frame, orient=tk.HORIZONTAL,
                         mode='determinate', variable=self.progress_var).grid(row=0, column=1, sticky="ew")
        
        row += 1
        
        # ===== 控制按钮 =====
        # 标题
        create_section_title(main_grid, "⚡ 控制面板").grid(row=row, column=0, columnspan=12, sticky="ew", padx=0, pady=(0, 12))
        row += 1
        
        # 内容容器
        control_frame = ttk.Frame(main_grid, style='TFrame')
        control_frame.grid(row=row, column=0, columnspan=12, sticky="ew", padx=0, pady=(0, 16))
        
        # 第一行按钮
        CursorTheme.create_primary_button(control_frame, "▶️ 开始处理", self.start_processing).grid(row=0, column=0, padx=(0, 8), pady=(0, 8), sticky="ew")
        ttk.Button(control_frame, text="📁 打开输出", command=self.open_output_dir).grid(row=0, column=1, padx=(0, 8), pady=(0, 8), sticky="ew")
        ttk.Button(control_frame, text="💾 保存配置", command=lambda: self.save_config(True)).grid(row=0, column=2, padx=(0, 8), pady=(0, 8), sticky="ew")
        ttk.Button(control_frame, text="🔄 重载配置", command=self.reload_config).grid(row=0, column=3, padx=0, pady=(0, 8), sticky="ew")
        
        # 第二行按钮
        ttk.Button(control_frame, text="📊 性能统计", command=self.show_performance_stats).grid(row=1, column=0, padx=(0, 8), pady=0, sticky="ew")
        ttk.Button(control_frame, text="🧹 内存优化", command=self.optimize_memory).grid(row=1, column=1, padx=(0, 8), pady=0, sticky="ew")
        
        # 配置列宽度相等
        for i in range(4):
            control_frame.columnconfigure(i, weight=1, uniform="button")
        
        # 输出前缀自定义控制
        def update_prefix_state(*args):
            # 移除禁用逻辑，允许同时使用自定义前缀和第一张图片名称
            pass
        
        # 绑定前缀选项变化事件
        self.use_date_prefix.trace_add("write", update_prefix_state)
        self.use_first_image_name.trace_add("write", update_prefix_state)
        
        
    def update_status(self, message):
        """更新状态文本"""
        def update():
            self.status_text.set(message)
            # 只在有父窗口回调且不是完成通知的情况下才传递消息
            if self.parent_update_status and not message.endswith("处理完成"):
                # 只传递消息，不标记完成
                self.parent_update_status(message, False)
        if hasattr(self, 'parent'):
            self.parent.after(0, update)

    def _center_dialog_on_parent(self, dialog):
        """将弹窗居中到主程序窗口，而非屏幕中心。"""
        try:
            dialog.update_idletasks()
            parent_win = self.parent.winfo_toplevel() if hasattr(self, "parent") else dialog.master
            if parent_win is None:
                return
            parent_win.update_idletasks()

            pw = parent_win.winfo_width()
            ph = parent_win.winfo_height()
            px = parent_win.winfo_x()
            py = parent_win.winfo_y()
            dw = dialog.winfo_width()
            dh = dialog.winfo_height()

            x = px + max(0, (pw - dw) // 2)
            y = py + max(0, (ph - dh) // 2)
            screen_w = dialog.winfo_screenwidth()
            screen_h = dialog.winfo_screenheight()
            x = max(0, min(x, screen_w - dw))
            y = max(0, min(y, screen_h - dh))
            dialog.geometry(f"+{x}+{y}")
        except Exception:
            pass
    
    def show_performance_stats(self):
        """显示 Turbo 加速器性能统计"""
        if self.turbo_accelerator and self.turbo_accelerator.enabled:
            try:
                stats = self.turbo_accelerator.get_performance_stats()
                
                # 创建统计信息窗口
                stats_window = tk.Toplevel(self.parent)
                stats_window.title("🚀 Turbo 加速器性能统计")
                stats_window.geometry("600x400")
                stats_window.resizable(True, True)
                self._center_dialog_on_parent(stats_window)
                
                import tkinter.scrolledtext as scrolledtext
                stats_window.grid_columnconfigure(0, weight=1)
                stats_window.grid_rowconfigure(0, weight=1)
                text_widget = scrolledtext.ScrolledText(stats_window, wrap=tk.WORD)
                text_widget.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
                
                # 格式化统计信息
                stats_text = "Turbo 加速器性能统计\n"
                stats_text += "=" * 50 + "\n\n"
                
                stats_text += "[基本状态]\n"
                enabled_text = "[已启用]" if stats['enabled'] else "[已禁用]"
                stats_text += f"  • 状态: {enabled_text}\n"
                stats_text += f"  • 运行时间: {stats['runtime_hours']:.2f} 小时\n"
                stats_text += f"  • 线程池大小: {stats['thread_pool_workers']} 个\n\n"
                
                stats_text += "[图片处理统计]\n"
                stats_text += f"  • 已处理图片: {stats['images_processed']} 张\n"
                stats_text += f"  • 已创建视频: {stats['videos_created']} 个\n\n"
                
                stats_text += "[缓存性能]\n"
                stats_text += f"  • 缓存命中率: {stats['cache_hit_rate']}\n"
                stats_text += f"  • 缓存大小: {stats['cache_size']} 项\n"
                stats_text += f"  • 缓存内存: {stats['cache_memory_mb']:.1f} MB\n\n"
                
                stats_text += "[系统状态]\n"
                stats_text += f"  • 系统内存使用率: {stats['system_memory_percent']:.1f}%\n"
                stats_text += f"  • 系统CPU使用率: {stats['system_cpu_percent']:.1f}%\n"
                stats_text += f"  • 内存优化次数: {stats['memory_optimizations']}\n\n"
                
                stats_text += "[性能提示]\n"
                if stats['cache_hit_rate'] and float(stats['cache_hit_rate'].replace('%', '')) > 50:
                    success_text = "[OK] 缓存命中率较高，性能表现良好"
                    stats_text += f"  {success_text}\n"
                else:
                    warning_text = "[WARN] 缓存命中率较低，可能需要内存优化"
                    stats_text += f"  {warning_text}\n"
                    
                if stats['system_memory_percent'] > 80:
                    high_memory_text = "[WARN] 系统内存使用率较高，建议执行内存优化"
                    stats_text += f"  {high_memory_text}\n"
                elif stats['system_memory_percent'] < 50:
                    normal_memory_text = "[OK] 系统内存使用率正常"
                    stats_text += f"  {normal_memory_text}\n"
                
                text_widget.insert(tk.END, stats_text)
                text_widget.config(state=tk.DISABLED)
                
                self.update_status("已显示 Turbo 加速器性能统计")
                
            except Exception as e:
                from tkinter import messagebox
                messagebox.showerror("错误", f"获取 Turbo 加速器统计失败: {str(e)}")
        else:
            from tkinter import messagebox
            messagebox.showinfo("信息", "Turbo 加速器未启用或不可用")
    
    def optimize_memory(self):
        """执行内存优化"""
        if self.turbo_accelerator and self.turbo_accelerator.enabled:
            try:
                self.turbo_accelerator.force_memory_optimization()
                from tkinter import messagebox
                messagebox.showinfo("成功", "Turbo 加速器内存优化完成！")
                self.update_status("Turbo 内存优化完成")
            except Exception as e:
                from tkinter import messagebox
                messagebox.showerror("错误", f"Turbo 内存优化失败: {str(e)}")
        else:
            # 基本的内存清理
            try:
                import gc
                collected = gc.collect()
                from tkinter import messagebox
                messagebox.showinfo("成功", f"基本内存清理完成，回收了 {collected} 个对象")
                self.update_status(f"内存清理完成，回收 {collected} 个对象")
            except Exception as e:
                from tkinter import messagebox
                messagebox.showerror("错误", f"内存清理失败: {str(e)}")
    
    def browse_input_dir(self):
        """选择输入目录"""
        directory = filedialog.askdirectory(title="选择包含图片的目录")
        if directory:
            self.input_dir.set(directory)
    
    def browse_output_dir(self):
        """选择输出目录"""
        directory = filedialog.askdirectory(title="选择视频输出目录")
        if directory:
            self.output_dir.set(directory)
    
    def browse_bgm_dir(self):
        """浏览选择背景音乐目录"""
        bgm_dir = filedialog.askdirectory(title="选择背景音乐目录")
        if bgm_dir:
            self.bgm_dir.set(bgm_dir)
    
    def browse_watermark_file(self):
        """浏览选择水印文件或文件夹"""
        watermark_mode = self.watermark_mode.get()
        
        if watermark_mode == "单文件":
            # 单文件模式，选择单个水印文件
            filetypes = [("视频文件", "*.mov;*.mp4;*.avi;*.mkv"), ("所有文件", "*.*")]
                
            watermark_file = filedialog.askopenfilename(
                title="选择视频水印文件",
                filetypes=filetypes
            )
            
            if watermark_file:
                self.watermark_path.set(watermark_file)
        
        else:
            # 文件夹模式，选择水印文件夹
            watermark_dir = filedialog.askdirectory(
                title="选择包含视频水印的文件夹"
            )
            
            if watermark_dir:
                self.watermark_path.set(watermark_dir)
                
                # 验证文件夹中是否包含水印文件
                extensions = ['.mov', '.mp4', '.avi', '.mkv']
                
                # 检查文件夹中是否包含指定类型的文件
                has_valid_files = False
                for root, _, files in os.walk(watermark_dir):
                    for file in files:
                        if any(file.lower().endswith(ext) for ext in extensions):
                            has_valid_files = True
                            break
                    if has_valid_files:
                        break
                
                if not has_valid_files:
                    messagebox.showwarning("警告", "选择的文件夹中没有找到视频文件")
                    # 继续使用，用户可能会后续添加文件

    def _clear_watermark_layer_rows(self):
        if hasattr(self, 'watermark_layers_container'):
            for child in self.watermark_layers_container.winfo_children():
                child.destroy()
        self.watermark_layer_rows = []

    def _add_watermark_layer_row(self, layer=None):
        """在主界面添加一行多重水印配置"""
        if not hasattr(self, 'watermark_layers_container'):
            return
        layer = layer or {}
        row = ttk.Frame(self.watermark_layers_container)
        row_index = len(self.watermark_layer_rows)
        row.grid(row=row_index, column=0, sticky="ew", pady=GridSystem.SPACING['xs'])
        row.grid_columnconfigure(2, weight=1)

        enabled_var = tk.BooleanVar(value=layer.get("enabled", True))
        fixed_var = tk.BooleanVar(value=layer.get("fixed", False))
        folder_random_single_var = tk.BooleanVar(value=bool(layer.get("folder_random_single", False)))
        path_var = tk.StringVar(value=layer.get("path", ""))
        position_var = tk.StringVar(value=layer.get("position", "右下"))
        size_mode_var = tk.StringVar(value=layer.get("size_mode", "自适应覆盖"))
        scale_var = tk.DoubleVar(value=layer.get("scale", 20.0))
        blend_var = tk.StringVar(value=layer.get("blend_mode", "正常"))
        opacity_var = tk.DoubleVar(value=layer.get("opacity", 0.5))

        ttk.Checkbutton(row, text="启用", variable=enabled_var).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(row, text="路径").grid(row=0, column=1, sticky="w", padx=(0, 8))
        ttk.Entry(row, textvariable=path_var, width=22).grid(row=0, column=2, sticky="ew", padx=(0, 8))
        ttk.Button(
            row, text="浏览",
            command=lambda v=path_var: v.set(filedialog.askopenfilename(
                title="选择水印图片",
                filetypes=[("图片文件", "*.png;*.jpg;*.jpeg;*.bmp;*.gif"), ("所有文件", "*.*")]
            ) or v.get()),
            width=4
        ).grid(row=0, column=3, sticky="w", padx=(0, 8))

        ttk.Label(row, text="位置").grid(row=0, column=4, sticky="w", padx=(0, 8))
        ttk.Combobox(row, textvariable=position_var,
                     values=["左上", "右上", "左下", "右下", "中心"],
                     width=5, state="readonly").grid(row=0, column=5, sticky="w", padx=(0, 8))

        ttk.Checkbutton(row, text="固定", variable=fixed_var).grid(row=0, column=6, sticky="w", padx=(0, 8))
        ttk.Checkbutton(row, text="目录随机1个", variable=folder_random_single_var).grid(row=0, column=7, sticky="w", padx=(0, 8))

        ttk.Label(row, text="大小").grid(row=0, column=8, sticky="w", padx=(0, 8))
        ttk.Combobox(row, textvariable=size_mode_var,
                     values=["固定比例", "自适应覆盖", "完全覆盖"],
                     width=8, state="readonly").grid(row=0, column=9, sticky="w", padx=(0, 8))

        ttk.Label(row, text="缩放").grid(row=0, column=10, sticky="w", padx=(0, 8))
        ttk.Spinbox(row, from_=5, to=100, increment=5,
                    textvariable=scale_var, width=5).grid(row=0, column=11, sticky="w", padx=(0, 8))

        ttk.Label(row, text="混合").grid(row=0, column=12, sticky="w", padx=(0, 8))
        ttk.Combobox(row, textvariable=blend_var,
                     values=["正常", "滤色", "叠加", "正片叠底", "变亮", "变暗", "相加"],
                     width=6, state="readonly").grid(row=0, column=13, sticky="w", padx=(0, 8))

        ttk.Label(row, text="透明度").grid(row=0, column=14, sticky="w", padx=(0, 8))
        ttk.Spinbox(row, from_=0.1, to=1.0, increment=0.1,
                    textvariable=opacity_var, width=4).grid(row=0, column=15, sticky="w", padx=(0, 8))

        def remove_row():
            row.destroy()
            self.watermark_layer_rows = [r for r in self.watermark_layer_rows if r["row"] is not row]
            self._auto_resize_parent()

        ttk.Button(row, text="删除", command=remove_row, width=4).grid(row=0, column=16, sticky="w")

        self.watermark_layer_rows.append({
            "row": row,
            "enabled": enabled_var,
            "fixed": fixed_var,
            "folder_random_single": folder_random_single_var,
            "path": path_var,
            "position": position_var,
            "size_mode": size_mode_var,
            "scale": scale_var,
            "blend_mode": blend_var,
            "opacity": opacity_var
        })
        self._auto_resize_parent()

    def _auto_resize_parent(self, force=False):
        """根据真实内容高度自动调整窗口高度。"""
        try:
            if not force and not getattr(self, "auto_resize_enabled", True):
                return
            top = self.parent.winfo_toplevel()
            top.update_idletasks()

            cur_w = top.winfo_width()
            cur_h = top.winfo_height()
            cur_x = top.winfo_x()
            cur_y = top.winfo_y()
            min_h = top.winfo_minsize()[1]
            screen_w = top.winfo_screenwidth()
            screen_h = top.winfo_screenheight()

            # 基于Canvas内真实内容高度计算，而不是依赖顶层reqheight（其对滚动容器不敏感）
            content_h = 0
            if hasattr(self, "_scrollable_frame") and self._scrollable_frame is not None:
                try:
                    content_h = max(content_h, int(self._scrollable_frame.winfo_reqheight()))
                except Exception:
                    pass
            if hasattr(self, "_canvas") and self._canvas is not None:
                try:
                    bbox = self._canvas.bbox("all")
                    if bbox:
                        content_h = max(content_h, int(bbox[3] - bbox[1]))
                except Exception:
                    pass

            if content_h <= 0 or not hasattr(self, "_canvas") or self._canvas is None:
                return

            canvas_h = max(1, int(self._canvas.winfo_height()))
            delta = content_h - canvas_h

            # 小抖动忽略，避免几何抖动
            if abs(delta) < 6:
                return

            target_h = cur_h + delta
            max_h = max(min_h, screen_h - 10)
            target_h = max(min_h, min(int(target_h), int(max_h)))
            if target_h == cur_h:
                return

            # 如目标高度会超出屏幕底部，则自动上移
            max_y = screen_h - target_h - 8
            new_y = cur_y if cur_y <= max_y else max(0, max_y)
            new_x = max(0, min(cur_x, screen_w - cur_w - 8))
            top.geometry(f"{cur_w}x{target_h}+{int(new_x)}+{int(new_y)}")
        except Exception:
            pass

    def _load_watermark_layers_to_ui(self):
        """将配置加载到主界面多重水印区域"""
        self._clear_watermark_layer_rows()
        layers = self._normalize_watermark_layers()
        if layers:
            for layer in layers:
                self._add_watermark_layer_row(layer)
        else:
            self._add_watermark_layer_row()

    def sync_watermark_layers_from_ui(self):
        """从主界面多重水印区域同步到配置"""
        layers = []
        for v in self.watermark_layer_rows:
            if not v["path"].get():
                continue
            layers.append({
                "enabled": v["enabled"].get(),
                "type": "图片",
                "path": v["path"].get(),
                "position": v["position"].get(),
                "size_mode": v["size_mode"].get(),
                "scale": v["scale"].get(),
                "blend_mode": v["blend_mode"].get(),
                "opacity": v["opacity"].get(),
                "fixed": v["fixed"].get(),
                "folder_random_single": v["folder_random_single"].get(),
            })
        self.watermark_layers = layers

    def open_watermark_layers_dialog(self):
        """打开多重水印图层管理窗口（图片水印）"""
        dialog = tk.Toplevel(self.parent)
        dialog.title("多重水印管理")
        dialog.geometry("900x380")
        dialog.transient(self.parent)
        dialog.grab_set()
        self._center_dialog_on_parent(dialog)

        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(0, weight=1)
        container = ttk.Frame(dialog, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(1, weight=1)

        header = ttk.Label(container, text="多重水印（仅图片水印）", style='Subtitle.TLabel')
        header.grid(row=0, column=0, sticky="w", pady=(0, 8))

        rows_frame = ttk.Frame(container)
        rows_frame.grid(row=1, column=0, sticky="nsew")
        rows_frame.grid_columnconfigure(0, weight=1)

        row_vars = []

        def add_row(layer=None):
            layer = layer or {}
            row = ttk.Frame(rows_frame)
            row_index = len(row_vars)
            row.grid(row=row_index, column=0, sticky="ew", pady=GridSystem.SPACING['xs'])
            row.grid_columnconfigure(2, weight=1)

            enabled_var = tk.BooleanVar(value=layer.get("enabled", True))
            fixed_var = tk.BooleanVar(value=layer.get("fixed", False))
            folder_random_single_var = tk.BooleanVar(value=bool(layer.get("folder_random_single", False)))
            path_var = tk.StringVar(value=layer.get("path", ""))
            position_var = tk.StringVar(value=layer.get("position", "右下"))
            size_mode_var = tk.StringVar(value=layer.get("size_mode", "自适应覆盖"))
            scale_var = tk.DoubleVar(value=layer.get("scale", 20.0))
            blend_var = tk.StringVar(value=layer.get("blend_mode", "正常"))
            opacity_var = tk.DoubleVar(value=layer.get("opacity", 0.5))

            ttk.Checkbutton(row, text="启用", variable=enabled_var).grid(row=0, column=0, sticky="w", padx=(0, 8))
            ttk.Label(row, text="路径").grid(row=0, column=1, sticky="w", padx=(0, 8))
            ttk.Entry(row, textvariable=path_var, width=26).grid(row=0, column=2, sticky="ew", padx=(0, 8))
            ttk.Button(
                row, text="浏览",
                command=lambda v=path_var: v.set(filedialog.askopenfilename(
                    title="选择水印图片",
                    filetypes=[("图片文件", "*.png;*.jpg;*.jpeg;*.bmp;*.gif"), ("所有文件", "*.*")]
                ) or v.get()),
                width=4
            ).grid(row=0, column=3, sticky="w", padx=(0, 8))

            ttk.Label(row, text="位置").grid(row=0, column=4, sticky="w", padx=(0, 8))
            ttk.Combobox(row, textvariable=position_var,
                         values=["左上", "右上", "左下", "右下", "中心"],
                         width=5, state="readonly").grid(row=0, column=5, sticky="w", padx=(0, 8))

            ttk.Checkbutton(row, text="固定", variable=fixed_var).grid(row=0, column=6, sticky="w", padx=(0, 8))
            ttk.Checkbutton(row, text="目录随机1个", variable=folder_random_single_var).grid(row=0, column=7, sticky="w", padx=(0, 8))

            ttk.Label(row, text="大小").grid(row=0, column=8, sticky="w", padx=(0, 8))
            ttk.Combobox(row, textvariable=size_mode_var,
                         values=["固定比例", "自适应覆盖", "完全覆盖"],
                         width=8, state="readonly").grid(row=0, column=9, sticky="w", padx=(0, 8))

            ttk.Label(row, text="缩放").grid(row=0, column=10, sticky="w", padx=(0, 8))
            ttk.Spinbox(row, from_=5, to=100, increment=5,
                        textvariable=scale_var, width=5).grid(row=0, column=11, sticky="w", padx=(0, 8))

            ttk.Label(row, text="混合").grid(row=0, column=12, sticky="w", padx=(0, 8))
            ttk.Combobox(row, textvariable=blend_var,
                         values=["正常", "滤色", "叠加", "正片叠底", "变亮", "变暗", "相加"],
                         width=6, state="readonly").grid(row=0, column=13, sticky="w", padx=(0, 8))

            ttk.Label(row, text="透明度").grid(row=0, column=14, sticky="w", padx=(0, 8))
            ttk.Spinbox(row, from_=0.1, to=1.0, increment=0.1,
                        textvariable=opacity_var, width=4).grid(row=0, column=15, sticky="w")

            row_vars.append({
                "enabled": enabled_var,
                "fixed": fixed_var,
                "folder_random_single": folder_random_single_var,
                "path": path_var,
                "position": position_var,
                "size_mode": size_mode_var,
                "scale": scale_var,
                "blend_mode": blend_var,
                "opacity": opacity_var
            })

        for layer in self._normalize_watermark_layers():
            add_row(layer)
        if not row_vars:
            add_row()

        controls = ttk.Frame(container)
        controls.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        controls.grid_columnconfigure(0, weight=1)

        def on_add():
            add_row()

        def on_save():
            layers = []
            for v in row_vars:
                if not v["path"].get():
                    continue
                layers.append({
                    "enabled": v["enabled"].get(),
                    "type": "图片",
                    "path": v["path"].get(),
                    "position": v["position"].get(),
                    "size_mode": v["size_mode"].get(),
                    "scale": v["scale"].get(),
                    "blend_mode": v["blend_mode"].get(),
                    "opacity": v["opacity"].get(),
                    "fixed": v["fixed"].get(),
                    "folder_random_single": v["folder_random_single"].get(),
                })
            self.watermark_layers = layers
            self.update_status(f"已保存多重水印配置: {len(layers)}层")
            dialog.destroy()

        ttk.Button(controls, text="添加图层", command=on_add).grid(row=0, column=0, sticky="w")
        ttk.Button(controls, text="保存", command=on_save).grid(row=0, column=1, sticky="e")
    
    def open_output_dir(self):
        """打开输出目录"""
        output_dir = self.output_dir.get()
        if os.path.exists(output_dir):
            # 根据操作系统打开文件夹
            if sys.platform == 'win32':
                os.startfile(output_dir)
            elif sys.platform == 'darwin':  # macOS
                os.system(f'open "{output_dir}"')
            else:  # Linux
                os.system(f'xdg-open "{output_dir}"')
        else:
            # 如果目录不存在，询问是否创建
            if messagebox.askyesno("提示", f"输出目录 {output_dir} 不存在，是否创建?"):
                try:
                    os.makedirs(output_dir, exist_ok=True)
                    messagebox.showinfo("成功", f"已创建目录: {output_dir}")
                    self.open_output_dir()  # 创建后打开
                except Exception as e:
                    messagebox.showerror("错误", f"创建目录失败: {str(e)}")
            else:
                messagebox.showinfo("提示", "请选择有效的输出目录")
    
    def get_images_list(self, input_dir, limit_count=None, selection_mode="随机选择"):
        """获取输入目录中的所有图片文件
        
        Args:
            input_dir: 输入目录路径
            limit_count: 限制图片数量，为None时不限制
            selection_mode: 图片选择方式，"随机选择"或"按名称排序"
        
        Returns:
            list: 图片文件路径列表
        """
        # 标准化路径
        input_dir = self.normalize_path(input_dir)
        
        image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp']
        images = []
        
        # 尝试使用Path对象
        try:
            for ext in image_extensions:
                # 同时搜索小写和大写扩展名，避免重复
                lower_files = list(Path(input_dir).glob(f'*{ext}'))
                upper_files = list(Path(input_dir).glob(f'*{ext.upper()}'))
                
                # 去重：只添加不在小写列表中的大写文件
                images.extend(lower_files)
                for upper_file in upper_files:
                    if upper_file not in lower_files:
                        images.append(upper_file)
            
            if images:
                image_paths = [str(img) for img in images]
                
                # 根据选择模式处理图片列表
                if selection_mode == "按名称排序":
                    # 使用自然排序（数字排序）
                    image_paths = self.sort_images_naturally(image_paths)
                    if limit_count and len(image_paths) > limit_count:
                        image_paths = image_paths[:limit_count]
                elif selection_mode == "随机选择" and limit_count and len(image_paths) > limit_count:
                    # 随机选择指定数量
                    import random
                    image_paths = random.sample(image_paths, limit_count)
                
                return image_paths
        except Exception as e:
            self.update_status(f"使用Path获取图片列表时出错: {str(e)}，尝试使用os.walk")
        
        # 备用方法：使用os.walk
        try:
            for root, _, files in os.walk(input_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_ext = os.path.splitext(file)[1].lower()
                    if file_ext in image_extensions:
                        images.append(file_path)
            
            # 根据选择模式处理图片列表
            if selection_mode == "按名称排序":
                # 使用自然排序（数字排序）
                images = self.sort_images_naturally(images)
                if limit_count and len(images) > limit_count:
                    images = images[:limit_count]
            elif selection_mode == "随机选择" and limit_count and len(images) > limit_count:
                # 随机选择指定数量
                import random
                images = random.sample(images, limit_count)
            
            return images
        except Exception as e:
            self.update_status(f"获取图片列表时出错: {str(e)}")
            return []
    
    def natural_sort_key(self, filename):
        """生成自然排序的键值"""
        import re
        # 提取文件名（去除路径和扩展名）
        basename = os.path.splitext(os.path.basename(filename))[0]
        
        # 将数字和文字分开，数字部分转换为整数
        parts = re.split(r'(\d+)', basename)
        result = []
        
        for part in parts:
            if part.isdigit():
                result.append(int(part))  # 数字部分转整数
            else:
                result.append(part.lower())  # 文字部分转小写
        
        return result
    
    def sort_images_naturally(self, image_paths):
        """使用自然排序对图片进行排序
        
        Args:
            image_paths: 图片路径列表
            
        Returns:
            list: 排序后的图片路径列表
        """
        try:
            # 使用自然排序键进行排序
            sorted_paths = sorted(image_paths, key=self.natural_sort_key)
            
            # 输出排序信息用于调试
            if len(sorted_paths) > 0:
                first_few = [os.path.basename(path) for path in sorted_paths[:5]]
                last_few = [os.path.basename(path) for path in sorted_paths[-5:]] if len(sorted_paths) > 5 else []
                
                if last_few and len(sorted_paths) > 5:
                    self.update_status(f"按名称排序完成: 前5个 {first_few}...后5个 {last_few}")
                else:
                    self.update_status(f"按名称排序完成: {first_few}")
            
            return sorted_paths
            
        except Exception as e:
            self.update_status(f"自然排序出错: {str(e)}，使用默认排序")
            # 出错时降级为默认排序
            return sorted(image_paths)
    
    def safe_read_image(self, img_path):
        """安全读取图片，处理中文路径问题（支持 Turbo 加速）"""
        # 尝试使用 Turbo 加速器
        if self.turbo_accelerator and self.turbo_accelerator.enabled:
            try:
                return self.turbo_accelerator.optimized_image_read(img_path)
            except Exception as e:
                self.update_status(f"Turbo 读取失败，使用标准方法: {str(e)}")
        
        # 标准读取方法
        try:
            # 首先尝试使用numpy从文件加载，这种方法可以更好地处理中文路径
            try:
                # 确保路径编码正确
                encoded_path = img_path
                if isinstance(img_path, str):
                    if os.path.exists(img_path):
                        # 使用numpy读取，避开OpenCV的路径编码问题
                        img_array = np.fromfile(img_path, dtype=np.uint8)
                        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                        if img is not None:
                            return img
                    else:
                        # 尝试不同的编码方式
                        for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030']:
                            try:
                                # 尝试转换路径编码
                                decoded_path = img_path.encode('latin1').decode(encoding)
                                if os.path.exists(decoded_path):
                                    img_array = np.fromfile(decoded_path, dtype=np.uint8)
                                    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                                    if img is not None:
                                        return img
                            except Exception:
                                pass
            except Exception as e:
                self.update_status(f"使用numpy方法读取图片出错: {str(e)}，尝试直接读取")
            
            # 如果numpy方法失败，尝试直接读取
            img = cv2.imread(img_path)
            if img is not None:
                return img
            
            self.update_status(f"警告：无法读取图片 {img_path}")
            return None
        except Exception as e:
            self.update_status(f"读取图片出错: {str(e)}")
            return None
    
    def resize_with_aspect_ratio(self, img, target_width, target_height):
        """等比缩放图片，保持原始比例，不足的部分添加黑边"""
        if img is None:
            return None
            
        # 获取原始图片尺寸
        h, w = img.shape[:2]
        
        # 计算宽高比
        img_ratio = w / h
        target_ratio = target_width / target_height
        
        # 创建一个黑色背景图像（目标尺寸）
        result = np.zeros((target_height, target_width, 3), dtype=np.uint8)
        
        # 计算缩放后的尺寸和位置
        if img_ratio > target_ratio:
            # 图片比目标更宽，以宽度为准缩放
            new_w = target_width
            new_h = int(target_width / img_ratio)
            # 计算垂直居中的起始位置
            y_offset = (target_height - new_h) // 2
            x_offset = 0
        else:
            # 图片比目标更高，以高度为准缩放
            new_h = target_height
            new_w = int(target_height * img_ratio)
            # 计算水平居中的起始位置
            x_offset = (target_width - new_w) // 2
            y_offset = 0
        
        # 对原图进行缩放
        resized_img = cv2.resize(img, (new_w, new_h))
        
        # 将缩放后的图片放入黑色背景中
        result[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized_img
        
        return result

    def _center_crop(self, img, target_width, target_height):
        """从中心裁剪到目标尺寸"""
        if img is None:
            return None
        h, w = img.shape[:2]
        if h < target_height or w < target_width:
            return cv2.resize(img, (target_width, target_height))
        x_start = max((w - target_width) // 2, 0)
        y_start = max((h - target_height) // 2, 0)
        return img[y_start:y_start + target_height, x_start:x_start + target_width]

    def _frame_to_photoimage(self, frame, max_w=520, max_h=260):
        """将OpenCV帧转换为Tk可显示图片。"""
        if frame is None:
            return None
        h, w = frame.shape[:2]
        if h <= 0 or w <= 0:
            return None
        scale = min(max_w / float(w), max_h / float(h), 1.0)
        preview_w = max(1, int(w * scale))
        preview_h = max(1, int(h * scale))
        resized = cv2.resize(frame, (preview_w, preview_h), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".png", resized)
        if not ok:
            return None
        data = base64.b64encode(encoded.tobytes())
        return tk.PhotoImage(data=data)

    def _build_effect_preview_source_frame(self):
        """构建特效预览使用的基础帧（未应用特效）。"""
        input_dir = self.input_dir.get().strip()
        if not input_dir or not os.path.isdir(input_dir):
            self.update_status("预览失败：请先设置有效输入目录")
            return None

        images = self.get_images_list(input_dir, limit_count=None, selection_mode="按名称排序")
        if not images:
            self.update_status("预览失败：输入目录没有可用图片")
            return None

        source_path = images[0]
        src = self.safe_read_image(source_path)
        if src is None:
            self.update_status(f"预览失败：无法读取图片 {os.path.basename(source_path)}")
            return None

        width = int(self.width.get())
        height = int(self.height.get())
        frame = self.resize_image(src, width, height, "适应", self.keep_aspect_ratio.get())
        if frame is None:
            self.update_status("预览失败：图片缩放处理失败")
            return None
        return frame

    def _render_single_effect_preview_frame(self, time_sec, base_frame=None):
        """基于时间点渲染特效预览帧。"""
        frame = base_frame if base_frame is not None else self._build_effect_preview_source_frame()
        if frame is None:
            return None

        effect_type = self.video_effect_type.get()
        duration_sec = max(0.001, float(self.duration.get()))
        time_sec = max(0.0, float(time_sec))
        rendered = self.apply_single_image_effect(
            frame.copy(),
            effect_type,
            time_sec,
            duration_sec,
            self.video_effect_intensity.get(),
            self.video_effect_speed.get(),
        )
        return rendered

    def _build_single_effect_preview_frame(self):
        """基于当前参数生成单图特效预览帧。"""
        return self._render_single_effect_preview_frame(self.effect_preview_time.get())

    def _stop_effect_preview_animation(self):
        """停止动态特效预览计时器。"""
        if getattr(self, "_effect_preview_after_id", None):
            try:
                self.parent.after_cancel(self._effect_preview_after_id)
            except Exception:
                pass
        self._effect_preview_after_id = None

    def _set_effect_preview_visibility(self, visible):
        """设置内嵌特效预览区域显示/收起。"""
        old_visible = bool(getattr(self, "_effect_preview_visible", True))
        new_visible = bool(visible)
        self._effect_preview_visible = new_visible
        if hasattr(self, "effect_preview_label") and self.effect_preview_label is not None:
            if self._effect_preview_visible:
                self.effect_preview_label.grid()
            else:
                self.effect_preview_label.grid_remove()

        if getattr(self, "_effect_preview_toggle_button", None) is not None:
            text = "收起预览" if self._effect_preview_visible else "展开预览"
            try:
                self._effect_preview_toggle_button.configure(text=text)
            except Exception:
                pass
        # 对预览显隐做确定性高度调整，避免仅依赖 reqheight 导致不生效
        if old_visible != new_visible:
            self._adjust_window_height_for_preview(new_visible)

    def _adjust_window_height_for_preview(self, visible):
        """预览显隐后按真实内容重算顶层窗口高度。"""
        self._auto_resize_parent(force=True)

    def _toggle_effect_preview_visibility(self):
        """切换内嵌特效预览区域显示状态。"""
        if self._effect_preview_visible:
            self._stop_effect_preview_animation()
        self._set_effect_preview_visibility(not self._effect_preview_visible)

    def _effect_preview_tick(self):
        """动态特效预览帧刷新。"""
        if self._effect_preview_source_frame is None:
            self._stop_effect_preview_animation()
            return

        elapsed = max(0.0, time.time() - self._effect_preview_started_at)
        if elapsed > self._effect_preview_max_seconds:
            self._stop_effect_preview_animation()
            self.update_status(
                f"动态预览完成：{self.video_effect_type.get()}（{self._effect_preview_max_seconds:.0f}s）"
            )
            return

        duration_sec = max(0.001, float(self.duration.get()))
        preview_time = (self._effect_preview_start_offset + elapsed) % duration_sec
        frame = self._render_single_effect_preview_frame(
            preview_time,
            base_frame=self._effect_preview_source_frame
        )
        photo = self._frame_to_photoimage(frame) if frame is not None else None
        if photo is None:
            self._stop_effect_preview_animation()
            self.update_status("预览失败：图像渲染失败")
            return

        self._effect_preview_photo = photo
        if hasattr(self, "effect_preview_label"):
            self.effect_preview_label.configure(image=photo, text="")
        self._effect_preview_after_id = self.parent.after(50, self._effect_preview_tick)

    def preview_single_effect_frame(self):
        """刷新单图特效预览面板（启用特效时播放动态预览）。"""
        self._set_effect_preview_visibility(True)
        self._stop_effect_preview_animation()
        try:
            # 启用单图特效时，提供动态预览以体现运动效果
            if self.use_video_effect.get() and self.video_effect_type.get() != "无特效":
                self._effect_preview_source_frame = self._build_effect_preview_source_frame()
                if self._effect_preview_source_frame is None:
                    return
                self._effect_preview_started_at = time.time()
                self._effect_preview_start_offset = max(0.0, float(self.effect_preview_time.get()))
                self.update_status(
                    f"开始动态预览：{self.video_effect_type.get()}（起始 {self._effect_preview_start_offset:.1f}s）"
                )
                self._effect_preview_tick()
                return

            # 未启用特效时，保持单帧预览
            frame = self._build_single_effect_preview_frame()
            if frame is None:
                return
            photo = self._frame_to_photoimage(frame)
            if photo is None:
                self.update_status("预览失败：图像渲染失败")
                return
            self._effect_preview_photo = photo
            if hasattr(self, "effect_preview_label"):
                self.effect_preview_label.configure(image=photo, text="")
            self.update_status(f"预览已更新：{self.video_effect_type.get()} @ {self.effect_preview_time.get():.1f}s")
        except Exception as e:
            self.update_status(f"预览失败：{str(e)}")

    def apply_single_image_effect(self, img, effect_type, time_sec, duration_sec, intensity=100.0, speed=1.0):
        """单图视频特效：让静态图片产生运动感"""
        try:
            if img is None:
                return img
            h, w = img.shape[:2]
            time_sec = max(0.0, float(time_sec))
            duration_sec = max(0.001, float(duration_sec))
            # 速度按“每秒进度”计算，避免时长越长越慢
            progress = min(1.0, time_sec * max(0.01, float(speed)))
            intensity = max(1.0, float(intensity))
            speed = max(0.01, float(speed))
            intensity_scale = intensity / 100.0

            if effect_type == "无特效":
                return img

            # 兼容旧配置：将已移除的“单次运动”特效映射到循环复合特效
            legacy_effect_alias = {
                "心跳跃动": "心跳跳动",
                "轻微放大": "镜头呼吸",
                "轻微缩小": "脉冲放大",
                "左右平移": "左右晃动",
                "上下平移": "上下浮动",
                "旋转缩放": "旋转摆动",
                "缓慢推近": "摇摆推拉",
                "缓慢拉远": "双轴呼吸",
                "右下平移": "圆周漂移",
                "左上平移": "8字漂移",
            }
            effect_type = legacy_effect_alias.get(effect_type, effect_type)

            def _affine_transform(scale=1.0, angle=0.0, tx=0.0, ty=0.0):
                """统一仿射变换，避免重复代码。"""
                M = cv2.getRotationMatrix2D((w * 0.5, h * 0.5), angle, scale)
                M[0, 2] += tx
                M[1, 2] += ty
                return cv2.warpAffine(
                    img, M, (w, h),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_REFLECT
                )

            # 循环相位（不依赖视频总时长，始终无限循环）
            p1 = 2 * np.pi * 1.0 * speed * time_sec
            p2 = 2 * np.pi * 1.6 * speed * time_sec
            p3 = 2 * np.pi * 2.2 * speed * time_sec

            # 新增：20个无限循环复合特效
            if effect_type == "旋转呼吸":
                scale = 1.02 + 0.06 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
                angle = 5.0 * intensity_scale * np.sin(p2)
                return _affine_transform(scale=scale, angle=angle)

            if effect_type == "摇摆推拉":
                scale = 1.04 + 0.10 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
                angle = 3.5 * intensity_scale * np.sin(p2)
                tx = 0.015 * w * intensity_scale * np.sin(p3)
                return _affine_transform(scale=scale, angle=angle, tx=tx)

            if effect_type == "圆周漂移":
                scale = 1.08 + 0.03 * intensity_scale
                tx = 0.035 * w * intensity_scale * np.cos(p1)
                ty = 0.035 * h * intensity_scale * np.sin(p1)
                return _affine_transform(scale=scale, tx=tx, ty=ty)

            if effect_type == "螺旋摆动":
                radius = (0.015 + 0.02 * (0.5 - 0.5 * np.cos(p2))) * intensity_scale
                tx = radius * w * np.cos(p1)
                ty = radius * h * np.sin(p1)
                angle = 4.0 * intensity_scale * np.sin(p3)
                scale = 1.04 + 0.04 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
                return _affine_transform(scale=scale, angle=angle, tx=tx, ty=ty)

            if effect_type == "双轴呼吸":
                sx = 1.0 + 0.07 * intensity_scale * np.sin(p1)
                sy = 1.0 + 0.07 * intensity_scale * np.cos(p2)
                scaled = cv2.resize(img, (int(w * sx), int(h * sy)))
                return self._center_crop(scaled, w, h)

            if effect_type == "心跳摇摆":
                beat = (0.5 - 0.5 * np.cos(p2)) ** 1.7
                scale = 1.0 + 0.12 * intensity_scale * beat
                angle = 2.5 * intensity_scale * np.sin(p1)
                return _affine_transform(scale=scale, angle=angle)

            if effect_type == "波浪平移":
                scale = 1.08 + 0.03 * intensity_scale
                tx = 0.04 * w * intensity_scale * np.sin(p1)
                ty = 0.025 * h * intensity_scale * np.sin(p2)
                return _affine_transform(scale=scale, tx=tx, ty=ty)

            if effect_type == "8字漂移":
                scale = 1.08 + 0.03 * intensity_scale
                tx = 0.04 * w * intensity_scale * np.sin(p1)
                ty = 0.03 * h * intensity_scale * np.sin(2 * p1)
                return _affine_transform(scale=scale, tx=tx, ty=ty)

            if effect_type == "径向脉冲旋转":
                pulse = 0.5 - 0.5 * np.cos(p3)
                scale = 1.03 + 0.10 * intensity_scale * pulse
                angle = 8.0 * intensity_scale * np.sin(p2)
                return _affine_transform(scale=scale, angle=angle)

            if effect_type == "镜头抖动呼吸":
                scale = 1.03 + 0.06 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
                tx = 0.01 * w * intensity_scale * np.sin(8 * p1)
                ty = 0.01 * h * intensity_scale * np.cos(7 * p1)
                return _affine_transform(scale=scale, tx=tx, ty=ty)

            if effect_type == "反向双旋":
                f1 = _affine_transform(scale=1.05 + 0.03 * intensity_scale, angle=6.0 * intensity_scale * np.sin(p1))
                f2 = _affine_transform(scale=1.05 + 0.03 * intensity_scale, angle=-6.0 * intensity_scale * np.sin(p1))
                alpha = 0.5 + 0.25 * np.sin(p2)
                return cv2.addWeighted(f1, alpha, f2, 1.0 - alpha, 0)

            if effect_type == "呼吸变焦扫光":
                scale = 1.02 + 0.08 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
                frame = _affine_transform(scale=scale)
                band_center = int((0.5 + 0.5 * np.sin(p2)) * w)
                band_width = max(10, int(w * (0.08 + 0.04 * intensity_scale)))
                x_arr = np.arange(w, dtype=np.float32)
                alpha_line = np.clip(1.0 - np.abs(x_arr - band_center) / band_width, 0.0, 1.0) * (0.15 + 0.22 * intensity_scale)
                alpha = np.repeat(alpha_line[np.newaxis, :], h, axis=0)[..., np.newaxis]
                return np.clip(frame.astype(np.float32) * (1.0 - alpha) + 255.0 * alpha, 0, 255).astype(np.uint8)

            if effect_type == "旋摆模糊脉冲":
                angle = 5.0 * intensity_scale * np.sin(p1)
                frame = _affine_transform(scale=1.04 + 0.04 * intensity_scale, angle=angle)
                blur_wave = 0.5 - 0.5 * np.cos(p2)
                ksize = max(1, int((1 + 8 * intensity_scale) * blur_wave) * 2 + 1)
                blurred = cv2.GaussianBlur(frame, (ksize, ksize), sigmaX=0)
                alpha = 0.25 + 0.45 * blur_wave
                return cv2.addWeighted(frame, 1 - alpha, blurred, alpha, 0)

            if effect_type == "透视呼吸摆动":
                tilt = (0.02 + 0.05 * intensity_scale) * np.sin(p1)
                dx = w * tilt
                src = np.float32([[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]])
                dst = np.float32([[dx, 0], [w - 1 - dx, 0], [-dx, h - 1], [w - 1 + dx, h - 1]])
                M = cv2.getPerspectiveTransform(src, dst)
                warped = cv2.warpPerspective(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                M2 = cv2.getRotationMatrix2D(
                    (w * 0.5, h * 0.5),
                    2.5 * intensity_scale * np.sin(p2),
                    1.02 + 0.03 * intensity_scale
                )
                return cv2.warpAffine(warped, M2, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

            if effect_type == "涡旋推拉":
                swirl = self.apply_single_image_effect(img, "漩涡旋转", time_sec, duration_sec, intensity, speed)
                scale = 1.03 + 0.08 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
                angle = 3.0 * intensity_scale * np.sin(p2)
                M = cv2.getRotationMatrix2D((w * 0.5, h * 0.5), angle, scale)
                return cv2.warpAffine(swirl, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

            if effect_type == "变焦摇移":
                scale = 1.06 + 0.08 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
                tx = 0.03 * w * intensity_scale * np.sin(p2)
                ty = 0.03 * h * intensity_scale * np.cos(p2)
                return _affine_transform(scale=scale, tx=tx, ty=ty)

            if effect_type == "旋转漂移闪动":
                frame = _affine_transform(
                    scale=1.05 + 0.03 * intensity_scale,
                    angle=6.0 * intensity_scale * np.sin(p1),
                    tx=0.02 * w * intensity_scale * np.sin(p2),
                    ty=0.02 * h * intensity_scale * np.cos(p2),
                )
                glow = 0.08 + 0.18 * intensity_scale * (0.5 - 0.5 * np.cos(p3))
                return np.clip(frame.astype(np.float32) * (1.0 + glow), 0, 255).astype(np.uint8)

            if effect_type == "双频摆动":
                angle = (
                    4.0 * intensity_scale * np.sin(p1)
                    + 2.0 * intensity_scale * np.sin(2.7 * p1)
                )
                tx = 0.025 * w * intensity_scale * np.sin(p2)
                return _affine_transform(scale=1.04 + 0.03 * intensity_scale, angle=angle, tx=tx)

            if effect_type == "环形巡航":
                scale = 1.10 + 0.03 * intensity_scale
                tx = 0.045 * w * intensity_scale * np.cos(p1)
                ty = 0.035 * h * intensity_scale * np.sin(1.3 * p1)
                angle = 2.0 * intensity_scale * np.sin(p2)
                return _affine_transform(scale=scale, angle=angle, tx=tx, ty=ty)

            if effect_type == "呼吸鱼眼旋摆":
                fisheye = self.apply_single_image_effect(img, "鱼眼镜头", time_sec, duration_sec, intensity, speed)
                scale = 1.02 + 0.06 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
                angle = 4.0 * intensity_scale * np.sin(p2)
                M = cv2.getRotationMatrix2D((w * 0.5, h * 0.5), angle, scale)
                return cv2.warpAffine(fisheye, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

            if effect_type == "心跳跳动":
                # 两次心跳：快速放大-回落
                cycles = 2.0 * speed
                wave = 0.5 - 0.5 * np.cos(2 * np.pi * cycles * time_sec)
                scale = 1.0 + (0.10 * intensity_scale) * wave
                resized = cv2.resize(img, (int(w * scale), int(h * scale)))
                return self._center_crop(resized, w, h)

            if effect_type == "反复缩放":
                # 平滑来回缩放（ping-pong）
                cycles = 1.5 * speed
                t = 0.5 - 0.5 * np.cos(2 * np.pi * cycles * time_sec)
                scale = (1.0 - 0.05 * intensity_scale) + (0.15 * intensity_scale) * t
                resized = cv2.resize(img, (int(w * scale), int(h * scale)))
                return self._center_crop(resized, w, h)

            if effect_type == "轻微摇摆":
                # 轻微左右旋转摆动
                angle = (3.0 * intensity_scale) * np.sin(2 * np.pi * 1.0 * speed * time_sec)
                scale = 1.02 + 0.02 * intensity_scale
                resized = cv2.resize(img, (int(w * scale), int(h * scale)))
                rh, rw = resized.shape[:2]
                center = (rw // 2, rh // 2)
                M = cv2.getRotationMatrix2D(center, angle, 1.0)
                rotated = cv2.warpAffine(
                    resized, M, (rw, rh),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_REFLECT
                )
                return self._center_crop(rotated, w, h)

            if effect_type == "左右晃动":
                # 水平往返移动
                scale = 1.04 + 0.06 * intensity_scale
                resized = cv2.resize(img, (int(w * scale), int(h * scale)))
                max_x = max(resized.shape[1] - w, 0)
                t = 0.5 - 0.5 * np.cos(2 * np.pi * 2.0 * speed * time_sec)
                x = int(max_x * t)
                return self._center_crop(resized[:, x:x + w], w, h)

            if effect_type == "上下浮动":
                # 垂直往返移动
                scale = 1.04 + 0.06 * intensity_scale
                resized = cv2.resize(img, (int(w * scale), int(h * scale)))
                max_y = max(resized.shape[0] - h, 0)
                t = 0.5 - 0.5 * np.cos(2 * np.pi * 2.0 * speed * time_sec)
                y = int(max_y * t)
                return self._center_crop(resized[y:y + h, :], w, h)

            if effect_type == "缓慢推近":
                # 缓慢推近
                scale = 1.0 + (0.12 * intensity_scale) * progress
                resized = cv2.resize(img, (int(w * scale), int(h * scale)))
                return self._center_crop(resized, w, h)

            if effect_type == "缓慢拉远":
                # 缓慢拉远
                scale = (1.0 + 0.12 * intensity_scale) - (0.12 * intensity_scale) * progress
                resized = cv2.resize(img, (int(w * scale), int(h * scale)))
                return self._center_crop(resized, w, h)

            if effect_type == "右下平移":
                # 向右下缓慢移动
                scale = 1.05 + 0.05 * intensity_scale
                resized = cv2.resize(img, (int(w * scale), int(h * scale)))
                max_x = max(resized.shape[1] - w, 0)
                max_y = max(resized.shape[0] - h, 0)
                x = int(max_x * progress)
                y = int(max_y * progress)
                return resized[y:y + h, x:x + w]

            if effect_type == "左上平移":
                # 向左上缓慢移动
                scale = 1.05 + 0.05 * intensity_scale
                resized = cv2.resize(img, (int(w * scale), int(h * scale)))
                max_x = max(resized.shape[1] - w, 0)
                max_y = max(resized.shape[0] - h, 0)
                x = int(max_x * (1.0 - progress))
                y = int(max_y * (1.0 - progress))
                return resized[y:y + h, x:x + w]

            if effect_type == "镜头呼吸":
                # 缓慢呼吸式缩放
                t = 0.5 - 0.5 * np.cos(2 * np.pi * 1.0 * speed * time_sec)
                scale = 1.01 + (0.06 * intensity_scale) * t
                resized = cv2.resize(img, (int(w * scale), int(h * scale)))
                return self._center_crop(resized, w, h)

            if effect_type == "脉冲放大":
                # 周期性脉冲放大
                t = 0.5 - 0.5 * np.cos(2 * np.pi * 3.0 * speed * time_sec)
                scale = 1.0 + (0.08 * intensity_scale) * t
                resized = cv2.resize(img, (int(w * scale), int(h * scale)))
                return self._center_crop(resized, w, h)

            if effect_type == "旋转摆动":
                # 旋转摆动，幅度稍大
                angle = (6.0 * intensity_scale) * np.sin(2 * np.pi * 1.5 * speed * time_sec)
                scale = 1.02 + 0.04 * intensity_scale
                resized = cv2.resize(img, (int(w * scale), int(h * scale)))
                rh, rw = resized.shape[:2]
                center = (rw // 2, rh // 2)
                M = cv2.getRotationMatrix2D(center, angle, 1.0)
                rotated = cv2.warpAffine(
                    resized, M, (rw, rh),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_REFLECT
                )
                return self._center_crop(rotated, w, h)

            if effect_type == "水波扭曲":
                # 基于正弦场的水波位移
                y_coords, x_coords = np.indices((h, w), dtype=np.float32)
                cx, cy = w * 0.5, h * 0.5
                dx = x_coords - cx
                dy = y_coords - cy
                dist = np.sqrt(dx * dx + dy * dy) + 1e-6
                wave_amp = (6.0 + 10.0 * intensity_scale) * (0.8 + 0.2 * np.sin(2 * np.pi * 0.5 * speed * time_sec))
                wave_freq = 0.035
                wave_phase = 2 * np.pi * speed * time_sec * 2.0
                offset = wave_amp * np.sin(dist * wave_freq + wave_phase)
                map_x = (x_coords + dx / dist * offset).astype(np.float32)
                map_y = (y_coords + dy / dist * offset).astype(np.float32)
                return cv2.remap(img, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

            if effect_type == "漩涡旋转":
                # 中心强、边缘弱的旋涡变换
                y_coords, x_coords = np.indices((h, w), dtype=np.float32)
                cx, cy = w * 0.5, h * 0.5
                x = x_coords - cx
                y = y_coords - cy
                r = np.sqrt(x * x + y * y)
                max_r = max(1.0, np.sqrt(cx * cx + cy * cy))
                base_theta = np.arctan2(y, x)
                swirl_strength = (2.8 * intensity_scale) * np.sin(2 * np.pi * 0.4 * speed * time_sec)
                theta = base_theta + swirl_strength * (1.0 - (r / max_r)) * (r / max_r)
                map_x = (cx + r * np.cos(theta)).astype(np.float32)
                map_y = (cy + r * np.sin(theta)).astype(np.float32)
                return cv2.remap(img, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

            if effect_type == "鱼眼镜头":
                # 轻度桶形畸变，营造鱼眼镜头呼吸感
                y_coords, x_coords = np.indices((h, w), dtype=np.float32)
                cx, cy = w * 0.5, h * 0.5
                nx = (x_coords - cx) / max(1.0, cx)
                ny = (y_coords - cy) / max(1.0, cy)
                r2 = nx * nx + ny * ny
                k = (0.18 * intensity_scale) * np.sin(2 * np.pi * 0.6 * speed * time_sec)
                scale_d = 1.0 + k * r2
                map_x = (cx + nx * scale_d * cx).astype(np.float32)
                map_y = (cy + ny * scale_d * cy).astype(np.float32)
                return cv2.remap(img, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

            if effect_type == "故障抖动":
                # RGB通道错位 + 条带位移
                shift = int((3 + 7 * intensity_scale) * np.sin(2 * np.pi * 3.0 * speed * time_sec))
                b, g, r = cv2.split(img)
                r_shift = np.roll(r, shift, axis=1)
                b_shift = np.roll(b, -shift, axis=1)
                glitch = cv2.merge([b_shift, g, r_shift])
                band_h = max(2, int(h * 0.06))
                band_y = int((0.5 - 0.5 * np.cos(2 * np.pi * 1.7 * speed * time_sec)) * max(1, h - band_h))
                band_offset = int((10 + 20 * intensity_scale) * np.sin(2 * np.pi * 6.0 * speed * time_sec))
                if band_h > 0:
                    glitch[band_y:band_y + band_h, :] = np.roll(glitch[band_y:band_y + band_h, :], band_offset, axis=1)
                return glitch

            if effect_type == "镜像扫光":
                # 反射高光带横向扫过
                frame = img.copy().astype(np.float32)
                band_center = int(progress * w)
                band_width = max(10, int(w * (0.08 + 0.04 * intensity_scale)))
                x = np.arange(w, dtype=np.float32)
                dist = np.abs(x - band_center)
                alpha_line = np.clip(1.0 - dist / band_width, 0.0, 1.0) * (0.22 + 0.18 * intensity_scale)
                alpha = np.repeat(alpha_line[np.newaxis, :], h, axis=0)
                alpha = np.expand_dims(alpha, axis=2)
                light = np.full_like(frame, 255.0)
                mixed = frame * (1.0 - alpha) + light * alpha
                return np.clip(mixed, 0, 255).astype(np.uint8)

            if effect_type == "呼吸模糊":
                # 在清晰与轻模糊间呼吸切换
                blur_wave = 0.5 - 0.5 * np.cos(2 * np.pi * 1.3 * speed * time_sec)
                blur_strength = int((1 + 8 * intensity_scale) * blur_wave)
                ksize = max(1, blur_strength * 2 + 1)
                blurred = cv2.GaussianBlur(img, (ksize, ksize), sigmaX=0)
                alpha = 0.35 + 0.45 * blur_wave
                return cv2.addWeighted(img, 1.0 - alpha, blurred, alpha, 0)

            if effect_type == "径向拉伸":
                # 近似Zoom blur：多次缩放回贴并叠加
                layers = 5
                acc = img.astype(np.float32) * 0.35
                for i in range(1, layers + 1):
                    t = i / layers
                    s = 1.0 + (0.02 + 0.08 * intensity_scale) * t * (0.5 - 0.5 * np.cos(2 * np.pi * speed * time_sec))
                    resized = cv2.resize(img, (int(w * s), int(h * s)))
                    cropped = self._center_crop(resized, w, h).astype(np.float32)
                    acc += cropped * (0.65 / layers)
                return np.clip(acc, 0, 255).astype(np.uint8)

            if effect_type == "边缘闪烁":
                # 边缘提取 + 发光叠加
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                edges = cv2.Canny(gray, 60, 140)
                edges = cv2.GaussianBlur(edges, (3, 3), 0)
                glow = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR).astype(np.float32)
                pulse = 0.15 + (0.45 * intensity_scale) * (0.5 - 0.5 * np.cos(2 * np.pi * 3.2 * speed * time_sec))
                frame = img.astype(np.float32)
                return np.clip(frame + glow * pulse, 0, 255).astype(np.uint8)

            if effect_type == "透视俯仰":
                # 模拟相机轻微俯仰透视
                tilt = (0.02 + 0.06 * intensity_scale) * np.sin(2 * np.pi * 0.8 * speed * time_sec)
                dx = w * tilt
                src = np.float32([[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]])
                dst = np.float32([[dx, 0], [w - 1 - dx, 0], [-dx, h - 1], [w - 1 + dx, h - 1]])
                M = cv2.getPerspectiveTransform(src, dst)
                warped = cv2.warpPerspective(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                return warped

            if effect_type == "滚动快门":
                # 按行位移模拟rolling shutter
                frame = img.copy()
                rows = np.arange(h, dtype=np.float32).reshape(-1, 1)
                phase = 2 * np.pi * (rows / max(1.0, h) * 4.0 + speed * time_sec * 2.0)
                line_shift = (3 + 10 * intensity_scale) * np.sin(phase)
                for y in range(h):
                    shift = int(line_shift[y, 0])
                    frame[y:y + 1, :] = np.roll(frame[y:y + 1, :], shift, axis=1)
                return frame

            if effect_type == "灵魂出窍":
                from ..core.video_effect_engine import apply_soul_out
                return apply_soul_out(img, time_sec, speed=speed, intensity=intensity_scale)

            return img
        except Exception:
            return img
    
    def apply_fade_transition(self, img1, img2, frame_idx, total_frames):
        """淡入淡出转场效果"""
        alpha = frame_idx / total_frames
        return cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)
    
    def apply_blinds_transition(self, img1, img2, frame_idx, total_frames):
        """百叶窗转场效果"""
        result = img1.copy()
        h, w = img1.shape[:2]
        
        # 百叶窗条数 (在5-15之间，随机选择)
        blinds = 10
        
        # 计算每个百叶窗的高度
        blind_height = h // blinds
        
        # 计算当前应该显示多少百叶窗
        visible_blinds = int((frame_idx / total_frames) * blinds) + 1
        
        # 应用百叶窗效果
        for i in range(blinds):
            start_y = i * blind_height
            end_y = start_y + blind_height
            
            # 确保不超出图像边界
            if end_y > h:
                end_y = h
            
            if i < visible_blinds:
                # 如果百叶窗已经可见，显示img2
                result[start_y:end_y, :] = img2[start_y:end_y, :]
        
        return result
    
    def apply_slide_transition(self, img1, img2, frame_idx, total_frames):
        """滑动转场效果"""
        result = img1.copy()
        h, w = img1.shape[:2]
        
        # 计算当前滑动的位置
        slide_pos = int((frame_idx / total_frames) * w)
        
        # 应用滑动效果(从右向左)
        result[:, (w-slide_pos):w] = img2[:, 0:slide_pos]
        
        return result
    
    def apply_dissolve_transition(self, img1, img2, frame_idx, total_frames):
        """溶解转场效果"""
        alpha = frame_idx / total_frames
        
        # 创建随机噪声掩码
        noise = np.random.random(img1.shape[:2])
        mask = (noise < alpha).astype(np.float32)
        mask = np.expand_dims(mask, axis=2)
        mask = np.repeat(mask, 3, axis=2)
        
        # 应用掩码
        result = img1.copy()
        np.copyto(result, img2, where=(mask > 0.5))
        
        return result
    
    def apply_wipe_transition(self, img1, img2, frame_idx, total_frames):
        """擦除转场效果"""
        result = img1.copy()
        h, w = img1.shape[:2]
        
        # 计算当前擦除的位置
        wipe_pos = int((frame_idx / total_frames) * h)
        
        # 应用擦除效果(从上到下)
        result[0:wipe_pos, :] = img2[0:wipe_pos, :]
        
        return result
    
    def apply_transition(self, img1, img2, video_writer, num_frames, transition_type="淡入淡出"):
        """应用转场效果并写入到视频"""
        try:
            # 优先统一走Turbo转场引擎（支持新增高级转场）
            if self.transition_engine and num_frames > 0 and transition_type != "无转场":
                try:
                    frames = self.transition_engine.generate_transition_frames(
                        img1, img2, transition_type, num_frames, use_cache=True
                    )
                    if frames:
                        for frame in frames:
                            video_writer.write(frame)
                        return
                except Exception:
                    pass

            h, w = img1.shape[:2]
            
            # 确保两张图片尺寸相同
            if img1.shape != img2.shape:
                img2 = cv2.resize(img2, (w, h))
            
            print(f"应用转场效果: {transition_type}, 总帧数: {num_frames}")
            
            for i in range(num_frames):
                # 计算过渡比例（避开0和1，避免重复帧）
                alpha = (i + 1) / (num_frames + 1) if num_frames > 0 else 1
                
                # 根据转场类型应用不同效果
                try:
                    if transition_type == "淡入淡出":
                        # 淡入淡出效果
                        frame = cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)
                    
                    elif transition_type == "左右滑动":
                        # 水平滑动效果 - 从右向左滑动
                        result = img1.copy()
                        slide_pos = int(alpha * w)
                        result[:, (w-slide_pos):w] = img2[:, 0:slide_pos]
                        frame = result
                    
                    elif transition_type == "上下滑动":
                        # 垂直滑动效果 - 从上到下滑动
                        result = img1.copy()
                        slide_pos = int(alpha * h)
                        result[0:slide_pos, :] = img2[0:slide_pos, :]
                        frame = result
                    
                    elif transition_type == "交叉溶解":
                        # 使用随机噪声创建溶解效果
                        mask = np.random.random(img1.shape[:2])
                        mask = (mask < alpha).astype(np.float32)
                        mask = np.expand_dims(mask, axis=2)
                        mask = np.repeat(mask, 3, axis=2)
                        
                        result = img1.copy() * (1-mask) + img2 * mask
                        frame = result.astype(np.uint8)
                    
                    elif transition_type == "缩放过渡":
                        # 缩放过渡效果
                        center_y, center_x = h//2, w//2
                        max_size = max(h, w)
                        scaling = int(max_size * alpha)
                        
                        # 创建掩码
                        mask = np.zeros((h, w), dtype=np.uint8)
                        cv2.circle(mask, (center_x, center_y), scaling, 255, -1)
                        
                        # 应用掩码
                        mask_3ch = cv2.merge([mask, mask, mask])
                        frame = np.where(mask_3ch > 128, img2, img1)
                    
                    elif transition_type == "方块过渡":
                        # 创建方块过渡效果
                        block_size = max(1, int(50 * (1 - alpha)))  # 块大小从大到小
                        
                        # 创建方块掩码
                        mask = np.zeros((h, w), dtype=np.uint8)
                        for y in range(0, h, block_size*2):
                            for x in range(0, w, block_size*2):
                                y2 = min(y + block_size, h)
                                x2 = min(x + block_size, w)
                                mask[y:y2, x:x2] = 255
                        
                        # 进度控制显示区域
                        progress_mask = np.zeros((h, w), dtype=np.uint8)
                        progress_height = int(h * alpha)
                        progress_mask[0:progress_height, :] = 255
                        
                        # 结合两个掩码
                        final_mask = cv2.bitwise_and(mask, progress_mask)
                        final_mask_3ch = cv2.merge([final_mask, final_mask, final_mask])
                        
                        # 应用掩码
                        frame = np.where(final_mask_3ch > 128, img2, img1)
                    
                    elif transition_type == "圆形扩展":
                        # 从中心扩展的圆形
                        center_y, center_x = h//2, w//2
                        radius = int(np.sqrt(center_x**2 + center_y**2) * alpha)
                        
                        # 创建圆形掩码
                        mask = np.zeros((h, w), dtype=np.uint8)
                        cv2.circle(mask, (center_x, center_y), radius, 255, -1)
                        
                        # 应用掩码
                        mask_3ch = cv2.merge([mask, mask, mask])
                        frame = np.where(mask_3ch > 128, img2, img1)
                    
                    elif transition_type == "百叶窗":
                        # 创建交错线条效果 (对应main_with_presets.py中的"交错效果")
                        stripe_width = max(1, int(h * 0.05))  # 条纹宽度为图像高度的5%
                        result = img1.copy()
                        
                        # 根据进度增加第二张图片的条纹数量
                        num_stripes = int(h / stripe_width * alpha)
                        
                        for j in range(num_stripes):
                            y_start = j * stripe_width
                            y_end = min(y_start + stripe_width, h)
                            result[y_start:y_end, :] = img2[y_start:y_end, :]
                        
                        frame = result
                    
                    elif transition_type == "像素化":
                        # 像素化效果
                        max_block = max(1, min(h, w) // 10)
                        block_size = max(1, int(max_block * (1 - alpha)))
                        
                        if block_size > 1:
                            # 对第二张图像进行像素化
                            temp = cv2.resize(img2, (w // block_size, h // block_size), interpolation=cv2.INTER_LINEAR)
                            pixelated = cv2.resize(temp, (w, h), interpolation=cv2.INTER_NEAREST)
                            
                            # 根据进度混合原图和像素化图像
                            frame = cv2.addWeighted(img1, 1 - alpha, pixelated, alpha, 0)
                        else:
                            frame = cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)
                    
                    elif transition_type == "旋转变换":
                        # 旋转过渡效果
                        center_x, center_y = w // 2, h // 2
                        
                        # 计算旋转角度 (0-90度)
                        angle = 90 * alpha
                        
                        # 创建旋转矩阵和应用到第二张图片
                        M = cv2.getRotationMatrix2D((center_x, center_y), angle, 1.0)
                        rotated = cv2.warpAffine(img2, M, (w, h))
                        
                        # 创建圆形掩码
                        mask = np.zeros((h, w), dtype=np.uint8)
                        radius = int(min(w, h) * 0.5 * alpha)
                        cv2.circle(mask, (center_x, center_y), radius, 255, -1)
                        
                        # 应用掩码
                        mask_3ch = cv2.merge([mask, mask, mask])
                        frame = np.where(mask_3ch > 128, rotated, img1)
                    
                    else:
                        # 默认使用淡入淡出
                        print(f"未识别的转场效果 '{transition_type}'，使用默认淡入淡出")
                        frame = cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)
                
                except Exception as e:
                    # 如果特效应用失败，回退到基本的淡入淡出
                    print(f"应用转场效果 {transition_type} 失败: {str(e)}，原因: {type(e).__name__}")
                    print(f"图像尺寸: img1={img1.shape}, img2={img2.shape}")
                    frame = cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)
                
                # 确保帧有效
                if frame is None or frame.shape[0] == 0 or frame.shape[1] == 0:
                    print(f"转场生成的帧无效，使用基本帧")
                    frame = cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)
                    
                # 写入帧
                video_writer.write(frame)
            
            print(f"转场效果 '{transition_type}' 应用完成")
                
        except Exception as e:
            print(f"转场效果处理失败: {str(e)}, 类型: {type(e).__name__}")
            print(f"图像尺寸: img1={img1.shape if img1 is not None else None}, img2={img2.shape if img2 is not None else None}")
            
            # 错误处理 - 写入两张静态图片作为应急方案
            if video_writer.isOpened():
                # 各写一半帧
                half_frames = num_frames // 2
                for _ in range(half_frames):
                    if img1 is not None and img1.size > 0:
                        video_writer.write(img1)
                    else:
                        # 如果img1无效，创建黑色图像
                        blank = np.zeros((h, w, 3), dtype=np.uint8)
                        video_writer.write(blank)
                        
                for _ in range(num_frames - half_frames):
                    if img2 is not None and img2.size > 0:
                        video_writer.write(img2)
                    else:
                        # 如果img2无效，创建黑色图像
                        blank = np.zeros((h, w, 3), dtype=np.uint8)
                        video_writer.write(blank)
    
    def get_h264_codec(self):
        """获取系统支持的H.264编码器标识符"""
        # 尝试不同的H.264编码器代码
        h264_codecs = ['avc1', 'h264', 'x264', 'H264']
        
        for codec in h264_codecs:
            if self.check_codec_availability(codec):
                self.update_status(f"找到可用的H.264编码器: {codec}")
                return codec
        
        # 如果没有找到可用的H.264编码器，返回None
        self.update_status("未找到可用的H.264编码器")
        return None

    def _get_selected_codec_name(self):
        """获取用户选择的编码器名称"""
        if hasattr(self, "codec_var"):
            return self.codec_var.get()
        return "XVID"

    def _resolve_cv_fourcc(self):
        """解析用户选择的编码器为OpenCV fourcc"""
        selected = self._get_selected_codec_name()
        if selected == "H264":
            return self.get_h264_codec()
        if self.check_codec_availability(selected):
            return selected
        return None

    def _resolve_processing_fourcc(self):
        """后处理环节严格沿用用户选择的OpenCV编码器，不再自动回退。"""
        return self._resolve_cv_fourcc()

    def _get_ffmpeg_vcodec(self):
        """获取FFmpeg视频编码器名称"""
        selected = self._get_selected_codec_name()
        mapping = {
            "H264": "libx264",
            "XVID": "libxvid",
            "MJPG": "mjpeg",
            "mp4v": "mpeg4"
        }
        return mapping.get(selected, "libx264")

    def _get_strict_ffmpeg_vcodec_for_output(self, output_path):
        """获取严格编码器：必须是用户选择且与目标容器兼容。"""
        selected = self._get_ffmpeg_vcodec()
        compatible = self._get_container_compatible_vcodecs(output_path)
        if selected not in compatible:
            return None
        return selected

    def _get_output_extension(self, output_path):
        """获取输出文件扩展名（小写），默认.mp4。"""
        ext = os.path.splitext(str(output_path))[1].lower()
        return ext if ext else ".mp4"

    def _build_temp_output_path(self, output_path, suffix):
        """按目标输出扩展名生成临时文件路径。"""
        base, _ = os.path.splitext(output_path)
        ext = self._get_output_extension(output_path)
        return f"{base}.{suffix}{ext}"

    def _get_ffmpeg_muxer_for_output(self, output_path):
        """根据目标扩展名返回FFmpeg muxer。"""
        ext = self._get_output_extension(output_path)
        mapping = {
            ".mp4": "mp4",
            ".m4v": "mp4",
            ".mov": "mov",
            ".avi": "avi",
            ".mkv": "matroska",
        }
        return mapping.get(ext)

    def _get_container_compatible_vcodecs(self, output_path, preferred_codec=None):
        """根据目标容器返回兼容的视频编码器候选列表。"""
        ext = self._get_output_extension(output_path)
        container_codecs = {
            ".mp4": ["libx264", "mpeg4"],
            ".m4v": ["libx264", "mpeg4"],
            ".mov": ["libx264", "mpeg4", "prores_ks"],
            ".avi": ["libxvid", "mpeg4", "mjpeg"],
            ".mkv": ["libx264", "mpeg4", "libxvid", "mjpeg"],
        }
        candidates = list(container_codecs.get(ext, ["libx264", "mpeg4", "libxvid", "mjpeg"]))
        if preferred_codec and preferred_codec in candidates:
            candidates.remove(preferred_codec)
            candidates.insert(0, preferred_codec)
        return candidates

    def _get_container_compatible_acodec(self, output_path):
        """根据目标容器返回兼容音频编码器。"""
        ext = self._get_output_extension(output_path)
        if ext == ".avi":
            return "mp3"
        return "aac"

    def _get_fallback_processing_fourcc(self):
        """为OpenCV处理阶段提供兜底编码器（仅中间文件使用）。"""
        preferred = None
        if isinstance(getattr(self, "_runtime_probe", None), dict):
            preferred = self._runtime_probe.get("preferred_cv_codec")
        candidates = tuple(c for c in (preferred, "mp4v", "XVID", "MJPG") if c)
        for codec in candidates:
            if self.check_codec_availability(codec):
                return codec
        return None

    def _reencode_video_to_selected_codec(self, src_path, dst_path, log_func=None):
        """将中间文件重编码为用户指定编码器/容器。"""
        def _log(msg):
            if log_func:
                log_func(msg)
            else:
                print(msg)

        if not self.ffmpeg_available:
            _log("FFmpeg不可用，无法执行重编码")
            return False

        strict_vcodec = self._get_strict_ffmpeg_vcodec_for_output(dst_path)
        if not strict_vcodec:
            _log(
                f"目标编码器与容器不兼容: codec={self._get_selected_codec_name()}, ext={self._get_output_extension(dst_path)}"
            )
            return False

        muxer = self._get_ffmpeg_muxer_for_output(dst_path)
        fps = 30
        try:
            meta = self._probe_video_meta(src_path)
            if meta and meta.get("fps", 0) > 0:
                fps = int(round(meta["fps"]))
        except Exception:
            pass

        cmd = [
            getattr(self, "ffmpeg_executable", None) or "ffmpeg", "-y",
            "-i", src_path,
            "-map", "0:v:0",
            "-map", "0:a?",
            "-c:v", strict_vcodec,
            "-pix_fmt", "yuv420p",
            "-r", str(max(1, fps)),
        ]
        if strict_vcodec == "libx264":
            cmd += ["-preset", "medium"]
        # OpenCV生成的中间文件通常无音频，保留可选映射并设定兼容编码器
        cmd += ["-c:a", self._get_container_compatible_acodec(dst_path), "-b:a", "192k"]
        if muxer:
            cmd += ["-f", muxer]
        cmd += [dst_path]

        _log(f"执行重编码命令: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=self.startupinfo if hasattr(self, 'startupinfo') else None,
        )
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="ignore")
            _log(f"重编码失败，错误码={result.returncode}, 详情={err[:300]}")
            return False
        if not (os.path.exists(dst_path) and os.path.getsize(dst_path) > 1000):
            _log("重编码后输出文件无效")
            return False
        self._log_output_probe(dst_path, log_func)
        return True

    def _log_output_probe(self, output_path, log_func=None):
        """使用ffprobe记录输出文件容器/编码信息，便于排查。"""
        def _log(msg):
            if log_func:
                log_func(msg)
            else:
                print(msg)

        ffprobe_path = getattr(self, "ffprobe_executable", None) or resolve_ffprobe_path(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            getattr(self, "ffmpeg_executable", None),
        )
        if not ffprobe_path:
            meta = self._probe_video_meta(output_path)
            if meta:
                _log(
                    f"[PROBE] 输出校验: size={meta['width']}x{meta['height']}, "
                    f"fps={meta['fps']:.3f}, duration={meta['duration']:.3f}s"
                )
            return

        try:
            cmd = [
                ffprobe_path,
                "-v", "error",
                "-show_entries", "format=format_name:stream=codec_name,pix_fmt,width,height,avg_frame_rate",
                "-select_streams", "v:0",
                "-of", "json",
                output_path
            ]
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=self.startupinfo if hasattr(self, 'startupinfo') else None,
            )
            if result.returncode != 0:
                err = result.stderr.decode("utf-8", errors="ignore")
                _log(f"[PROBE] ffprobe失败: {err[:240]}")
                return

            payload = json.loads(result.stdout.decode("utf-8", errors="ignore") or "{}")
            fmt = (payload.get("format") or {}).get("format_name", "unknown")
            streams = payload.get("streams") or []
            if streams:
                s = streams[0]
                codec = s.get("codec_name", "unknown")
                pix = s.get("pix_fmt", "unknown")
                w = s.get("width", "?")
                h = s.get("height", "?")
                fps = s.get("avg_frame_rate", "unknown")
                _log(f"[PROBE] 输出校验: format={fmt}, vcodec={codec}, pix_fmt={pix}, size={w}x{h}, fps={fps}")
            else:
                _log(f"[PROBE] 输出校验: format={fmt}, 未找到视频流")
        except Exception as e:
            _log(f"[PROBE] 输出校验异常: {str(e)}")
    
    def create_video(self, images, output_path, duration, fps, width=1920, height=1080,
                     apply_image_watermark=False, watermark_path=None, watermark_position="右下",
                     resize_mode="适应", maintain_aspect=True, transition_frames=15, transition_type="淡入淡出",
                     watermark_opacity=0.5, watermark_size=20, video_effect_type_override=None):
        """创建图片到视频的转换（支持码率控制+自动编码器切换+详细日志+文件日志）

        参数:
            images: 图片文件路径列表
            output_path: 输出视频文件路径
            duration: 每张图片的显示时长（秒），即用户设置的单张图片持续时间
            fps: 视频帧率
            width: 视频宽度
            height: 视频高度
            apply_image_watermark: 是否应用图片水印
            watermark_path: 水印图片路径
            watermark_position: 水印位置（"左上"、"右上"、"左下"、"右下"、"中心"）
            resize_mode: 图片调整大小模式（"适应"、"拉伸"、"填充"、"原始尺寸"）
            maintain_aspect: 是否保持宽高比
            transition_frames: 转场帧数
            transition_type: 转场效果类型
            watermark_opacity: 水印不透明度（0.0-1.0）
            watermark_size: 水印大小百分比
        """
        import traceback
        def log(msg):
            print(msg)
            try:
                with open("video_create_debug.log", "a", encoding="utf-8") as f:
                    f.write(msg+"\n")
            except Exception:
                pass
        if not images or not output_path:
            msg = "没有选择图片或输出路径"
            self.update_status(msg)
            log(msg)
            return False
        
        try:
            task_start_time = time.time()
            total_images = len(images)
            effect_type_for_video = (
                video_effect_type_override
                if video_effect_type_override in VIDEO_EFFECTS
                else self.video_effect_type.get()
            )
            msg = f"处理 {total_images} 张图片"
            self.update_status(msg)
            log(msg)
            if total_images < 1:
                msg = "至少需要一张图片"
                self.update_status(msg)
                log(msg)
                return False
            # 修改：每张图片的总时间包含转场时间，而不是额外添加
            total_time_per_img = duration  # 用户设置的每张图片总时间
            total_frames_per_img = int(total_time_per_img * fps)

            # 计算转场帧数（包含在每张图片时间内）
            transition_frames = min(transition_frames, total_frames_per_img // 3)  # 转场时间不超过1/3

            # 每张图片的静态显示帧数 = 总帧数 - 转场帧数
            display_frames_per_img = total_frames_per_img - transition_frames

            # 确保静态显示帧数不会太少
            if display_frames_per_img < fps // 2:  # 至少0.5秒静态显示
                display_frames_per_img = fps // 2
                transition_frames = total_frames_per_img - display_frames_per_img

            # 添加日志输出来确认时间计算
            static_time = display_frames_per_img / fps
            transition_time = transition_frames / fps
            total_video_duration = total_time_per_img * total_images  # 总时长就是图片数量×每张时间

            msg = f"每张图片总时长: {total_time_per_img}秒 (静态: {static_time:.2f}秒 + 转场: {transition_time:.2f}秒), 总视频时长: {total_video_duration:.2f}秒"
            self.update_status(msg)
            log(msg)
            
            first_img = self.safe_read_image(images[0])
            if first_img is None:
                msg = f"无法加载图片: {images[0]}"
                self.update_status(msg)
                log(msg)
                return False
            msg = f"首图shape: {first_img.shape}"
            self.update_status(msg)
            log(msg)
            if resize_mode == "原始尺寸":
                h, w = first_img.shape[:2]
                out_w, out_h = w, h
            else:
                out_w, out_h = width, height
            prepared_layers = self._prepare_image_watermark_layers() if apply_image_watermark else []
            follow_layers = [l for l in prepared_layers if not l.get("fixed")]
            fixed_layers = [l for l in prepared_layers if l.get("fixed")]
            # 获取用户设置的码率
            target_bitrate = self.bitrate.get() if hasattr(self, 'bitrate') else 5000
            msg = f"目标码率设置: {target_bitrate} kbps"
            self.update_status(msg)
            log(msg)

            # 阶段2：主渲染优先使用FFmpeg（统一编码出口）
            selected_codec_name = self._get_selected_codec_name()
            use_ffmpeg_primary = bool(self.ffmpeg_available)

            if use_ffmpeg_primary:
                msg = f"统一编排：主渲染使用FFmpeg，编码器={selected_codec_name}，目标码率={target_bitrate} kbps"
                self.update_status(msg)
                log(msg)
                success = self.create_video_with_ffmpeg(
                    images, output_path, duration, fps, out_w, out_h,
                    apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                    transition_frames, transition_type, watermark_opacity,
                    watermark_size, target_bitrate, log, effect_type_for_video
                )
                if success:
                    self._postprocess_video_output(output_path, fixed_layers, watermark_position, log, pipeline_start_time=task_start_time)
                    return True
                msg = "FFmpeg主渲染失败，自动降级到OpenCV编码链路继续处理"
                self.update_status(msg)
                log(msg)
            else:
                msg = f"使用OpenCV创建视频（码率由编码器自动决定）"
                self.update_status(msg)
                log(msg)

            selected_codec = self._resolve_cv_fourcc()
            if not selected_codec:
                msg = f"编码器不可用: {self._get_selected_codec_name()}"
                self.update_status(msg)
                log(msg)
                if self.ffmpeg_available:
                    msg = "尝试使用FFmpeg按指定编码器生成视频"
                    self.update_status(msg)
                    log(msg)
                    success = self.create_video_with_ffmpeg(
                        images, output_path, duration, fps, out_w, out_h,
                        apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                        transition_frames, transition_type, watermark_opacity,
                        watermark_size, target_bitrate, log, effect_type_for_video
                    )
                    if success:
                        self._postprocess_video_output(output_path, fixed_layers, watermark_position, log, pipeline_start_time=task_start_time)
                    return success
                return False

            fourcc = cv2.VideoWriter_fourcc(*selected_codec)
            video_writer = cv2.VideoWriter(output_path, fourcc, fps, (out_w, out_h))
            if video_writer.isOpened():
                msg = f"使用编码器: {selected_codec}"
                self.update_status(msg)
                log(msg)
            else:
                msg = f"编码器 {selected_codec} 创建失败"
                self.update_status(msg)
                log(msg)
                if self.ffmpeg_available:
                    msg = "尝试使用FFmpeg按指定编码器生成视频"
                    self.update_status(msg)
                    log(msg)
                    success = self.create_video_with_ffmpeg(
                        images, output_path, duration, fps, out_w, out_h,
                        apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                        transition_frames, transition_type, watermark_opacity,
                        watermark_size, target_bitrate, log, effect_type_for_video
                    )
                    if success:
                        self._postprocess_video_output(output_path, fixed_layers, watermark_position, log, pipeline_start_time=task_start_time)
                    return success
                return False
                
            # 计算视频总帧数 - 新逻辑：每张图片都占用相同的时间
            # 所有图片都占用 total_frames_per_img 帧，包括最后一张
            total_frames = total_images * total_frames_per_img

            msg = f"每张图片帧数: {total_frames_per_img} (静态: {display_frames_per_img}, 转场: {transition_frames}), 总帧数: {total_frames}, 实际视频时长: {total_frames/fps:.2f}秒"
            self.update_status(msg)
            log(msg)
            
            if hasattr(self, 'progress_var'):
                render_weight = 0.82 if self._has_postprocess_work(fixed_layers) else 1.0
                self.reset_progress(total_frames, render_weight=render_weight)
            frames_written = 0
            effect_enabled = (
                hasattr(self, 'use_video_effect')
                and self.use_video_effect.get()
                and effect_type_for_video != "无特效"
            )
            for img_index, img_path in enumerate(images):
                msg = f"处理图片 {img_index+1}/{total_images}: {os.path.basename(img_path)}"
                self.update_status(msg)
                log(msg)
                try:
                    current_img = self.safe_read_image(img_path)
                    if current_img is None:
                        msg = f"无法加载图片: {img_path}"
                        self.update_status(msg)
                        log(msg)
                        continue
                    msg = f"图片{img_index+1} shape: {current_img.shape}"
                    self.update_status(msg)
                    log(msg)
                    if resize_mode != "原始尺寸":
                        current_img = self.resize_image(current_img, out_w, out_h, resize_mode, maintain_aspect)
                        if current_img is None:
                            msg = f"图片resize失败: {img_path}"
                            self.update_status(msg)
                            log(msg)
                            continue
                    if follow_layers:
                        current_img = self.apply_image_watermark_layers(current_img, follow_layers, image_index=img_index)
                    current_img_processed = current_img

                    # 特效帧：按每张图的静态展示阶段应用，支持多图视频
                    if effect_enabled:
                        effect_frames = max(1, display_frames_per_img)
                        duration_sec = max(0.001, effect_frames / max(1, fps))
                        for frame_idx in range(effect_frames):
                            time_sec = frame_idx / max(1, fps)
                            frame = self.apply_single_image_effect(
                                current_img_processed,
                                effect_type_for_video,
                                time_sec,
                                duration_sec,
                                self.video_effect_intensity.get(),
                                self.video_effect_speed.get()
                            )
                            video_writer.write(frame)
                            frames_written += 1
                            self.update_progress(frames_written)
                    else:
                        # 写入静态显示帧
                        for _ in range(display_frames_per_img):
                            video_writer.write(current_img_processed)
                            frames_written += 1
                            self.update_progress(frames_written)

                    # 处理转场或补齐时间
                    if img_index < total_images - 1:
                        next_img_path = images[img_index + 1]
                        next_img = self.safe_read_image(next_img_path)
                        if next_img is None:
                            msg = f"无法加载下一张图片: {next_img_path}"
                            self.update_status(msg)
                            log(msg)
                            continue
                        if resize_mode != "原始尺寸":
                            next_img = self.resize_image(next_img, out_w, out_h, resize_mode, maintain_aspect)
                            if next_img is None:
                                msg = f"下一张图片resize失败: {next_img_path}"
                                self.update_status(msg)
                                log(msg)
                                continue
                        if follow_layers:
                            next_img = self.apply_image_watermark_layers(next_img, follow_layers, image_index=img_index + 1)
                        self.apply_transition(current_img_processed, next_img, video_writer, transition_frames, transition_type)
                        frames_written += transition_frames
                        self.update_progress(frames_written)
                    else:
                        # 最后一张图片：补齐剩余时间（相当于转场时间）
                        for _ in range(transition_frames):
                            video_writer.write(current_img_processed)
                            frames_written += 1
                            self.update_progress(frames_written)
                except Exception as e:
                    msg = f"处理图片 {img_path} 时出错: {str(e)}\n{traceback.format_exc()}"
                    self.update_status(msg)
                    log(msg)
                    continue
            video_writer.release()
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                if fixed_layers:
                    self.add_fixed_image_watermarks_to_video(output_path, fixed_layers)
                msg = f"视频创建完成! 编码器: {selected_codec}, 路径: {output_path}, 大小: {os.path.getsize(output_path)} 字节"
                self.update_status(msg)
                log(msg)
                return True
            else:
                msg = f"视频创建失败: 输出文件无效, 路径: {output_path}"
                self.update_status(msg)
                log(msg)
                return False
        except Exception as e:
            import traceback
            msg = f"创建视频时出错: {str(e)}\n{traceback.format_exc()}"
            self.update_status(msg)
            log(msg)
            if 'video_writer' in locals() and video_writer and video_writer.isOpened():
                video_writer.release()
            return False
    
    def create_video_turbo_enhanced(self, images, output_path, duration, fps, width=1920, height=1080,
                     apply_image_watermark=False, watermark_path=None, watermark_position="右下",
                     resize_mode="适应", maintain_aspect=True, transition_frames=15, transition_type="淡入淡出",
                     watermark_opacity=0.5, watermark_size=20, video_effect_type_override=None):
        """使用Turbo增强的视频创建方法 - 高性能优化版本
        
        主要优化：
        1. 并行图片处理
        2. Turbo缓存加速
        3. 优化的转场处理
        4. 批量帧写入
        """
        import traceback
        import time
        
        def log(msg):
            print(f"[Turbo] {msg}")
            self.update_status(f"[Turbo] {msg}")
            try:
                with open("video_create_turbo.log", "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            except Exception:
                pass
        
        if not images or not output_path:
            log("没有选择图片或输出路径")
            return False
        
        start_time = time.time()
        
        try:
            total_images = len(images)
            log(f"开始Turbo增强处理 {total_images} 张图片")
            effect_type_for_video = (
                video_effect_type_override
                if video_effect_type_override in VIDEO_EFFECTS
                else self.video_effect_type.get()
            )
            
            if total_images < 1:
                log("至少需要一张图片")
                return False
            
            # 计算帧数和转场设置
            total_time_per_img = duration
            total_frames_per_img = int(total_time_per_img * fps)
            
            # 根据转场设置计算帧数
            if transition_frames > 0 and transition_type != "无转场":
                transition_frames = min(transition_frames, total_frames_per_img // 3)
                display_frames_per_img = total_frames_per_img - transition_frames
                if display_frames_per_img < fps // 2:
                    display_frames_per_img = fps // 2
                    transition_frames = total_frames_per_img - display_frames_per_img
            else:
                # 无转场模式
                transition_frames = 0
                display_frames_per_img = total_frames_per_img
            
            static_time = display_frames_per_img / fps
            transition_time = transition_frames / fps
            total_video_duration = total_time_per_img * total_images
            
            log(f"每张图片总时长: {total_time_per_img}秒 (静态: {static_time:.2f}秒 + 转场: {transition_time:.2f}秒)")
            log(f"总视频时长: {total_video_duration:.2f}秒, 转场类型: {transition_type}")
            
            prepared_layers = self._prepare_image_watermark_layers() if apply_image_watermark else []
            follow_layers = [l for l in prepared_layers if not l.get("fixed")]
            fixed_layers = [l for l in prepared_layers if l.get("fixed")]

            path_index_map = {p: i for i, p in enumerate(images)}

            # Turbo并行预加载所有图片
            log("开始Turbo并行图片预加载...")
            preload_start = time.time()
            
            # 使用Turbo加速器并行加载图片
            if self.turbo_accelerator and self.turbo_accelerator.enabled:
                processed_images = self.turbo_accelerator.parallel_image_processing(
                    images, 
                    self._turbo_preprocess_image,
                    width, height, resize_mode, maintain_aspect,
                    apply_image_watermark, follow_layers, watermark_position, 
                    watermark_opacity, watermark_size, path_index_map
                )
            else:
                # 回退到串行处理
                processed_images = []
                for img_path in images:
                    if not self._wait_for_processing_control():
                        raise InterruptedError("用户取消处理")
                    processed_img = self._turbo_preprocess_image(
                        img_path, width, height, resize_mode, maintain_aspect,
                        apply_image_watermark, follow_layers, watermark_position,
                        watermark_opacity, watermark_size, path_index_map
                    )
                    processed_images.append(processed_img)
            
            # 过滤无效图片，同时保留路径与预处理帧的一一对应关系
            valid_pairs = [
                (images[idx], img)
                for idx, img in enumerate(processed_images)
                if img is not None
            ]
            valid_image_paths = [pair[0] for pair in valid_pairs]
            valid_images = [pair[1] for pair in valid_pairs]
            if len(valid_images) != total_images:
                log(f"警告: {total_images - len(valid_images)} 张图片加载失败")
                total_images = len(valid_images)
                if total_images == 0:
                    log("所有图片都加载失败")
                    return False
            
            preload_time = time.time() - preload_start
            log(f"Turbo预加载完成: {preload_time:.2f}秒, 成功加载 {len(valid_images)} 张图片")
            
            # 创建视频写入器
            if resize_mode == "原始尺寸" and valid_images:
                h, w = valid_images[0].shape[:2]
                out_w, out_h = w, h
            else:
                out_w, out_h = width, height
            
            # 阶段2：主渲染优先使用FFmpeg（统一编码出口）
            if self.ffmpeg_available:
                log(f"统一编排：主渲染使用FFmpeg，编码器={self._get_selected_codec_name()}")
                target_bitrate = self.bitrate.get() if hasattr(self, 'bitrate') else 5000
                success = self.create_video_with_ffmpeg(
                    valid_image_paths, output_path, duration, fps, out_w, out_h,
                    apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                    transition_frames, transition_type, watermark_opacity,
                    watermark_size, target_bitrate, log, effect_type_for_video,
                    preprocessed_images=valid_images
                )
                if success:
                    self._postprocess_video_output(output_path, fixed_layers, watermark_position, log, pipeline_start_time=start_time)
                    return True
                log("FFmpeg主渲染失败，自动降级到OpenCV编码链路继续处理")

            # 使用用户选择的编码器
            selected_codec = self._resolve_cv_fourcc()
            if not selected_codec:
                log(f"编码器不可用: {self._get_selected_codec_name()}")
                if self.ffmpeg_available:
                    log("尝试使用FFmpeg按指定编码器生成视频")
                    target_bitrate = self.bitrate.get() if hasattr(self, 'bitrate') else 5000
                    success = self.create_video_with_ffmpeg(
                        valid_image_paths, output_path, duration, fps, out_w, out_h,
                        apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                        transition_frames, transition_type, watermark_opacity,
                        watermark_size, target_bitrate, log, effect_type_for_video,
                        preprocessed_images=valid_images
                    )
                    if success:
                        self._postprocess_video_output(output_path, fixed_layers, watermark_position, log, pipeline_start_time=start_time)
                    return success
                return False

            fourcc = cv2.VideoWriter_fourcc(*selected_codec)
            video_writer = cv2.VideoWriter(output_path, fourcc, fps, (out_w, out_h))
            if video_writer.isOpened():
                log(f"使用编码器: {selected_codec}")
            else:
                log(f"编码器 {selected_codec} 创建失败")
                if self.ffmpeg_available:
                    log("尝试使用FFmpeg按指定编码器生成视频")
                    target_bitrate = self.bitrate.get() if hasattr(self, 'bitrate') else 5000
                    success = self.create_video_with_ffmpeg(
                        valid_image_paths, output_path, duration, fps, out_w, out_h,
                        apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                        transition_frames, transition_type, watermark_opacity,
                        watermark_size, target_bitrate, log, effect_type_for_video,
                        preprocessed_images=valid_images
                    )
                    if success:
                        self._postprocess_video_output(output_path, fixed_layers, watermark_position, log, pipeline_start_time=start_time)
                    return success
                return False
            
            # 计算总帧数
            total_frames = total_images * total_frames_per_img
            log(f"开始视频生成: 总帧数 {total_frames}")
            
            if hasattr(self, 'progress_var'):
                render_weight = 0.82 if self._has_postprocess_work(fixed_layers) else 1.0
                self.reset_progress(total_frames, render_weight=render_weight)
            
            frames_written = 0
            encoding_start = time.time()
            effect_enabled = (
                hasattr(self, 'use_video_effect')
                and self.use_video_effect.get()
                and effect_type_for_video != "无特效"
            )
            
            # 高效帧写入循环
            for img_index, current_img in enumerate(valid_images):
                if not self._wait_for_processing_control():
                    raise InterruptedError("用户取消处理")
                log(f"处理图片 {img_index+1}/{total_images}")

                # 特效帧：按每张图的静态展示阶段应用，支持多图视频
                if effect_enabled:
                    effect_frames = max(1, display_frames_per_img)
                    duration_sec = max(0.001, effect_frames / max(1, fps))
                    for frame_idx in range(effect_frames):
                        if not self._wait_for_processing_control():
                            raise InterruptedError("用户取消处理")
                        time_sec = frame_idx / max(1, fps)
                        frame = self.apply_single_image_effect(
                            current_img,
                            effect_type_for_video,
                            time_sec,
                            duration_sec,
                            self.video_effect_intensity.get(),
                            self.video_effect_speed.get()
                        )
                        video_writer.write(frame)
                        frames_written += 1
                        if frames_written % 30 == 0:
                            self.update_progress(frames_written)
                    self.update_progress(frames_written)
                else:
                    # 批量写入静态帧
                    for _ in range(display_frames_per_img):
                        if not self._wait_for_processing_control():
                            raise InterruptedError("用户取消处理")
                        video_writer.write(current_img)
                        frames_written += 1
                        if frames_written % 30 == 0:  # 每30帧更新一次进度
                            self.update_progress(frames_written)
                
                # 处理转场（当前视频统一使用同一种转场）
                if transition_frames > 0 and img_index < total_images - 1:
                    next_img = valid_images[img_index + 1]
                    written_transition = self._turbo_write_transition_frames(
                        video_writer, current_img, next_img, 
                        transition_frames, transition_type
                    )
                    frames_written += written_transition
                    if written_transition < transition_frames and self.cancel_requested:
                        raise InterruptedError("用户取消处理")
                    self.update_progress(frames_written)
                elif transition_frames > 0:  # 最后一张图片补齐时间
                    for _ in range(transition_frames):
                        if not self._wait_for_processing_control():
                            raise InterruptedError("用户取消处理")
                        video_writer.write(current_img)
                        frames_written += 1
                    self.update_progress(frames_written)
            
            video_writer.release()
            encoding_time = time.time() - encoding_start
            total_time = time.time() - start_time
            
            # 验证输出文件
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                file_size = os.path.getsize(output_path)
                image_speed = (total_images / total_time) if total_time > 0 else 0.0
                frame_speed = (frames_written / encoding_time) if encoding_time > 0 else 0.0
                log(f"Turbo视频创建成功!")
                log(f"编码器: {selected_codec}, 文件大小: {file_size} 字节")
                log(f"性能统计: 预加载 {preload_time:.2f}秒, 编码 {encoding_time:.2f}秒, 总耗时 {total_time:.2f}秒")
                log(f"处理速度: {image_speed:.2f} 张/秒, {frame_speed:.1f} 帧/秒")
                
                # 更新Turbo统计
                if self.turbo_accelerator:
                    self.turbo_accelerator.stats['videos_created'] += 1
                
                self._postprocess_video_output(output_path, fixed_layers, watermark_position, log, pipeline_start_time=start_time)
                
                return True
            else:
                log("视频创建失败: 输出文件无效")
                return False
                
        except InterruptedError:
            if 'video_writer' in locals() and video_writer and video_writer.isOpened():
                video_writer.release()
            log("已取消当前视频生成")
            return False
        except Exception as e:
            import traceback
            error_msg = f"Turbo增强视频创建出错: {str(e)}\n{traceback.format_exc()}"
            log(error_msg)
            if 'video_writer' in locals() and video_writer and video_writer.isOpened():
                video_writer.release()
            return False
    
    def _turbo_preprocess_image(self, img_path, width, height, resize_mode, maintain_aspect,
                               apply_watermark, watermark_layers, watermark_position,
                               watermark_opacity, watermark_size, path_index_map=None):
        """
Turbo图片预处理 - 并行优化版本
        
        包括: 加载 -> resize -> 水印
        """
        try:
            # 使用Turbo加速读取
            img = self.safe_read_image(img_path)
            if img is None:
                return None
            
            # resize处理
            if resize_mode != "原始尺寸":
                img = self.resize_image(img, width, height, resize_mode, maintain_aspect)
                if img is None:
                    return None
            
            # 水印处理
            if apply_watermark and watermark_layers:
                try:
                    image_index = 0
                    if path_index_map and img_path in path_index_map:
                        image_index = path_index_map[img_path]
                    img = self.apply_image_watermark_layers(img, watermark_layers, image_index=image_index)
                except Exception as e:
                    print(f"水印处理失败: {str(e)}")
            
            return img
            
        except Exception as e:
            print(f"Turbo图片预处理失败 {img_path}: {str(e)}")
            return None
    
    def _turbo_write_transition_frames(self, video_writer, img1, img2, num_frames, transition_type):
        """
        Turbo转场帧写入 - 使用高性能转场引擎
        
        使用转场引擎批量生成帧后写入，提升性能和效果
        """
        frames_written = 0
        try:
            if num_frames <= 0 or transition_type == "无转场":
                return 0
            
            h, w = img1.shape[:2]
            
            # 确保两张图片尺寸相同
            if img1.shape != img2.shape:
                img2 = cv2.resize(img2, (w, h))
            
            # 使用转场引擎生成转场帧
            if self.transition_engine:
                try:
                    # 使用高性能转场引擎批量生成所有转场帧
                    transition_frames_list = self.transition_engine.generate_transition_frames(
                        img1, img2, transition_type, num_frames, use_cache=True
                    )
                    
                    # 批量写入帧
                    for frame in transition_frames_list:
                        if not self._wait_for_processing_control():
                            return frames_written
                        if frame is not None and frame.shape[0] > 0 and frame.shape[1] > 0:
                            video_writer.write(frame)
                        else:
                            # 帧无效，使用原图
                            video_writer.write(img1)
                        frames_written += 1
                    
                    return frames_written
                    
                except Exception as e:
                    print(f"[WARN] 转场引擎生成失败: {e}, 回退到基本实现")
            
            # 回退方案：使用基本的淡入淡出
            print(f"[WARN] 转场引擎不可用，使用基本淡入淡出")
            for i in range(num_frames):
                if not self._wait_for_processing_control():
                    return frames_written
                alpha = i / (num_frames - 1) if num_frames > 1 else 1
                frame = cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)
                video_writer.write(frame)
                frames_written += 1
                
        except Exception as e:
            print(f"Turbo转场帧写入失败: {str(e)}")
            # 如果转场失败，用静态帧填充
            for _ in range(num_frames):
                if not self._wait_for_processing_control():
                    break
                video_writer.write(img1)
                frames_written += 1
        return frames_written

    def add_audio_with_ffmpeg(self, video_path, audio_file, volume=0.5):
        """使用ffmpeg直接添加背景音乐"""
        try:
            # 标准化路径
            video_path = self.normalize_path(video_path)
            audio_file = self.normalize_path(audio_file)
            
            # 创建临时输出文件
            temp_output = self._build_temp_output_path(video_path, "temp")
            
            # 构建ffmpeg命令 - 简化版，更可靠
            volume_str = f"{volume:.2f}"
            loop_audio = True
            if hasattr(self, "loop_bgm"):
                loop_audio = bool(self.loop_bgm.get())
            cmd = [
                getattr(self, "ffmpeg_executable", None) or "ffmpeg", "-y",  # 覆盖输出文件
                "-i", video_path,  # 输入视频
            ]
            if loop_audio:
                cmd += ["-stream_loop", "-1"]  # 循环音频
            cmd += [
                "-i", audio_file,  # 输入音频
                "-filter_complex", f"[1:a]volume={volume_str}[a]",  # 设置音量
                "-map", "0:v", "-map", "[a]",  # 使用原视频和处理后的音频
                "-c:v", "copy",  # 复制视频流
                "-shortest",  # 使用最短流的长度（视频）
                temp_output
            ]
            
            # 打印完整命令方便调试
            cmd_str = " ".join(str(c) for c in cmd)
            self.update_status(f"执行命令: {cmd_str}")
            
            # 执行命令并获取详细错误信息（含超时与重试）
            result = self._run_process_with_retry(
                cmd,
                stage="BGM",
                timeout_sec=240,
                retries=2,
                log_func=lambda m: self.update_status(m),
            )
            if result is None:
                self.update_status("ffmpeg执行失败：无可用结果")
                return False
            stderr_output = result.stderr.decode('utf-8', errors='ignore')
            
            if result.returncode != 0:
                self.update_status(f"ffmpeg命令执行失败，错误码: {result.returncode}")
                self.update_status(f"错误信息: {stderr_output}")
                return False
            
            # 检查输出文件
            if os.path.exists(temp_output) and os.path.getsize(temp_output) > 1000:
                # 成功生成，替换原文件
                if not self._safe_replace_file(temp_output, video_path):
                    self.update_status("替换文件失败: 无法用新文件覆盖旧视频")
                    return False
                
                self.update_status(f"成功使用FFmpeg添加背景音乐")
                return True
            else:
                self.update_status("FFmpeg生成的文件无效")
                if os.path.exists(temp_output):
                    self.update_status(f"临时文件大小: {os.path.getsize(temp_output)} 字节")
                return False
        except Exception as e:
            self.update_status(f"使用FFmpeg添加音频时出错: {str(e)}")
            import traceback
            self.update_status(traceback.format_exc())
            return False

    def verify_watermark_file(self):
        """验证水印文件是否有效"""
        try:
            if not self.use_watermark.get():
                return True
            
            watermark_path = self.watermark_path.get()
            
            if not watermark_path or not os.path.exists(watermark_path):
                self.update_status("水印文件路径无效")
                return False
            
            # 验证视频水印
            try:
                # 简单验证视频文件是否可以打开
                cap = cv2.VideoCapture(watermark_path)
                if not cap.isOpened():
                    self.update_status("无法读取水印视频")
                    cap.release()
                    return False
                cap.release()
                return True
            except Exception as e:
                self.update_status(f"水印视频验证失败: {str(e)}")
                return False
        
        except Exception as e:
            self.update_status(f"验证水印文件时出错: {str(e)}")
            return False
    
    def verify_bgm_directory(self):
        """验证BGM目录是否有效"""
        try:
            if not self.use_bgm.get():
                return True
            
            bgm_dir = self.bgm_dir.get()
            
            if not bgm_dir or not os.path.exists(bgm_dir):
                self.update_status("BGM目录路径无效")
                return False
            
            # 检查目录中是否有音频文件
            audio_files = self.get_audio_files(bgm_dir)
            if not audio_files:
                self.update_status("BGM目录中没有找到音频文件")
                return False
            
            return True
        
        except Exception as e:
            self.update_status(f"验证BGM目录时出错: {str(e)}")
            return False
    
    def get_audio_files(self, directory):
        """获取目录中的音频文件列表"""
        audio_files = []
        
        try:
            for file in os.listdir(directory):
                if file.lower().endswith(('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac')):
                    audio_files.append(os.path.join(directory, file))
        except Exception as e:
            self.update_status(f"获取音频文件列表时出错: {str(e)}")
        
        return audio_files
    
    def get_watermark_files(self, directory):
        """获取目录中的水印文件列表（支持图片和视频）"""
        watermark_files = []
        
        try:
            # 仅视频水印
            extensions = ('.mov', '.mp4', '.avi', '.mkv')
            
            # 遍历目录获取文件
            for file in os.listdir(directory):
                if file.lower().endswith(extensions):
                    watermark_files.append(os.path.join(directory, file))
            
            # 按文件名排序
            watermark_files.sort()
            
        except Exception as e:
            self.update_status(f"获取水印文件列表时出错: {str(e)}")
        
        return watermark_files
            
    def apply_config_from_dict(self, config_dict):
        """从字典直接应用配置"""
        try:
            # 设置各个控件的值
            self.input_dir.set(config_dict.get("input_dir", ""))
            self.output_dir.set(config_dict.get("output_dir", ""))
            self.num_images.set(str(config_dict.get("num_images", 10)))
            self.duration.set(str(config_dict.get("duration", 2.0)))
            self.total_duration.set(str(config_dict.get("total_duration", 0.0)))
            self.fps.set(str(config_dict.get("fps", 30)))
            self.video_count.set(str(config_dict.get("video_count", 1)))
            self.video_format.set(config_dict.get("video_format", "mp4"))
            self.width.set(str(config_dict.get("width", 1280)))
            self.height.set(str(config_dict.get("height", 720)))
            self.keep_aspect_ratio.set(config_dict.get("keep_aspect_ratio", True))
            self.use_transition.set(config_dict.get("use_transition", True))
            self.transition_type.set(config_dict.get("transition_type", "淡入淡出"))
            self.random_transition.set(config_dict.get("random_transition", False))
            preset_enabled = config_dict.get("enabled_transitions")
            if isinstance(preset_enabled, list):
                valid_transitions = [t for t in preset_enabled if t in GUI_TRANSITIONS]
                self.enabled_transitions = valid_transitions or DEFAULT_ENABLED_TRANSITIONS.copy()
            self.use_video_effect.set(config_dict.get("use_video_effect", False))
            self.video_effect_type.set(config_dict.get("video_effect_type", "镜头呼吸"))
            self.random_video_effect.set(config_dict.get("random_video_effect", False))
            preset_effects = config_dict.get("enabled_video_effects")
            if isinstance(preset_effects, list):
                valid_effects = [e for e in preset_effects if e in VIDEO_EFFECTS and e != "无特效"]
                self.enabled_video_effects = valid_effects or [e for e in VIDEO_EFFECTS if e != "无特效"]
            self.video_effect_intensity.set(config_dict.get("video_effect_intensity", 100.0))
            self.video_effect_speed.set(config_dict.get("video_effect_speed", 1.0))
            self.effect_preview_time.set(config_dict.get("effect_preview_time", 1.0))
            self.use_bgm.set(config_dict.get("use_bgm", False))
            self.bgm_dir.set(config_dict.get("bgm_dir", ""))
            self._bgm_files = [
                str(path) for path in (config_dict.get("bgm_files") or [])
                if isinstance(path, str) and str(path).strip()
            ]
            self.random_bgm.set(config_dict.get("random_bgm", True))
            self.bgm_volume.set(config_dict.get("bgm_volume", 0.5))
            self.loop_bgm.set(config_dict.get("loop_bgm", True))
            self.codec_var.set(config_dict.get("codec", "H264"))
            self.use_watermark.set(config_dict.get("use_watermark", False))
            self.watermark_path.set(config_dict.get("watermark_path", ""))
            self.watermark_type.set("视频")
            self.watermark_position.set(config_dict.get("watermark_position", "右下"))
            self.watermark_match_method.set(config_dict.get("watermark_match_method", "循环"))
            self.watermark_audio.set(config_dict.get("watermark_audio", "使用BGM"))
            self.watermark_mode.set(config_dict.get("watermark_mode", "单文件"))  # 添加水印模式
            self.watermark_layers = config_dict.get("watermark_layers", [])
            self.use_date_prefix.set(config_dict.get("use_date_prefix", True))
            self.use_first_image_name.set(config_dict.get("use_first_image_name", False))
            self.custom_prefix.set(config_dict.get("custom_prefix", "video"))
            self.bitrate.set(str(config_dict.get("bitrate", 5000)))
            
            # 更新UI状态
            self.update_ui_state()
            self.update_status("已应用预设配置")
            self._load_watermark_layers_to_ui()
        except Exception as e:
            self.update_status(f"应用预设配置失败: {str(e)}")

    def get_enabled_transitions(self):
        """获取当前启用的转场效果列表"""
        # 检查是否有override_transitions属性
        if hasattr(self, 'override_transitions') and self.override_transitions:
            return self.override_transitions
            
        # 否则检查enabled_transitions
        if hasattr(self, 'enabled_transitions'):
            transitions = self.enabled_transitions
            # 新版结构：list[str]
            if isinstance(transitions, list):
                enabled = [t for t in transitions if t in GUI_TRANSITIONS]
                if enabled:
                    return enabled
            # 兼容旧版结构：dict[str, tk.BooleanVar]
            elif isinstance(transitions, dict):
                enabled = []
                for trans, var in transitions.items():
                    try:
                        if var.get():
                            enabled.append(trans)
                    except Exception:
                        continue
                enabled = [t for t in enabled if t in GUI_TRANSITIONS]
                if enabled:
                    return enabled
                
        # 默认返回淡入淡出
        return ["淡入淡出"]

    def _build_random_transition_plan(self, video_count):
        """为多个视频生成随机转场计划，尽量避免连续重复。"""
        count = max(0, int(video_count))
        if count <= 0:
            return []

        enabled_pool = self.get_enabled_transitions()
        pool = [t for t in enabled_pool if t in GUI_TRANSITIONS]
        if not pool:
            pool = ["淡入淡出"]

        # 只有1个效果时只能重复
        if len(pool) == 1:
            return [pool[0]] * count

        plan = []
        last_transition = None
        while len(plan) < count:
            batch = pool.copy()
            random.shuffle(batch)
            # 避免跨批次首尾重复
            if last_transition is not None and batch and batch[0] == last_transition and len(batch) > 1:
                batch[0], batch[1] = batch[1], batch[0]
            for transition in batch:
                if len(plan) >= count:
                    break
                if last_transition is not None and transition == last_transition:
                    continue
                plan.append(transition)
                last_transition = transition

            # 保险：极端情况下补齐
            if len(plan) < count:
                fallback = next((t for t in pool if t != last_transition), pool[0])
                plan.append(fallback)
                last_transition = fallback

        return plan

    def get_enabled_video_effects(self):
        """获取当前启用的随机特效池。"""
        if hasattr(self, "enabled_video_effects") and isinstance(self.enabled_video_effects, list):
            valid = [e for e in self.enabled_video_effects if e in VIDEO_EFFECTS and e != "无特效"]
            if valid:
                return valid
        return [e for e in VIDEO_EFFECTS if e != "无特效"]

    def reset_progress(self, total_frames, render_weight=1.0):
        """重置进度条"""
        if hasattr(self, 'progress_var'):
            self.progress_var.set(0)
        if hasattr(self, 'progress_info_var'):
            self.progress_info_var.set("进度: 0%")
        if hasattr(self, 'speed_info_var'):
            self.speed_info_var.set("速度: 0.0 张/秒")
        self._speed_start_time = time.time()
        self._speed_processed = 0
        self._speed_last_value = 0
        self.total_frames = total_frames
        self._progress_render_weight = max(0.1, min(1.0, float(render_weight)))
        self._progress_last_percent = -1
        self._progress_phase_label = "渲染中"

    def _set_absolute_progress(self, percent, info_text=None, force=False):
        """按百分比直接设置当前视频进度（用于后处理阶段）。"""
        try:
            percent_int = max(0, min(100, int(percent)))
        except Exception:
            return

        now = time.time()
        flush_due = (now - getattr(self, "_progress_last_ui_ts", 0.0)) >= getattr(self, "_progress_ui_min_interval", 0.08)
        percent_changed = (percent_int != getattr(self, "_progress_last_percent", -1))
        if not force and not (percent_changed and flush_due):
            return

        self._progress_last_ui_ts = now
        self._progress_last_percent = percent_int

        if hasattr(self, 'progress_var'):
            self.progress_var.set(percent_int)
        if hasattr(self, 'progress_info_var'):
            if info_text:
                self.progress_info_var.set(info_text)
            else:
                phase = str(getattr(self, "_progress_phase_label", "渲染中"))
                self.progress_info_var.set(f"任务进度: {percent_int}%（{phase}）")
        self._update_overall_progress(percent_int)
        if hasattr(self, 'parent'):
            self.parent.update_idletasks()

    def reset_overall_progress(self, total_videos):
        """重置总进度条"""
        self.overall_total_videos = max(1, int(total_videos)) if total_videos else 0
        self.current_video_index = 0
        if hasattr(self, 'overall_progress_var'):
            self.overall_progress_var.set(0)
        if hasattr(self, 'overall_progress_info_var'):
            self.overall_progress_info_var.set("总进度: 0%")

    def _wait_for_processing_control(self, sleep_sec=0.03):
        """处理暂停/取消控制，返回False表示应立即中断。"""
        if getattr(self, "cancel_requested", False):
            return False

        pause_event = getattr(self, "pause_event", None)
        if pause_event is None:
            return True

        while not pause_event.is_set():
            if getattr(self, "cancel_requested", False):
                return False
            time.sleep(max(0.01, float(sleep_sec)))

        return not getattr(self, "cancel_requested", False)

    def resize_image(self, img, target_w, target_h, mode="适应", keep_aspect=True):
        """通用图片缩放方法，支持适应、拉伸、填充"""
        if img is None:
            return None
        h, w = img.shape[:2]
        if mode == "适应":
            return self.resize_with_aspect_ratio(img, target_w, target_h)
        elif mode == "拉伸":
            return cv2.resize(img, (target_w, target_h))
        elif mode == "填充":
            # 等比缩放后裁剪
            scale = max(target_w / w, target_h / h)
            new_w, new_h = int(w * scale), int(h * scale)
            resized = cv2.resize(img, (new_w, new_h))
            x0 = (new_w - target_w) // 2
            y0 = (new_h - target_h) // 2
            return resized[y0:y0+target_h, x0:x0+target_w]
        else:
            # 默认等比适应
            return self.resize_with_aspect_ratio(img, target_w, target_h)

    def _ensure_even_frame(self, frame):
        """确保帧尺寸为偶数，满足H.264编码要求"""
        if frame is None:
            return None
        h, w = frame.shape[:2]
        pad_w = w % 2
        pad_h = h % 2
        if pad_w == 0 and pad_h == 0:
            return frame
        return cv2.copyMakeBorder(
            frame,
            0, pad_h, 0, pad_w,
            cv2.BORDER_CONSTANT,
            value=(0, 0, 0)
        )

    def _log_pipeline_stage(self, stage, message, log_func=None):
        """统一流水线日志输出（阶段5：可观测性）。"""
        line = f"[PIPELINE][{stage}] {message}"
        if log_func:
            log_func(line)
        else:
            print(line)
        try:
            with open(self._pipeline_log_file, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {line}\n")
        except Exception:
            pass

    def _run_process_with_retry(self, cmd, stage="PROC", timeout_sec=300, retries=1, log_func=None):
        """子进程执行守护：超时、重试、统一日志。"""
        attempts = max(1, int(retries))
        last_result = None
        for attempt in range(attempts):
            try:
                if log_func:
                    log_func(f"[{stage}] 执行命令（尝试 {attempt + 1}/{attempts}）")
                last_result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    startupinfo=self.startupinfo if hasattr(self, "startupinfo") else None,
                    timeout=max(10, int(timeout_sec)),
                )
                if last_result.returncode == 0:
                    return last_result
                if log_func:
                    err = (last_result.stderr or b"").decode("utf-8", errors="ignore")
                    log_func(f"[{stage}] 命令失败: code={last_result.returncode}, err={err[:220]}")
            except subprocess.TimeoutExpired:
                if log_func:
                    log_func(f"[{stage}] 命令超时: {timeout_sec}s")
            except Exception as e:
                if log_func:
                    log_func(f"[{stage}] 命令异常: {str(e)}")
        return last_result

    @staticmethod
    def _safe_replace_file(src_path, dst_path):
        """安全替换文件，优先原子替换，失败回退复制。"""
        if not os.path.exists(src_path):
            return False
        try:
            if os.path.exists(dst_path):
                os.remove(dst_path)
            os.replace(src_path, dst_path)
            return True
        except Exception:
            try:
                shutil.copy2(src_path, dst_path)
                os.remove(src_path)
                return True
            except Exception:
                return False

    def _probe_video_meta(self, video_path):
        """读取视频元信息。"""
        def _safe_float(value, default=0.0):
            try:
                return float(value)
            except Exception:
                return float(default)

        def _safe_int(value, default=0):
            try:
                return int(float(value))
            except Exception:
                return int(default)

        def _parse_fps(value):
            text = str(value or "").strip()
            if not text or text in ("0/0", "N/A"):
                return 0.0
            if "/" in text:
                num_text, den_text = text.split("/", 1)
                num = _safe_float(num_text, 0.0)
                den = _safe_float(den_text, 0.0)
                if den > 0:
                    return num / den
                return 0.0
            return _safe_float(text, 0.0)

        # 1) 优先用 ffprobe，避免 OpenCV 在部分编码/容器上返回异常 FPS（常见导致时长异常）
        ffprobe_path = getattr(self, "ffprobe_executable", None) or resolve_ffprobe_path(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            getattr(self, "ffmpeg_executable", None),
        )
        try:
            if not ffprobe_path:
                raise FileNotFoundError("ffprobe unavailable")
            cmd = [
                ffprobe_path,
                "-v", "error",
                "-show_entries", "format=duration:stream=width,height,avg_frame_rate,r_frame_rate,nb_frames",
                "-select_streams", "v:0",
                "-of", "json",
                video_path,
            ]
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=self.startupinfo if hasattr(self, "startupinfo") else None,
                timeout=20,
            )
            if result.returncode == 0:
                payload = json.loads(result.stdout.decode("utf-8", errors="ignore") or "{}")
                streams = payload.get("streams") or []
                if streams:
                    stream = streams[0]
                    width = _safe_int(stream.get("width"), 0)
                    height = _safe_int(stream.get("height"), 0)
                    fps = _parse_fps(stream.get("avg_frame_rate"))
                    if fps <= 0:
                        fps = _parse_fps(stream.get("r_frame_rate"))
                    frames = _safe_int(stream.get("nb_frames"), 0)
                    duration = _safe_float((payload.get("format") or {}).get("duration"), 0.0)

                    if duration <= 0 and fps > 0 and frames > 0:
                        duration = frames / fps
                    if frames <= 0 and fps > 0 and duration > 0:
                        frames = int(round(fps * duration))

                    if width > 0 and height > 0:
                        return {
                            "width": width,
                            "height": height,
                            "fps": fps,
                            "frames": max(0, int(frames)),
                            "duration": max(0.0, float(duration)),
                        }
        except Exception:
            pass

        # 2) 回退 OpenCV
        cap = cv2.VideoCapture(video_path)
        try:
            if not cap.isOpened():
                return None
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            duration = (frames / fps) if fps > 0 else 0.0

            # OpenCV 读取到异常 FPS 时，回落到用户设置值，避免后处理重编码后时长被拉长
            if fps <= 1.0 or fps > 240.0:
                try:
                    fallback_fps = float(self.fps.get())
                    if fallback_fps > 0:
                        fps = fallback_fps
                except Exception:
                    pass

            return {
                "width": width,
                "height": height,
                "fps": fps,
                "frames": frames,
                "duration": duration,
            }
        finally:
            cap.release()

    def _calc_overlay_geometry(self, main_w, main_h, wm_w, wm_h, size_mode, scale_value, position):
        """计算叠加尺寸与位置。"""
        wm_ratio = wm_w / max(1, wm_h)
        main_ratio = main_w / max(1, main_h)

        if size_mode == "自适应覆盖":
            if wm_ratio > main_ratio:
                target_h = main_h
                target_w = int(target_h * wm_ratio)
            else:
                target_w = main_w
                target_h = int(target_w / wm_ratio)
        elif size_mode == "完全覆盖":
            target_w, target_h = main_w, main_h
        else:
            target_w = max(1, int(main_w * (float(scale_value) / 100.0)))
            target_h = max(1, int(target_w / wm_ratio))

        margin = 10 if size_mode == "固定比例" else 0
        if position == "左上":
            x_pos, y_pos = margin, margin
        elif position == "右上":
            x_pos, y_pos = main_w - target_w - margin, margin
        elif position == "左下":
            x_pos, y_pos = margin, main_h - target_h - margin
        elif position == "中心":
            x_pos, y_pos = (main_w - target_w) // 2, (main_h - target_h) // 2
        else:
            x_pos, y_pos = main_w - target_w - margin, main_h - target_h - margin

        return target_w, target_h, x_pos, y_pos

    def _select_video_watermark_file(self, log_func=None):
        """解析当前配置中的视频水印文件。"""
        if not (self.use_watermark.get() and self.watermark_type.get() == "视频"):
            return None

        watermark_base_path = self.watermark_path.get()
        if not watermark_base_path or not os.path.exists(watermark_base_path):
            return None

        watermark_mode = getattr(self, 'watermark_mode', None)
        watermark_mode_value = watermark_mode.get() if watermark_mode else "单文件"

        if watermark_mode_value == "文件夹" and os.path.isdir(watermark_base_path):
            watermark_files = self.get_watermark_files(watermark_base_path)
            if not watermark_files:
                return None
            video_idx = getattr(self, '_current_video_index', 0)
            selected = watermark_files[video_idx % len(watermark_files)]
            self._log_pipeline_stage("POST-CHECK", f"选择文件夹水印: {os.path.basename(selected)}", log_func)
            return selected

        if os.path.isfile(watermark_base_path):
            self._log_pipeline_stage("POST-CHECK", f"使用单文件水印: {os.path.basename(watermark_base_path)}", log_func)
            return watermark_base_path
        return None

    def _resolve_bgm_candidates(self):
        """返回本次可用的BGM候选：优先使用素材库显式选定的文件，否则扫描音频目录。"""
        explicit = [
            path for path in getattr(self, "_bgm_files", None) or []
            if os.path.isfile(path)
        ]
        if explicit:
            return sorted(explicit)
        bgm_dir = self.bgm_dir.get()
        if not bgm_dir or not os.path.exists(bgm_dir):
            return []
        return sorted(self.get_audio_files(bgm_dir))

    def _select_bgm_file(self):
        """获取本次应使用的BGM文件。"""
        if not self.use_bgm.get():
            return None
        audio_strategy = self.watermark_audio.get() if hasattr(self, "watermark_audio") else "使用BGM"
        if audio_strategy not in ("使用BGM", "两者混合"):
            return None
        bgm_files = self._resolve_bgm_candidates()
        if not bgm_files:
            return None
        if self.random_bgm.get():
            return random.choice(bgm_files)
        return bgm_files[0]

    def _has_postprocess_work(self, fixed_layers=None):
        """判断是否存在渲染后处理任务（固定图层/视频水印/BGM）。"""
        has_fixed = bool(fixed_layers)
        has_video_wm = bool(
            self.use_watermark.get()
            and self.watermark_type.get() == "视频"
            and self.watermark_path.get()
            and os.path.exists(self.watermark_path.get())
        )
        has_bgm = bool(
            self.use_bgm.get()
            and (
                bool(getattr(self, "_bgm_files", None))
                or (
                    self.bgm_dir.get()
                    and os.path.exists(self.bgm_dir.get())
                )
            )
        )
        return has_fixed or has_video_wm or has_bgm

    def _get_video_watermark_blend_mode(self):
        """获取视频水印混合模式。"""
        blend_mode_var = getattr(self, 'watermark_blend_mode', None)
        return blend_mode_var.get() if blend_mode_var else "正常"

    def _get_video_watermark_alpha(self, blend_mode):
        """根据混合模式返回更合理的默认强度。"""
        alpha_map = {
            "正常": 0.50,
            "滤色": 1.00,
            "叠加": 0.90,
            "正片叠底": 0.85,
            "变亮": 0.90,
            "变暗": 0.90,
            "相加": 0.95,
        }
        return float(alpha_map.get(blend_mode, 0.50))

    def _get_ffmpeg_blend_mode(self, blend_mode):
        """将UI混合模式映射为FFmpeg blend滤镜模式。"""
        mapping = {
            "滤色": "screen",
            "叠加": "overlay",
            "正片叠底": "multiply",
            "变亮": "lighten",
            "变暗": "darken",
            "相加": "addition",
        }
        return mapping.get(str(blend_mode), None)

    def _collect_fixed_layer_specs_for_ffmpeg(self):
        """收集可由FFmpeg一次性处理的固定图片图层。"""
        specs = []
        for layer in self._normalize_watermark_layers():
            if not layer.get("enabled", True):
                continue
            if layer.get("type", "图片") != "图片":
                continue
            if not bool(layer.get("fixed", False)):
                continue
            path = layer.get("path", "")
            if not path:
                continue

            selected_path = None
            if os.path.isdir(path):
                files = self._get_image_files_in_dir(path)
                if files:
                    files.sort()
                    if bool(layer.get("folder_random_single", False)):
                        selected_path = random.choice(files)
                    else:
                        selected_path = files[0]
            elif os.path.isfile(path):
                selected_path = path

            if not selected_path:
                continue

            specs.append({
                "path": selected_path,
                "position": layer.get("position", "右下"),
                "size_mode": layer.get("size_mode", "自适应覆盖"),
                "scale": float(layer.get("scale", 20.0)),
                "blend_mode": layer.get("blend_mode", "正常"),
                "opacity": float(layer.get("opacity", 0.5)),
            })
        return specs

    def _run_unified_postprocess_ffmpeg(self, output_path, fixed_layers, watermark_position, log_func=None):
        """阶段3：固定图层/视频水印/BGM 尽量一次FFmpeg完成。"""
        if not self.ffmpeg_available:
            return False
        if not os.path.isfile(output_path):
            return False

        main_meta = self._probe_video_meta(output_path)
        if not main_meta:
            return False

        watermark_video = self._select_video_watermark_file(log_func)
        bgm_file = self._select_bgm_file()
        fixed_specs = self._collect_fixed_layer_specs_for_ffmpeg() if fixed_layers else []
        blend_mode = self._get_video_watermark_blend_mode()

        if not (watermark_video or bgm_file or fixed_specs):
            return True

        ffmpeg_blend_mode = self._get_ffmpeg_blend_mode(blend_mode)
        wm_match_method = self.watermark_match_method.get() if hasattr(self, "watermark_match_method") else "循环"
        # 高级混合模式只要 FFmpeg 支持，就走 FFmpeg 快速路径（含“单次”匹配）。
        # 单次模式通过 blend 的 eof_action=pass + repeatlast=0 实现“水印结束后透传原画面”。
        if watermark_video and blend_mode != "正常":
            if ffmpeg_blend_mode is None:
                self._log_pipeline_stage(
                    "POST-SKIP",
                    f"视频水印混合模式={blend_mode} 暂不支持FFmpeg快速路径，回退OpenCV",
                    log_func,
                )
                return False

        # 固定图片图层若使用高级混合模式，同样回退到OpenCV路径
        if any(spec.get("blend_mode", "正常") != "正常" for spec in fixed_specs):
            self._log_pipeline_stage(
                "POST-SKIP",
                "检测到图片水印高级混合模式，回退OpenCV以保证混合模式生效",
                log_func,
            )
            return False

        self._log_pipeline_stage(
            "POST-START",
            f"输入={output_path}, 帧数={main_meta['frames']}, 编排={{固定图层:{len(fixed_specs)}, 视频水印:{bool(watermark_video)}, BGM:{bool(bgm_file)}}}",
            log_func,
        )

        base_cmd = [getattr(self, "ffmpeg_executable", None) or "ffmpeg", "-y", "-i", output_path]
        filter_parts = []
        current_label = "[0:v]"
        input_idx = 1
        audio_label = None

        # 视频水印
        if watermark_video and os.path.isfile(watermark_video):
            match_method = self.watermark_match_method.get()
            loop_wm = (match_method == "循环")
            if loop_wm:
                base_cmd += ["-stream_loop", "-1"]
            base_cmd += ["-i", watermark_video]

            wm_meta = self._probe_video_meta(watermark_video)
            if wm_meta:
                wm_w, wm_h = wm_meta["width"], wm_meta["height"]
                target_w, target_h, x_pos, y_pos = self._calc_overlay_geometry(
                    main_meta["width"],
                    main_meta["height"],
                    wm_w,
                    wm_h,
                    self.watermark_size_mode.get(),
                    self.watermark_scale.get(),
                    watermark_position,
                )
                wm_label = f"wmv_{input_idx}"
                wm_chain = f"[{input_idx}:v]setpts=PTS-STARTPTS,scale={target_w}:{target_h}"
                if match_method == "拉伸" and wm_meta["duration"] > 0 and main_meta["duration"] > 0:
                    stretch_ratio = main_meta["duration"] / wm_meta["duration"]
                    wm_chain = f"[{input_idx}:v]setpts={stretch_ratio:.6f}*PTS,scale={target_w}:{target_h}"
                if blend_mode == "正常":
                    blend_alpha = self._get_video_watermark_alpha(blend_mode)
                    wm_chain += f",format=rgba,colorchannelmixer=aa={blend_alpha:.3f}"
                filter_parts.append(f"{wm_chain}[{wm_label}]")
                next_label = f"v_wm_{input_idx}"
                if blend_mode == "正常":
                    overlay_mode = "shortest=1" if loop_wm else "eof_action=pass"
                    filter_parts.append(
                        f"{current_label}[{wm_label}]overlay=x={x_pos}:y={y_pos}:{overlay_mode}[{next_label}]"
                    )
                    current_label = f"[{next_label}]"
                else:
                    blend_alpha = self._get_video_watermark_alpha(blend_mode)
                    # 仅在ROI区域做blend，避免对整帧颜色空间产生副作用（修复色偏问题）
                    # 先将ROI与水印统一到 gbrp，再混合后贴回原视频。
                    x_clip = max(0, min(x_pos, max(0, main_meta["width"] - target_w)))
                    y_clip = max(0, min(y_pos, max(0, main_meta["height"] - target_h)))
                    roi_base_label = f"roi_base_{input_idx}"
                    wm_blend_src_label = f"wm_src_{input_idx}"
                    roi_blend_label = f"roi_blend_{input_idx}"
                    if loop_wm:
                        # 循环模式：水印流无限，按最短流结束（主视频）即可。
                        blend_sync_opts = "shortest=1"
                    else:
                        # 单次/拉伸：水印流结束后透传主视频，不保留最后一帧。
                        blend_sync_opts = "eof_action=pass:repeatlast=0"
                    filter_parts.append(
                        f"{current_label}crop={target_w}:{target_h}:{x_clip}:{y_clip},format=gbrp[{roi_base_label}]"
                    )
                    filter_parts.append(f"[{wm_label}]format=gbrp[{wm_blend_src_label}]")
                    filter_parts.append(
                        f"[{roi_base_label}][{wm_blend_src_label}]blend=all_mode={ffmpeg_blend_mode}:all_opacity={blend_alpha:.3f}:{blend_sync_opts}[{roi_blend_label}]"
                    )
                    overlay_mode = "shortest=1" if loop_wm else "eof_action=pass"
                    filter_parts.append(
                        f"{current_label}[{roi_blend_label}]overlay=x={x_clip}:y={y_clip}:{overlay_mode}[{next_label}]"
                    )
                    current_label = f"[{next_label}]"
            input_idx += 1

        # 固定图片图层
        for idx, spec in enumerate(fixed_specs):
            if not os.path.isfile(spec["path"]):
                continue
            base_cmd += ["-loop", "1", "-i", spec["path"]]
            wm_img = self._safe_read_image_with_alpha(spec["path"])
            if wm_img is None:
                input_idx += 1
                continue
            wm_h, wm_w = wm_img.shape[:2]
            target_w, target_h, x_pos, y_pos = self._calc_overlay_geometry(
                main_meta["width"],
                main_meta["height"],
                wm_w,
                wm_h,
                spec["size_mode"],
                spec["scale"],
                spec["position"],
            )
            fix_label = f"fix_{idx}"
            filter_parts.append(
                f"[{input_idx}:v]format=rgba,colorchannelmixer=aa={spec['opacity']:.3f},scale={target_w}:{target_h}[{fix_label}]"
            )
            next_label = f"v_fix_{idx}"
            filter_parts.append(
                f"{current_label}[{fix_label}]overlay=x={x_pos}:y={y_pos}:shortest=1[{next_label}]"
            )
            current_label = f"[{next_label}]"
            input_idx += 1

        # BGM
        if bgm_file and os.path.isfile(bgm_file):
            if hasattr(self, "loop_bgm") and bool(self.loop_bgm.get()):
                base_cmd += ["-stream_loop", "-1"]
            base_cmd += ["-i", bgm_file]
            audio_label = "bgm_a"
            volume = float(self.bgm_volume.get()) if hasattr(self, "bgm_volume") else 0.5
            filter_parts.append(f"[{input_idx}:a]volume={volume:.2f}[{audio_label}]")
            input_idx += 1

        def build_cmd(vcodec):
            temp_output = self._build_temp_output_path(output_path, "pipeline_temp")
            cmd = list(base_cmd)
            if filter_parts:
                cmd += ["-filter_complex", ";".join(filter_parts)]
            video_map = current_label if current_label != "[0:v]" else "0:v"
            cmd += ["-map", video_map]
            if audio_label:
                a_codec = self._get_container_compatible_acodec(output_path)
                cmd += ["-map", f"[{audio_label}]", "-c:a", a_codec, "-b:a", "192k", "-shortest"]
            else:
                cmd += ["-map", "0:a?", "-c:a", "copy"]
            cmd += ["-c:v", vcodec]
            if vcodec == "libx264":
                cmd += ["-preset", "medium"]
            cmd += ["-filter_threads", "0", "-threads", "0"]
            muxer = self._get_ffmpeg_muxer_for_output(output_path)
            # 后处理保持源视频时基，不强制改写 FPS，避免短视频被拉成长视频。
            cmd += ["-pix_fmt", "yuv420p"]
            if muxer:
                cmd += ["-f", muxer]
            cmd += [temp_output]
            return cmd, temp_output

        strict_codec = self._get_strict_ffmpeg_vcodec_for_output(output_path)
        if not strict_codec:
            self._log_pipeline_stage(
                "POST-FAIL",
                f"编码器与容器不兼容: codec={self._get_selected_codec_name()}, ext={self._get_output_extension(output_path)}",
                log_func,
            )
            return False
        codec_candidates = [strict_codec]

        start_ts = time.time()
        for codec in codec_candidates:
            cmd, temp_output = build_cmd(codec)
            self._log_pipeline_stage("POST-RUN", f"尝试编码器={codec}", log_func)
            result = self._run_process_with_retry(
                cmd,
                stage="POST",
                timeout_sec=900,
                retries=2,
                log_func=log_func,
            )
            if result is None:
                self._log_pipeline_stage("POST-FAIL", f"编码器={codec}, 无可用执行结果", log_func)
                continue
            if result.returncode == 0 and os.path.exists(temp_output) and os.path.getsize(temp_output) > 1000:
                if not self._safe_replace_file(temp_output, output_path):
                    self._log_pipeline_stage("POST-FAIL", f"编码器={codec}, 文件替换失败", log_func)
                    continue
                elapsed = time.time() - start_ts
                self._log_pipeline_stage(
                    "POST-OK",
                    f"输出={output_path}, 编码器={codec}, 容器={self._get_output_extension(output_path)}, 耗时={elapsed:.2f}s",
                    log_func,
                )
                self._log_output_probe(output_path, log_func)
                return True

            err = result.stderr.decode("utf-8", errors="ignore")
            self._log_pipeline_stage(
                "POST-FAIL",
                f"编码器={codec}, 错误码={result.returncode}, 原因={err[:200]}",
                log_func,
            )
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except Exception:
                    pass

        return False

    def _run_fixed_layers_ffmpeg_only(self, output_path, fixed_layers, log_func=None):
        """仅用FFmpeg处理固定图片图层（正常混合模式），用于高级视频混合场景提速。"""
        if not self.ffmpeg_available:
            return False
        if not fixed_layers or not os.path.isfile(output_path):
            return False

        def _log(msg):
            if log_func:
                log_func(msg)

        main_meta = self._probe_video_meta(output_path)
        if not main_meta:
            return False

        fixed_specs = self._collect_fixed_layer_specs_for_ffmpeg()
        if not fixed_specs:
            return False
        if any(spec.get("blend_mode", "正常") != "正常" for spec in fixed_specs):
            _log("固定图层包含高级混合模式，跳过FFmpeg固定图层加速")
            return False

        base_cmd = [getattr(self, "ffmpeg_executable", None) or "ffmpeg", "-y", "-i", output_path]
        filter_parts = []
        current_label = "[0:v]"
        input_idx = 1

        for idx, spec in enumerate(fixed_specs):
            if not os.path.isfile(spec["path"]):
                continue
            base_cmd += ["-loop", "1", "-i", spec["path"]]
            wm_img = self._safe_read_image_with_alpha(spec["path"])
            if wm_img is None:
                input_idx += 1
                continue
            wm_h, wm_w = wm_img.shape[:2]
            target_w, target_h, x_pos, y_pos = self._calc_overlay_geometry(
                main_meta["width"],
                main_meta["height"],
                wm_w,
                wm_h,
                spec["size_mode"],
                spec["scale"],
                spec["position"],
            )
            fix_label = f"fix_only_{idx}"
            filter_parts.append(
                f"[{input_idx}:v]format=rgba,colorchannelmixer=aa={spec['opacity']:.3f},scale={target_w}:{target_h}[{fix_label}]"
            )
            next_label = f"v_fix_only_{idx}"
            filter_parts.append(
                f"{current_label}[{fix_label}]overlay=x={x_pos}:y={y_pos}:shortest=1[{next_label}]"
            )
            current_label = f"[{next_label}]"
            input_idx += 1

        if not filter_parts:
            return False

        strict_codec = self._get_strict_ffmpeg_vcodec_for_output(output_path)
        if not strict_codec:
            return False

        temp_output = self._build_temp_output_path(output_path, "fixed_ffmpeg_temp")
        cmd = list(base_cmd)
        cmd += ["-filter_complex", ";".join(filter_parts)]
        video_map = current_label if current_label != "[0:v]" else "0:v"
        cmd += ["-map", video_map, "-map", "0:a?", "-c:a", "copy", "-c:v", strict_codec]
        if strict_codec == "libx264":
            cmd += ["-preset", "medium"]
        muxer = self._get_ffmpeg_muxer_for_output(output_path)
        # 固定图层后处理同样不改 FPS，避免时长偏移。
        cmd += ["-pix_fmt", "yuv420p"]
        if muxer:
            cmd += ["-f", muxer]
        cmd += [temp_output]

        result = self._run_process_with_retry(
            cmd,
            stage="FIXED",
            timeout_sec=600,
            retries=2,
            log_func=log_func,
        )
        if result is None:
            return False
        if result.returncode == 0 and os.path.exists(temp_output) and os.path.getsize(temp_output) > 1000:
            if not self._safe_replace_file(temp_output, output_path):
                return False
            _log("固定图层FFmpeg加速处理成功")
            return True

        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except Exception:
                pass
        return False

    def _postprocess_video_output(self, output_path, fixed_layers, watermark_position, log_func=None, pipeline_start_time=None):
        """统一处理固定水印、视频水印与BGM"""
        def _log(msg):
            if log_func:
                log_func(msg)
            else:
                print(msg)

        task_start_ts = float(pipeline_start_time) if pipeline_start_time else time.time()
        render_weight = float(getattr(self, "_progress_render_weight", 1.0))
        base_percent = int(max(0, min(100, round(render_weight * 100))))
        post_span = max(0, 100 - base_percent)

        def _post_progress(ratio, stage_text=None, force=False):
            if post_span <= 0:
                return
            ratio = max(0.0, min(1.0, float(ratio)))
            percent = base_percent + int(round(post_span * ratio))
            if stage_text:
                self._progress_phase_label = stage_text
                try:
                    self.update_status(f"{stage_text}...")
                except Exception:
                    pass
            info = f"任务进度: {percent}%"
            if stage_text:
                info = f"{info}（{stage_text}）"
            self._set_absolute_progress(percent, info_text=info, force=force)

        def _finish_with_elapsed(note="任务完成"):
            self._set_absolute_progress(100, info_text="任务进度: 100%（完成）", force=True)
            elapsed = max(0.0, time.time() - task_start_ts)
            self.update_status(f"{note}，耗时: {elapsed:.1f} 秒")
            _log(f"{note}，总耗时: {elapsed:.2f} 秒")

        _post_progress(0.05, "收尾中", force=True)

        current_video_blend_mode = self._get_video_watermark_blend_mode()
        ffmpeg_video_blend_supported = (
            self._get_ffmpeg_blend_mode(current_video_blend_mode) is not None
        )
        advanced_video_blend = (
            self.use_watermark.get()
            and self.watermark_type.get() == "视频"
            and current_video_blend_mode != "正常"
            and not ffmpeg_video_blend_supported
        )

        # 高级视频混合模式优先走分层链路：
        # 1) 固定图片图层（正常模式）先用FFmpeg提速；
        # 2) MOV视频水印继续走OpenCV高级混合，确保效果一致。
        if advanced_video_blend:
            _log("检测到视频水印高级混合模式：启用分层后处理链路")
            _post_progress(0.15, "水印中")
            fixed_done = False
            if fixed_layers:
                try:
                    fixed_done = self._run_fixed_layers_ffmpeg_only(output_path, fixed_layers, _log)
                except Exception as e:
                    _log(f"固定图层FFmpeg加速失败，将回退OpenCV: {str(e)}")
                if not fixed_done:
                    try:
                        self.add_fixed_image_watermarks_to_video(output_path, fixed_layers)
                        fixed_done = True
                    except Exception as e:
                        _log(f"固定水印处理失败: {str(e)}")
            if fixed_done:
                _log("固定图层处理完成")
            _post_progress(0.45, "水印中")

        else:
            # 优先使用一次性FFmpeg后处理（阶段3），失败时再回退原流程（阶段4）
            try:
                _post_progress(0.35, "水印中")
                unified_success = self._run_unified_postprocess_ffmpeg(
                    output_path,
                    fixed_layers,
                    watermark_position,
                    _log,
                )
                if unified_success:
                    self._log_output_probe(output_path, _log)
                    _finish_with_elapsed("后处理完成")
                    return
                _log("统一后处理失败，回退到兼容链路（不中断任务）")
                _post_progress(0.45, "水印中")
            except Exception as e:
                _log(f"统一后处理异常，回退兼容链路: {str(e)}")
                _post_progress(0.45, "水印中")

            # 固定图片水印（不跟随转场/特效）
            if fixed_layers:
                try:
                    self.add_fixed_image_watermarks_to_video(output_path, fixed_layers)
                except Exception as e:
                    _log(f"固定水印处理失败: {str(e)}")
            _post_progress(0.60, "水印中")

        # 视频水印（MOV）
        if self.use_watermark.get() and self.watermark_type.get() == "视频":
            watermark_base_path = self.watermark_path.get()
            if watermark_base_path and os.path.exists(watermark_base_path):
                watermark_mode = getattr(self, 'watermark_mode', None)
                watermark_mode_value = watermark_mode.get() if watermark_mode else "单文件"

                watermark_video_path = None
                if watermark_mode_value == "文件夹" and os.path.isdir(watermark_base_path):
                    _log(f"检测到文件夹模式水印: {watermark_base_path}")
                    watermark_files = self.get_watermark_files(watermark_base_path)
                    if watermark_files:
                        video_idx = getattr(self, '_current_video_index', 0)
                        watermark_video_path = watermark_files[video_idx % len(watermark_files)]
                        _log(f"选择水印文件 [{video_idx % len(watermark_files) + 1}/{len(watermark_files)}]: {os.path.basename(watermark_video_path)}")
                    else:
                        _log("文件夹中没有找到视频水印文件")
                else:
                    if os.path.isfile(watermark_base_path):
                        watermark_video_path = watermark_base_path
                        _log(f"使用单文件水印: {watermark_video_path}")
                    else:
                        _log(f"水印路径无效: {watermark_base_path}")

                if watermark_video_path and os.path.isfile(watermark_video_path):
                    _log(f"开始添加视频水印: {os.path.basename(watermark_video_path)}")
                    temp_output = self._build_temp_output_path(output_path, "watermark_temp")
                    try:
                        watermark_success = self.add_video_watermark(
                            main_video_path=output_path,
                            watermark_path=watermark_video_path,
                            output_path=temp_output,
                            position=watermark_position,
                            match_method=self.watermark_match_method.get()
                        )
                        if watermark_success and os.path.exists(temp_output):
                            if os.path.exists(output_path):
                                os.remove(output_path)
                            os.rename(temp_output, output_path)
                            _log("视频水印添加成功")
                        else:
                            _log("视频水印添加失败")
                            if os.path.exists(temp_output):
                                os.remove(temp_output)
                    except Exception as e:
                        _log(f"视频水印处理出错: {str(e)}")
                        if os.path.exists(temp_output):
                            os.remove(temp_output)
                else:
                    _log("没有找到有效的水印文件")
        _post_progress(0.80, "水印中")

        # 背景音乐
        audio_strategy = self.watermark_audio.get() if hasattr(self, "watermark_audio") else "使用BGM"
        if self.use_bgm.get() and audio_strategy in ("使用BGM", "两者混合"):
            bgm_files = self._resolve_bgm_candidates()
            if bgm_files:
                _log(f"开始添加背景音乐: {os.path.dirname(bgm_files[0])}")
                if self.random_bgm.get():
                    import random
                    bgm_file = random.choice(bgm_files)
                else:
                    bgm_file = bgm_files[0]
                _log(f"选择音乐文件: {os.path.basename(bgm_file)}")
                try:
                    volume = self.bgm_volume.get()
                    bgm_success = self.add_audio_with_ffmpeg(output_path, bgm_file, volume)
                    if bgm_success:
                        _log("背景音乐添加成功")
                    else:
                        _log("背景音乐添加失败")
                except Exception as e:
                    _log(f"添加背景音乐出错: {str(e)}")
            else:
                _log("BGM目录中没有找到音乐文件")
        _post_progress(0.95, "BGM中")

        # 末端容器/编码校验日志
        self._progress_phase_label = "收尾中"
        self._log_output_probe(output_path, _log)
        _finish_with_elapsed("后处理完成")

    def update_progress(self, value):
        """更新进度条，value可以是帧数或百分比"""
        raw_value = None
        try:
            raw_value = int(value)
        except Exception:
            raw_value = None

        percent = None
        if hasattr(self, 'total_frames') and self.total_frames:
            safe_value = max(0, raw_value if raw_value is not None else 0)
            raw_percent = min(100, int(safe_value / self.total_frames * 100))
            render_weight = float(getattr(self, "_progress_render_weight", 1.0))
            percent = min(100, int(raw_percent * render_weight))
        else:
            try:
                percent = min(100, max(0, raw_value if raw_value is not None else int(value)))
            except Exception:
                percent = None

        now = time.time()
        flush_due = (now - getattr(self, "_progress_last_ui_ts", 0.0)) >= getattr(self, "_progress_ui_min_interval", 0.08)
        percent_changed = (percent is not None and percent != getattr(self, "_progress_last_percent", -1))
        should_flush = bool(percent_changed and (flush_due or percent in (0, 100)))

        if hasattr(self, '_speed_start_time') and self._speed_start_time:
            if raw_value is not None and raw_value >= 0:
                last_value = int(getattr(self, "_speed_last_value", 0) or 0)
                if raw_value >= last_value:
                    self._speed_processed += (raw_value - last_value)
                else:
                    # 新任务或计数重置场景
                    self._speed_processed += raw_value
                self._speed_last_value = raw_value
            else:
                self._speed_processed += 1

        if percent is None or not should_flush:
            return

        phase = str(getattr(self, "_progress_phase_label", "渲染中"))
        self._set_absolute_progress(percent, info_text=f"任务进度: {percent}%（{phase}）", force=True)

        if hasattr(self, '_speed_start_time') and self._speed_start_time:
            elapsed = max(0.001, now - self._speed_start_time)
            speed = self._speed_processed / elapsed
            if hasattr(self, 'speed_info_var'):
                self.speed_info_var.set(f"速度: {speed:.1f} 张/秒")
        self._maybe_realtime_cleanup()

    def _maybe_realtime_cleanup(self, force: bool = False):
        """处理过程中实时清理缓存，避免堆积"""
        now = time.time()
        if not force and (now - self._last_cache_cleanup) < self._cache_cleanup_interval:
            return
        self._last_cache_cleanup = now
        if self.turbo_accelerator and self.turbo_accelerator.enabled:
            self.turbo_accelerator.realtime_cleanup(force=force)
        if self.transition_engine and hasattr(self.transition_engine, "realtime_cleanup"):
            self.transition_engine.realtime_cleanup(force=force)

    def _update_overall_progress(self, percent):
        """基于当前视频进度更新总进度"""
        if not getattr(self, 'overall_total_videos', 0):
            return
        current_index = max(0, min(self.current_video_index, self.overall_total_videos - 1))
        overall = ((current_index + (percent / 100.0)) / self.overall_total_videos) * 100
        overall = max(0, min(100, overall))
        if hasattr(self, 'overall_progress_var'):
            self.overall_progress_var.set(int(overall))
        if hasattr(self, 'overall_progress_info_var'):
            self.overall_progress_info_var.set(f"总进度: {int(overall)}%")

    def apply_blend_mode(self, background, foreground, mode="正常", alpha=0.5):
        """
        应用不同的混合模式
        
        Args:
            background: 背景图像（主视频帧）
            foreground: 前景图像（水印）
            mode: 混合模式
            alpha: 透明度（0.0-1.0）
            
        Returns:
            混合后的图像
        """
        try:
            # 确保图像类型一致
            bg = background.astype(np.float32) / 255.0
            fg = foreground.astype(np.float32) / 255.0
            
            if mode == "正常":
                # 正常混合（Alpha混合）
                result = bg * (1 - alpha) + fg * alpha
                
            elif mode == "滤色":
                # 滤色模式 - 适合黑色背景，黑色变透明
                # Screen: 1 - (1-A) * (1-B)
                result = 1 - (1 - bg) * (1 - fg)
                # 应用透明度
                result = bg * (1 - alpha) + result * alpha
                
            elif mode == "叠加":
                # 叠加模式 - 根据背景亮度选择正片叠底或滤色
                # Overlay: if bg < 0.5: 2*A*B else 1-2*(1-A)*(1-B)
                mask = bg < 0.5
                result = np.where(mask, 2 * bg * fg, 1 - 2 * (1 - bg) * (1 - fg))
                result = bg * (1 - alpha) + result * alpha
                
            elif mode == "正片叠底":
                # 正片叠底 - 变暗效果
                # Multiply: A * B
                result = bg * fg
                result = bg * (1 - alpha) + result * alpha
                
            elif mode == "变亮":
                # 变亮模式 - 保留较亮的像素
                # Lighten: max(A, B)
                result = np.maximum(bg, fg)
                result = bg * (1 - alpha) + result * alpha
                
            elif mode == "变暗":
                # 变暗模式 - 保留较暗的像素
                # Darken: min(A, B)
                result = np.minimum(bg, fg)
                result = bg * (1 - alpha) + result * alpha
                
            elif mode == "相加":
                # 相加模式 - 线性减淡
                # Add: A + B
                result = bg + fg
                result = np.clip(result, 0, 1)
                result = bg * (1 - alpha) + result * alpha
                
            else:
                # 默认使用正常混合
                result = bg * (1 - alpha) + fg * alpha
            
            # 转换回uint8
            result = np.clip(result * 255, 0, 255).astype(np.uint8)
            return result
            
        except Exception as e:
            print(f"混合模式应用失败: {str(e)}")
            return background

    def _safe_read_image_with_alpha(self, img_path):
        """读取图片并保留透明通道（支持中文路径）"""
        try:
            if isinstance(img_path, str) and os.path.exists(img_path):
                img_array = np.fromfile(img_path, dtype=np.uint8)
                img = cv2.imdecode(img_array, cv2.IMREAD_UNCHANGED)
                return img
            return None
        except Exception:
            return None

    def _normalize_watermark_layers(self):
        """统一水印图层配置（兼容单水印配置）"""
        layers = []
        if isinstance(self.watermark_layers, list) and self.watermark_layers:
            layers = self.watermark_layers
        return layers

    def _get_image_files_in_dir(self, directory):
        extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
        try:
            return [
                os.path.join(directory, f)
                for f in os.listdir(directory)
                if f.lower().endswith(extensions)
            ]
        except Exception:
            return []

    def _prepare_image_watermark_layers(self):
        """加载图片水印图层（含多层）"""
        prepared = []
        for layer in self._normalize_watermark_layers():
            if not layer.get("enabled", True):
                continue
            if layer.get("type", "图片") != "图片":
                continue
            path = layer.get("path", "")
            if not path:
                continue
            files = []
            if os.path.isdir(path):
                files = self._get_image_files_in_dir(path)
                if files and bool(layer.get("folder_random_single", False)):
                    files = [random.choice(files)]
            else:
                files = [path]
            images = []
            for f in files:
                wm_img = self._safe_read_image_with_alpha(f)
                if wm_img is not None:
                    images.append(wm_img)
            if not images:
                continue
            prepared.append({
                "images": images,
                "position": layer.get("position", "右下"),
                "size_mode": layer.get("size_mode", "自适应覆盖"),
                "scale": layer.get("scale", 20.0),
                "blend_mode": layer.get("blend_mode", "正常"),
                "opacity": layer.get("opacity", 0.5),
                "fixed": bool(layer.get("fixed", False)),
                "folder_random_single": bool(layer.get("folder_random_single", False)),
            })
        return prepared

    def _apply_image_watermark_layer(self, image, layer, image_index=0):
        """应用单层图片水印"""
        if image is None:
            return image
        h, w = image.shape[:2]
        wm_images = layer.get("images", [])
        if not wm_images:
            return image
        wm_img = wm_images[image_index % len(wm_images)]

        wm_h, wm_w = wm_img.shape[:2]
        watermark_ratio = wm_w / max(1, wm_h)
        main_ratio = w / max(1, h)
        size_mode_value = layer.get("size_mode", "自适应覆盖")
        scale_value = float(layer.get("scale", 20.0))

        if size_mode_value == "自适应覆盖":
            if watermark_ratio > main_ratio:
                wm_target_height = h
                wm_target_width = int(wm_target_height * watermark_ratio)
            else:
                wm_target_width = w
                wm_target_height = int(wm_target_width / watermark_ratio)
        elif size_mode_value == "完全覆盖":
            wm_target_width = w
            wm_target_height = h
        else:
            watermark_size = int(w * (scale_value / 100.0))
            wm_target_width = max(1, watermark_size)
            wm_target_height = max(1, int(wm_target_width / watermark_ratio))

        # 调整水印大小
        if wm_target_width != wm_w or wm_target_height != wm_h:
            wm_resized = cv2.resize(wm_img, (wm_target_width, wm_target_height))
        else:
            wm_resized = wm_img

        # 计算位置
        margin = 10 if size_mode_value == "固定比例" else 0
        position = layer.get("position", "右下")
        if position == "左上":
            x_pos, y_pos = margin, margin
        elif position == "右上":
            x_pos, y_pos = w - wm_target_width - margin, margin
        elif position == "左下":
            x_pos, y_pos = margin, h - wm_target_height - margin
        elif position == "中心":
            x_pos, y_pos = (w - wm_target_width) // 2, (h - wm_target_height) // 2
        else:
            x_pos, y_pos = w - wm_target_width - margin, h - wm_target_height - margin

        # 裁剪到有效范围
        src_x_start = max(0, -x_pos)
        src_y_start = max(0, -y_pos)
        dst_x_start = max(0, x_pos)
        dst_y_start = max(0, y_pos)
        actual_w = min(wm_target_width - src_x_start, w - dst_x_start)
        actual_h = min(wm_target_height - src_y_start, h - dst_y_start)
        if actual_w <= 0 or actual_h <= 0:
            return image

        wm_crop = wm_resized[src_y_start:src_y_start+actual_h, src_x_start:src_x_start+actual_w]
        roi = image[dst_y_start:dst_y_start+actual_h, dst_x_start:dst_x_start+actual_w]

        blend_mode = layer.get("blend_mode", "正常")
        opacity = float(layer.get("opacity", 0.5))

        # 支持透明通道
        if wm_crop.shape[2] == 4:
            wm_rgb = wm_crop[:, :, :3]
            alpha_mask = (wm_crop[:, :, 3] / 255.0) * opacity
            blended_full = self.apply_blend_mode(roi, wm_rgb, mode=blend_mode, alpha=1.0)
            alpha_mask = np.expand_dims(alpha_mask, axis=2)
            result = roi * (1 - alpha_mask) + blended_full * alpha_mask
            image[dst_y_start:dst_y_start+actual_h, dst_x_start:dst_x_start+actual_w] = result.astype(np.uint8)
        else:
            blended = self.apply_blend_mode(roi, wm_crop[:, :, :3], mode=blend_mode, alpha=opacity)
            image[dst_y_start:dst_y_start+actual_h, dst_x_start:dst_x_start+actual_w] = blended

        return image

    def apply_image_watermark_layers(self, image, layers, image_index=0):
        """应用多层图片水印"""
        result = image
        for layer in layers:
            result = self._apply_image_watermark_layer(result, layer, image_index=image_index)
        return result

    def add_fixed_image_watermarks_to_video(self, input_path, layers):
        """为已生成的视频添加固定图片水印图层"""
        if not layers:
            return True
        try:
            cap = cv2.VideoCapture(input_path)
            if not cap.isOpened():
                return False
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            temp_output = self._build_temp_output_path(input_path, "fixed_wm_temp")
            selected_codec = self._resolve_processing_fourcc()
            needs_reencode = False
            if not selected_codec:
                selected_codec = self._get_fallback_processing_fourcc()
                needs_reencode = bool(selected_codec)
                if not selected_codec:
                    self.update_status(f"固定水印编码器不可用: {self._get_selected_codec_name()}")
                    cap.release()
                    return False
                self.update_status(
                    f"固定水印阶段使用中间编码器: {selected_codec}，完成后将转码为 {self._get_selected_codec_name()}"
                )
            fourcc = cv2.VideoWriter_fourcc(*selected_codec)
            writer = cv2.VideoWriter(temp_output, fourcc, fps, (width, height))
            if not writer.isOpened():
                self.update_status(f"固定水印编码器创建失败: {selected_codec}")
                cap.release()
                return False

            idx = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                frame = self.apply_image_watermark_layers(frame, layers, image_index=idx)
                writer.write(frame)
                idx += 1
                if idx % max(1, total // 100) == 0:
                    self.update_status(f"固定水印处理中: {int(idx / max(1, total) * 100)}%")

            cap.release()
            writer.release()

            if os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
                final_temp = temp_output
                if needs_reencode:
                    reencoded = self._build_temp_output_path(input_path, "fixed_wm_reencoded")
                    if not self._reencode_video_to_selected_codec(temp_output, reencoded, self.update_status):
                        try:
                            os.remove(temp_output)
                        except Exception:
                            pass
                        return False
                    try:
                        os.remove(temp_output)
                    except Exception:
                        pass
                    final_temp = reencoded
                os.remove(input_path)
                os.rename(final_temp, input_path)
                # 动画叠加层（ffmpeg ProRes MOV overlay）
                self._apply_ffmpeg_animated_overlays_stage(input_path)
                return True
            return False
        except Exception:
            return False

    def _apply_ffmpeg_animated_overlays_stage(self, video_path: str) -> None:
        """
        在静态水印处理后调用：将动画叠加层（ProRes MOV with alpha）合成到视频上。
        从 self.watermark_layers 中检测有 seq_overlay_path 的图层，使用 ffmpeg overlay 滤镜合成。
        """
        try:
            animated_layers = self._normalize_watermark_layers()
            from ..services.video_service import apply_ffmpeg_animated_overlays
            apply_ffmpeg_animated_overlays(
                video_path,
                animated_layers,
                status_callback=self.update_status,
            )
        except Exception:
            pass

    def add_video_watermark(self, main_video_path, watermark_path, output_path, position="右下", match_method="循环"):
        """使用OpenCV给视频添加视频水印
        
        Args:
            main_video_path: 主视频文件路径
            watermark_path: 水印视频文件路径
            output_path: 输出视频文件路径
            position: 水印位置 ("左上", "右上", "左下", "右下", "中心")
            match_method: 水印匹配方法 ("循环", "拉伸", "单次")
            
        Returns:
            bool: 成功返回True，失败返回False
        """
        import traceback
        
        # 自定义日志函数
        def log(msg):
            print(msg)
            try:
                with open("video_watermark_debug.log", "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass
        
        try:
            # 打开主视频
            log(f"打开主视频: {main_video_path}")
            main_cap = cv2.VideoCapture(main_video_path)
            if not main_cap.isOpened():
                log(f"无法打开主视频: {main_video_path}")
                return False
            
            # 获取主视频的基本信息
            main_width = int(main_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            main_height = int(main_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            main_fps = main_cap.get(cv2.CAP_PROP_FPS)
            main_frame_count = int(main_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            main_duration = main_frame_count / main_fps
            
            log(f"主视频信息: {main_width}x{main_height}, {main_fps}fps, {main_frame_count}帧, 时长:{main_duration:.2f}秒")
            
            # 打开水印视频
            log(f"打开水印视频: {watermark_path}")
            watermark_cap = cv2.VideoCapture(watermark_path)
            if not watermark_cap.isOpened():
                log(f"无法打开水印视频: {watermark_path}")
                main_cap.release()
                return False
            
            # 获取水印视频的基本信息
            wm_width = int(watermark_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            wm_height = int(watermark_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            wm_fps = watermark_cap.get(cv2.CAP_PROP_FPS)
            wm_frame_count = int(watermark_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            wm_duration = wm_frame_count / max(0.0001, wm_fps)
            
            # OpenCV 解码会丢弃 alpha 通道；优先用 FFmpeg 解码 RGBA 帧保留透明通道
            wm_alpha_frames = None
            try:
                from ..utils.ffmpeg_runtime import read_video_frames_rgba

                wm_alpha_frames = read_video_frames_rgba(
                    getattr(self, "ffmpeg_executable", None) or "ffmpeg",
                    watermark_path,
                )
            except Exception:
                wm_alpha_frames = None
            if wm_alpha_frames is not None:
                wm_frame_count = min(wm_frame_count, len(wm_alpha_frames))
                log(f"已通过 FFmpeg 解码 {len(wm_alpha_frames)} 帧 RGBA 水印（保留透明通道）")
            
            log(f"水印视频信息: {wm_width}x{wm_height}, {wm_fps}fps, {wm_frame_count}帧, 时长:{wm_duration:.2f}秒")
            
            # 获取水印大小模式和缩放比例
            size_mode = getattr(self, 'watermark_size_mode', None)
            size_mode_value = size_mode.get() if size_mode else "自适应覆盖"
            scale_percent = getattr(self, 'watermark_scale', None)
            scale_value = scale_percent.get() if scale_percent else 20.0
            
            # 计算水印大小 - 根据模式自适应
            watermark_ratio = wm_width / wm_height
            main_ratio = main_width / main_height
            
            if size_mode_value == "自适应覆盖":
                # 自适应覆盖：保持比例，完全覆盖主视频（可能会裁剪水印）
                if watermark_ratio > main_ratio:
                    # 水印更宽，按高度适配
                    wm_target_height = main_height
                    wm_target_width = int(wm_target_height * watermark_ratio)
                else:
                    # 水印更高，按宽度适配
                    wm_target_width = main_width
                    wm_target_height = int(wm_target_width / watermark_ratio)
                log(f"自适应覆盖模式: 水印比例={watermark_ratio:.2f}, 主视频比例={main_ratio:.2f}")
            elif size_mode_value == "完全覆盖":
                # 完全覆盖：拉伸到完全匹配主视频大小（不保持比例）
                wm_target_width = main_width
                wm_target_height = main_height
                log(f"完全覆盖模式: 拉伸到主视频大小")
            else:
                # 固定比例模式：按百分比缩放
                watermark_size = int(main_width * (scale_value / 100.0))
                wm_target_width = watermark_size
                wm_target_height = int(wm_target_width / watermark_ratio)
                log(f"固定比例模式: 缩放{scale_value}%")
            
            log(f"调整后的水印大小: {wm_target_width}x{wm_target_height} (原始: {wm_width}x{wm_height})")
            
            # 确定水印位置
            margin = 10 if size_mode_value == "固定比例" else 0  # 自适应模式无边距
            
            if position == "左上":
                x_pos = margin
                y_pos = margin
            elif position == "右上":
                x_pos = main_width - wm_target_width - margin
                y_pos = margin
            elif position == "左下":
                x_pos = margin
                y_pos = main_height - wm_target_height - margin
            elif position == "中心":
                x_pos = (main_width - wm_target_width) // 2
                y_pos = (main_height - wm_target_height) // 2
            else:  # 默认右下
                x_pos = main_width - wm_target_width - margin
                y_pos = main_height - wm_target_height - margin
            
            log(f"水印位置: {position} ({x_pos}, {y_pos}), 边距: {margin}px")
            
            # 创建输出写入器：优先FFmpeg管道编码（避免中间重编码），失败则回退OpenCV写入
            log(f"创建输出视频: {output_path}")
            stage_output = output_path
            use_ffmpeg_pipe = False
            ffmpeg_proc = None
            video_writer = None
            selected_codec = None
            needs_reencode = False

            if self.ffmpeg_available:
                strict_vcodec = self._get_strict_ffmpeg_vcodec_for_output(output_path)
                if strict_vcodec:
                    muxer = self._get_ffmpeg_muxer_for_output(output_path)
                    ffmpeg_cmd = [
                        getattr(self, "ffmpeg_executable", None) or "ffmpeg", "-y",
                        "-f", "rawvideo",
                        "-pix_fmt", "bgr24",
                        "-s", f"{main_width}x{main_height}",
                        "-r", str(max(1, int(round(main_fps)))),
                        "-i", "-",
                        "-an",
                        "-c:v", strict_vcodec,
                        "-pix_fmt", "yuv420p",
                        "-r", str(max(1, int(round(main_fps)))),
                    ]
                    if strict_vcodec == "libx264":
                        ffmpeg_cmd += ["-preset", "medium"]
                    if muxer:
                        ffmpeg_cmd += ["-f", muxer]
                    ffmpeg_cmd += [stage_output]
                    try:
                        ffmpeg_proc = subprocess.Popen(
                            ffmpeg_cmd,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            startupinfo=self.startupinfo if hasattr(self, 'startupinfo') else None,
                        )
                        use_ffmpeg_pipe = True
                        log(f"使用FFmpeg管道编码: {strict_vcodec}")
                    except Exception as pipe_err:
                        log(f"FFmpeg管道编码初始化失败，回退OpenCV: {str(pipe_err)}")

            if not use_ffmpeg_pipe:
                selected_codec = self._resolve_processing_fourcc()
                if not selected_codec:
                    selected_codec = self._get_fallback_processing_fourcc()
                    needs_reencode = bool(selected_codec)
                    if not selected_codec:
                        log(f"编码器不可用: {self._get_selected_codec_name()}")
                        main_cap.release()
                        watermark_cap.release()
                        return False
                    log(f"水印阶段使用中间编码器: {selected_codec}，完成后将转码为 {self._get_selected_codec_name()}")
                if needs_reencode:
                    stage_output = self._build_temp_output_path(output_path, "wm_stage")
                fourcc = cv2.VideoWriter_fourcc(*selected_codec)
                video_writer = cv2.VideoWriter(stage_output, fourcc, main_fps, (main_width, main_height))
                if video_writer.isOpened():
                    log(f"使用编码器: {selected_codec}")
                else:
                    log(f"编码器 {selected_codec} 创建失败")
                    main_cap.release()
                    watermark_cap.release()
                    return False
            
            # 处理帧
            main_frame_idx = 0
            wm_frame_idx = 0
            total_frames_processed = 0
            blend_mode_var = getattr(self, 'watermark_blend_mode', None)
            blend_mode = blend_mode_var.get() if blend_mode_var else "正常"
            blend_alpha = self._get_video_watermark_alpha(blend_mode)
            
            # 设置进度更新间隔
            progress_update_interval = max(1, main_frame_count // 100)

            # 预计算ROI裁剪参数（位置固定，无需每帧重复计算）
            src_x_start = max(0, -x_pos)
            src_y_start = max(0, -y_pos)
            dst_x_start = max(0, x_pos)
            dst_y_start = max(0, y_pos)
            actual_w = min(wm_target_width - src_x_start, main_width - dst_x_start)
            actual_h = min(wm_target_height - src_y_start, main_height - dst_y_start)
            if actual_w <= 0 or actual_h <= 0:
                log(f"无效的裁剪区域: actual_w={actual_w}, actual_h={actual_h}")
                main_cap.release()
                watermark_cap.release()
                video_writer.release()
                return False
            
            # 计算主视频和水印视频的总帧数比例，用于同步播放
            if match_method == "拉伸":
                # 对于拉伸匹配，将水印视频时长拉伸到主视频时长
                wm_speed_ratio = main_frame_count / max(1, wm_frame_count)
                log(f"拉伸匹配 - 水印速度比例: {wm_speed_ratio:.4f}")
            else:
                wm_speed_ratio = 1.0

            # 顺序解码缓存，避免逐帧CAP_PROP_POS_FRAMES随机跳转导致的性能损耗
            wm_read_idx = 0
            wm_last_idx = -1
            wm_last_frame = None
            resized_last_idx = -1
            resized_last_frame = None

            def _reset_watermark_capture():
                nonlocal watermark_cap, wm_read_idx, wm_last_idx, wm_last_frame, resized_last_idx, resized_last_frame
                try:
                    watermark_cap.release()
                except Exception:
                    pass
                watermark_cap = cv2.VideoCapture(watermark_path)
                if not watermark_cap.isOpened():
                    return False
                wm_read_idx = 0
                wm_last_idx = -1
                wm_last_frame = None
                resized_last_idx = -1
                resized_last_frame = None
                return True

            def _get_wm_frame_by_index(target_idx):
                nonlocal wm_read_idx, wm_last_idx, wm_last_frame
                if target_idx < 0 or target_idx >= wm_frame_count:
                    return None
                if wm_alpha_frames is not None:
                    return wm_alpha_frames[target_idx].copy()
                if target_idx == wm_last_idx and wm_last_frame is not None:
                    return wm_last_frame
                if target_idx < wm_read_idx:
                    if not _reset_watermark_capture():
                        return None
                while wm_read_idx <= target_idx:
                    ret_wm, frame_wm = watermark_cap.read()
                    if not ret_wm:
                        return None
                    wm_last_frame = frame_wm
                    wm_last_idx = wm_read_idx
                    wm_read_idx += 1
                return wm_last_frame
            
            # 记录帧处理开始时间
            start_time = time.time()
            log(f"开始处理视频帧, 匹配方法: {match_method}")
            
            while True:
                # 读取主视频帧
                ret, main_frame = main_cap.read()
                if not ret:
                    break  # 主视频读取完毕
                
                # 如果是"单次"匹配方式且水印已播放完，不再添加水印
                if match_method == "单次" and wm_frame_idx >= wm_frame_count:
                    if use_ffmpeg_pipe:
                        ffmpeg_proc.stdin.write(main_frame.tobytes())
                    else:
                        video_writer.write(main_frame)
                    main_frame_idx += 1
                    continue
                
                # 根据匹配方法计算水印帧索引
                if match_method == "拉伸":
                    current_wm_idx = int(main_frame_idx * wm_speed_ratio) % wm_frame_count
                elif match_method == "循环":
                    current_wm_idx = wm_frame_idx % wm_frame_count
                else:  # 单次
                    current_wm_idx = wm_frame_idx

                wm_frame = _get_wm_frame_by_index(current_wm_idx)
                if wm_frame is not None:
                    # 缩放缓存：同一帧索引重复使用时不重复resize（拉伸模式常见）
                    if current_wm_idx == resized_last_idx and resized_last_frame is not None:
                        wm_frame_resized = resized_last_frame
                    else:
                        if wm_frame.shape[1] == wm_target_width and wm_frame.shape[0] == wm_target_height:
                            wm_frame_resized = wm_frame
                        else:
                            wm_frame_resized = cv2.resize(wm_frame, (wm_target_width, wm_target_height))
                        resized_last_idx = current_wm_idx
                        resized_last_frame = wm_frame_resized

                    try:
                        # 裁剪水印帧到实际区域
                        wm_crop = wm_frame_resized[
                            src_y_start:src_y_start + actual_h,
                            src_x_start:src_x_start + actual_w
                        ]
                        # 获取主视频对应区域
                        roi = main_frame[
                            dst_y_start:dst_y_start + actual_h,
                            dst_x_start:dst_x_start + actual_w
                        ]
                        # 确保尺寸匹配
                        if wm_crop.shape[:2] == roi.shape[:2]:
                            if wm_crop.shape[2] == 4:
                                # RGBA 水印：按 alpha 通道合成（透明区域透出主画面）
                                wm_rgb = wm_crop[:, :, :3]
                                alpha_mask = (wm_crop[:, :, 3].astype(np.float32) / 255.0) * blend_alpha
                                blended_full = self.apply_blend_mode(roi, wm_rgb, mode=blend_mode, alpha=1.0)
                                alpha_mask = np.expand_dims(alpha_mask, axis=2)
                                result = roi.astype(np.float32) * (1 - alpha_mask) + blended_full * alpha_mask
                                main_frame[
                                    dst_y_start:dst_y_start + actual_h,
                                    dst_x_start:dst_x_start + actual_w
                                ] = result.astype(np.uint8)
                            else:
                                blended = self.apply_blend_mode(roi, wm_crop, mode=blend_mode, alpha=blend_alpha)
                                main_frame[
                                    dst_y_start:dst_y_start + actual_h,
                                    dst_x_start:dst_x_start + actual_w
                                ] = blended
                        else:
                            log(f"尺寸不匹配: wm_crop={wm_crop.shape}, roi={roi.shape}")
                    except Exception as e:
                        log(f"水印帧处理失败: {str(e)}")
                
                # 写入输出视频
                if use_ffmpeg_pipe:
                    ffmpeg_proc.stdin.write(main_frame.tobytes())
                else:
                    video_writer.write(main_frame)
                
                # 更新帧索引
                main_frame_idx += 1
                wm_frame_idx += 1
                total_frames_processed += 1
                
                # 定期更新进度
                if main_frame_idx % progress_update_interval == 0:
                    progress = (main_frame_idx / main_frame_count) * 100
                    elapsed = time.time() - start_time
                    fps = main_frame_idx / max(0.1, elapsed)
                    remaining = (main_frame_count - main_frame_idx) / max(1, fps)
                    
                    self.update_status(f"添加视频水印: {progress:.1f}%, 速度: {fps:.1f}fps, 剩余: {remaining:.1f}秒")
                    log(f"进度: {main_frame_idx}/{main_frame_count} ({progress:.1f}%), 速度: {fps:.1f}fps")
            
            # 释放资源
            main_cap.release()
            watermark_cap.release()
            if use_ffmpeg_pipe:
                if ffmpeg_proc and ffmpeg_proc.stdin:
                    ffmpeg_proc.stdin.close()
                    ffmpeg_proc.stdin = None
                ff_stdout, ff_stderr = ffmpeg_proc.communicate()
                if ffmpeg_proc.returncode != 0:
                    err = ff_stderr.decode("utf-8", errors="ignore") if ff_stderr else ""
                    log(f"FFmpeg管道编码失败: {err[:300]}")
                    try:
                        main_cap.release()
                        watermark_cap.release()
                    except Exception:
                        pass
                    return False
            else:
                video_writer.release()
            
            # 计算总处理时间
            total_time = time.time() - start_time
            log(f"视频水印添加完成，共处理 {total_frames_processed} 帧，耗时 {total_time:.2f} 秒")
            
            # 验证输出视频
            if os.path.exists(stage_output) and os.path.getsize(stage_output) > 0:
                if (not use_ffmpeg_pipe) and needs_reencode:
                    if not self._reencode_video_to_selected_codec(stage_output, output_path, log):
                        try:
                            os.remove(stage_output)
                        except Exception:
                            pass
                        self.update_status("视频水印添加失败：重编码失败")
                        return False
                    try:
                        os.remove(stage_output)
                    except Exception:
                        pass
                self.update_status(f"视频水印添加成功: {output_path}")
                return True
            else:
                log(f"输出视频无效: {stage_output}")
                self.update_status("视频水印添加失败：输出文件无效")
                return False
                
        except Exception as e:
            log(f"添加视频水印时出错: {str(e)}\n{traceback.format_exc()}")
            self.update_status(f"添加视频水印失败: {str(e)}")
            
            # 尝试清理资源
            try:
                if 'main_cap' in locals() and main_cap is not None:
                    main_cap.release()
                if 'watermark_cap' in locals() and watermark_cap is not None:
                    watermark_cap.release()
                if 'video_writer' in locals() and video_writer is not None and video_writer.isOpened():
                    video_writer.release()
                if 'ffmpeg_proc' in locals() and ffmpeg_proc is not None:
                    try:
                        if ffmpeg_proc.stdin:
                            ffmpeg_proc.stdin.close()
                    except Exception:
                        pass
                    try:
                        ffmpeg_proc.kill()
                    except Exception:
                        pass
            except Exception:
                pass
                
            return False

    def resize_image_hq(self, image, target_width, target_height, resize_mode="适应", maintain_aspect=True):
        """高质量图片resize方法

        Args:
            image: 输入图片
            target_width: 目标宽度
            target_height: 目标高度
            resize_mode: resize模式
            maintain_aspect: 是否保持宽高比

        Returns:
            处理后的图片
        """
        try:
            if image is None:
                return None

            h, w = image.shape[:2]

            if resize_mode == "原始尺寸":
                return image
            elif resize_mode == "拉伸":
                # 直接拉伸到目标尺寸，使用高质量插值
                return cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
            elif resize_mode == "适应":
                if maintain_aspect:
                    # 保持宽高比，适应目标尺寸
                    scale = min(target_width / w, target_height / h)
                    new_w = int(w * scale)
                    new_h = int(h * scale)

                    # 高质量resize
                    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

                    # 创建目标尺寸的黑色背景
                    result = np.zeros((target_height, target_width, 3), dtype=np.uint8)

                    # 计算居中位置
                    y_offset = (target_height - new_h) // 2
                    x_offset = (target_width - new_w) // 2

                    # 将resize后的图片放在中心
                    result[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized

                    return result
                else:
                    return cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
            elif resize_mode == "填充":
                # 裁剪填充模式
                scale = max(target_width / w, target_height / h)
                new_w = int(w * scale)
                new_h = int(h * scale)

                # 高质量resize
                resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

                # 计算裁剪位置（居中裁剪）
                y_start = (new_h - target_height) // 2
                x_start = (new_w - target_width) // 2

                # 裁剪到目标尺寸
                result = resized[y_start:y_start+target_height, x_start:x_start+target_width]

                return result
            else:
                # 默认使用适应模式
                return self.resize_image_hq(image, target_width, target_height, "适应", maintain_aspect)

        except Exception as e:
            print(f"高质量resize图片时出错: {str(e)}")
            # 回退到普通resize
            try:
                return cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
            except:
                return None

    def create_single_image_video(self, image_path, watermark_video_path, output_path, width, height, position="右下", match_method="循环"):
        """创建单图转视频：将单张图片与视频水印组合成视频

        Args:
            image_path: 单张图片路径
            watermark_video_path: 视频水印路径（.mov文件）
            output_path: 输出视频路径
            width: 输出视频宽度
            height: 输出视频高度
            position: 水印位置
            match_method: 水印匹配方法

        Returns:
            bool: 成功返回True，失败返回False
        """
        import traceback
        import time

        def log(msg):
            print(f"[单图转视频] {msg}")
            if hasattr(self, 'log_to_file'):
                self.log_to_file(f"[单图转视频] {msg}")

        try:
            log(f"开始单图转视频处理")
            log(f"图片: {image_path}")
            log(f"视频水印: {watermark_video_path}")
            log(f"输出: {output_path}")

            # 读取单张图片
            image = self.safe_read_image(image_path)
            if image is None:
                log(f"无法读取图片: {image_path}")
                self.update_status("无法读取图片")
                return False

            # 高质量调整图片大小
            image = self.resize_image_hq(image, width, height, "适应", True)
            if image is None:
                log(f"图片resize失败")
                self.update_status("图片处理失败")
                return False

            # 打开视频水印
            watermark_cap = cv2.VideoCapture(watermark_video_path)
            if not watermark_cap.isOpened():
                log(f"无法打开视频水印: {watermark_video_path}")
                self.update_status("无法打开视频水印")
                return False

            # 获取视频水印信息
            watermark_fps = watermark_cap.get(cv2.CAP_PROP_FPS)
            watermark_frame_count = int(watermark_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            watermark_width = int(watermark_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            watermark_height = int(watermark_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            watermark_duration = watermark_frame_count / watermark_fps if watermark_fps > 0 else 0

            log(f"视频水印信息: {watermark_width}x{watermark_height}, {watermark_fps}fps, {watermark_frame_count}帧, {watermark_duration:.2f}秒")

            # 检查是否使用FFmpeg进行高质量输出
            use_ffmpeg_for_quality = self.ffmpeg_available if hasattr(self, 'ffmpeg_available') else False
            target_bitrate = self.bitrate.get() if hasattr(self, 'bitrate') else 8000  # 默认高码率

            if use_ffmpeg_for_quality:
                log(f"使用FFmpeg创建高质量单图转视频，码率: {target_bitrate} kbps")
                return self.create_single_image_video_with_ffmpeg(
                    image_path, watermark_video_path, output_path, width, height,
                    position, watermark_fps, watermark_frame_count, target_bitrate, log
                )
            else:
                log("使用OpenCV创建单图转视频（质量由编码器决定）")

            # 创建输出视频写入器（优先用户编码器，失败时自动回退）
            selected_codec = self._resolve_processing_fourcc()
            if not selected_codec:
                log(f"编码器不可用: {self._get_selected_codec_name()}")
                self.update_status("无法创建输出视频")
                watermark_cap.release()
                return False
            if selected_codec != self._get_selected_codec_name():
                log(f"单图转视频阶段编码器映射: {self._get_selected_codec_name()} -> {selected_codec}")
            try:
                fourcc = cv2.VideoWriter_fourcc(*selected_codec)
                video_writer = cv2.VideoWriter(output_path, fourcc, watermark_fps, (width, height))
                if video_writer.isOpened():
                    log(f"使用编码器: {selected_codec}")
                else:
                    log(f"编码器 {selected_codec} 创建失败")
                    self.update_status("无法创建输出视频")
                    watermark_cap.release()
                    return False
            except Exception as e:
                log(f"编码器 {selected_codec} 失败: {str(e)}")
                self.update_status("无法创建输出视频")
                watermark_cap.release()
                return False

            log(f"开始合成视频，总帧数: {watermark_frame_count}")
            self.update_status(f"正在合成单图转视频，时长: {watermark_duration:.1f}秒...")

            # 重置进度
            if hasattr(self, 'progress_var'):
                self.reset_progress(watermark_frame_count)

            start_time = time.time()
            processed_frames = 0

            # 逐帧处理
            for frame_idx in range(watermark_frame_count):
                # 读取水印帧
                ret, watermark_frame = watermark_cap.read()
                if not ret:
                    log(f"无法读取水印帧 {frame_idx}")
                    break

                # 高质量调整水印帧大小以匹配输出尺寸
                if watermark_frame.shape[:2] != (height, width):
                    watermark_frame = cv2.resize(watermark_frame, (width, height), interpolation=cv2.INTER_LANCZOS4)

                # 将图片作为背景，水印作为前景进行高质量合成
                result_frame = self.blend_image_with_video_frame_hq(image, watermark_frame, position)

                # 写入帧
                video_writer.write(result_frame)
                processed_frames += 1

                # 更新进度
                if hasattr(self, 'progress_var'):
                    self.update_progress(processed_frames)

                # 定期更新状态
                if frame_idx % 30 == 0:  # 每30帧更新一次
                    elapsed = time.time() - start_time
                    fps = processed_frames / max(0.1, elapsed)
                    remaining = (watermark_frame_count - processed_frames) / max(1, fps)
                    progress = (processed_frames / watermark_frame_count) * 100

                    self.update_status(f"单图转视频: {progress:.1f}%, 速度: {fps:.1f}fps, 剩余: {remaining:.1f}秒")

            # 释放资源
            watermark_cap.release()
            video_writer.release()

            # 验证输出
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                total_time = time.time() - start_time
                log(f"单图转视频完成，处理了 {processed_frames} 帧，耗时 {total_time:.2f} 秒")
                self.update_status(f"单图转视频完成: {output_path}")
                return True
            else:
                log("输出视频无效")
                self.update_status("单图转视频失败：输出文件无效")
                return False

        except Exception as e:
            log(f"单图转视频处理出错: {str(e)}")
            log(traceback.format_exc())
            self.update_status(f"单图转视频失败: {str(e)}")

            # 清理资源
            try:
                if 'watermark_cap' in locals() and watermark_cap is not None:
                    watermark_cap.release()
                if 'video_writer' in locals() and video_writer is not None:
                    video_writer.release()
            except Exception:
                pass

            return False

    def blend_image_with_video_frame_hq(self, background_image, video_frame, position="右下"):
        """高质量将背景图片与视频帧进行混合

        Args:
            background_image: 背景图片
            video_frame: 视频帧
            position: 混合位置

        Returns:
            混合后的帧
        """
        try:
            # 确保两个图像尺寸相同
            if background_image.shape != video_frame.shape:
                video_frame = cv2.resize(video_frame, (background_image.shape[1], background_image.shape[0]),
                                       interpolation=cv2.INTER_LANCZOS4)

            # 转换为浮点数进行高精度计算
            bg_float = background_image.astype(np.float64)
            fg_float = video_frame.astype(np.float64)

            # 根据位置决定混合方式
            if position == "中心":
                # 中心位置：高质量alpha混合
                alpha = 0.6  # 视频帧的透明度，稍微降低以保持背景可见性
                result = bg_float * (1 - alpha) + fg_float * alpha
            elif position == "右下":
                # 右下角：将视频帧作为水印叠加
                # 创建一个基于视频帧亮度的alpha通道
                gray_fg = cv2.cvtColor(video_frame, cv2.COLOR_BGR2GRAY)
                alpha_mask = gray_fg.astype(np.float64) / 255.0
                alpha_mask = np.stack([alpha_mask, alpha_mask, alpha_mask], axis=2)

                # 使用亮度作为混合权重，保持细节
                alpha_strength = 0.7
                alpha_mask = alpha_mask * alpha_strength

                result = bg_float * (1 - alpha_mask) + fg_float * alpha_mask
            else:
                # 其他位置：智能混合
                # 检测视频帧中的主要内容区域
                gray_fg = cv2.cvtColor(video_frame, cv2.COLOR_BGR2GRAY)
                _, mask = cv2.threshold(gray_fg, 30, 255, cv2.THRESH_BINARY)
                mask_float = mask.astype(np.float64) / 255.0
                mask_3d = np.stack([mask_float, mask_float, mask_float], axis=2)

                # 在有内容的区域使用较高的混合比例
                alpha_content = 0.8
                alpha_background = 0.3

                alpha_mask = mask_3d * alpha_content + (1 - mask_3d) * alpha_background
                result = bg_float * (1 - alpha_mask) + fg_float * alpha_mask

            # 转换回uint8并确保值在有效范围内
            result = np.clip(result, 0, 255).astype(np.uint8)
            return result

        except Exception as e:
            print(f"高质量混合图像时出错: {str(e)}")
            # 如果混合失败，返回简单的alpha混合
            try:
                alpha = 0.6
                result = cv2.addWeighted(background_image, 1-alpha, video_frame, alpha, 0)
                return result
            except:
                return video_frame

    def blend_image_with_video_frame(self, background_image, video_frame, position="右下"):
        """兼容性方法：调用高质量混合方法"""
        return self.blend_image_with_video_frame_hq(background_image, video_frame, position)

    def create_single_image_video_with_ffmpeg(self, image_path, watermark_video_path, output_path,
                                            width, height, position, watermark_fps, watermark_frame_count,
                                            target_bitrate, log_func):
        """使用FFmpeg创建高质量单图转视频

        Args:
            image_path: 单张图片路径
            watermark_video_path: 视频水印路径
            output_path: 输出视频路径
            width: 输出视频宽度
            height: 输出视频高度
            position: 混合位置
            watermark_fps: 水印视频帧率
            watermark_frame_count: 水印视频帧数
            target_bitrate: 目标码率
            log_func: 日志函数

        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            import tempfile
            import shutil

            log_func(f"开始使用FFmpeg创建高质量单图转视频，码率: {target_bitrate} kbps")

            # 创建临时目录存放帧图片
            temp_dir = tempfile.mkdtemp(prefix="single_img_ffmpeg_")
            log_func(f"创建临时目录: {temp_dir}")

            try:
                # 读取单张图片
                image = self.safe_read_image(image_path)
                if image is None:
                    log_func(f"无法读取图片: {image_path}")
                    return False

                # 高质量调整图片大小
                image = cv2.resize(image, (width, height), interpolation=cv2.INTER_LANCZOS4)

                # 打开视频水印
                watermark_cap = cv2.VideoCapture(watermark_video_path)
                if not watermark_cap.isOpened():
                    log_func(f"无法打开视频水印: {watermark_video_path}")
                    return False

                log_func(f"开始生成高质量帧图片，总帧数: {watermark_frame_count}")

                if hasattr(self, 'progress_var'):
                    self.reset_progress(watermark_frame_count)

                # 逐帧处理并保存为PNG（无损）
                for frame_idx in range(watermark_frame_count):
                    # 读取水印帧
                    ret, watermark_frame = watermark_cap.read()
                    if not ret:
                        log_func(f"无法读取水印帧 {frame_idx}")
                        break

                    # 高质量调整水印帧大小
                    if watermark_frame.shape[:2] != (height, width):
                        watermark_frame = cv2.resize(watermark_frame, (width, height),
                                                   interpolation=cv2.INTER_LANCZOS4)

                    # 高质量图像混合
                    result_frame = self.blend_image_with_video_frame_hq(image, watermark_frame, position)
                    result_frame = self._ensure_even_frame(result_frame)

                    # 保存为PNG格式（无损）
                    frame_filename = os.path.join(temp_dir, f"frame_{frame_idx:06d}.png")
                    # 使用最高质量保存PNG
                    cv2.imwrite(frame_filename, result_frame, [cv2.IMWRITE_PNG_COMPRESSION, 0])

                    # 更新进度
                    if hasattr(self, 'progress_var'):
                        self.update_progress(frame_idx + 1)

                    # 定期更新状态
                    if frame_idx % 30 == 0:
                        progress = ((frame_idx + 1) / watermark_frame_count) * 100
                        self.update_status(f"生成高质量帧: {progress:.1f}%")

                watermark_cap.release()
                log_func(f"生成了 {watermark_frame_count} 帧高质量图片")

                # 使用FFmpeg将帧图片合成高质量视频
                log_func("开始使用FFmpeg合成高质量视频...")
                self.update_status("正在使用FFmpeg合成高质量视频...")

                strict_vcodec = self._get_strict_ffmpeg_vcodec_for_output(output_path)
                if not strict_vcodec:
                    log_func(
                        f"编码器与容器不兼容: codec={self._get_selected_codec_name()}, ext={self._get_output_extension(output_path)}"
                    )
                    return False
                codec_candidates = [strict_vcodec]
                muxer = self._get_ffmpeg_muxer_for_output(output_path)

                for vcodec in codec_candidates:
                    ffmpeg_cmd = [
                        getattr(self, "ffmpeg_executable", None) or "ffmpeg", "-y",  # 覆盖输出文件
                        "-framerate", str(watermark_fps),  # 输入帧率
                        "-i", os.path.join(temp_dir, "frame_%06d.png"),  # 输入图片序列
                        "-c:v", vcodec,
                    ]
                    if vcodec == "libx264":
                        ffmpeg_cmd += [
                            "-preset", "slow",
                            "-crf", "18",
                            "-profile:v", "high",
                            "-level", "4.1",
                        ]
                    ffmpeg_cmd += [
                        "-b:v", f"{target_bitrate}k",
                        "-maxrate", f"{int(target_bitrate * 1.2)}k",
                        "-bufsize", f"{int(target_bitrate * 2)}k",
                        "-pix_fmt", "yuv420p",
                        "-r", str(watermark_fps),
                    ]
                    if muxer:
                        ffmpeg_cmd += ["-f", muxer]
                    ffmpeg_cmd += [output_path]

                    log_func(f"FFmpeg高质量命令[{vcodec}]: {' '.join(ffmpeg_cmd)}")
                    result = subprocess.run(
                        ffmpeg_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        startupinfo=self.startupinfo if hasattr(self, 'startupinfo') else None
                    )

                    if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                        log_func(f"FFmpeg高质量视频合成成功，编码器={vcodec}")
                        log_func(f"高质量单图转视频完成: {output_path}")
                        log_func(f"文件大小: {os.path.getsize(output_path)} 字节")
                        self._log_output_probe(output_path, log_func)
                        self.update_status(f"高质量单图转视频完成: {output_path}")
                        return True

                    stderr_output = result.stderr.decode('utf-8', errors='ignore')
                    log_func(f"FFmpeg执行失败[{vcodec}]，错误码: {result.returncode}")
                    log_func(f"错误信息: {stderr_output[:300]}")

                log_func("所有容器兼容编码器均失败")
                return False

            finally:
                # 清理临时目录
                try:
                    shutil.rmtree(temp_dir)
                    log_func(f"清理临时目录: {temp_dir}")
                except Exception as e:
                    log_func(f"清理临时目录失败: {str(e)}")

        except Exception as e:
            log_func(f"使用FFmpeg创建高质量单图转视频时出错: {str(e)}")
            import traceback
            log_func(traceback.format_exc())
            return False

    def create_video_with_ffmpeg(self, images, output_path, duration, fps, width, height,
                                apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                                transition_frames, transition_type, watermark_opacity,
                                watermark_size, target_bitrate, log_func, video_effect_type_override=None,
                                preprocessed_images=None):
        """使用FFmpeg创建视频并控制码率

        Args:
            images: 图片文件路径列表
            output_path: 输出视频文件路径
            duration: 每张图片的显示时长（秒）
            fps: 视频帧率
            width: 视频宽度
            height: 视频高度
            apply_image_watermark: 是否应用图片水印
            watermark_images: 水印图片列表
            watermark_position: 水印位置
            transition_frames: 转场帧数
            transition_type: 转场效果类型
            watermark_opacity: 水印不透明度
            watermark_size: 水印大小百分比
            target_bitrate: 目标码率（kbps）
            log_func: 日志函数
            preprocessed_images: 与 images 对齐的预处理帧列表（可选，用于复用Turbo预处理结果）

        Returns:
            bool: 成功返回True，失败返回False
        """
        ffmpeg_proc = None
        try:
            log_func(f"开始使用FFmpeg管道创建视频，目标码率: {target_bitrate} kbps")

            strict_vcodec = self._get_strict_ffmpeg_vcodec_for_output(output_path)
            if not strict_vcodec:
                log_func(
                    f"编码器与容器不兼容: codec={self._get_selected_codec_name()}, ext={self._get_output_extension(output_path)}"
                )
                return False
            muxer = self._get_ffmpeg_muxer_for_output(output_path)
            ffmpeg_cmd = [
                getattr(self, "ffmpeg_executable", None) or "ffmpeg", "-y",
                "-f", "rawvideo",
                "-pix_fmt", "bgr24",
                "-s", f"{width}x{height}",
                "-r", str(fps),
                "-i", "-",
                "-an",
                "-c:v", strict_vcodec,
                "-b:v", f"{target_bitrate}k",
                "-maxrate", f"{int(target_bitrate * 1.1)}k",
                "-bufsize", f"{int(target_bitrate * 1.5)}k",
                "-pix_fmt", "yuv420p",
                "-r", str(fps),
            ]
            if strict_vcodec == "libx264":
                ffmpeg_cmd += ["-preset", "medium"]
            if muxer:
                ffmpeg_cmd += ["-f", muxer]
            ffmpeg_cmd += [output_path]
            log_func(f"管道编码命令[{strict_vcodec}]: {' '.join(ffmpeg_cmd)}")

            ffmpeg_proc = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=self.startupinfo if hasattr(self, "startupinfo") else None,
            )

            total_images = len(images)
            total_time_per_img = duration
            total_frames_per_img = int(total_time_per_img * fps)
            transition_frames = min(transition_frames, total_frames_per_img // 3)
            display_frames_per_img = total_frames_per_img - transition_frames
            if display_frames_per_img < fps // 2:
                display_frames_per_img = fps // 2
                transition_frames = total_frames_per_img - display_frames_per_img
            total_frames = total_images * total_frames_per_img
            static_time = display_frames_per_img / fps
            transition_time = transition_frames / fps
            log_func(
                f"每张图片总时长: {total_time_per_img}秒 (静态: {static_time:.2f}秒 + 转场: {transition_time:.2f}秒), "
                f"总帧数: {total_frames}, 实际视频时长: {total_frames / max(1, fps):.2f}秒"
            )
            if hasattr(self, 'progress_var'):
                render_weight = 0.82 if self._has_postprocess_work(fixed_layers) else 1.0
                self.reset_progress(total_frames, render_weight=render_weight)

            frame_count = 0
            # 降低 UI/桥接更新频率，减少导出过程中 Python 与 GUI 开销。
            progress_interval = max(12, min(60, int(max(1, fps) // 2)))
            use_preprocessed_frames = (
                isinstance(preprocessed_images, list)
                and len(preprocessed_images) == len(images)
            )
            if preprocessed_images is not None and not use_preprocessed_frames:
                log_func("预处理帧数量与图片数量不一致，回退实时读取链路")
            if use_preprocessed_frames:
                log_func("FFmpeg渲染复用Turbo预处理帧，跳过重复读图/缩放/跟随水印")
            effect_type_for_video = (
                video_effect_type_override
                if video_effect_type_override in VIDEO_EFFECTS
                else self.video_effect_type.get()
            )
            effect_enabled = (
                hasattr(self, 'use_video_effect')
                and self.use_video_effect.get()
                and effect_type_for_video != "无特效"
            )

            def ensure_runtime_control():
                if not self._wait_for_processing_control():
                    raise InterruptedError("用户取消处理")

            def write_frame(frame):
                nonlocal frame_count
                ensure_runtime_control()
                frame = self._ensure_even_frame(frame)
                if frame is None:
                    return False
                h, w = frame.shape[:2]
                if w != width or h != height:
                    frame = cv2.resize(frame, (width, height))
                if ffmpeg_proc.stdin is None:
                    return False
                ffmpeg_proc.stdin.write(frame.tobytes())
                frame_count += 1
                if frame_count % progress_interval == 0:
                    self.update_progress(frame_count)
                return True

            def load_processed_frame(img_path, image_index):
                if use_preprocessed_frames:
                    frame = preprocessed_images[image_index]
                    if frame is None:
                        log_func(f"预处理帧为空，跳过: {img_path}")
                        return None
                    return self._ensure_even_frame(frame)

                frame = self.safe_read_image(img_path)
                if frame is None:
                    log_func(f"无法加载图片: {img_path}")
                    return None
                frame = self.resize_image(frame, width, height, "适应", True)
                if frame is None:
                    log_func(f"图片resize失败: {img_path}")
                    return None
                if follow_layers:
                    frame = self.apply_image_watermark_layers(
                        frame, follow_layers, image_index=image_index
                    )
                return self._ensure_even_frame(frame)

            for img_index, img_path in enumerate(images):
                ensure_runtime_control()
                log_func(f"处理图片 {img_index + 1}/{total_images}: {os.path.basename(img_path)}")
                current_img = load_processed_frame(img_path, img_index)
                if current_img is None:
                    continue

                if effect_enabled:
                    effect_frames = max(1, display_frames_per_img)
                    duration_sec = max(0.001, effect_frames / max(1, fps))
                    for frame_idx in range(effect_frames):
                        ensure_runtime_control()
                        time_sec = frame_idx / max(1, fps)
                        frame = self.apply_single_image_effect(
                            current_img,
                            effect_type_for_video,
                            time_sec,
                            duration_sec,
                            self.video_effect_intensity.get(),
                            self.video_effect_speed.get()
                        )
                        if not write_frame(frame):
                            raise BrokenPipeError("FFmpeg管道写入失败")
                else:
                    for _ in range(display_frames_per_img):
                        ensure_runtime_control()
                        if not write_frame(current_img):
                            raise BrokenPipeError("FFmpeg管道写入失败")

                if img_index < total_images - 1:
                    ensure_runtime_control()
                    next_img_path = images[img_index + 1]
                    next_img = load_processed_frame(next_img_path, img_index + 1)
                    if next_img is not None:
                        if transition_frames > 0 and transition_type != "无转场":
                            transition_frames_list = None
                            if self.transition_engine:
                                try:
                                    transition_frames_list = self.transition_engine.generate_transition_frames(
                                        current_img, next_img, transition_type, transition_frames, use_cache=True
                                    )
                                except Exception as trans_err:
                                    log_func(f"转场引擎失败，回退基础转场: {str(trans_err)}")
                                    transition_frames_list = None

                            if transition_frames_list:
                                for transition_frame in transition_frames_list:
                                    ensure_runtime_control()
                                    if not write_frame(transition_frame):
                                        raise BrokenPipeError("FFmpeg管道写入失败")
                            else:
                                # 回退：至少保持可见过渡
                                for t_frame in range(transition_frames):
                                    ensure_runtime_control()
                                    progress = (t_frame + 1) / (transition_frames + 1)
                                    transition_frame = cv2.addWeighted(
                                        current_img, 1 - progress, next_img, progress, 0
                                    )
                                    if not write_frame(transition_frame):
                                        raise BrokenPipeError("FFmpeg管道写入失败")
                else:
                    for _ in range(transition_frames):
                        ensure_runtime_control()
                        if not write_frame(current_img):
                            raise BrokenPipeError("FFmpeg管道写入失败")

            if ffmpeg_proc.stdin:
                ffmpeg_proc.stdin.close()
                ffmpeg_proc.stdin = None
            # 结束前强制刷新一次进度，保证 UI 最终状态准确。
            self.update_progress(frame_count)
            _, stderr_data = ffmpeg_proc.communicate()
            if ffmpeg_proc.returncode != 0:
                stderr_output = stderr_data.decode('utf-8', errors='ignore') if stderr_data else ""
                log_func(f"FFmpeg管道编码失败[{strict_vcodec}]，错误码: {ffmpeg_proc.returncode}")
                log_func(f"错误信息: {stderr_output[:300]}")
                return False

            log_func(f"FFmpeg管道写入完成，共输出 {frame_count} 帧")
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                log_func(f"FFmpeg视频合成成功，编码器={strict_vcodec}")
                log_func(f"视频文件创建成功: {output_path}")
                log_func(f"文件大小: {os.path.getsize(output_path)} 字节")
                self._log_output_probe(output_path, log_func)
                if fixed_layers:
                    self.add_fixed_image_watermarks_to_video(output_path, fixed_layers)
                return True

            log_func("FFmpeg管道编码结束但输出文件无效")
            return False

        except InterruptedError:
            try:
                if ffmpeg_proc is not None:
                    if ffmpeg_proc.stdin:
                        ffmpeg_proc.stdin.close()
                    ffmpeg_proc.terminate()
                    try:
                        ffmpeg_proc.wait(timeout=2)
                    except Exception:
                        ffmpeg_proc.kill()
            except Exception:
                pass
            log_func("已取消当前视频生成")
            return False
        except Exception as e:
            try:
                if ffmpeg_proc is not None:
                    if ffmpeg_proc.stdin:
                        ffmpeg_proc.stdin.close()
                    ffmpeg_proc.kill()
            except Exception:
                pass
            log_func(f"使用FFmpeg管道创建视频时出错: {str(e)}")
            import traceback
            log_func(traceback.format_exc())
            return False
    
    def process_videos(self):
        """处理视频生成 - 主要处理逻辑"""
        try:
            # 获取参数
            input_dir = self.input_dir.get().strip()
            output_dir = self.output_dir.get().strip()
            num_images = self.num_images.get()
            video_count = self.video_count.get()
            selection_mode = self.image_selection_mode.get()  # 获取图片选择方式

            try:
                timeline_slot_count(self.duration.get(), self.total_duration.get())
            except ValueError as exc:
                self.update_status(str(exc))
                return False
            
            # 参数验证
            if not input_dir:
                self.update_status("请选择输入目录")
                return False
            
            if not os.path.exists(input_dir):
                self.update_status("输入目录不存在")
                return False
            
            if not output_dir:
                self.update_status("请选择输出目录")
                return False

            # 严格编码器-容器兼容性校验（主渲染与后处理统一）
            probe_output = os.path.join(output_dir, f"probe{('.' + self.video_format.get().lstrip('.'))}")
            strict_codec = self._get_strict_ffmpeg_vcodec_for_output(probe_output)
            if not strict_codec:
                self.update_status(
                    f"编码器/容器不兼容：编码器={self._get_selected_codec_name()}，格式={self.video_format.get()}，请调整后重试"
                )
                return False
            
            # 创建输出目录
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
            
            # 获取图片列表
            self.update_status(f"正在获取图片列表（模式：{selection_mode}）...")
            all_images = self.get_images_list(input_dir, limit_count=None, selection_mode=selection_mode)
            
            if not all_images:
                self.update_status("目录中没有找到图片文件")
                return False
            
            # 检查图片数量
            if selection_mode == "按名称排序":
                min_required = video_count * num_images
                if len(all_images) < min_required:
                    self.update_status(f"图片数量不足，共有{len(all_images)}张，生成{video_count}个视频需要{min_required}张（每个{num_images}张）")
                    return False
            else:
                if len(all_images) < num_images:
                    self.update_status(f"图片数量不足，只有{len(all_images)}张，需要{num_images}张")
                    return False
                # 随机选择模式下，要求每个视频首图不重复。
                if len(all_images) < video_count:
                    self.update_status(
                        f"图片数量不足以保证首图不重复：共有{len(all_images)}张，计划生成{video_count}个视频"
                    )
                    return False
            
            self.update_status(f"找到{len(all_images)}张图片，将生成{video_count}个视频")
            
            # 生成多个视频
            successful_videos = 0
            overall_start_ts = time.time()
            self._task_start_ts = overall_start_ts
            self.reset_overall_progress(video_count)
            self._maybe_realtime_cleanup(force=True)
            used_first_images = set()
            transition_plan = []
            if self.use_transition.get() and self.random_transition.get():
                transition_plan = self._build_random_transition_plan(video_count)
                if transition_plan:
                    self.update_status(f"[RANDOM] 已生成转场计划: {' | '.join(transition_plan)}")
            for video_index in range(video_count):
                if self.cancel_requested:
                    self.update_status("已取消处理")
                    return False
                self.pause_event.wait()
                self.current_video_index = video_index
                self._maybe_realtime_cleanup()
                self.update_status(f"正在生成第{video_index + 1}个视频...")
                
                # 根据选择模式获取图片
                if selection_mode == "按名称排序":
                    start_index = video_index * num_images
                    selected_images = []
                    for i in range(num_images):
                        if self.cancel_requested:
                            self.update_status("已取消处理")
                            return False
                        self.pause_event.wait()
                        img_index = start_index + i
                        if img_index < len(all_images):
                            selected_images.append(all_images[img_index])
                    
                    self.update_status(f"第{video_index + 1}个视频使用图片 {start_index+1}-{start_index+len(selected_images)}: {[os.path.basename(img) for img in selected_images]}")
                else:
                    import random
                    # 先随机首图（未使用过），再补齐剩余图片，确保“首图不重复”。
                    first_candidates = [img for img in all_images if img not in used_first_images]
                    if not first_candidates:
                        self.update_status("随机首图池已耗尽，无法继续保证首图不重复")
                        return False
                    first_image = random.choice(first_candidates)
                    used_first_images.add(first_image)

                    target_count = min(num_images, len(all_images))
                    remain_need = max(0, target_count - 1)
                    remain_pool = [img for img in all_images if img != first_image]
                    remain_images = random.sample(remain_pool, min(remain_need, len(remain_pool)))
                    selected_images = [first_image] + remain_images
                    self.update_status(f"第{video_index + 1}个视频随机选择图片: {[os.path.basename(img) for img in selected_images]}")

                source_image_count = len(selected_images)
                selected_images = cycle_images_to_duration(
                    selected_images,
                    self.duration.get(),
                    self.total_duration.get(),
                )
                if len(selected_images) != source_image_count:
                    self.update_status(
                        f"第{video_index + 1}个视频按总时长循环为 {len(selected_images)} 个图片片段"
                    )
                
                if hasattr(self, 'progress_info_var'):
                    self.progress_info_var.set(f"视频进度: {video_index + 1}/{video_count}")
                
                # 生成输出文件名：连接符统一为 "-"、末尾序号不补零、
                # 前缀为空不注入默认文案（见 src/utils/naming.py）
                from ..utils.naming import compose_output_filename

                first_image_name = ""
                if selected_images:
                    first_image_name = os.path.splitext(os.path.basename(selected_images[0]))[0]
                output_filename = compose_output_filename(
                    use_date_prefix=self.use_date_prefix.get(),
                    use_first_image_name=self.use_first_image_name.get(),
                    first_image_name=first_image_name,
                    custom_prefix=self.custom_prefix.get(),
                    index=video_index + 1,
                    video_format=self.video_format.get(),
                )
                
                output_path = os.path.join(output_dir, output_filename)
                
                # 调用创建视频方法 - 修复转场效果和Turbo加速
                # 检查转场效果是否启用
                transition_frames = 15 if self.use_transition.get() else 0
                
                # 处理随机转场
                if self.use_transition.get():
                    if self.random_transition.get():
                        transition_type = (
                            transition_plan[video_index]
                            if video_index < len(transition_plan)
                            else "淡入淡出"
                        )
                        self.update_status(f"[RANDOM] 第{video_index + 1}个视频随机转场: {transition_type}")
                    else:
                        transition_type = self.transition_type.get()
                else:
                    transition_type = "无转场"

                # 处理随机特效（按视频随机一次）
                video_effect_type_for_video = self.video_effect_type.get()
                random_effect_enabled = (
                    self.use_video_effect.get()
                    and self.random_video_effect.get()
                    and int(video_count) >= 1
                )
                if random_effect_enabled:
                    enabled_effects = self.get_enabled_video_effects()
                    if enabled_effects:
                        video_effect_type_for_video = random.choice(enabled_effects)
                        self.update_status(f"[RANDOM] 第{video_index + 1}个视频随机特效: {video_effect_type_for_video}")
                
                self.update_status(
                    f"第{video_index + 1}个视频 - 转场: {transition_type}, 特效: {video_effect_type_for_video}, 帧数: {transition_frames}"
                )
                
                # 设置当前视频索引，供视频水印文件夹模式使用
                self._current_video_index = video_index
                per_video_start_ts = time.time()
                
                success = self.create_video_turbo_enhanced(
                    selected_images,
                    output_path,
                    self.duration.get(),
                    self.fps.get(),
                    self.width.get(),
                    self.height.get(),
                    bool(self.watermark_layers),
                    None,
                    self.watermark_position.get(),
                    "适应",  # resize_mode
                    self.keep_aspect_ratio.get(),
                    transition_frames,  # 使用动态计算的转场帧数
                    transition_type,    # 使用动态计算的转场类型
                    0.5,  # watermark_opacity
                    20,  # watermark_size
                    video_effect_type_for_video
                )
                
                if success:
                    successful_videos += 1
                    per_video_elapsed = max(0.0, time.time() - per_video_start_ts)
                    self.update_status(f"成功生成第{video_index + 1}个视频: {output_filename}，耗时 {per_video_elapsed:.1f} 秒")
                else:
                    per_video_elapsed = max(0.0, time.time() - per_video_start_ts)
                    self.update_status(f"生成第{video_index + 1}个视频失败，耗时 {per_video_elapsed:.1f} 秒")
                self._maybe_realtime_cleanup()
            
            # 显示最终结果
            if hasattr(self, 'overall_progress_var'):
                self.overall_progress_var.set(100)
            if hasattr(self, 'overall_progress_info_var'):
                self.overall_progress_info_var.set("总进度: 100%")
            if successful_videos > 0:
                overall_elapsed = max(0.0, time.time() - overall_start_ts)
                self.update_status(f"处理完成！成功生成{successful_videos}个视频（共{video_count}个），总耗时 {overall_elapsed:.1f} 秒")
                if not getattr(self, "batch_mode", False) and not getattr(self, "_completion_notified", False):
                    self._completion_notified = True
                    if hasattr(self, "detail_info_var"):
                        self.detail_info_var.set(f"状态: 处理完成（共{successful_videos}个，耗时 {overall_elapsed:.1f} 秒）")
                if hasattr(self, 'batch_mode') and self.batch_mode and hasattr(self, 'parent_update_status'):
                    self.parent_update_status(f"标签页处理完成：成功生成{successful_videos}个视频", True)
                    self.batch_mode = False
                
                return True
            else:
                self.update_status("所有视频生成都失败！")
                return False
                
        except Exception as e:
            import traceback
            error_msg = f"处理视频时出错: {str(e)}\n{traceback.format_exc()}"
            self.update_status(error_msg)
            print(error_msg)
            return False
        finally:
            self.is_processing = False
            if hasattr(self, 'start_button'):
                self.start_button.config(state='normal')
    
    def start_processing(self):
        """开始处理 - 启动处理线程"""
        if getattr(self, 'is_processing', False):
            self.update_status("正在处理中，请等待...")
            return
        
        # 同步多重水印配置
        self.sync_watermark_layers_from_ui()
        
        # 设置处理状态
        self.is_processing = True
        self.cancel_requested = False
        self.pause_event.set()
        self.is_paused = False
        self._completion_notified = False
        
        # 禁用开始按钮
        if hasattr(self, 'start_button'):
            self.start_button.config(state='disabled')
        if hasattr(self, 'pause_button'):
            self.pause_button.config(state='normal', text="⏸ 暂停")
        if hasattr(self, 'cancel_button'):
            self.cancel_button.config(state='normal')
        
        # 在新线程中运行处理
        def run_processing():
            try:
                self.process_videos()
            except Exception as e:
                import traceback
                error_msg = f"处理过程中出错: {str(e)}\n{traceback.format_exc()}"
                self.update_status(error_msg)
                print(error_msg)
            finally:
                self.is_processing = False
                if hasattr(self, 'parent'):
                    self.parent.after(0, lambda: setattr(getattr(self, 'start_button', None), 'state', 'normal') if hasattr(self, 'start_button') else None)
                if hasattr(self, 'pause_button'):
                    self.parent.after(0, lambda: self.pause_button.config(state='disabled', text="⏸ 暂停"))
                if hasattr(self, 'cancel_button'):
                    self.parent.after(0, lambda: self.cancel_button.config(state='disabled'))
        
        # 启动处理线程
        self.processing_thread = threading.Thread(target=run_processing, daemon=True)
        self.processing_thread.start()
        
        return True
    
    def stop_processing(self):
        """停止处理 - 兼容性方法"""
        if hasattr(self, 'is_processing'):
            self.is_processing = False
        
        if hasattr(self, 'start_button'):
            self.start_button.config(state='normal')
        
        return True

    def toggle_pause(self):
        """暂停/继续处理"""
        if not getattr(self, 'is_processing', False):
            return
        if self.is_paused:
            self.pause_event.set()
            self.is_paused = False
            self.update_status("继续处理")
            if hasattr(self, 'pause_button'):
                self.pause_button.config(text="⏸ 暂停")
        else:
            self.pause_event.clear()
            self.is_paused = True
            self.update_status("已暂停")
            if hasattr(self, 'pause_button'):
                self.pause_button.config(text="▶ 继续")

    def cancel_processing(self):
        """取消处理"""
        if not getattr(self, 'is_processing', False):
            return
        self.cancel_requested = True
        self.pause_event.set()
        self.update_status("已请求取消")
    
    def reload_config(self):
        """重新加载配置 - 兼容性方法"""
        try:
            if hasattr(self, 'config_file') and os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 应用配置
                    if hasattr(self, 'apply_config'):
                        self.apply_config(config)
            return True
        except Exception as e:
            print(f"重新加载配置失败: {str(e)}")
            return False
