//! 配置：默认值、归一化与校验，逐条对齐 `src/engine/config.py`。
//!
//! 默认配置**不是手抄**的：`default_config.json` 直接由 Python 的
//! `build_default_config()` 导出（46 个字段、33 个转场、39 个特效），
//! Rust 侧 `include_str!` 内嵌解析。这样新增字段不会有第二份手写清单，
//! 而 `tests/test_config_contract_parity.py` 会盯着两边是否漂移。
//!
//! 校验函数的每个分支都按 Python 的语义复刻，包括几个容易被忽略的点：
//! - Python 的 truthy 判定（`bool("")` 为假、`bool("0")` 为真）；
//! - `str(None)` 是 `"None"`，所以显式为 null 的字段不会走默认值分支；
//! - `total_duration` 转换失败时兜底成 `-1.0`（故意让它触发「不能小于 0」）；
//! - 「按子文件夹抽取」不校验 `num_images`，且图片数为 0 的检查走另一条路径。

use std::fs;
use std::path::Path;

use serde_json::{json, Value};

use super::paths;
use super::scan;
use super::sort::compare_names;

pub const SUBFOLDER_SELECTION_MODE: &str = "按子文件夹抽取";

const AUDIO_EXTENSIONS: [&str; 6] = [".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"];
const SLOT_COUNT_TOLERANCE: f64 = 1e-3;
const VIDEO_EFFECT_ALIASES: [(&str, &str); 1] = [("心跳跃动", "心跳跳动")];
const DEFAULT_CONFIG_JSON: &str = include_str!("default_config.json");

/// 与 `build_default_config()` 等价的默认配置。
pub fn default_config() -> Value {
    serde_json::from_str(DEFAULT_CONFIG_JSON).expect("内置默认配置必须是合法 JSON")
}

// ---------- Python 取值语义的等价实现 ----------

pub(crate) fn is_truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(flag)) => *flag,
        Some(Value::Number(number)) => number.as_f64().map(|value| value != 0.0).unwrap_or(false),
        Some(Value::String(text)) => !text.is_empty(),
        Some(Value::Array(items)) => !items.is_empty(),
        Some(Value::Object(map)) => !map.is_empty(),
    }
}

/// Python `str(value)`：注意 `None` → `"None"`，布尔 → `"True"` / `"False"`。
fn py_str(value: Option<&Value>) -> String {
    match value {
        None | Some(Value::Null) => "None".to_string(),
        Some(Value::String(text)) => text.clone(),
        Some(Value::Bool(flag)) => if *flag { "True" } else { "False" }.to_string(),
        Some(Value::Number(number)) => match number.as_i64() {
            Some(integer) => integer.to_string(),
            None => number.to_string(),
        },
        Some(other) => other.to_string(),
    }
}

/// `config.get(key, fallback)` + `str(...)`：键缺失才用 fallback。
fn text_or(config: &Value, key: &str, fallback: &str) -> String {
    match config.get(key) {
        None => fallback.to_string(),
        Some(value) => py_str(Some(value)),
    }
}

fn to_int(value: &Value) -> Option<i64> {
    match value {
        Value::Bool(flag) => Some(if *flag { 1 } else { 0 }),
        Value::Number(number) => number
            .as_i64()
            .or_else(|| number.as_f64().map(|float| float.trunc() as i64)),
        Value::String(text) => text.trim().parse::<i64>().ok(),
        _ => None,
    }
}

fn to_float(value: &Value) -> Option<f64> {
    match value {
        Value::Bool(flag) => Some(if *flag { 1.0 } else { 0.0 }),
        Value::Number(number) => number.as_f64(),
        Value::String(text) => text.trim().parse::<f64>().ok(),
        _ => None,
    }
}

fn int_or(config: &Value, key: &str, fallback: i64) -> i64 {
    config.get(key).and_then(to_int).unwrap_or(fallback)
}

fn float_or(config: &Value, key: &str, fallback: f64) -> f64 {
    config.get(key).and_then(to_float).unwrap_or(fallback)
}

fn alias(effect: &str) -> String {
    VIDEO_EFFECT_ALIASES
        .iter()
        .find(|(from, _)| *from == effect)
        .map(|(_, to)| (*to).to_string())
        .unwrap_or_else(|| effect.to_string())
}

// ---------- 归一化 ----------

