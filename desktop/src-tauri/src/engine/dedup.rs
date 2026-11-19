//! 素材库查重（仅 BGM）：与 `src/engine/library.py` 的 `find_duplicates` 对齐。
//!
//! 只接管 `kind == "bgm"`：SHA-256 精确分组后，剩余音频按响度指纹聚类。
//!
//! ⚠️ **水印查重（`kind == "watermark"`）仍交给 Python**，原因不是偷懒：
//! 它用 PIL 的 `convert("L").resize((9, 8), LANCZOS)` 算 dHash，而 PIL 的定点
//! Lanczos 与 ffmpeg 的 swscale 不是同一实现。实测 10 张样本图（纯色/渐变/棋盘/
//! 圆形/噪声/条纹/JPEG/缩放版/带 alpha）中有 3 张 dHash 不同：
//! `circle` 差 8 个字符、`noise` 差 3 个、`stripes` 差 8 个；灰度值本身就能差 3
//! （PIL 85 vs ffmpeg 82，ffmpeg 的 gray 转换做了范围压缩）。
//! 阈值是 8 个字符，这种差异足以改变聚类结果 —— 与其留一个「有时查得出、有时查不出」
//! 的实现，不如继续用旧引擎，等有精力逐位复刻 PIL 的重采样再接。

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use serde_json::{json, Map, Value};

use super::library;
use super::paths;
use super::snapshot;
use super::write_ops;

fn name_of(item: &Value) -> String {
    item.get("name")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string()
}

fn path_of(item: &Value) -> String {
    item.get("path")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string()
}

fn text(params: &Map<String, Value>, key: &str) -> String {
    params
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_string()
}

fn library_base(kind: &str, params: &Map<String, Value>) -> PathBuf {
    let (_, bgm, watermark) = library::default_paths();
    let (key, fallback) = if kind == "bgm" {
        ("bgm_dir", bgm)
    } else {
        ("watermark_dir", watermark)
    };
    snapshot::resolve_dir(params, key, &fallback)
}

/// 与 `_make_dup_group()` 等价：代表项取「名称小写 + 路径」排序后的第一个。
fn make_dup_group(members: &[Value]) -> Value {
    let mut sorted: Vec<Value> = members.to_vec();
    sorted.sort_by(|a, b| {
        name_of(a)
            .to_lowercase()
            .cmp(&name_of(b).to_lowercase())
            .then_with(|| path_of(a).cmp(&path_of(b)))
    });
    let representative = sorted.first().cloned().unwrap_or(Value::Null);
    let duplicates: Vec<Value> = sorted.iter().skip(1).cloned().collect();
    let saved: i64 = duplicates
        .iter()
        .map(|item| item.get("size_bytes").and_then(Value::as_i64).unwrap_or(0))
        .sum();
    json!({
        "reason": "内容完全相同",
        "representative": representative,
        "duplicates": duplicates,
        "count": sorted.len(),
        "saved_bytes": saved,
    })
}

fn cluster_bgm_similar(base: &Path, items: &[Value]) -> Vec<Value> {
    let mut signatures: BTreeMap<String, (Vec<f64>, f64)> = BTreeMap::new();
    for (folder, name, entry) in write_ops::all_index_entries(base) {
        let Some(signature) = entry.get("signature").and_then(Value::as_array) else {
            continue;
        };
        let Some(duration) = entry.get("duration").and_then(Value::as_f64) else {
            continue;
        };
        if signature.is_empty() || duration == 0.0 {
            continue;
        }
        let curve: Vec<f64> = signature.iter().filter_map(Value::as_f64).collect();
        let key = if folder.is_empty() {
            base.join(&name)
        } else {
            base.join(&folder).join(&name)
        };
        signatures.insert(paths::display(&paths::absolute(&key)), (curve, duration));
    }

    let mut clusters: Vec<Vec<Value>> = Vec::new();
    let mut cluster_sigs: Vec<(Vec<f64>, f64)> = Vec::new();
    for item in items {
        let key = paths::display(&paths::absolute(Path::new(&path_of(item))));
        let Some((curve, duration)) = signatures.get(&key) else {
            continue;
        };
        let matched = cluster_sigs.iter().position(|(ref_curve, ref_duration)| {
            write_ops::fingerprints_duplicate(curve, *duration, ref_curve, *ref_duration)
        });
        match matched {
            Some(index) => clusters[index].push(item.clone()),
            None => {
                clusters.push(vec![item.clone()]);
                cluster_sigs.push((curve.clone(), *duration));
            }
        }
    }
    let mut groups = Vec::new();
    for members in clusters {
        if members.len() < 2 {
            continue;
        }
        let mut group = make_dup_group(&members);
        group["reason"] = json!("音频内容相似（同曲不同版本）");
        groups.push(group);
    }
    groups
}

pub fn find_duplicates(params: &Map<String, Value>) -> Result<Value, String> {
    let kind = text(params, "kind");
    if kind != "bgm" {
        // 水印查重依赖 PIL 的 dHash（见模块注释），不在这里处理。
        return Err("Rust 引擎只处理 BGM 查重".to_string());
    }
    let base = library_base(&kind, params);
    let (items, _folders) = snapshot::scan_tree(&base, &kind);

    let mut groups: Vec<Value> = Vec::new();
    let mut by_sha: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for item in &items {
        let key = item
            .get("duplicate_key")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        by_sha.entry(key).or_default().push(item.clone());
    }
    let mut used: BTreeSet<String> = BTreeSet::new();
    for members in by_sha.values() {
        if members.len() < 2 {
            continue;
        }
        groups.push(make_dup_group(members));
        for item in members {
            used.insert(path_of(item));
        }
    }
    let remaining: Vec<Value> = items
        .iter()
        .filter(|item| !used.contains(&path_of(item)))
        .cloned()
        .collect();
    groups.extend(cluster_bgm_similar(&base, &remaining));

    groups.sort_by(|a, b| {
        let saved_a = a.get("saved_bytes").and_then(Value::as_i64).unwrap_or(0);
        let saved_b = b.get("saved_bytes").and_then(Value::as_i64).unwrap_or(0);
        saved_b
            .cmp(&saved_a)
            .then_with(|| {
                let name_a = a
                    .get("representative")
                    .map(name_of)
                    .unwrap_or_default()
                    .to_lowercase();
                let name_b = b
                    .get("representative")
                    .map(name_of)
                    .unwrap_or_default()
                    .to_lowercase();
                name_a.cmp(&name_b)
            })
    });

    Ok(json!({ "groups": groups, "scanned": items.len() }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn representative_is_lowest_name_and_saved_bytes_exclude_it() {
        let members = vec![
            json!({"name": "B.wav", "path": "b", "size_bytes": 10}),
            json!({"name": "a.wav", "path": "a", "size_bytes": 20}),
            json!({"name": "c.wav", "path": "c", "size_bytes": 30}),
        ];
        let group = make_dup_group(&members);
        assert_eq!(group["count"], 3);
        assert_eq!(group["representative"]["name"], "a.wav");
        assert_eq!(group["saved_bytes"], 40);
        assert_eq!(group["duplicates"].as_array().map(Vec::len), Some(2));
    }

    #[test]
    fn watermark_is_left_to_the_python_engine() {
        let mut params = Map::new();
        params.insert("kind".to_string(), json!("watermark"));
        assert!(find_duplicates(&params).is_err());
    }

    #[test]
    fn unknown_kind_is_rejected() {
        let mut params = Map::new();
        params.insert("kind".to_string(), json!("video"));
        assert!(find_duplicates(&params).is_err());
    }
}
