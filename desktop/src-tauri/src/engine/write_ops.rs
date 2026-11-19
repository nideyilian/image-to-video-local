//! 素材库写操作：导入（含跨库去重）、重命名、元数据。
//!
//! 对照 `src/engine/library.py` 的 `import_files` / `rename_item` / `set_metadata`。
//!
//! 导入是这块最要紧的一步：它决定「同一首歌换个码率再导入」会不会变成两条。
//! 判定顺序与旧引擎一致 —— 先比 SHA-256，再比音频指纹（时长差 ≤2.5 秒、
//! 归一化响度曲线在 ±1 秒对齐下的最小 MAE ≤0.07）。

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Map, Value};

use super::fingerprint;
use super::hash;
use super::library;
use super::paths;
use super::snapshot;
use super::system;

const DURATION_TOLERANCE: f64 = 2.5;
const SHIFT_TOLERANCE: i32 = 1;
const DUP_MAE_THRESHOLD: f64 = 0.07;
const MIN_OVERLAP_FRACTION: f64 = 0.5;

// ---------- 参数与路径 ----------

fn text(params: &Map<String, Value>, key: &str) -> String {
    params
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_string()
}

fn kind_of(params: &Map<String, Value>) -> Result<String, String> {
    let kind = text(params, "kind");
    if kind != "bgm" && kind != "watermark" {
        return Err("素材类型必须是 bgm 或 watermark".to_string());
    }
    Ok(kind)
}

/// 与 `_resolve_dirs()` 等价：params 指定则用指定值，否则用默认目录。
fn base_of(kind: &str, params: &Map<String, Value>) -> PathBuf {
    let (_, bgm, watermark) = library::default_paths();
    let (key, fallback) = if kind == "bgm" {
        ("bgm_dir", bgm)
    } else {
        ("watermark_dir", watermark)
    };
    snapshot::resolve_dir(params, key, &fallback)
}

/// 与 `_relative_folder()` 等价：只接受相对子路径，拒绝 `..` 与非法字符。
fn relative_folder(raw: Option<&Value>) -> Result<String, String> {
    let value = raw
        .and_then(Value::as_str)
        .unwrap_or_default()
        .replace('\\', "/");
    let parts: Vec<&str> = value
        .trim()
        .trim_matches('/')
        .split('/')
        .filter(|part| !part.is_empty() && *part != "." && *part != "..")
        .collect();
    if parts.is_empty() {
        return Ok(String::new());
    }
    for part in &parts {
        if part.chars().count() > 80 || part.chars().any(|ch| "<>:\"|?*".contains(ch)) {
            return Err("文件夹名称包含非法字符".to_string());
        }
    }
    Ok(parts.join("/"))
}

/// 与 `_inside()` 等价：目标必须落在库里（解析后比较，防 `..` 越界）。
fn inside(base: &Path, path: &Path) -> bool {
    let (Ok(base), Ok(path)) = (paths::resolve(base), paths::resolve(path)) else {
        return false;
    };
    path.starts_with(&base)
}

/// 返回给前端的路径：与 Python 的 `str(path.resolve())` 等价（绝对路径 + 系统分隔符）。
fn shown(path: &Path) -> String {
    paths::display(&paths::absolute(path))
}

fn resolve_target(base: &Path, raw: &str) -> PathBuf {
    let candidate = PathBuf::from(raw);
    if candidate.is_absolute() {
        paths::absolute(&candidate)
    } else {
        paths::absolute(&base.join(candidate))
    }
}

// ---------- 指纹查重 ----------

fn normalize(values: &[f64]) -> Vec<f64> {
    let peak = values.iter().cloned().fold(0.0f64, f64::max);
    if peak <= 1e-9 {
        return values.to_vec();
    }
    values.iter().map(|value| value / peak).collect()
}

fn overlap_mae(first: &[f64], second: &[f64], shift: i32) -> Option<f64> {
    let (first_start, second_start) = if shift >= 0 {
        (0i64, shift as i64)
    } else {
        (-(shift as i64), 0)
    };
    let overlap = std::cmp::min(
        first.len() as i64 - first_start,
        second.len() as i64 - second_start,
    );
    if overlap <= 0 {
        return None;
    }
    let shortest = std::cmp::min(first.len(), second.len()) as f64;
    if (overlap as f64) < MIN_OVERLAP_FRACTION * shortest {
        return None;
    }
    let mut total = 0.0f64;
    for index in 0..overlap as usize {
        total += (first[first_start as usize + index] - second[second_start as usize + index]).abs();
    }
    Some(total / overlap as f64)
}