/// 与 `parse_resolution()` 等价：匹配 `<宽>x<高>`，否则退回 1280x720；最小 2。
pub fn parse_resolution(value: Option<&Value>) -> (i64, i64) {
    let raw = if is_truthy(value) {
        py_str(value)
    } else {
        String::new()
    };
    let text = raw.trim();
    let mut parts = text.split(['x', 'X', '×']);
    let (Some(left), Some(right), None) = (parts.next(), parts.next(), parts.next()) else {
        return (1280, 720);
    };
    let (left, right) = (left.trim(), right.trim());
    let digits = |part: &str| !part.is_empty() && part.chars().all(|ch| ch.is_ascii_digit());
    if !digits(left) || !digits(right) {
        return (1280, 720);
    }
    let (Ok(width), Ok(height)) = (left.parse::<i64>(), right.parse::<i64>()) else {
        return (1280, 720);
    };
    (width.max(2), height.max(2))
}

pub fn normalize_config(raw: Option<&Value>) -> Value {
    let mut config = default_config();
    if let Some(Value::Object(overrides)) = raw {
        if let Some(target) = config.as_object_mut() {
            for (key, value) in overrides {
                target.insert(key.clone(), value.clone());
            }
        }
    }

    let (width, height) = parse_resolution(config.get("resolution_preset"));
    let effect = alias(&text_or(&config, "video_effect_type", "无特效"));
    let enabled_effects: Option<Vec<Value>> = match config.get("enabled_video_effects") {
        Some(Value::Array(items)) => Some(
            items
                .iter()
                .map(|item| json!(alias(&py_str(Some(item)))))
                .collect(),
        ),
        _ => None,
    };
    let prefix = text_or(&config, "custom_prefix", "").trim().to_string();
    let bgm_files: Vec<Value> = match config.get("bgm_files") {
        Some(Value::Array(items)) => items
            .iter()
            .filter_map(|item| match item {
                Value::String(text) if !text.trim().is_empty() => Some(Value::String(text.clone())),
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    };

    {
        let target = config.as_object_mut().expect("默认配置必须是对象");
        target.insert("width".to_string(), json!(width));
        target.insert("height".to_string(), json!(height));
        target.insert("watermark_type".to_string(), json!("视频"));
        target.insert("video_effect_type".to_string(), json!(effect));
        if let Some(effects) = enabled_effects {
            target.insert("enabled_video_effects".to_string(), Value::Array(effects));
        }
        target.insert("custom_prefix".to_string(), json!(prefix));
        target.insert("bgm_files".to_string(), Value::Array(bgm_files));
        // 特效专属参数：缺省给空表。结构是「特效 id → 参数键 → 值」，
        // 没设过的由 `effect_params::resolve` 用 catalog 里的默认值兜底，
        // 所以这里不需要预填任何内容 —— 预填反而会让「用户没改过」和
        // 「用户改成了默认值」无法区分。
        if !target.contains_key("effect_params") {
            target.insert("effect_params".to_string(), json!({}));
        }
    }
    config
}

// ---------- 扫描辅助 ----------

fn is_audio(path: &Path) -> bool {
    match path.extension().and_then(|ext| ext.to_str()) {
        Some(ext) => AUDIO_EXTENSIONS.contains(&format!(".{}", ext.to_lowercase()).as_str()),
        None => false,
    }
}

/// 与 `scan_audio_files()` 等价：只扫一层、按自然顺序排序、返回绝对路径。
pub fn scan_audio_files(dir: &str) -> Vec<String> {
    let root = Path::new(dir.trim());
    if !root.is_dir() {
        return Vec::new();
    }
    let Ok(entries) = fs::read_dir(root) else {
        return Vec::new();
    };
    let mut files: Vec<String> = entries
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| path.is_file() && is_audio(path))
        .map(|path| paths::to_string(&paths::absolute(&path)))
        .collect();
    files.sort_by(|left, right| compare_names(left, right));
    files
}

// ---------- 校验 ----------

fn issue(field: &str, section: &str, message: &str) -> Value {
    json!({ "field": field, "section": section, "message": message })
}

/// 与 `timeline_slot_count()` 等价；`Ok(None)` 表示总时长为 0（自动）。
pub fn timeline_slot_count(
    image_duration: f64,
    total_duration: f64,
) -> Result<Option<i64>, String> {
    if image_duration <= 0.0 {
        return Err("每图时长必须大于 0".to_string());
    }
    if total_duration < 0.0 {
        return Err("总时长不能小于 0".to_string());
    }
    if total_duration == 0.0 {
        return Ok(None);
    }
    let raw_slots = total_duration / image_duration;
    let slot_count = raw_slots.round();
    if slot_count < 1.0 || (raw_slots - slot_count).abs() > SLOT_COUNT_TOLERANCE {
        return Err("总时长必须是每图时长的整数倍（例如每图 1 秒、总时长 8 秒）".to_string());
    }
    Ok(Some(slot_count as i64))
}

fn subfolder_selection_issues(input_dir: &str) -> Vec<Value> {
    let scan = scan::scan_subfolders(input_dir);
    if !scan.groups.is_empty() {
        return Vec::new();
    }
    let detail = if scan.skipped.is_empty() {
        String::new()
    } else {
        format!("，其中 {} 个空文件夹", scan.skipped.len())
    };
    vec![issue(
        "input_dir",
        "basic",
        &format!(
            "输入目录里没有包含图片的子文件夹{detail}；请放入形如 1、2、3 的子文件夹，或改用其它选图方式。"
        ),
    )]
}

pub fn validate_config_detailed(raw: Option<&Value>, check_files: bool) -> Vec<Value> {
    let config = normalize_config(raw);
    let mut issues: Vec<Value> = Vec::new();

    let input_dir = text_or(&config, "input_dir", "").trim().to_string();
    let output_dir = text_or(&config, "output_dir", "").trim().to_string();

    if input_dir.is_empty() {
        issues.push(issue(
            "input_dir",
            "basic",
            "请先选择「输入目录」（存放图片的文件夹），再开始导出。",
        ));
    } else if check_files && !Path::new(&input_dir).is_dir() {
        issues.push(issue(
            "input_dir",
            "basic",
            "找不到输入目录，请重新选择已存在的图片文件夹。",
        ));
    }
    if output_dir.is_empty() {
        issues.push(issue(
            "output_dir",
            "basic",
            "请先选择「输出目录」（视频保存位置）。",
        ));
    }

    if check_files && is_truthy(config.get("use_bgm")) {
        let strategy = text_or(&config, "watermark_audio", "使用BGM");
        if strategy == "使用BGM" || strategy == "两者混合" {
            let bgm_files: Vec<String> = config
                .get("bgm_files")
                .and_then(Value::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(|item| item.as_str().map(str::to_string))
                        .collect()
                })
                .unwrap_or_default();
            if !bgm_files.is_empty() {
                if let Some(first) = bgm_files.iter().find(|path| !Path::new(path).is_file()) {
                    issues.push(issue(
                        "bgm_files",
                        "basic",
                        &format!(
                            "选定的 BGM 素材不存在：{}，请在素材库中重新选择。",
                            paths::file_name(first)
                        ),
                    ));
                }
            } else {
                let bgm_dir = text_or(&config, "bgm_dir", "").trim().to_string();
                if bgm_dir.is_empty() || !Path::new(&bgm_dir).is_dir() {
                    issues.push(issue(
                        "bgm_dir",
                        "basic",
                        "找不到 BGM 目录，请重新选择存放音频的文件夹。",
                    ));
                } else if scan_audio_files(&bgm_dir).is_empty() {
                    issues.push(issue(
                        "bgm_dir",
                        "basic",
                        "BGM 目录里没有可用的音频文件，请放入 mp3 / wav 等音频后再试。",
                    ));
                }
            }
        }
    }

    let num_images = int_or(&config, "num_images", 0);
    let video_count = int_or(&config, "video_count", 0);
    let duration = float_or(&config, "duration", 0.0);
    let total_duration = float_or(&config, "total_duration", -1.0);
    let selection_mode = text_or(&config, "image_selection_mode", "随机选择");

    // 「按子文件夹抽取」的每视频图片数由子文件夹个数决定，该项被忽略。
    if num_images <= 0 && selection_mode != SUBFOLDER_SELECTION_MODE {
        issues.push(issue(
            "num_images",
            "basic",
            "「图片数」需要大于 0，请把每个视频的图片数调到 1 张以上。",
        ));
    }
    if video_count <= 0 {
        issues.push(issue(
            "video_count",
            "basic",
            "「视频数」需要大于 0，请至少导出 1 个视频。",
        ));
    }
    if let Err(message) = timeline_slot_count(duration, total_duration) {
        issues.push(issue("duration", "basic", &message));
    }

    if !issues.is_empty() || !check_files {
        return issues;
    }

    if selection_mode == SUBFOLDER_SELECTION_MODE {
        // 该模式下图片放在子文件夹里，根目录本身可以没有图片，先于通用检查返回。
        return subfolder_selection_issues(&input_dir);
    }

    let image_count = scan::scan_images(&input_dir).len() as i64;
    if image_count == 0 {
        return vec![issue(
            "input_dir",
            "basic",
            "输入目录里没有图片，请先放入图片再导出",
        )];
    }

    if selection_mode == "按名称排序" {
        let required = video_count.saturating_mul(num_images);
        if image_count < required {
            issues.push(issue(
                "input_dir",
                "basic",
                &format!(
                    "输出数量超出图片数量：当前只有 {image_count} 张图片，按名称排序模式生成 {video_count} 个视频需要 {required} 张"
                ),
            ));
        }
    } else if image_count < num_images {
        issues.push(issue(
            "input_dir",
            "basic",
            &format!("图片数量不足：当前只有 {image_count} 张，每个视频需要 {num_images} 张"),
        ));
    } else if image_count < video_count {
        issues.push(issue(
            "input_dir",
            "basic",
            &format!(
                "输出数量超出图片数量：随机模式下当前 {image_count} 张图片最多生成 {image_count} 个视频"
            ),
        ));
    }
    issues
}

