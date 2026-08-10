#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件浏览器组件
支持图片文件选择、预览、拖拽等功能
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import List, Dict, Callable, Optional
from pathlib import Path
import os

class FileBrowser(ttk.Frame):
    """文件浏览器组件"""
    
    def __init__(self, parent, file_types=None, multi_select=True, preview_enabled=True):
        super().__init__(parent)
        
        # 配置
        self.file_types = file_types or [
            ("图片文件", "*.jpg *.jpeg *.png *.bmp *.gif *.tiff"),
            ("所有文件", "*.*")
        ]
        self.multi_select = multi_select
        self.preview_enabled = preview_enabled
        
        # 数据
        self.file_list: List[str] = []
        self.selected_files: List[str] = []
        
        # 回调函数
        self.selection_change_callback: Optional[Callable] = None
        self.file_add_callback: Optional[Callable] = None
        self.file_remove_callback: Optional[Callable] = None
        
        self._create_widgets()
    
    def _create_widgets(self):
        """创建界面组件"""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # 工具栏
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        for col in range(4):
            toolbar.grid_columnconfigure(col, weight=0)
        
        ttk.Button(toolbar, text="添加文件", command=self.add_files).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Button(toolbar, text="添加文件夹", command=self.add_folder).grid(row=0, column=1, sticky="w", padx=(0, 8))
        ttk.Button(toolbar, text="移除选中", command=self.remove_selected).grid(row=0, column=2, sticky="w", padx=(0, 8))
        ttk.Button(toolbar, text="清空列表", command=self.clear_all).grid(row=0, column=3, sticky="w")
        
        # 文件列表区域
        list_frame = ttk.Frame(self)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        # 文件列表
        self.file_listbox = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED if self.multi_select else tk.SINGLE,
            height=10
        )
        self.file_listbox.grid(row=0, column=0, sticky="nsew")
        
        # 滚动条
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.file_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.file_listbox.config(yscrollcommand=scrollbar.set)
        
        # 绑定事件
        self.file_listbox.bind("<<ListboxSelect>>", self._on_selection_change)
        self.file_listbox.bind("<Double-Button-1>", self._on_double_click)
        
        # 状态栏
        self.status_var = tk.StringVar(value="文件列表为空")
        status_bar = ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        
        # 启用拖拽（如果支持）
        self._setup_drag_drop()
    
    def _setup_drag_drop(self):
        """设置拖拽功能"""
        try:
            # 尝试启用文件拖拽
            self.file_listbox.drop_target_register(tk.DND_FILES)
            self.file_listbox.dnd_bind('<<Drop>>', self._on_drop)
        except:
            # 如果拖拽不可用，跳过
            pass
    
    def _on_drop(self, event):
        """拖拽文件处理"""
        try:
            files = event.data.split()
            valid_files = []
            
            for file_path in files:
                file_path = file_path.strip('{}')  # 移除可能的大括号
                path = Path(file_path)
                
                if path.is_file() and self._is_valid_file(path):
                    valid_files.append(str(path))
                elif path.is_dir():
                    # 如果是文件夹，添加其中的图片文件
                    folder_files = self._get_files_from_folder(path)
                    valid_files.extend(folder_files)
            
            if valid_files:
                self.add_files_from_list(valid_files)
        except Exception as e:
            messagebox.showerror("拖拽错误", f"处理拖拽文件时出错: {e}")
    
    def _is_valid_file(self, file_path: Path) -> bool:
        """检查文件是否有效"""
        if not file_path.exists():
            return False
        
        # 检查文件扩展名
        valid_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp']
        return file_path.suffix.lower() in valid_extensions
    
    def _get_files_from_folder(self, folder_path: Path) -> List[str]:
        """从文件夹获取图片文件"""
        files = []
        try:
            for file_path in folder_path.iterdir():
                if file_path.is_file() and self._is_valid_file(file_path):
                    files.append(str(file_path))
        except Exception as e:
            print(f"扫描文件夹失败 {folder_path}: {e}")
        
        return sorted(files)
    
    def _on_selection_change(self, event):
        """列表选择变更处理"""
        selection = self.file_listbox.curselection()
        self.selected_files = [self.file_list[i] for i in selection]
        
        # 更新状态栏
        if self.selected_files:
            count = len(self.selected_files)
            self.status_var.set(f"已选择 {count} 个文件")
        else:
            total = len(self.file_list)
            self.status_var.set(f"共 {total} 个文件")
        
        # 触发回调
        if self.selection_change_callback:
            self.selection_change_callback(self.selected_files)
    
    def _on_double_click(self, event):
        """双击处理"""
        selection = self.file_listbox.curselection()
        if selection:
            file_path = self.file_list[selection[0]]
            self._preview_file(file_path)
    
    def _preview_file(self, file_path: str):
        """预览文件"""
        if not self.preview_enabled:
            return
        
        try:
            # 这里可以实现文件预览功能
            # 暂时使用系统默认程序打开
            os.startfile(file_path)
        except Exception as e:
            messagebox.showerror("预览错误", f"无法预览文件: {e}")
    
    def _update_listbox(self):
        """更新列表框显示"""
        self.file_listbox.delete(0, tk.END)
        
        for file_path in self.file_list:
            # 只显示文件名
            display_name = Path(file_path).name
            self.file_listbox.insert(tk.END, display_name)
        
        # 更新状态栏
        total = len(self.file_list)
        self.status_var.set(f"共 {total} 个文件")
    
    # 公共API
    def add_files(self):
        """添加文件"""
        files = filedialog.askopenfilenames(
            title="选择图片文件",
            filetypes=self.file_types
        )
        
        if files:
            self.add_files_from_list(files)
    
    def add_folder(self):
        """添加文件夹"""
        folder = filedialog.askdirectory(title="选择图片文件夹")
        
        if folder:
            files = self._get_files_from_folder(Path(folder))
            if files:
                self.add_files_from_list(files)
            else:
                messagebox.showinfo("信息", "所选文件夹中没有找到图片文件")
    
    def add_files_from_list(self, files: List[str]):
        """从文件列表添加文件"""
        added_count = 0
        
        for file_path in files:
            if file_path not in self.file_list:
                self.file_list.append(file_path)
                added_count += 1
        
        if added_count > 0:
            self._update_listbox()
            
            if self.file_add_callback:
                self.file_add_callback(files)
        
        if added_count == 0:
            messagebox.showinfo("信息", "没有新文件被添加（可能已存在）")
    
    def remove_selected(self):
        """移除选中的文件"""
        if not self.selected_files:
            messagebox.showinfo("提示", "请先选择要移除的文件")
            return
        
        # 移除文件
        for file_path in self.selected_files:
            if file_path in self.file_list:
                self.file_list.remove(file_path)
        
        self._update_listbox()
        self.selected_files.clear()
        
        if self.file_remove_callback:
            self.file_remove_callback(self.selected_files)
    
    def clear_all(self):
        """清空所有文件"""
        if self.file_list and messagebox.askyesno("确认", "确定要清空所有文件吗？"):
            self.file_list.clear()
            self.selected_files.clear()
            self._update_listbox()
    
    def get_files(self) -> List[str]:
        """获取所有文件列表"""
        return self.file_list.copy()
    
    def get_selected_files(self) -> List[str]:
        """获取选中的文件列表"""
        return self.selected_files.copy()
    
    def set_files(self, files: List[str]):
        """设置文件列表"""
        self.file_list = [f for f in files if Path(f).exists()]
        self.selected_files.clear()
        self._update_listbox()
    
    def select_all(self):
        """选择所有文件"""
        self.file_listbox.select_set(0, tk.END)
        self._on_selection_change(None)
    
    def select_none(self):
        """取消所有选择"""
        self.file_listbox.selection_clear(0, tk.END)
        self._on_selection_change(None)
    
    # 回调设置
    def set_selection_change_callback(self, callback: Callable):
        """设置选择变更回调"""
        self.selection_change_callback = callback
    
    def set_file_add_callback(self, callback: Callable):
        """设置文件添加回调"""
        self.file_add_callback = callback
    
    def set_file_remove_callback(self, callback: Callable):
        """设置文件移除回调"""
        self.file_remove_callback = callback