pub fn fingerprints_duplicate(
    first: &[f64],
    first_duration: f64,
    second: &[f64],
    second_duration: f64,
) -> bool {
    if (first_duration - second_duration).abs() > DURATION_TOLERANCE {
        return false;
    }
    if first == second {
        return true;
    }
    let left = normalize(first);
    let right = normalize(second);
    let mut best: Option<f64> = None;
    for shift in -SHIFT_TOLERANCE..=SHIFT_TOLERANCE {
        if let Some(distance) = overlap_mae(&left, &right, shift) {
            if best.map(|current| distance < current).unwrap_or(true) {
                best = Some(distance);
            }
        }
    }
    best.map(|value| value <= DUP_MAE_THRESHOLD).unwrap_or(false)
}

// ---------- 索引扫描 ----------

/// 与 `_all_index_entries()` 等价：库内所有子目录索引的 (相对文件夹, 文件名, entry)。
fn all_index_entries(base: &Path) -> Vec<(String, String, Value)> {
    let mut collected = Vec::new();
    if !base.is_dir() {
        return collected;
    }
    let mut index_files: Vec<PathBuf> = Vec::new();
    collect_index_files(base, &mut index_files);
    index_files.sort();
    for index_path in index_files {
        let Ok(text) = fs::read_to_string(&index_path) else {
            continue;
        };
        let Ok(data) = serde_json::from_str::<Value>(&text) else {
            continue;
        };
        let Some(entries) = data.get("entries").and_then(Value::as_object) else {
            continue;
        };
        let folder = index_path
            .parent()
            .map(|parent| {
                parent
                    .strip_prefix(base)
                    .map(|value| value.to_string_lossy().replace('\\', "/"))
                    .unwrap_or_default()
            })
            .unwrap_or_default();
        for (name, entry) in entries {
            if entry.is_object() {
                collected.push((folder.clone(), name.clone(), entry.clone()));
            }
        }
    }
    collected
}

fn collect_index_files(directory: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(directory) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_index_files(&path, out);
        } else if path.file_name().map(|name| name == snapshot::INDEX_FILE_NAME).unwrap_or(false) {
            out.push(path);
        }
    }
}

fn dir_content_hashes(directory: &Path, kind: &str) -> BTreeMap<String, String> {
    let mut hashes = BTreeMap::new();
    let Ok(entries) = fs::read_dir(directory) else {
        return hashes;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = path
            .file_name()
            .map(|value| value.to_string_lossy().into_owned())
            .unwrap_or_default();
        if !path.is_file() || name.starts_with('.') || !is_supported(kind, &path) {
            continue;
        }
        if let Ok(sha) = hash::file_sha256(&path) {
            hashes.insert(name, sha);
        }
    }
    hashes
}

fn is_supported(kind: &str, path: &Path) -> bool {
    if kind == "bgm" {
        snapshot::has_extension(path, &snapshot::AUDIO_EXTENSIONS)
    } else {
        snapshot::has_extension(path, &snapshot::IMAGE_EXTENSIONS)
            || snapshot::has_extension(path, &snapshot::VIDEO_EXTENSIONS)
    }
}

/// 与 `_unique_path()` 等价：重名且内容不同就加 `(2)`、`(3)`；内容相同直接复用。
fn unique_path(directory: &Path, name: &str, existing: &BTreeMap<String, String>) -> PathBuf {
    let target = directory.join(name);
    if !target.exists() {
        return target;
    }
    if target.is_file() {
        if let Ok(sha) = hash::file_sha256(&target) {
            if existing.get(name) == Some(&sha) {
                return target;
            }
        }
    }
    let path = Path::new(name);
    let stem = path
        .file_stem()
        .map(|value| value.to_string_lossy().into_owned())
        .unwrap_or_else(|| name.to_string());
    let suffix = path
        .extension()
        .map(|value| format!(".{}", value.to_string_lossy()))
        .unwrap_or_default();
    let mut counter = 2;
    loop {
        let candidate = directory.join(format!("{stem} ({counter}){suffix}"));
        if !candidate.exists() {
            return candidate;
        }
        counter += 1;
    }
}

// ---------- 导入 ----------