/// 兼容旧接口：只返回文本列表。
pub fn validate_config(raw: Option<&Value>, check_files: bool) -> Vec<String> {
    validate_config_detailed(raw, check_files)
        .iter()
        .filter_map(|item| {
            item.get("message")
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// 调色字段必须能穿过 normalize —— 这是「界面调了没生效」最容易断的一环。
    #[test]
    fn normalize_keeps_color_fields() {
        let raw = json!({
            "color_brightness": 55.0,
            "color_contrast": -30.0,
            "color_saturation": 70.0,
            "color_temperature": 25.0,
        });
        let normalized = normalize_config(Some(&raw));
        assert_eq!(normalized["color_brightness"], json!(55.0));
        assert_eq!(normalized["color_contrast"], json!(-30.0));
        assert_eq!(normalized["color_saturation"], json!(70.0));
        assert_eq!(normalized["color_temperature"], json!(25.0));
    }

    /// effect_params 也必须能穿过去。
    #[test]
    fn normalize_keeps_effect_params() {
        let raw = json!({
            "effect_params": { "色调分离": { "steps": 3.0 } },
        });
        let normalized = normalize_config(Some(&raw));
        assert_eq!(normalized["effect_params"]["色调分离"]["steps"], json!(3.0));
    }

    /// 端到端：从「界面会发出的 JSON」走完整 normalize，确认字段没丢。
    ///
    /// 这条模拟的是 `start_job` 收到的原始配置 —— 如果 normalize 有白名单
    /// 过滤，这里会立刻暴露。
    #[test]
    fn normalize_preserves_passthrough_of_unknown_keys() {
        let raw = json!({
            "color_brightness": 42.0,
            "color_saturation": -60.0,
            "effect_params": { "色调分离": { "steps": 3.0 } },
            "video_effect_type": "色调分离",
            "use_video_effect": true,
        });
        let normalized = normalize_config(Some(&raw));
        assert_eq!(normalized["color_brightness"], json!(42.0), "亮度被丢了");
        assert_eq!(normalized["color_saturation"], json!(-60.0), "饱和度被丢了");
        assert_eq!(
            normalized["effect_params"]["色调分离"]["steps"],
            json!(3.0),
            "effect_params 被丢了"
        );
        assert_eq!(normalized["video_effect_type"], json!("色调分离"));
        assert_eq!(normalized["use_video_effect"], json!(true));
    }

    #[test]
    fn default_config_matches_expected_shape() {
        let config = default_config();
        // 46 → 47：新增 effect_params（特效专属参数，2026-11-20）
        // 47 → 51：新增 4 个调色字段（color_brightness 等，2026-11-20）
        assert_eq!(config.as_object().map(|map| map.len()), Some(51));
        assert_eq!(config["resolution_preset"], "1280x720");
        assert_eq!(config["image_selection_mode"], "随机选择");
        assert_eq!(
            config["enabled_video_effects"].as_array().map(Vec::len),
            // 39 → 42：新增 色差分离 / 色调分离 / 半调网点
            // 42 → 46：补回 缓慢拉远 / 右下平移 / 左上平移 / 缓慢推近
            // （这 4 个内核早有实现，列表漏了很久，界面选不到）
            Some(46)
        );
        assert_eq!(
            config["enabled_transitions"].as_array().map(Vec::len),
            Some(33)
        );
    }

    #[test]
    fn parse_resolution_accepts_common_forms() {
        assert_eq!(parse_resolution(Some(&json!("1920x1080"))), (1920, 1080));
        assert_eq!(parse_resolution(Some(&json!(" 720 X 1280 "))), (720, 1280));
        assert_eq!(parse_resolution(Some(&json!("1080×1920"))), (1080, 1920));
        assert_eq!(parse_resolution(Some(&json!("坏值"))), (1280, 720));
        assert_eq!(parse_resolution(Some(&json!(null))), (1280, 720));
        assert_eq!(parse_resolution(Some(&json!("1x1"))), (2, 2));
    }

    #[test]
    fn normalize_fills_derived_fields_and_cleans_bgm_files() {
        let config = normalize_config(Some(&json!({
            "resolution_preset": "1080x1920",
            "video_effect_type": "心跳跃动",
            "enabled_video_effects": ["心跳跃动", "轻微摇摆"],
            "custom_prefix": "  前缀  ",
            "bgm_files": ["C:/a.mp3", "", "  ", 42],
        })));
        assert_eq!(config["width"], 1080);
        assert_eq!(config["height"], 1920);
        assert_eq!(config["watermark_type"], "视频");
        assert_eq!(config["video_effect_type"], "心跳跳动");
        assert_eq!(
            config["enabled_video_effects"],
            json!(["心跳跳动", "轻微摇摆"])
        );
        assert_eq!(config["custom_prefix"], "前缀");
        assert_eq!(config["bgm_files"], json!(["C:/a.mp3"]));
    }

    #[test]
    fn timeline_requires_integer_multiple() {
        assert_eq!(timeline_slot_count(1.0, 8.0), Ok(Some(8)));
        assert_eq!(timeline_slot_count(1.0, 0.0), Ok(None));
        // 3.3333 × 3 = 9.9999，舍入误差在容差内
        assert_eq!(timeline_slot_count(3.3333, 10.0), Ok(Some(3)));
        assert!(timeline_slot_count(8.0, 10.0).is_err());
        assert!(timeline_slot_count(0.0, 10.0).is_err());
        assert!(timeline_slot_count(1.0, -1.0).is_err());
    }

    #[test]
    fn validate_reports_missing_dirs() {
        let issues = validate_config_detailed(None, true);
        let fields: Vec<&str> = issues
            .iter()
            .filter_map(|item| item["field"].as_str())
            .collect();
        assert_eq!(fields, vec!["input_dir", "output_dir"]);
    }

    #[test]
    fn validate_ignores_num_images_in_subfolder_mode() {
        let issues = validate_config_detailed(
            Some(&json!({
                "input_dir": "",
                "output_dir": "C:/out",
                "num_images": 0,
                "video_count": 1,
                "image_selection_mode": SUBFOLDER_SELECTION_MODE,
            })),
            false,
        );
        assert!(
            !issues.iter().any(|item| item["field"] == "num_images"),
            "子文件夹模式不该报 num_images：{issues:?}"
        );
    }

    #[test]
    fn validate_keeps_python_truthiness_for_strings() {
        // use_bgm 是字符串 "0"：Python 里这是真值，所以会走 BGM 校验
        let issues = validate_config_detailed(
            Some(&json!({
                "input_dir": "C:/不存在",
                "output_dir": "C:/out",
                "num_images": 1,
                "video_count": 1,
                "use_bgm": "0",
                "bgm_files": [],
                "bgm_dir": "C:/也没有",
            })),
            true,
        );
        let fields: Vec<&str> = issues
            .iter()
            .filter_map(|item| item["field"].as_str())
            .collect();
        assert!(fields.contains(&"bgm_dir"), "应当校验 BGM 目录：{issues:?}");
    }
}
