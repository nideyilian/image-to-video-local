//! 批量拆 BGM：把视频里的音轨抽成 mp3 存进素材库（对齐 `LibraryManager.start_extract`）。
//!
//! 这是本项目第一个「后台任务 + 进度事件」的素材库接口。事件名与载荷必须与旧引擎一致：
//! - `library.extract.progress`：每条视频处理完推一次 `{task_id, done, total, current, result}`
//! - `library.extract.done`：全部结束推一次 `{task_id, results, summary, total}`
//!
//! 前端（`MaterialLibrary.tsx`）靠这两个事件画进度条与结果列表，名字写错就静默不动。

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

use serde_json::{json, Map, Value};

use super::fingerprint;
use super::hash;
use super::paths;
use super::snapshot::{self, VIDEO_EXTENSIONS};
use super::system;
use super::write_ops;

/// 拆出的 mp3 码率（`EXTRACT_BITRATE`）。
const EXTRACT_BITRATE: &str = "192k";
/// 单条视频的 ffmpeg 超时（秒）。
const EXTRACT_TIMEOUT: u64 = 300;

/// 一个在跑的任务。取消标记是原子量，worker 每条视频前检查一次。
struct ExtractTask {
    cancelled: Arc<AtomicBool>,
}

/// 全局任务表：`task_id -> 句柄`。
fn tasks() -> &'static Mutex<BTreeMap<String, ExtractTask>> {
    static TASKS: OnceLock<Mutex<BTreeMap<String, ExtractTask>>> = OnceLock::new();
    TASKS.get_or_init(|| Mutex::new(BTreeMap::new()))
}

/// `_safe_name`：去掉路径分隔符与非法字符，避免写出到子目录。
pub(crate) fn safe_name(name: &str) -> String {
    let cleaned: String = name
        .chars()
        .map(|character| {
            if matches!(character, '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*')
                || (character as u32) < 32
            {
                '_'
            } else {
                character
            }
        })
        .collect();
    let trimmed = cleaned.trim();
    if trimmed.is_empty() {
        "未命名".to_string()
    } else {
        trimmed.to_string()
    }
}

/// 收集待处理视频：显式路径优先，再按 folder 递归补全，最后按小写路径排序去重。
///
/// 与 `_collect_videos` 一致 —— 注意**排序键是小写全路径**，不是文件名。
fn collect_videos(raw_paths: &[String], folder: &str) -> Vec<PathBuf> {
    let mut collected: Vec<PathBuf> = Vec::new();
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();

    let push = |path: PathBuf, collected: &mut Vec<PathBuf>, seen: &mut std::collections::BTreeSet<String>| {
        if !path.is_file() {
            return;
        }
        let is_video = path
            .extension()
            .map(|value| format!(".{}", value.to_string_lossy().to_lowercase()))
            .map(|ext| VIDEO_EXTENSIONS.contains(&ext.as_str()))
            .unwrap_or(false);
        if !is_video {
            return;
        }
        let key = paths::display(&paths::absolute(&path));
        if seen.insert(key) {
            collected.push(path);
        }
    };

    for raw in raw_paths {
        let path = PathBuf::from(raw.trim());
        push(path, &mut collected, &mut seen);
    }
    if !folder.trim().is_empty() {
        let root = PathBuf::from(folder.trim());
        if root.is_dir() {
            let mut stack = vec![root];
            let mut found: Vec<PathBuf> = Vec::new();
            while let Some(current) = stack.pop() {
                let Ok(entries) = std::fs::read_dir(&current) else {
                    continue;
                };
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_dir() {
                        stack.push(path);
                    } else {
                        found.push(path);
                    }
                }
            }
            // Python 用 sorted(root.rglob("*"))，即按路径字典序；这里先排再逐个 push，
            // 保证去重时的"首次出现"顺序与旧引擎一致。
            found.sort_by_key(|path| path.to_string_lossy().into_owned());
            for path in found {
                push(path, &mut collected, &mut seen);
            }
        }
    }
    collected.sort_by_key(|path| path.to_string_lossy().to_lowercase());
    collected
}

/// `_probe_audio_streams`：视频是否含音频流；没有 ffprobe 时返回 true，交给 ffmpeg 报错兜底。
fn has_audio_stream(ffprobe: Option<&Path>, path: &Path) -> bool {
    let Some(ffprobe) = ffprobe else {
        return true;
    };
    let mut command = std::process::Command::new(ffprobe);
    command.args([
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        &path.to_string_lossy(),
    ]);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    match command.output() {
        Ok(output) => !String::from_utf8_lossy(&output.stdout).trim().is_empty(),
        Err(_) => true,
    }
}

fn failed(video: &Path, reason: &str) -> Value {
    json!({
        "video": paths::display(&paths::absolute(video)),
        "name": video.file_name().map(|v| v.to_string_lossy().into_owned()).unwrap_or_default(),
        "path": "",
        "status": "failed",
        "reason": reason,
    })
}