pub fn import_files(params: &Map<String, Value>) -> Result<Value, String> {
    let kind = kind_of(params)?;
    let sources = params
        .get("paths")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if sources.is_empty() {
        return Err("没有可导入的素材".to_string());
    }

    let base = base_of(&kind, params);
    let relative = relative_folder(params.get("folder"))?;
    let target_dir = if relative.is_empty() {
        base.clone()
    } else {
        base.join(&relative)
    };
    fs::create_dir_all(&target_dir).map_err(|error| error.to_string())?;

    let mut global: Vec<(String, String, Option<String>, Vec<f64>, f64)> = all_index_entries(&base)
        .into_iter()
        .map(|(folder, name, entry)| {
            let sha = entry.get("sha256").and_then(Value::as_str).map(str::to_string);
            let signature = entry
                .get("signature")
                .and_then(Value::as_array)
                .map(|items| items.iter().filter_map(Value::as_f64).collect::<Vec<f64>>())
                .unwrap_or_default();
            let duration = entry.get("duration").and_then(Value::as_f64).unwrap_or(0.0);
            (folder, name, sha, signature, duration)
        })
        .collect();

    let ffmpeg = system::resolve_ffmpeg(None);
    let ffprobe = system::resolve_ffprobe(None, ffmpeg.as_deref());
    let mut local_hashes = dir_content_hashes(&target_dir, &kind);

    let mut index = snapshot::load_index(&target_dir);
    let mut results: Vec<Value> = Vec::new();

    for raw in sources {
        let source_text = raw.as_str().unwrap_or_default().trim().to_string();
        let source = paths::absolute(&PathBuf::from(&source_text));
        let display_name = source
            .file_name()
            .map(|value| value.to_string_lossy().into_owned())
            .unwrap_or_default();

        if source_text.is_empty() || !source.is_file() {
            results.push(json!({
                "name": display_name,
                "path": source_text,
                "status": "failed",
                "reason": "文件不存在",
            }));
            continue;
        }
        if !is_supported(&kind, &source) {
            let suffix = source
                .extension()
                .map(|value| format!(".{}", value.to_string_lossy()))
                .unwrap_or_else(|| "（无扩展名）".to_string());
            results.push(json!({
                "name": display_name,
                "path": source_text,
                "status": "failed",
                "reason": format!("不支持的格式 {suffix}"),
            }));
            continue;
        }

        let Ok(metadata) = fs::metadata(&source) else {
            results.push(json!({
                "name": display_name,
                "path": source_text,
                "status": "failed",
                "reason": "读取文件信息失败",
            }));
            continue;
        };
        let size = metadata.len();
        let Ok(sha256) = hash::file_sha256(&source) else {
            results.push(json!({
                "name": display_name,
                "path": source_text,
                "status": "failed",
                "reason": "读取文件失败",
            }));
            continue;
        };

        let mut duplicate: Option<(String, String)> = global
            .iter()
            .find(|(_, _, cached, _, _)| cached.as_deref() == Some(sha256.as_str()))
            .map(|(folder, name, _, _, _)| (folder.clone(), name.clone()));

        let mut duration: Option<f64> = None;
        let mut signature: Option<Vec<f64>> = None;
        if duplicate.is_none() && kind == "bgm" {
            if let Some(result) = fingerprint::compute(ffmpeg.as_deref(), &source) {
                duration = Some(result.duration);
                signature = Some(result.signature.clone());
                duplicate = global
                    .iter()
                    .find(|(_, _, _, cached_signature, cached_duration)| {
                        !cached_signature.is_empty()
                            && fingerprints_duplicate(
                                &result.signature,
                                result.duration,
                                cached_signature,
                                *cached_duration,
                            )
                    })
                    .map(|(folder, name, _, _, _)| (folder.clone(), name.clone()));
            }
        }

        if let Some((folder, name)) = duplicate {
            let display = if folder.is_empty() {
                name
            } else {
                format!("{folder}/{name}")
            };
            results.push(json!({
                "name": display_name,
                "path": shown(&source),
                "status": "duplicate",
                "reason": format!("库中已有相同素材：{display}"),
                "size_bytes": size,
                "duration": duration,
            }));
            continue;
        }

        let target = unique_path(&target_dir, &display_name, &local_hashes);
        if let Err(error) = fs::copy(&source, &target) {
            results.push(json!({
                "name": display_name,
                "path": shown(&source),
                "status": "failed",
                "reason": error.to_string(),
            }));
            continue;
        }
        let target_size = fs::metadata(&target).map(|value| value.len()).unwrap_or(size);
        let target_mtime = fs::metadata(&target)
            .map(|value| snapshot::modified_ns(&value))
            .unwrap_or(0);

        let mut entry = json!({
            "sha256": sha256,
            "added_at": snapshot::now_iso(),
            "mtime_ns": target_mtime,
            "size": target_size,
        });
        if kind == "bgm" {
            if let Some(result) = fingerprint::compute(ffmpeg.as_deref(), &target) {
                entry["signature"] = json!(result.signature);
                entry["duration"] = json!(result.duration);
                duration = Some(result.duration);
                signature = Some(result.signature);
            }
        } else {
            let is_video = snapshot::has_extension(&target, &snapshot::VIDEO_EXTENSIONS);
            entry["type"] = json!(if is_video { "video" } else { "image" });
            if is_video {
                entry["duration"] = json!(system::probe_duration(ffprobe.as_deref(), &target));
            }
        }

        index
            .entries
            .insert(target.file_name().unwrap_or_default().to_string_lossy().into_owned(), entry);
        let target_name = target
            .file_name()
            .map(|value| value.to_string_lossy().into_owned())
            .unwrap_or_default();
        local_hashes.insert(target_name.clone(), sha256.clone());
        global.push((relative.clone(), target_name.clone(), Some(sha256), signature.unwrap_or_default(), duration.unwrap_or(0.0)));

        results.push(json!({
            "name": target_name,
            "path": shown(&target),
            "status": "imported",
            "folder": relative,
            "size_bytes": target_size,
            "duration": duration,
        }));
    }

    snapshot::save_index(&target_dir, &index).map_err(|error| error.to_string())?;
    Ok(json!({ "results": results }))
}

