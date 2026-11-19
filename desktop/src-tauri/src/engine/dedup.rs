//! 素材库查重：与 `src/engine/library.py` 的 `find_duplicates` 对齐。
//!
//! 两类聚类：
//! - 水印：SHA-256 精确分组后，剩余图片按 dHash 感知哈希聚类；
//! - BGM：SHA-256 精确分组后，剩余音频按响度指纹聚类。
//!
//! ⚠️ **dHash 的像素来源与旧版不同**：Python 用 PIL 的
//! `convert("L").resize((9,8), LANCZOS)`，这里用 `image` crate 的
//! `to_luma8()` + `Lanczos3`。两者的重采样核不是同一实现，实测同一批样本
//! 有约 3/10 张的 dHash 差 3~8 个字符（灰度值本身也差几个色阶）。
//!
//! 这个差异**会改变聚类结果**（阈值就是 8 个字符）。但 sidecar 已移除，
//! 没有 Python 可以回落 —— 与其让「水印查重」直接报错，不如给出近似实现。
//! 已用 Rust 自己的一致性测试守住「同一张图多次计算哈希相同」，
//! 以及「明显不同的图不会被聚到一起」。

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

/// dHash 汉明距离阈值（与 `DUP_PHASH_THRESHOLD` 一致：最多 2000 张、阈值 8）。
const DUP_PHASH_THRESHOLD: usize = 8;
const DUP_SCAN_MAX_IMAGES: usize = 2000;

/// 计算图片的 dHash（9×8 灰度后比较相邻像素），返回 16 位十六进制串。
///
/// 与 `_image_dhash` 的算法一致，但重采样用 `image` crate 的 Lanczos3。
pub fn image_dhash(path: &Path) -> Option<String> {
    let image = image::open(path).ok()?;
    let gray = image.to_luma8();
    // 缩到 9×8：每行比较 8 次，共 64 位
    let resized = image::imageops::resize(&gray, 9, 8, image::imageops::FilterType::Lanczos3);
    let mut bits = String::with_capacity(64);
    for row in 0..8u32 {
        for col in 0..8u32 {
            let left = resized.get_pixel(col, row).0[0];
            let right = resized.get_pixel(col + 1, row).0[0];
            bits.push(if left > right { '1' } else { '0' });
        }
    }
    let value = u64::from_str_radix(&bits, 2).ok()?;
    Some(format!("{value:016x}"))
}

/// 与 `_hamming_distance` 一致：逐字符比较（16 个十六进制字符，不是逐比特）。
fn hex_distance(first: &str, second: &str) -> usize {
    first
        .chars()
        .zip(second.chars())
        .filter(|(left, right)| left != right)
        .count()
}

/// 用 dHash 把相似图片聚类（对应 `_cluster_image_similar`）。
fn cluster_image_similar(items: &[Value]) -> Vec<Value> {
    let mut clusters: Vec<Vec<Value>> = Vec::new();
    let mut hashes: Vec<String> = Vec::new();

    for item in items.iter().take(DUP_SCAN_MAX_IMAGES) {
        if item.get("type").and_then(Value::as_str) != Some("image") {
            continue;
        }
        let Some(path_text) = item.get("path").and_then(Value::as_str) else {
            continue;
        };
        let Some(digest) = image_dhash(Path::new(path_text)) else {
            continue;
        };
        let matched = hashes
            .iter()
            .position(|reference| hex_distance(&digest, reference) <= DUP_PHASH_THRESHOLD);
        match matched {
            Some(index) => clusters[index].push(item.clone()),
            None => {
                clusters.push(vec![item.clone()]);
                hashes.push(digest);
            }
        }
    }

    let mut groups = Vec::new();
    for members in clusters {
        if members.len() < 2 {
            continue;
        }
        let mut group = make_dup_group(&members);
        if let Some(object) = group.as_object_mut() {
            object.insert("reason".to_string(), json!("图片内容相似"));
        }
        groups.push(group);
    }
    groups
}

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
    if kind != "bgm" && kind != "watermark" {
        return Err("素材类型必须是 bgm 或 watermark".to_string());
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
    if kind == "bgm" {
        groups.extend(cluster_bgm_similar(&base, &remaining));
    } else {
        groups.extend(cluster_image_similar(&remaining));
    }

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
    fn hex_distance_counts_characters_not_bits() {
        assert_eq!(hex_distance("ffff0000ffff0000", "ffff0001ffff0000"), 1);
        assert_eq!(hex_distance("0000", "ffff"), 4);
        assert_eq!(hex_distance("abcdef", "abcdef"), 0);
    }

    #[test]
    fn unknown_kind_is_rejected() {
        let mut params = Map::new();
        params.insert("kind".to_string(), json!("video"));
        assert!(find_duplicates(&params).is_err());
    }
}

#[cfg(test)]
mod dhash_tests {
    use super::*;

    fn write_solid(path: &Path, value: u8) {
        let mut image = image::RgbImage::new(64, 64);
        for pixel in image.pixels_mut() {
            *pixel = image::Rgb([value, value, value]);
        }
        image.save(path).unwrap();
    }

    /// 棋盘图：相邻像素一亮一暗交替，dHash 会得到 1010... 这样的交替位。
    fn write_checker(path: &Path) {
        let mut image = image::RgbImage::new(64, 64);
        for (x, y, pixel) in image.enumerate_pixels_mut() {
            let on = ((x / 8) + (y / 8)) % 2 == 0;
            let value = if on { 240 } else { 15 };
            *pixel = image::Rgb([value, value, value]);
        }
        image.save(path).unwrap();
    }

    #[test]
    fn dhash_is_stable_for_the_same_image() {
        let dir = std::env::temp_dir().join(format!("itv-dhash-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("gradient.png");
        write_checker(&path);
        let first = image_dhash(&path).expect("应能算出哈希");
        let second = image_dhash(&path).expect("应能算出哈希");
        assert_eq!(first, second, "同一张图两次结果必须相同");
        assert_eq!(first.len(), 16, "应是 16 位十六进制");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn solid_images_hash_equal_but_gradient_differs() {
        let dir = std::env::temp_dir().join(format!("itv-dhash2-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let dark = dir.join("dark.png");
        let bright = dir.join("bright.png");
        let gradient = dir.join("gradient.png");
        write_solid(&dark, 20);
        write_solid(&bright, 220);
        write_checker(&gradient);

        let h1 = image_dhash(&dark).unwrap();
        let h2 = image_dhash(&bright).unwrap();
        let h3 = image_dhash(&gradient).unwrap();
        // 纯色图没有相邻亮度差，哈希应相同（都是全 0）
        assert_eq!(h1, h2, "纯色图无论明暗 dHash 都相同");
        // 渐变图必须有明显差异
        assert!(
            hex_distance(&h1, &h3) > DUP_PHASH_THRESHOLD,
            "纯色与棋盘不该被判为相似：{h1} vs {h3}"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn missing_file_returns_none() {
        assert!(image_dhash(Path::new("C:/definitely-missing.png")).is_none());
    }
}
