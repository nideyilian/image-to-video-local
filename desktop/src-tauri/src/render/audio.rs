//! 背景音乐：候选筛选与 ffmpeg 混入，对齐 `src/render/audio.py`。
//!
//! 选曲规则与 `src/render/audio.py` 完全一致（顺序模式按视频序号轮转、随机模式重抽、
//! 显式选定的文件保持挑选顺序）。BGM 混入用与 Python 版**逐字相同**的 ffmpeg 参数，
//! 这样音轨可以逐字节对照。

// 选曲/混音接口目前由旧引擎驱动导出流程（compositor 仍走 Python 侧编排），
// 这里先备好并通过 `render::mod.rs` 的对照测试验收，等 worker 换成 Rust 再启用。
#![allow(dead_code)]

use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use super::codec;
use super::process::{probe_video_meta, run_with_retry, safe_replace_file};

/// 目录扫描时认可的音频扩展名（与 `get_audio_files()` 一致）。
const AUDIO_EXTENSIONS: [&str; 6] = [".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"];

/// 渲染参数的只读取值口（对应 Python 的 `read_value(ctx, name, default)`）。
pub trait RenderConfig {
    fn get(&self, key: &str) -> Option<Value>;

    fn bool_of(&self, key: &str, default: bool) -> bool {
        match self.get(key) {
            Some(Value::Bool(flag)) => flag,
            Some(Value::Number(number)) => number.as_f64().map(|v| v != 0.0).unwrap_or(default),
            Some(Value::String(text)) => !text.is_empty() && text != "0" && text != "false",
            Some(Value::Null) | None => default,
            Some(_) => default,
        }
    }

    fn text_of(&self, key: &str, default: &str) -> String {
        match self.get(key) {
            Some(Value::String(text)) => text.clone(),
            Some(Value::Null) | None => default.to_string(),
            Some(other) => other.to_string(),
        }
    }

    fn f64_of(&self, key: &str, default: f64) -> f64 {
        match self.get(key) {
            Some(Value::Number(number)) => number.as_f64().unwrap_or(default),
            Some(Value::String(text)) => text.trim().parse().unwrap_or(default),
            _ => default,
        }
    }

    fn i64_of(&self, key: &str, default: i64) -> i64 {
        match self.get(key) {
            Some(Value::Number(number)) => number.as_i64().unwrap_or(default),
            Some(Value::String(text)) => text.trim().parse().unwrap_or(default),
            _ => default,
        }
    }

    fn string_list(&self, key: &str) -> Vec<String> {
        match self.get(key) {
            Some(Value::Array(items)) => items
                .iter()
                .filter_map(|item| item.as_str().map(str::to_string))
                .collect(),
            _ => Vec::new(),
        }
    }
}

/// 目录里的音频文件（不递归，与 `os.listdir` 一致）。
pub fn get_audio_files(directory: &str) -> Vec<PathBuf> {
    let mut files = Vec::new();
    let Ok(entries) = std::fs::read_dir(directory) else {
        return files;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let lower = path
            .file_name()
            .map(|value| value.to_string_lossy().to_lowercase())
            .unwrap_or_default();
        if AUDIO_EXTENSIONS.iter().any(|ext| lower.ends_with(ext)) {
            files.push(path);
        }
    }
    files
}

/// BGM 候选：优先显式选定（保持挑选顺序），否则目录扫描并按名称排序。
pub fn resolve_bgm_candidates(config: &dyn RenderConfig) -> Vec<PathBuf> {
    let explicit: Vec<PathBuf> = config
        .string_list("_bgm_files")
        .into_iter()
        .map(PathBuf::from)
        .filter(|path| path.is_file())
        .collect();
    if !explicit.is_empty() {
        return explicit;
    }
    let Some(directory) = config.get("bgm_dir").and_then(|value| {
        value.as_str().map(str::to_string).or_else(|| {
            if value.is_null() {
                None
            } else {
                Some(value.to_string())
            }
        })
    }) else {
        return Vec::new();
    };
    if directory.is_empty() || !Path::new(&directory).exists() {
        return Vec::new();
    }
    let mut files = get_audio_files(&directory);
    files.sort();
    files
}

/// 当前视频序号（从 0 开始）；缺失或非法一律当 0。
pub fn current_video_index(config: &dyn RenderConfig) -> usize {
    let raw = config.i64_of("_current_video_index", 0);
    raw.max(0) as usize
}

/// 本次应使用的 BGM：
/// - 未启用 BGM、或配音策略不是「使用BGM / 两者混合」→ None；
/// - 顺序模式按视频序号轮转；随机模式每次重抽。
///
/// `rng` 由调用方注入，便于对照测试用固定序列验证随机分支。
pub fn select_bgm_file(
    config: &dyn RenderConfig,
    video_index: Option<usize>,
    mut rng: impl FnMut(usize) -> usize,
) -> Option<PathBuf> {
    if !config.bool_of("use_bgm", false) {
        return None;
    }
    let strategy = config.text_of("watermark_audio", "使用BGM");
    if strategy != "使用BGM" && strategy != "两者混合" {
        return None;
    }
    let candidates = resolve_bgm_candidates(config);
    if candidates.is_empty() {
        return None;
    }
    if config.bool_of("random_bgm", false) {
        let index = rng(candidates.len()).min(candidates.len() - 1);
        return Some(candidates[index].clone());
    }
    let index = video_index.unwrap_or_else(|| current_video_index(config));
    Some(candidates[index % candidates.len()].clone())
}