// ---------- 重命名 ----------

pub fn rename_item(params: &Map<String, Value>) -> Result<Value, String> {
    let kind = kind_of(params)?;
    let raw_path = text(params, "path");
    let new_name = text(params, "new_name");
    let base = base_of(&kind, params);
    let target = resolve_target(&base, &raw_path);

    if !target.is_file() || !inside(&base, &target) {
        return Err("只能重命名素材库内的文件".to_string());
    }
    if new_name.is_empty() || new_name == "." || new_name == ".." || new_name.contains('/') || new_name.contains('\\') {
        return Err("请输入合法的文件名".to_string());
    }
    if new_name.chars().any(|ch| "<>:\"|?*".contains(ch)) {
        return Err("文件名包含非法字符".to_string());
    }

    let suffix = target
        .extension()
        .map(|value| format!(".{}", value.to_string_lossy()))
        .unwrap_or_default();
    let stem = Path::new(&new_name)
        .file_stem()
        .map(|value| value.to_string_lossy().into_owned())
        .unwrap_or_default();
    if stem.is_empty() {
        return Err("请输入文件名".to_string());
    }
    let final_name = format!("{stem}{suffix}");
    let parent = target.parent().map(Path::to_path_buf).unwrap_or_else(|| base.clone());
    let new_target = parent.join(&final_name);

    if new_target == target {
        return Ok(json!({
            "renamed": true,
            "name": final_name,
            "path": shown(&target),
        }));
    }
    if new_target.exists() {
        return Err("同名文件已存在".to_string());
    }
    fs::rename(&target, &new_target).map_err(|error| error.to_string())?;

    let mut index = snapshot::load_index(&parent);
    let old_name = target
        .file_name()
        .map(|value| value.to_string_lossy().into_owned())
        .unwrap_or_default();
    if let Some(mut entry) = index.entries.remove(&old_name) {
        if let Ok(metadata) = fs::metadata(&new_target) {
            entry["mtime_ns"] = json!(snapshot::modified_ns(&metadata));
            entry["size"] = json!(metadata.len());
        }
        index.entries.insert(final_name.clone(), entry);
    }
    snapshot::save_index(&parent, &index).map_err(|error| error.to_string())?;

    Ok(json!({
        "renamed": true,
        "name": final_name,
        "path": shown(&new_target),
    }))
}

// ---------- 元数据 ----------