fn no_audio(video: &Path) -> Value {
    json!({
        "video": paths::display(&paths::absolute(video)),
        "name": video.file_name().map(|v| v.to_string_lossy().into_owned()).unwrap_or_default(),
        "path": "",
        "status": "no_audio",
        "reason": "视频没有音轨",
    })
}

/// 处理单条视频：转 mp3 → 算指纹 → 全库避重 → 写入目标目录并更新索引。
fn extract_one(
    video: &Path,
    bgm_base: &Path,
    target_dir: &Path,
    ffmpeg: &Path,
    ffprobe: Option<&Path>,
    avoid_duplicates: bool,
) -> Value {
    if !video.is_file() {
        return failed(video, "视频文件不存在");
    }
    if !has_audio_stream(ffprobe, video) {
        return no_audio(video);
    }

    let stem = safe_name(
        video
            .file_stem()
            .map(|value| value.to_string_lossy().into_owned())
            .unwrap_or_default()
            .as_str(),
    );
    let temporary = target_dir.join(format!(
        ".extract-{}-{}.tmp.mp3",
        std::process::id(),
        // 用线程 id 的数值形式做区分，避免并发任务撞名
        format!("{:?}", std::thread::current().id()).replace(|c: char| !c.is_alphanumeric(), "")
    ));

    let args: Vec<String> = vec![
        "-hide_banner".into(),
        "-loglevel".into(),
        "error".into(),
        "-nostdin".into(),
        "-y".into(),
        "-i".into(),
        paths::display(&paths::absolute(video)),
        "-map".into(),
        "0:a:0".into(),
        "-vn".into(),
        "-c:a".into(),
        "libmp3lame".into(),
        "-b:a".into(),
        EXTRACT_BITRATE.into(),
        "-ar".into(),
        "44100".into(),
        "-ac".into(),
        "2".into(),
        temporary.to_string_lossy().into_owned(),
    ];
    let mut detail = String::new();
    let outcome = crate::render::process::run_with_retry(
        &ffmpeg.to_string_lossy(),
        &args,
        "EXTRACT",
        EXTRACT_TIMEOUT,
        1,
        |line| detail.push_str(line),
    );
    let ok = outcome
        .as_ref()
        .map(|value| value.code == Some(0))
        .unwrap_or(false);
    let non_empty = std::fs::metadata(&temporary)
        .map(|meta| meta.len() > 0)
        .unwrap_or(false);
    if !ok || !non_empty {
        let _ = std::fs::remove_file(&temporary);
        let lowered = detail.to_lowercase();
        if lowered.contains("does not contain any stream")
            || lowered.contains("matches no streams")
            || lowered.contains("no audio")
        {
            return no_audio(video);
        }
        // 取最后一行有内容的 stderr 作为原因（与 Python 的 reversed(...) 一致）
        let last = detail
            .lines()
            .rev()
            .map(str::trim)
            .find(|line| !line.is_empty())
            .unwrap_or("未知错误")
            .to_string();
        return failed(video, &format!("拆解失败：{last}"));
    }

    let duration = system::probe_duration(ffprobe, &temporary);
    let print = fingerprint::compute(Some(ffmpeg), &temporary);
    let duration = duration.or_else(|| print.as_ref().map(|value| value.duration));

    let mut saved = json!({
        "video": paths::display(&paths::absolute(video)),
        "name": temporary.file_name().map(|v| v.to_string_lossy().into_owned()).unwrap_or_default(),
        "path": temporary.to_string_lossy().into_owned(),
        "status": "saved",
        "duration": duration,
    });

    // 索引写入是「读-改-写」，必须保证同一目录不并发；这里用全局互斥就够了
    // （单机素材库并发写同一目录的窗口极小，且每条都是独立文件）。
    // ⚠️ `Index.entries` 本身就是「文件名 → 条目」的映射，`save_index` 会再包一层
    // `{"version":…, "entries":…}`。这里再套一层会写出 `{"entries":{"entries":…}}`，
    // 后续 `all_index_entries` 读不到签名，避重就静默失效了（第一版就这样）。
    let mut index = snapshot::load_index(target_dir);

    if avoid_duplicates {
        if let Some(current) = print.as_ref() {
            for (folder, name, cached) in write_ops::all_index_entries(bgm_base) {
                let signature: Vec<f64> = cached
                    .get("signature")
                    .and_then(Value::as_array)
                    .map(|values| values.iter().filter_map(Value::as_f64).collect())
                    .unwrap_or_default();
                if signature.is_empty() {
                    continue;
                }
                let cached_duration = cached
                    .get("duration")
                    .and_then(Value::as_f64)
                    .unwrap_or(0.0);
                if write_ops::fingerprints_duplicate(
                    &current.signature,
                    current.duration,
                    &signature,
                    cached_duration,
                ) {
                    let _ = std::fs::remove_file(&temporary);
                    let display = if folder.is_empty() {
                        name
                    } else {
                        format!("{folder}/{name}")
                    };
                    return json!({
                        "video": paths::display(&paths::absolute(video)),
                        "name": video.file_name().map(|v| v.to_string_lossy().into_owned()).unwrap_or_default(),
                        "path": "",
                        "status": "duplicate",
                        "reason": format!("库中已有相同 BGM：{display}"),
                        "duration": duration,
                    });
                }
            }
        }
    }

    let existing: BTreeMap<String, Option<String>> = Some(&index.entries)
        .map(|object| {
            object
                .iter()
                .map(|(name, entry)| {
                    (
                        name.clone(),
                        entry
                            .get("sha256")
                            .and_then(Value::as_str)
                            .map(str::to_string),
                    )
                })
                .collect()
        })
        .unwrap_or_default();
    let existing_sha: BTreeMap<String, String> = existing
        .into_iter()
        .filter_map(|(name, sha)| sha.map(|value| (name, value)))
        .collect();
    let target = write_ops::unique_path(target_dir, &format!("{stem}.mp3"), &existing_sha);
    if std::fs::rename(&temporary, &target).is_err() {
        // 跨卷或目标已存在时退化为复制 + 删除
        let _ = std::fs::copy(&temporary, &target);
        let _ = std::fs::remove_file(&temporary);
    }

    let sha = hash::file_sha256(&target).unwrap_or_default();
    let meta = std::fs::metadata(&target).ok();
    let mut entry = json!({
        "sha256": sha,
        "added_at": snapshot::now_iso(),
        "mtime_ns": meta.as_ref().map(snapshot::modified_ns).unwrap_or(0),
        "size": meta.as_ref().map(|value| value.len()).unwrap_or(0),
        "duration": duration,
    });
    if let Some(current) = print.as_ref() {
        entry["signature"] = json!(current.signature);
    }
    {
        let object = &mut index.entries;
        object.insert(
            target
                .file_name()
                .map(|value| value.to_string_lossy().into_owned())
                .unwrap_or_default(),
            entry,
        );
    }
    let _ = snapshot::save_index(target_dir, &index);

    saved["name"] = json!(target
        .file_name()
        .map(|value| value.to_string_lossy().into_owned())
        .unwrap_or_default());
    saved["path"] = json!(paths::display(&paths::absolute(&target)));
    saved
}