/// 与 `add_audio_with_ffmpeg()` 等价：把 BGM 混进已生成的视频（视频流 copy）。
pub fn add_audio_with_ffmpeg(
    video_path: &str,
    audio_file: &str,
    volume: f64,
    config: &dyn RenderConfig,
    ffmpeg: &str,
    ffprobe: Option<&Path>,
    mut log: impl FnMut(&str),
) -> bool {
    let temp_output = codec::temp_output_path(video_path, "temp");
    let volume_text = format!("{volume:.2}");
    let loop_audio = config.bool_of("loop_bgm", true);

    let mut args: Vec<String> = vec!["-y".into(), "-i".into(), video_path.to_string()];
    if loop_audio {
        args.extend(["-stream_loop".into(), "-1".into()]);
    }
    args.extend([
        "-i".into(),
        audio_file.to_string(),
        "-filter_complex".into(),
        format!("[1:a]volume={volume_text}[a]"),
        "-map".into(),
        "0:v".into(),
        "-map".into(),
        "[a]".into(),
        "-c:v".into(),
        "copy".into(),
    ]);
    if loop_audio {
        args.push("-shortest".into());
    } else {
        // 非循环：用 -t 硬性限定为视频时长，避免 BGM 比视频短时 -shortest 把视频截短
        let duration = probe_video_meta(video_path, ffprobe)
            .map(|meta| meta.duration)
            .unwrap_or(0.0);
        if duration > 0.0 {
            args.extend(["-t".into(), format!("{duration:.3}")]);
        } else {
            args.push("-shortest".into());
        }
    }
    args.push(temp_output.clone());

    log(&format!("执行命令: {ffmpeg} {}", args.join(" ")));
    let Some(outcome) = run_with_retry(ffmpeg, &args, "BGM", 240, 2, &mut log) else {
        log("ffmpeg执行失败：无可用结果");
        return false;
    };
    if outcome.code != Some(0) || outcome.timed_out {
        log(&format!("ffmpeg命令执行失败，错误码: {:?}", outcome.code));
        log(&format!("错误信息: {}", outcome.stderr));
        return false;
    }
    let size = std::fs::metadata(&temp_output)
        .map(|meta| meta.len())
        .unwrap_or(0);
    if size <= 1000 {
        log("FFmpeg生成的文件无效");
        return false;
    }
    if !safe_replace_file(&temp_output, video_path) {
        log("替换文件失败: 无法用新文件覆盖旧视频");
        return false;
    }
    log("成功使用FFmpeg添加背景音乐");
    true
}

/// 供接口层直接使用的入口：把 JSON 配置包成 `RenderConfig`。
pub struct JsonConfig(pub serde_json::Map<String, Value>);

impl RenderConfig for JsonConfig {
    fn get(&self, key: &str) -> Option<Value> {
        self.0.get(key).cloned()
    }
}

impl JsonConfig {
    pub fn new(value: &Value) -> Self {
        JsonConfig(value.as_object().cloned().unwrap_or_default())
    }
}

/// `preview_bgm` 用得上的候选清单（前端要显示名字与路径）。
pub fn candidate_payload(config: &dyn RenderConfig) -> Value {
    let items: Vec<Value> = resolve_bgm_candidates(config)
        .into_iter()
        .map(|path| {
            json!({
                "name": path.file_name().map(|v| v.to_string_lossy().into_owned()).unwrap_or_default(),
                "path": path.to_string_lossy().into_owned(),
            })
        })
        .collect();
    json!({ "files": items, "count": items.len() })
}

#[cfg(test)]
mod tests {
    use super::*;

    struct MapConfig(serde_json::Map<String, Value>);

    impl RenderConfig for MapConfig {
        fn get(&self, key: &str) -> Option<Value> {
            self.0.get(key).cloned()
        }
    }

    fn config(pairs: Vec<(&str, Value)>) -> MapConfig {
        let mut map = serde_json::Map::new();
        for (key, value) in pairs {
            map.insert(key.to_string(), value);
        }
        MapConfig(map)
    }

