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
    "pygame",
    "moviepy",
    "moviepy.editor",
    "imageio",
    "imageio_ffmpeg",
]

for package in ("moviepy", "pygame", "imageio", "imageio_ffmpeg"):
    datas += collect_data_files(package)
    hiddenimports += collect_submodules(package)

for package in ("imageio", "imageio_ffmpeg", "moviepy"):
    datas += copy_metadata(package)

hiddenimports += collect_submodules("src")

a = Analysis(
    ["main_qt.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "scipy",
        "pandas",
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
    name="图转视频极速版-本地版",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=["icon.ico"],
)
