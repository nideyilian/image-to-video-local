# 图转视频极速版

这是图片转视频工具，所有图片处理、预览和视频导出均在当前电脑完成（本地版）。

当前版本：`3.0.0-local.12`（2026-08-16）

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
- 静态样片预览、配置保存与性能统计
- 多工作区、并行任务队列、暂停/继续/取消
- 新版 Windows 桌面界面（Tauri 2 + React + TypeScript）
- 启动时从 GitHub Releases 自动检查更新，并支持应用内下载、安装和重启
- 兼容旧版 PySide6 界面和既有渲染参数

### 固定视频总时长

“每图时长”控制图片切换间隔，“总时长”控制最终视频长度。总时长为 `0` 时沿用“图片数 × 每图时长”的自动计算；设置固定值时，图片会按原顺序循环补齐。固定总时长需要是每图时长的整数倍。

例如只有 4 张图片，希望每 1 秒切换一次并生成 8 秒视频：设置“每视频图片数”为 `4`、“每图时长”为 `1`、“总时长”为 `8`，导出顺序为 `1 → 2 → 3 → 4 → 1 → 2 → 3 → 4`。

## 环境要求

- Windows 10/11
- Python 3.10 或更高版本
- FFmpeg（建议添加到系统 `PATH`）

确认 FFmpeg 可用：

```powershell
ffmpeg -version
```

## 安装与运行

### 新版桌面工作台（推荐）

新版界面复用同一套 Python 渲染功能。开发模式需要 Node.js 20+、Rust 和 Python 环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd desktop
npm install
npm run tauri dev
```

桌面端会启动 `src.engine.server` 本地进程，通过 NDJSON 协议完成配置校验、素材扫描、样片生成和任务控制。所有素材仍只在本机处理。

只检查或构建前端：

```powershell
cd desktop
npm run build
```

### 旧版 PySide6 界面

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

### 新版 Tauri 应用

先冻结 Python 引擎，再由 Tauri 打包桌面应用：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
powershell -ExecutionPolicy Bypass -File .\desktop\scripts\build-engine-sidecar.ps1
cd desktop
npm run tauri build
```

`build-engine-sidecar.ps1` 会按当前 Rust target triple 生成 Tauri 所需的 sidecar 文件。开发模式仍直接使用当前 Python 环境，便于调试。

### 发布带自动更新的新版

桌面应用按顺序尝试以下更新源读取 `latest.json`（配置在 `desktop/src-tauri/tauri.conf.json` 的 `plugins.updater.endpoints`，按数组顺序逐个尝试，第一个成功的即被使用）：

1. GitHub 官方：`https://github.com/nideyilian/image-to-video-local/releases/latest/download/latest.json`
2. ghproxy 镜像（国内加速，由镜像站转发 GitHub 请求）：
   - `https://mirror.ghproxy.com/...`
   - `https://ghproxy.net/...`
   - `https://gh-proxy.com/...`

镜像站只转发 GitHub 的请求，无法加速镜像里 `latest.json` 指向的安装包下载；因此应用内额外提供了「镜像站加速下载 / 打开 GitHub 下载页」手动入口，下载安装包后运行即可覆盖安装，效果与自动更新一致。若你本机使用代理访问 GitHub，也可以在更新窗口的「网络代理设置」中填写代理地址（例如 `http://127.0.0.1:7890`），检查与下载都会走该代理。

首次发布前，在 GitHub 仓库的 `Settings → Secrets and variables → Actions` 中添加：

- `TAURI_SIGNING_PRIVATE_KEY`：本机 `$env:USERPROFILE\.tauri\image-to-video-local.key` 的完整内容
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`：本机 `$env:USERPROFILE\.tauri\image-to-video-local.password` 的完整内容

私钥和密码只保存在本机与 GitHub Actions Secret 中，不要提交到仓库；丢失后，已安装的客户端将无法验证后续更新。

发布时同步更新 `VERSION`、`desktop/package.json`、`desktop/src-tauri/Cargo.toml` 和 `desktop/src-tauri/tauri.conf.json` 中的版本号，提交后推送同版本标签：

```powershell
git tag v3.0.0-local.3
git push origin v3.0.0-local.3
```

`.github/workflows/release-desktop.yml` 会构建 Windows NSIS 安装包、签名更新包并创建 GitHub Release，同时上传自动更新所需的 `latest.json`。客户端默认在启动后检查，此后每 6 小时检查一次；也可以在顶部工具栏点击“检查更新”。渲染任务进行中时，安装会被阻止以避免中断导出。

#### 可选：Gitee 镜像仓库（国内直连）

如果 ghproxy 镜像仍不够稳定，可以再同步一份更新文件到 Gitee，让客户端直接从 Gitee 检查与下载：

1. 在 Gitee 上创建一个公开仓库（可为空仓库），例如 `image-to-video-local-releases`。
2. 在 Gitee「设置 → 私人令牌」中生成一个带 `projects` 权限的访问令牌。
3. 在 GitHub 仓库 Secrets 中新增：
   - `GITEE_TOKEN`：上面的 Gitee 访问令牌
   - `GITEE_REPO`：形如 `你的用户名/image-to-video-local-releases`
4. 下次发布时，`.github/workflows/release-desktop.yml` 会自动调用 `desktop/scripts/sync-gitee.ps1`，把安装包与改写为 Gitee 直链的 `latest.json` 推送到该仓库的 `release/` 目录（未配置这两个 Secret 时自动跳过）。

想优先使用 Gitee 源的用户（或你自己），把下面这一行加到 `desktop/src-tauri/tauri.conf.json` 的 `endpoints` 数组最前面，然后重新构建发布：

```json
"https://gitee.com/你的用户名/image-to-video-local-releases/raw/main/release/latest.json"
```

注意：`endpoints` 在编译时写入应用，修改配置后需要重新 `npm run tauri build` 才会生效；更新包签名只覆盖安装包内容，不涉及 `url` 字段，因此镜像改写 `url` 是安全的。

### 旧版 PySide6 应用

当前根目录的原 PyInstaller 配置继续用于旧版界面：

先安装 PyInstaller：

```powershell
pip install pyinstaller
pyinstaller --clean --noconfirm 图片转视频工具_本地版.spec
```

生成结果位于 `dist/`。如需把 FFmpeg 一起分发，请在本机自行准备合法来源的 FFmpeg，并在发布前确认其许可证和文件体积。

## 许可证

[MIT License](LICENSE)