pub fn set_metadata(params: &Map<String, Value>) -> Result<Value, String> {
    let kind = kind_of(params)?;
    let raw_path = text(params, "path");
    let base = base_of(&kind, params);
    let target = resolve_target(&base, &raw_path);
    if !target.is_file() || !inside(&base, &target) {
        return Err("只能编辑素材库内的素材".to_string());
    }

    let parent = target.parent().map(Path::to_path_buf).unwrap_or_else(|| base.clone());
    let name = target
        .file_name()
        .map(|value| value.to_string_lossy().into_owned())
        .unwrap_or_default();
    let mut index = snapshot::load_index(&parent);
    if !index.entries.contains_key(&name) {
        // 与旧引擎一致：索引里没有就先补一条基础记录，避免元数据丢失。
        if let Ok(metadata) = fs::metadata(&target) {
            index.entries.insert(
                name.clone(),
                json!({
                    "sha256": hash::file_sha256(&target).unwrap_or_default(),
                    "added_at": snapshot::now_iso(),
                    "mtime_ns": snapshot::modified_ns(&metadata),
                    "size": metadata.len(),
                }),
            );
        }
    }

    let mut changed = false;
    if let Some(entry) = index.entries.get_mut(&name) {
        if let Some(raw) = params.get("tags") {
            let items = raw.as_array().ok_or_else(|| "tags 必须是字符串列表".to_string())?;
            let mut tags: Vec<String> = Vec::new();
            for item in items {
                let cleaned = item.as_str().unwrap_or_default().trim().to_string();
                if cleaned.is_empty() || tags.contains(&cleaned) {
                    continue;
                }
                tags.push(cleaned.chars().take(30).collect());
            }
            tags.truncate(50);
            entry["tags"] = json!(tags);
            changed = true;
        }
        if let Some(raw) = params.get("starred") {
            entry["starred"] = json!(super::config::is_truthy(Some(raw)));
            changed = true;
        }
        if params.contains_key("note") {
            let note: String = text(params, "note").chars().take(500).collect();
            entry["note"] = json!(note);
            changed = true;
        }
    }
    if !changed {
        return Err("没有需要更新的元数据字段".to_string());
    }
    snapshot::save_index(&parent, &index).map_err(|error| error.to_string())?;

    let entry = index.entries.get(&name).cloned().unwrap_or(Value::Null);
    Ok(json!({
        "path": shown(&target),
        "tags": entry.get("tags").cloned().unwrap_or(json!([])),
        "starred": entry.get("starred").and_then(Value::as_bool).unwrap_or(false),
        "note": entry.get("note").and_then(Value::as_str).unwrap_or(""),
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identical_fingerprints_are_duplicates() {
        let signature = vec![0.1, 0.5, 0.3, 0.9];
        assert!(fingerprints_duplicate(&signature, 4.0, &signature, 4.0));
    }

    #[test]
    fn duration_gap_beyond_tolerance_is_not_duplicate() {
        let signature = vec![0.1, 0.5, 0.3, 0.9];
        assert!(!fingerprints_duplicate(&signature, 4.0, &signature, 9.0));
    }

    #[test]
    fn shifted_curve_is_still_duplicate() {
        // 同一段音频整体平移 1 秒：归一化后重叠区完全一致
        let first = vec![0.2, 0.4, 0.8, 0.4, 0.2];
        let second = vec![0.0, 0.2, 0.4, 0.8, 0.4, 0.2];
        assert!(fingerprints_duplicate(&first, 5.0, &second, 5.5));
    }

    #[test]
    fn unrelated_curves_are_not_duplicates() {
        // 注意别用周期性曲线当反例：错位一秒就对齐了，会误判成重复
        let first = vec![0.9, 0.2, 0.4, 0.1, 0.7, 0.3];
        let second = vec![0.1, 0.8, 0.2, 0.9, 0.3, 0.6];
        assert!(!fingerprints_duplicate(&first, 6.0, &second, 6.0));
    }

    #[test]
    fn relative_folder_rejects_escape_and_illegal_names() {
        assert_eq!(relative_folder(None).unwrap(), "");
        assert_eq!(relative_folder(Some(&json!("a/b"))).unwrap(), "a/b");
        assert_eq!(relative_folder(Some(&json!("../etc"))).unwrap(), "etc");
        assert!(relative_folder(Some(&json!("a<b"))).is_err());
    }

    #[test]
    fn unique_path_adds_counter_for_different_content() {
        let directory = std::env::temp_dir().join(format!("itv-unique-{}", std::process::id()));
        let _ = fs::remove_dir_all(&directory);
        fs::create_dir_all(&directory).expect("创建目录");
        fs::write(directory.join("a.mp3"), b"first").expect("写文件");
        let mut hashes = BTreeMap::new();
        hashes.insert("a.mp3".to_string(), "different".to_string());
        let chosen = unique_path(&directory, "a.mp3", &hashes);
        assert_eq!(chosen.file_name().unwrap().to_string_lossy(), "a (2).mp3");
        let _ = fs::remove_dir_all(&directory);
    }
}