    /// 只建一次、之后只读 —— 多个用例并行调用时不会互删目录。
    fn fixture() -> PathBuf {
        use std::sync::OnceLock;
        static DIR: OnceLock<PathBuf> = OnceLock::new();
        DIR.get_or_init(|| {
            let dir = std::env::temp_dir().join(format!("itv-render-audio-{}", std::process::id()));
            std::fs::create_dir_all(&dir).unwrap();
            for name in ["01-a.mp3", "02-b.WAV", "03-c.m4a", "note.txt", "d.mp4"] {
                std::fs::write(dir.join(name), b"x").unwrap();
            }
            std::fs::create_dir_all(dir.join("sub")).unwrap();
            std::fs::write(dir.join("sub").join("nested.mp3"), b"x").unwrap();
            dir
        })
        .clone()
    }

    #[test]
    fn audio_scan_is_flat_sorted_case_insensitive_on_extension() {
        let dir = fixture();
        let mut names: Vec<String> = get_audio_files(&dir.to_string_lossy())
            .into_iter()
            .map(|path| path.file_name().unwrap().to_string_lossy().into_owned())
            .collect();
        names.sort();
        assert_eq!(names, vec!["01-a.mp3", "02-b.WAV", "03-c.m4a"]);
    }

    #[test]
    fn missing_directory_yields_no_candidates() {
        let cfg = config(vec![("bgm_dir", json!("C:/definitely/not/here"))]);
        assert!(resolve_bgm_candidates(&cfg).is_empty());
    }

    #[test]
    fn explicit_files_keep_selection_order_and_skip_missing() {
        let dir = fixture();
        let first = dir.join("03-c.m4a");
        let second = dir.join("01-a.mp3");
        let cfg = config(vec![(
            "_bgm_files",
            json!([
                first.to_string_lossy(),
                "C:/missing.mp3",
                second.to_string_lossy()
            ]),
        )]);
        let picked = resolve_bgm_candidates(&cfg);
        assert_eq!(picked.len(), 2);
        assert_eq!(picked[0], first);
        assert_eq!(picked[1], second);
    }

    #[test]
    fn ordered_mode_rotates_by_video_index() {
        let dir = fixture();
        let cfg = config(vec![
            ("bgm_dir", json!(dir.to_string_lossy())),
            ("use_bgm", json!(true)),
            ("random_bgm", json!(false)),
            ("watermark_audio", json!("使用BGM")),
        ]);
        let picks: Vec<String> = (0..3)
            .map(|index| {
                select_bgm_file(&cfg, Some(index), |_| 0)
                    .unwrap()
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
                    .into_owned()
            })
            .collect();
        assert_eq!(picks, vec!["01-a.mp3", "02-b.WAV", "03-c.m4a"]);
    }

    #[test]
    fn ordered_mode_wraps_around() {
        let dir = fixture();
        let cfg = config(vec![
            ("bgm_dir", json!(dir.to_string_lossy())),
            ("use_bgm", json!(true)),
            ("watermark_audio", json!("使用BGM")),
        ]);
        let pick = |index: usize| {
            select_bgm_file(&cfg, Some(index), |_| 0)
                .unwrap()
                .file_name()
                .unwrap()
                .to_string_lossy()
                .into_owned()
        };
        assert_eq!(pick(3), "01-a.mp3");
        assert_eq!(pick(4), "02-b.WAV");
    }

    #[test]
    fn video_index_falls_back_to_context_value() {
        let dir = fixture();
        let cfg = config(vec![
            ("bgm_dir", json!(dir.to_string_lossy())),
            ("use_bgm", json!(true)),
            ("watermark_audio", json!("使用BGM")),
            ("_current_video_index", json!(1)),
        ]);
        let picked = select_bgm_file(&cfg, None, |_| 0).unwrap();
        assert_eq!(picked.file_name().unwrap(), "02-b.WAV");
    }

    #[test]
    fn bgm_disabled_or_wrong_strategy_returns_none() {
        let dir = fixture();
        let off = config(vec![
            ("bgm_dir", json!(dir.to_string_lossy())),
            ("use_bgm", json!(false)),
        ]);
        assert!(select_bgm_file(&off, Some(0), |_| 0).is_none());

        let watermark_only = config(vec![
            ("bgm_dir", json!(dir.to_string_lossy())),
            ("use_bgm", json!(true)),
            ("watermark_audio", json!("使用水印音频")),
        ]);
        assert!(select_bgm_file(&watermark_only, Some(0), |_| 0).is_none());
    }

    #[test]
    fn random_mode_uses_injected_rng() {
        let dir = fixture();
        let cfg = config(vec![
            ("bgm_dir", json!(dir.to_string_lossy())),
            ("use_bgm", json!(true)),
            ("random_bgm", json!(true)),
        ]);
        let picked = select_bgm_file(&cfg, Some(0), |len| len - 1).unwrap();
        assert_eq!(picked.file_name().unwrap(), "03-c.m4a");
    }

    #[test]
    fn empty_candidates_returns_none_even_when_enabled() {
        let dir =
            std::env::temp_dir().join(format!("itv-render-audio-empty-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let cfg = config(vec![
            ("bgm_dir", json!(dir.to_string_lossy())),
            ("use_bgm", json!(true)),
        ]);
        assert!(select_bgm_file(&cfg, Some(0), |_| 0).is_none());
    }
}
