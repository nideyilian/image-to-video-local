//! FFmpeg / FFprobe 定位与媒体时长探测，对齐 `src/utils/ffmpeg_runtime.py`。
//!
//! 查找顺序与旧引擎一致：环境变量 → PATH → 项目内相对路径 → 打包附带的
//! imageio_ffmpeg 二进制。少找一处，打包版就会「找不到 ffmpeg」而无法算指纹。

use std::path::{Path, PathBuf};
use std::process::Command;

const FFMPEG_RELATIVE: [&str; 5] = [
    "tools/ffmpeg/bin/ffmpeg.exe",
    "tools/ffmpeg/ffmpeg.exe",
    "ffmpeg/bin/ffmpeg.exe",
    "ffmpeg.exe",
    "bin/ffmpeg.exe",
];

const FFPROBE_RELATIVE: [&str; 4] = [
    "tools/ffmpeg/bin/ffprobe.exe",
    "ffmpeg/bin/ffprobe.exe",
    "ffprobe.exe",
    "bin/ffprobe.exe",
];

/// Windows 下不弹黑框（等价于 Python 的 `CREATE_NO_WINDOW`）。
pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub fn hide_console(command: &mut Command) -> &mut Command {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
}

fn candidate_bases(project_root: Option<&Path>) -> Vec<PathBuf> {
    let mut bases: Vec<PathBuf> = Vec::new();
    if let Some(root) = project_root {
        bases.push(root.to_path_buf());
    }
    if let Ok(cwd) = std::env::current_dir() {
        bases.push(cwd);
    }
    if let Ok(executable) = std::env::current_exe() {
        if let Some(parent) = executable.parent() {
            bases.push(parent.to_path_buf());
        }
    }
    bases.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."));

    let mut seen = std::collections::HashSet::new();
    bases
        .into_iter()
        .filter(|path| seen.insert(path.to_string_lossy().to_lowercase()))
        .collect()
}

fn find_in_path(name: &str) -> Option<PathBuf> {
    let paths = std::env::var_os("PATH")?;
    std::env::split_paths(&paths)
        .map(|dir| dir.join(name))
        .find(|candidate| candidate.is_file())
}

fn executable_name(stem: &str) -> &'static str {
    #[cfg(windows)]
    {
        match stem {
            "ffmpeg" => "ffmpeg.exe",
            _ => "ffprobe.exe",
        }
    }
    #[cfg(not(windows))]
    {
        match stem {
            "ffmpeg" => "ffmpeg",
            _ => "ffprobe",
        }
    }
}

/// 与 `resolve_ffmpeg_path()` 等价。
pub fn resolve_ffmpeg(project_root: Option<&Path>) -> Option<PathBuf> {
    for key in ["IMAGEIO_FFMPEG_EXE", "FFMPEG_BINARY"] {
        if let Some(value) = std::env::var_os(key) {
            let text = value.to_string_lossy();
            let candidate = PathBuf::from(text.trim().trim_matches('"'));
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }

    if let Some(found) = find_in_path(executable_name("ffmpeg")) {
        return Some(found);
    }

    for base in candidate_bases(project_root) {
        for relative in FFMPEG_RELATIVE {
            let candidate = base.join(relative);
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }

    // 打包版可能带 imageio_ffmpeg 的二进制（Python 侧靠 import，这里直接扫目录）
    for base in candidate_bases(project_root) {
        let directory = base.join("imageio_ffmpeg").join("binaries");
        let Ok(entries) = std::fs::read_dir(&directory) else {
            continue;
        };
        let mut matches: Vec<PathBuf> = entries
            .flatten()
            .map(|entry| entry.path())
            .filter(|path| {
                let name = path.file_name().map(|value| value.to_string_lossy().to_lowercase());
                matches!(name.as_deref(), Some(name) if name.starts_with("ffmpeg") && name.ends_with(".exe"))
            })
            .collect();
        matches.sort();
        if let Some(found) = matches.into_iter().next() {
            return Some(found);
        }
    }
    None
}

/// 与 `resolve_ffprobe_path()` 等价。
pub fn resolve_ffprobe(project_root: Option<&Path>, ffmpeg: Option<&Path>) -> Option<PathBuf> {
    if let Some(value) = std::env::var_os("FFPROBE_BINARY") {
        let text = value.to_string_lossy();
        let candidate = PathBuf::from(text.trim().trim_matches('"'));
        if candidate.is_file() {
            return Some(candidate);
        }
    }

    if let Some(found) = find_in_path(executable_name("ffprobe")) {
        return Some(found);
    }

    if let Some(ffmpeg) = ffmpeg {
        let sibling = ffmpeg.with_file_name(executable_name("ffprobe"));
        if sibling.is_file() {
            return Some(sibling);
        }
    }

    for base in candidate_bases(project_root) {
        for relative in FFPROBE_RELATIVE {
            let candidate = base.join(relative);
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

/// 与 `_probe_duration()` 等价：读容器时长（秒），失败返回 None。
pub fn probe_duration(ffprobe: Option<&Path>, path: &Path) -> Option<f64> {
    let ffprobe = ffprobe?;
    let mut command = Command::new(ffprobe);
    command.args([
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        &path.to_string_lossy(),
    ]);
    hide_console(&mut command);
    let output = command.output().ok()?;
    if !output.status.success() {
        return None;
    }
    String::from_utf8_lossy(&output.stdout).trim().parse::<f64>().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolves_a_usable_ffmpeg_on_this_machine() {
        // 本机开发环境一定有 ffmpeg（PATH 或项目 tools/）；找不到时至少不能 panic。
        if let Some(path) = resolve_ffmpeg(None) {
            assert!(path.is_file(), "解析出的 ffmpeg 必须是文件：{path:?}");
        }
    }

    #[test]
    fn missing_media_returns_no_duration() {
        assert_eq!(probe_duration(None, Path::new("nope.mp4")), None);
    }
}