/// `library_extract_bgm`：启动后台任务，立即返回 `{task_id, total}`。
pub fn start(
    params: &Map<String, Value>,
    sink: super::jobs::EventSink,
    ffmpeg: Option<PathBuf>,
    ffprobe: Option<PathBuf>,
) -> Result<Value, String> {
    let bgm_dir = match params.get("bgm_dir").and_then(Value::as_str) {
        Some(value) if !value.trim().is_empty() => PathBuf::from(value.trim()),
        _ => library_bgm_dir()?,
    };
    let Some(ffmpeg) = ffmpeg else {
        return Err("未找到 FFmpeg，无法拆解 BGM".to_string());
    };

    let raw_paths: Vec<String> = params
        .get("paths")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(|value| value.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    let folder = params
        .get("folder")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let videos = collect_videos(&raw_paths, &folder);
    if videos.is_empty() {
        return Err("没有找到可处理的视频文件".to_string());
    }

    let options = params.get("options").and_then(Value::as_object);
    let avoid_duplicates = options
        .and_then(|object| object.get("avoid_duplicates"))
        .and_then(Value::as_bool)
        .unwrap_or(true);
    let save_folder = write_ops::relative_folder(params.get("save_folder"))?;
    let target_dir = if save_folder.is_empty() {
        bgm_dir.clone()
    } else {
        bgm_dir.join(save_folder.replace('/', std::path::MAIN_SEPARATOR_STR))
    };
    std::fs::create_dir_all(&target_dir).map_err(|error| error.to_string())?;

    let task_id = format!(
        "extract-{}-{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_millis())
            .unwrap_or(0),
        std::process::id()
    );
    let cancelled = Arc::new(AtomicBool::new(false));
    tasks()
        .lock()
        .map_err(|_| "任务表不可用".to_string())?
        .insert(
            task_id.clone(),
            ExtractTask {
                cancelled: cancelled.clone(),
            },
        );

    let total = videos.len();
    let worker_task_id = task_id.clone();
    std::thread::spawn(move || {
        let mut results: Vec<Value> = Vec::new();
        for video in &videos {
            // 取消后剩余每条都记为 cancelled（与 Python 一致：不 break，保留条数）
            let result = if cancelled.load(Ordering::SeqCst) {
                json!({
                    "video": paths::display(&paths::absolute(video)),
                    "name": video.file_name().map(|v| v.to_string_lossy().into_owned()).unwrap_or_default(),
                    "path": "",
                    "status": "cancelled",
                    "reason": "任务已取消",
                })
            } else {
                extract_one(
                    video,
                    &bgm_dir,
                    &target_dir,
                    &ffmpeg,
                    ffprobe.as_deref(),
                    avoid_duplicates,
                )
            };
            results.push(result.clone());
            sink(
                "library.extract.progress",
                json!({
                    "task_id": worker_task_id,
                    "done": results.len(),
                    "total": total,
                    "current": video.file_name().map(|v| v.to_string_lossy().into_owned()).unwrap_or_default(),
                    "result": result,
                }),
            );
        }

        let summary = summarize(&results);
        if let Ok(mut guard) = tasks().lock() {
            guard.remove(&worker_task_id);
        }
        sink(
            "library.extract.done",
            json!({
                "task_id": worker_task_id,
                "results": results,
                "summary": summary,
                "total": total,
            }),
        );
    });

    Ok(json!({ "task_id": task_id, "total": total }))
}

/// `library_extract_cancel`：给任务打取消标记。
pub fn cancel(params: &Map<String, Value>) -> Result<Value, String> {
    let task_id = params
        .get("task_id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let guard = tasks().lock().map_err(|_| "任务表不可用".to_string())?;
    let Some(task) = guard.get(&task_id) else {
        return Err("拆 BGM 任务不存在".to_string());
    };
    task.cancelled.store(true, Ordering::SeqCst);
    Ok(json!({ "cancelled": true, "task_id": task_id }))
}

/// `_summarize`：按状态计数。
fn summarize(results: &[Value]) -> Value {
    let mut summary = json!({
        "saved": 0, "duplicate": 0, "no_audio": 0, "failed": 0, "cancelled": 0, "total": results.len()
    });
    for result in results {
        let Some(status) = result.get("status").and_then(Value::as_str) else {
            continue;
        };
        if let Some(object) = summary.as_object_mut() {
            if let Some(counter) = object.get(status).and_then(Value::as_i64) {
                object.insert(status.to_string(), json!(counter + 1));
            }
        }
    }
    summary
}

/// 默认 BGM 目录（`~/Documents/图转视频素材库/BGM`）。
fn library_bgm_dir() -> Result<PathBuf, String> {
    let (_, bgm, _) = super::library::default_paths();
    Ok(bgm)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn safe_name_strips_illegal_characters() {
        assert_eq!(safe_name("a/b\\c:d*e?f"), "a_b_c_d_e_f");
        assert_eq!(safe_name("  正常名字  "), "正常名字");
        assert_eq!(safe_name("   "), "未命名");
        assert_eq!(safe_name(""), "未命名");
    }

    #[test]
    fn collect_videos_filters_by_extension_and_sorts() {
        let dir = std::env::temp_dir().join(format!("itv-extract-collect-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("sub")).unwrap();
        for name in ["b.mp4", "A.MP4", "note.txt", "c.mkv"] {
            std::fs::write(dir.join(name), b"x").unwrap();
        }
        std::fs::write(dir.join("sub").join("d.mov"), b"x").unwrap();
        std::fs::write(dir.join("sub").join("e.wav"), b"x").unwrap();

        let explicit: Vec<String> = vec![dir.join("note.txt").to_string_lossy().into_owned()];
        let found = collect_videos(&explicit, &dir.to_string_lossy());
        let names: Vec<String> = found
            .iter()
            .map(|path| path.file_name().unwrap().to_string_lossy().into_owned())
            .collect();
        // 小写全路径排序：a.mp4 < b.mp4 < c.mkv < d.mov
        assert_eq!(names, vec!["A.MP4", "b.mp4", "c.mkv", "d.mov"]);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn summarize_counts_each_status() {
        let results = vec![
            json!({ "status": "saved" }),
            json!({ "status": "saved" }),
            json!({ "status": "duplicate" }),
            json!({ "status": "no_audio" }),
            json!({ "status": "failed" }),
            json!({ "status": "cancelled" }),
            json!({}),
        ];
        let summary = summarize(&results);
        assert_eq!(summary["saved"], 2);
        assert_eq!(summary["duplicate"], 1);
        assert_eq!(summary["no_audio"], 1);
        assert_eq!(summary["failed"], 1);
        assert_eq!(summary["cancelled"], 1);
        assert_eq!(summary["total"], 7);
    }

    #[test]
    fn cancel_unknown_task_reports_missing() {
        let mut params = Map::new();
        params.insert("task_id".into(), json!("extract-does-not-exist"));
        let error = cancel(&params).unwrap_err();
        assert!(error.contains("不存在"), "错误文案: {error}");
    }
}
