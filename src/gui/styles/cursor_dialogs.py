#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自定义对话框和弹窗
支持iOS浅色主题
"""

import tkinter as tk
from tkinter import ttk

# 尝试导入iOS主题，如果不可用则使用Cursor主题
try:
    from .ios_light_theme import IOSLightTheme as ThemeColors
except:
    try:
        from .cursor_theme import CursorTheme as ThemeColors
    except:
        # 默认主题
        class ThemeColors:
            COLORS = {
                'bg_primary': '#FFFFFF',
                'text_primary': '#000000',
                'accent': '#007AFF',
            }


class CursorMessageBox:
    """Cursor 风格的消息框"""
    
    @staticmethod
    def showinfo(title, message, parent=None):
        """显示信息对话框"""
        return CursorMessageBox._show_dialog(title, message, "info", parent)
    
    @staticmethod
    def showwarning(title, message, parent=None):
        """显示警告对话框"""
        return CursorMessageBox._show_dialog(title, message, "warning", parent)
    
    @staticmethod
    def showerror(title, message, parent=None):
        """显示错误对话框"""
        return CursorMessageBox._show_dialog(title, message, "error", parent)
    
    @staticmethod
    def askyesno(title, message, parent=None):
        """显示是/否对话框"""
        return CursorMessageBox._show_dialog(title, message, "question", parent, buttons=["是", "否"])
    
    @staticmethod
    def askokcancel(title, message, parent=None):
        """显示确定/取消对话框"""
        return CursorMessageBox._show_dialog(title, message, "question", parent, buttons=["确定", "取消"])
    
    @staticmethod
    def _show_dialog(title, message, dialog_type, parent=None, buttons=None):
        """内部方法：显示对话框"""
        if buttons is None:
            buttons = ["确定"]
        
        # 创建顶层窗口
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog.configure(bg=ThemeColors.COLORS['bg_primary'])
        dialog.resizable(False, False)
        
        # 设置窗口大小和位置
        dialog_width = 450
        dialog_height = 200
        
        if parent:
            parent_x = parent.winfo_x()
            parent_y = parent.winfo_y()
            parent_width = parent.winfo_width()
            parent_height = parent.winfo_height()
            x = parent_x + (parent_width - dialog_width) // 2
            y = parent_y + (parent_height - dialog_height) // 2
        else:
            screen_width = dialog.winfo_screenwidth()
            screen_height = dialog.winfo_screenheight()
            x = (screen_width - dialog_width) // 2
            y = (screen_height - dialog_height) // 2
        
        dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
        
        # 设置为模态窗口
        dialog.transient(parent)
        dialog.grab_set()
        
        # 图标映射
        icon_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "question": "❓"
        }
        
        # 主容器
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(0, weight=1)
        main_frame = ttk.Frame(dialog, style='TFrame', padding=24)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=1)
        
        # 图标和消息区域
        content_frame = ttk.Frame(main_frame, style='TFrame')
        content_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 20))
        content_frame.grid_columnconfigure(1, weight=1)
        
        # 对话框专用标签样式（避免主题缺失导致看不见）
        try:
            style = ttk.Style()
            style.configure(
                'Dialog.TLabel',
                background=ThemeColors.COLORS['bg_primary'],
                foreground=ThemeColors.COLORS['text_primary']
            )
        except Exception:
            pass

        # 图标
        icon_label = ttk.Label(
            content_frame, 
            text=icon_map.get(dialog_type, "ℹ️"),
            font=('Segoe UI', 32),
            style='Dialog.TLabel'
        )
        icon_label.grid(row=0, column=0, sticky="nw", padx=(0, 16))
        
        # 消息文本
        message_label = ttk.Label(
            content_frame,
            text=message,
            wraplength=350,
            justify=tk.LEFT,
            style='Dialog.TLabel'
        )
        message_label.grid(row=0, column=1, sticky="nsew")
        
        # 按钮区域
        button_frame = ttk.Frame(main_frame, style='TFrame')
        button_frame.grid(row=1, column=0, sticky="ew")
        button_frame.grid_columnconfigure(0, weight=1)
        
        # 结果变量
        result = [None]
        
        def on_button_click(button_text):
            result[0] = button_text
            dialog.destroy()
        
        # 创建按钮
        for i, button_text in enumerate(buttons):
            if i == 0:
                # 第一个按钮使用主按钮样式
                btn = ThemeColors.create_primary_button(
                    button_frame,
                    button_text,
                    lambda bt=button_text: on_button_click(bt)
                )
            else:
                # 其他按钮使用次要样式
                btn = ttk.Button(
                    button_frame,
                    text=button_text,
                    command=lambda bt=button_text: on_button_click(bt)
                )
            btn.grid(row=0, column=len(buttons) - i, sticky="e", padx=(8, 0) if i > 0 else (0, 0))
        
        # 绑定ESC键
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        
        # 等待窗口关闭
        dialog.wait_window()
        
        # 返回结果
        if len(buttons) == 1:
            return True
        else:
            return result[0] == buttons[0]


class CursorInputDialog:
    """Cursor 风格的输入对话框"""
    
    @staticmethod
    def askstring(title, prompt, parent=None, initialvalue="", **kwargs):
        """显示字符串输入对话框"""
        # 创建顶层窗口
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog.configure(bg=ThemeColors.COLORS['bg_primary'])
        dialog.resizable(False, False)
        
        # 设置窗口大小和位置
        dialog_width = 400
        dialog_height = 180
        
        if parent:
            parent_x = parent.winfo_x()
            parent_y = parent.winfo_y()
            parent_width = parent.winfo_width()
            parent_height = parent.winfo_height()
            x = parent_x + (parent_width - dialog_width) // 2
            y = parent_y + (parent_height - dialog_height) // 2
        else:
            screen_width = dialog.winfo_screenwidth()
            screen_height = dialog.winfo_screenheight()
            x = (screen_width - dialog_width) // 2
            y = (screen_height - dialog_height) // 2
        
        dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
        
        # 设置为模态窗口
        dialog.transient(parent)
        dialog.grab_set()
        
        # 主容器
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(0, weight=1)
        main_frame = ttk.Frame(dialog, style='TFrame', padding=24)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=1)

        # 对话框专用标签样式
        try:
            style = ttk.Style()
            style.configure(
                'Dialog.TLabel',
                background=ThemeColors.COLORS['bg_primary'],
                foreground=ThemeColors.COLORS['text_primary']
            )
        except Exception:
            pass
        
        # 提示文本
        prompt_label = ttk.Label(
            main_frame,
            text=prompt,
            style='Dialog.TLabel'
        )
        prompt_label.grid(row=0, column=0, sticky="w", pady=(0, 12))
        
        # 输入框
        entry_var = tk.StringVar(value=initialvalue)
        entry = ttk.Entry(
            main_frame,
            textvariable=entry_var,
            font=('Segoe UI', 10)
        )
        entry.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        entry.focus_set()
        entry.select_range(0, tk.END)
        
        # 按钮区域
        button_frame = ttk.Frame(main_frame, style='TFrame')
        button_frame.grid(row=2, column=0, sticky="ew")
        button_frame.grid_columnconfigure(0, weight=1)
        
        # 结果变量
        result = [None]
        
        def on_ok():
            result[0] = entry_var.get()
            dialog.destroy()
        
        def on_cancel():
            result[0] = None
            dialog.destroy()
        
        # 创建按钮
        cancel_btn = ttk.Button(
            button_frame,
            text="取消",
            command=on_cancel
        )
        cancel_btn.grid(row=0, column=1, sticky="e", padx=(8, 0))
        
        ok_btn = ThemeColors.create_primary_button(
            button_frame,
            "确定",
            on_ok
        )
        ok_btn.grid(row=0, column=2, sticky="e")
        
        # 绑定快捷键
        entry.bind('<Return>', lambda e: on_ok())
        dialog.bind('<Escape>', lambda e: on_cancel())
        
        # 等待窗口关闭
        dialog.wait_window()
        
        return result[0]

