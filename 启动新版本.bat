@echo off
setlocal
cd /d "%~dp0"

rem ============================================================
rem  图转视频极速版 - 本地启动
rem
rem  用法：
rem    启动新版本.bat            启动打包版桌面程序（dist\desktop-current）
rem    启动新版本.bat dev        启动 Tauri 开发模式（免打包，直接跑最新代码）
rem    启动新版本.bat qt         启动旧版 PySide6 界面（.venv python main_qt.py）
rem ============================================================

set "MODE=%~1"

if /i "%MODE%"=="dev" goto dev
if /i "%MODE%"=="qt" goto qt

set "APP_EXE=%~dp0dist\desktop-current\image-to-video-desktop.exe"
if not exist "%APP_EXE%" (
    echo [错误] 未找到桌面程序：%APP_EXE%
    echo.
    echo 当前打包版不存在或尚未构建，请二选一：
    echo.
    echo   1. 重新构建打包版（含素材库新功能）：
    echo        pwsh -File "%~dp0desktop\scripts\build-engine-sidecar.ps1"
    echo        cd /d "%~dp0desktop" ^&^& npm run tauri build
    echo        然后把 desktop\src-tauri\target\release\image-to-video-desktop.exe
    echo        与 dist\image-to-video-engine.exe 复制到 dist\desktop-current\
    echo.
    echo   2. 直接以开发模式运行最新代码：%~nx0 dev
    echo.
    pause
    exit /b 1
)
echo 正在启动图转视频极速版（打包版）...
start "" "%APP_EXE%"
exit /b 0

:dev
if not exist "%~dp0desktop\package.json" (
    echo [错误] 未找到 desktop 前端工程，无法启动开发模式。
    pause
    exit /b 1
)
echo 启动 Tauri 开发模式（免打包，直接运行最新代码）...
echo 提示：首次运行会自动启动 npm run dev 与 cargo；保持本窗口开启。
pushd "%~dp0desktop"
call npm run tauri dev
popd
exit /b 0

:qt
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [错误] 未找到 Python 虚拟环境：%PY%
    echo 请先执行：python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)
echo 正在启动旧版 PySide6 界面...
"%PY%" "%~dp0main_qt.py"
exit /b 0
