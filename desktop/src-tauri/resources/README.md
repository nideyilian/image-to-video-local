把 ffmpeg.exe 放这里，打包时会随安装包一起分发（`tauri.conf.json` 的 `bundle.resources`）。

## 为什么要放在这里

Python sidecar 已经移除，原来靠 `imageio_ffmpeg` 顺带打包的 ffmpeg 没有了。
渲染、预览、拆 BGM 全都依赖它，**没有 ffmpeg 的安装包装完是不能用的**。

只放 `ffmpeg.exe`（约 84MB），不放 `ffprobe.exe`：
两个都放会让安装包比改造前还大。代码里 `render/process.rs::probe_via_ffmpeg`
会用 `ffmpeg -i` 的 stderr 兜底解析时长/分辨率/帧率，够用。

## 本地打包前

```bash
cp .venv/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe \
   desktop/src-tauri/resources/ffmpeg.exe
```

或者从任意 FFmpeg 发行版拷一个静态构建的 `ffmpeg.exe` 过来。

## CI

`ffmpeg.exe` 有 84MB，被 `.gitignore` 排除，不进 git。
`.github/workflows/release-desktop.yml` 里用 choco 现装现拷，
并在构建前断言文件存在 —— 缺了就中断，避免又发出"装完不能用"的版本。
