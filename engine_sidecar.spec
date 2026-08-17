# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


datas = [("config", "config"), ("src", "src")]
hiddenimports = [
    "tkinter",
    "tkinter.ttk",
    "cv2",
    "numpy",
    "PIL",
    "PIL.Image",
    "PIL.ImageTk",
    "psutil",
    "tqdm",
    "moviepy",
    "moviepy.editor",
    "imageio",
    "imageio_ffmpeg",
]

for package in ("moviepy", "imageio", "imageio_ffmpeg"):
    datas += collect_data_files(package)
    hiddenimports += collect_submodules(package)

for package in ("imageio", "imageio_ffmpeg", "moviepy"):
    datas += copy_metadata(package)

hiddenimports += collect_submodules("src")

try:
    hiddenimports += collect_submodules("send2trash")
except Exception:
    hiddenimports.append("send2trash")

a = Analysis(
    ["engine_sidecar.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 引擎 worker 走 Tk 管线：剔除 Qt 桌面 GUI 与未使用的媒体库，显著减小体积
    excludes=[
        "matplotlib",
        "scipy",
        "pandas",
        "PySide6",
        "shiboken6",
        "pygame",
        "pygame.sdl2",
        "IPython",
        "notebook",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="image-to-video-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)
