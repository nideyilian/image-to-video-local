//! 路径规范化：保证返回给前端的字符串与旧 Python 引擎逐字符一致。
//!
//! Python 侧统一用 `Path.resolve()`：绝对路径、真实大小写、反斜杠分隔，
//! 并且**不带** Windows verbatim 前缀。Rust 的 `canonicalize` 会带 `\\?\`，
//! 所以这里统一剥掉，否则前端拿到的路径和旧引擎对不上（哈希、去重、日志都会分叉）。

use std::path::{Path, PathBuf};

/// `canonicalize` 之后剥掉 Windows 的 `\\?\` / `\\?\UNC\` 前缀。
pub fn resolve(path: &Path) -> std::io::Result<PathBuf> {
    std::fs::canonicalize(path).map(strip_verbatim)
}

/// 尽力返回绝对路径；`canonicalize` 失败（权限、路径过长）时退化为拼接当前目录，
/// 与 Python `resolve(strict=False)` 不抛异常的行为对齐。
pub fn absolute(path: &Path) -> PathBuf {
    if let Ok(resolved) = resolve(path) {
        return resolved;
    }
    if path.is_absolute() {
        return path.to_path_buf();
    }
    std::env::current_dir()
        .map(|base| base.join(path))
        .unwrap_or_else(|_| path.to_path_buf())
}

/// 剥掉 verbatim 前缀。非 Windows 平台原样返回。
pub fn strip_verbatim(path: PathBuf) -> PathBuf {
    #[cfg(windows)]
    {
        let text = path.to_string_lossy().into_owned();
        if let Some(rest) = text.strip_prefix("\\\\?\\") {
            // UNC 共享路径：\\?\UNC\server\share → \\server\share
            if let Some(unc) = rest.strip_prefix("UNC\\") {
                return PathBuf::from(format!("\\\\{}", unc));
            }
            return PathBuf::from(rest);
        }
        path
    }
    #[cfg(not(windows))]
    {
        path
    }
}

/// 路径字符串转成与 Python `Path(...).name` 等价的文件名。
pub fn file_name(path: &str) -> String {
    Path::new(path)
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default()
}

/// 路径转字符串（统一用系统分隔符，Windows 下是反斜杠）。
pub fn to_string(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn file_name_matches_python_path_name() {
        assert_eq!(file_name(r"D:\AAA\图片\01.jpg"), "01.jpg");
        assert_eq!(file_name("/tmp/歌曲.mp3"), "歌曲.mp3");
    }

    #[cfg(windows)]
    #[test]
    fn strips_verbatim_prefix() {
        assert_eq!(
            strip_verbatim(PathBuf::from("\\\\?\\D:\\AAA\\图片")),
            PathBuf::from("D:\\AAA\\图片")
        );
        assert_eq!(
            strip_verbatim(PathBuf::from("\\\\?\\UNC\\server\\share\\a")),
            PathBuf::from("\\\\server\\share\\a")
        );
        assert_eq!(strip_verbatim(PathBuf::from("D:\\AAA")), PathBuf::from("D:\\AAA"));
    }
}
