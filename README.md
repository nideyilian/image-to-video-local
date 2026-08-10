# 图转视频极速版（本地版）

这是图片转视频工具的独立本地版本，所有图片处理、预览和视频导出均在当前电脑完成。

当前版本：`3.0.0-local.1`（2026-08-10）

## 版本边界

本仓库专门发布本地桌面功能，不包含：

- 剪映素材库、剪映素材扫描与导入模块
- LingJing 远程任务面板
- HTTP 远程渲染服务
- FRP 公网穿透与远程连接向导

仓库中也不提交 FFmpeg 可执行文件。程序会优先查找本地 FFmpeg，然后回退到系统 `PATH` 中的 `ffmpeg`。

## 主要功能

- 批量将图片生成视频
- 多标签任务与批量队列
- 多种转场和画面动态效果
- BGM、图片水印和视频水印
- 实时预览、配置保存与性能统计
- Windows 桌面界面（PySide6）

## 环境要求

- Windows 10/11
- Python 3.10 或更高版本
- FFmpeg（建议添加到系统 `PATH`）

确认 FFmpeg 可用：

```powershell
ffmpeg -version
```

## 安装与运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main_qt.py
```

## 测试

```powershell
pip install -r requirements-test.txt
python -m pytest -q
```

## 打包 Windows 可执行文件

先安装 PyInstaller：

```powershell
pip install pyinstaller
pyinstaller --clean --noconfirm 图片转视频工具_本地版.spec
```

生成结果位于 `dist/`。如需把 FFmpeg 一起分发，请在本机自行准备合法来源的 FFmpeg，并在发布前确认其许可证和文件体积。

## 许可证

[MIT License](LICENSE)
