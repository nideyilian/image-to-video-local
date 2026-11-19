//! 素材库默认目录：对齐 `LibraryManager.default_dirs()`。
//!
//! 规则（与旧引擎逐字一致）：`~/Documents` 存在就用它，否则退回用户主目录，
//! 再拼 `图转视频素材库/{BGM, 水印}`。**只算路径，不创建目录**。

use std::path::PathBuf;

use serde_json::{json, Value};

const LIBRARY_ROOT_NAME: &str = "图转视频素材库";

fn home_dir() -> PathBuf {
    #[cfg(windows)]
    {
        if let Some(value) = std::env::var_os("USERPROFILE") {
            return PathBuf::from(value);
        }
    }
    #[cfg(not(windows))]
    {
        if let Some(value) = std::env::var_os("HOME") {
            return PathBuf::from(value);
        }
    }
    PathBuf::new()
}

pub fn dirs() -> Value {
    let home = home_dir();
    let documents = home.join("Documents");
    let base = if documents.is_dir() { documents } else { home };
    let root = base.join(LIBRARY_ROOT_NAME);
    json!({
        "library_root": root.to_string_lossy().into_owned(),
        "bgm_dir": root.join("BGM").to_string_lossy().into_owned(),
        "watermark_dir": root.join("水印").to_string_lossy().into_owned(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exposes_three_paths_under_library_root() {
        let value = dirs();
        let root = value["library_root"].as_str().expect("library_root");
        assert!(root.ends_with(LIBRARY_ROOT_NAME));
        assert!(value["bgm_dir"].as_str().expect("bgm_dir").ends_with("BGM"));
        assert!(value["watermark_dir"]
            .as_str()
            .expect("watermark_dir")
            .ends_with("水印"));
    }
}
