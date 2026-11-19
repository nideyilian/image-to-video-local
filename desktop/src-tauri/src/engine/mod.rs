//! 引擎原生实现（渐进迁移）。
//!
//! 首批只接管「不碰像素」的只读接口：素材库默认目录、图片扫描、子文件夹分组。
//!
//! **回落协议**：本模块只对已迁移且参数走主路径的请求返回 `handled: true`；
//! 其余一律 `handled: false`，前端继续走 Python sidecar。这样迁移期间功能不中断，
//! 也不需要维护两套前端 —— 少一个接口就少一条 Python 路径，逐步收敛。
//!
//! 目前明确回落的情况：
//! - 未迁移的 method；
//! - `preview_sequence > 0` 的扫描（「换一组看看」依赖旧引擎的确定性洗牌，
//!   要复现 Python `random.Random` 的 Fisher-Yates 才有同样结果，留到后续）。

mod config;
mod fingerprint;
mod hash;
mod library;
mod paths;
mod scan;
mod snapshot;
mod sort;
mod system;
mod write_ops;

use serde::Serialize;
use serde_json::{json, Map, Value};

#[derive(Debug, Serialize)]
pub struct DispatchResponse {
    pub handled: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl DispatchResponse {
    fn ok(result: Value) -> Self {
        Self { handled: true, result: Some(result), error: None }
    }

    fn unhandled() -> Self {
        Self { handled: false, result: None, error: None }
    }

    /// 已接管但业务上失败（如「只能删除素材库内的文件」），与 Python 抛错等价。
    fn failed(message: impl Into<String>) -> Self {
        Self { handled: true, result: None, error: Some(message.into()) }
    }
}

pub fn dispatch(method: &str, params: Option<Value>) -> DispatchResponse {
    let object = params
        .and_then(|value| value.as_object().cloned())
        .unwrap_or_else(Map::new);

    match method {
        "library_dirs" => DispatchResponse::ok(library::dirs()),
        "library_snapshot" => DispatchResponse::ok(snapshot::snapshot(&object)),
        "library_import" => match write_ops::import_files(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "library_rename" => match write_ops::rename_item(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "library_set_metadata" => match write_ops::set_metadata(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "library_remove" => match write_ops::remove(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "library_remove_batch" => match write_ops::remove_batch(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "library_move" => match write_ops::move_items(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "library_create_folder" => match write_ops::create_folder(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "library_rename_folder" => match write_ops::rename_folder(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "library_delete_folder" => match write_ops::delete_folder(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "library_get_tags" => match write_ops::get_tags(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "library_smart_folders_list" => match write_ops::smart_folders_list(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "library_smart_folders_save" => match write_ops::smart_folders_save(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "scan_images" => scan_images(&object),
        "scan_subfolders" => scan_subfolders(&object),
        "scan_subfolder_groups" => scan_subfolder_groups(&object),
        "default_config" => DispatchResponse::ok(config::default_config()),
        "normalize_config" => {
            DispatchResponse::ok(config::normalize_config(object.get("config")))
        }
        "validate_config" => {
            let errors = config::validate_config(object.get("config"), check_files(&object));
            DispatchResponse::ok(json!({ "valid": errors.is_empty(), "errors": errors }))
        }
        "validate_config_detailed" => {
            let issues = config::validate_config_detailed(
                object.get("config"),
                check_files(&object),
            );
            DispatchResponse::ok(json!({ "valid": issues.is_empty(), "issues": issues }))
        }
        _ => DispatchResponse::unhandled(),
    }
}

/// 与 Python `bool(params.get("check_files", True))` 等价。
fn check_files(params: &Map<String, Value>) -> bool {
    match params.get("check_files") {
        None => true,
        Some(value) => config::is_truthy(Some(value)),
    }
}

fn text(params: &Map<String, Value>, key: &str) -> String {
    params
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_string()
}

fn preview_sequence(params: &Map<String, Value>) -> i64 {
    params
        .get("preview_sequence")
        .and_then(Value::as_i64)
        .unwrap_or(0)
}

fn scan_images(params: &Map<String, Value>) -> DispatchResponse {
    if preview_sequence(params) > 0 {
        return DispatchResponse::unhandled();
    }
    let all = scan::scan_images(&text(params, "input_dir"));
    let limit = params.get("limit").and_then(Value::as_i64);
    let shown = match limit {
        // 与旧引擎一致：limit 为 0 或负数时返回空列表，count 仍是全量。
        Some(value) => &all[..all.len().min(value.max(0) as usize)],
        None => &all[..],
    };
    DispatchResponse::ok(json!({
        "count": all.len(),
        "images": shown
            .iter()
            .map(|path| json!({ "path": path, "name": paths::file_name(path) }))
            .collect::<Vec<_>>(),
    }))
}

fn scan_subfolders(params: &Map<String, Value>) -> DispatchResponse {
    if preview_sequence(params) > 0 {
        return DispatchResponse::unhandled();
    }
    let result = scan::scan_subfolders(&text(params, "input_dir"));
    DispatchResponse::ok(json!({
        "groups": result
            .groups
            .iter()
            .map(|group| json!({ "name": group.name, "count": group.images.len() }))
            .collect::<Vec<_>>(),
        "skipped": result.skipped,
    }))
}

fn scan_subfolder_groups(params: &Map<String, Value>) -> DispatchResponse {
    if preview_sequence(params) > 0 {
        return DispatchResponse::unhandled();
    }
    let result = scan::scan_subfolders(&text(params, "input_dir"));
    let count: usize = result.groups.iter().map(|group| group.images.len()).sum();
    let groups: Vec<Value> = result
        .groups
        .iter()
        .map(|group| {
            let first = group.images.first().cloned().unwrap_or_default();
            json!({
                "name": group.name,
                "count": group.images.len(),
                "first_path": first,
                "first_name": paths::file_name(&first),
            })
        })
        .collect();
    let images: Vec<Value> = result
        .groups
        .iter()
        .filter_map(|group| group.images.first())
        .map(|path| json!({ "path": path, "name": paths::file_name(path) }))
        .collect();
    let total = u64::try_from(scan::combination_total(&result.groups)).unwrap_or(u64::MAX);
    DispatchResponse::ok(json!({
        "count": count,
        "groups": groups,
        "images": images,
        "skipped": result.skipped,
        "combination_total": total,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unknown_method_is_left_to_the_python_engine() {
        let response = dispatch("library_find_duplicates", None);
        assert!(!response.handled);
        assert!(response.result.is_none());
    }

    #[test]
    fn library_dirs_is_handled_locally() {
        let response = dispatch("library_dirs", None);
        assert!(response.handled);
        let result = response.result.expect("result");
        assert!(result["library_root"].is_string());
        assert!(result["bgm_dir"].is_string());
        assert!(result["watermark_dir"].is_string());
    }

    #[test]
    fn preview_sequence_falls_back_to_python() {
        let params = json!({ "input_dir": "", "preview_sequence": 3 });
        assert!(!dispatch("scan_images", Some(params)).handled);
        let params = json!({ "input_dir": "", "preview_sequence": 1 });
        assert!(!dispatch("scan_subfolder_groups", Some(params)).handled);
    }

    /// 与 Python 版逐字段对照用：设 `ITV_PARITY_CASES` 指向两边共用的用例文件，
    /// 输出 `normalize` / `validate` 两个接口的完整结果。
    #[test]
    fn parity_dump_config_cases() {
        let Ok(path) = std::env::var("ITV_PARITY_CASES") else {
            return;
        };
        let text = std::fs::read_to_string(&path).expect("读取对照用例");
        let cases: Value = serde_json::from_str(&text).expect("解析对照用例");
        let mut out = serde_json::Map::new();
        if let Some(items) = cases.get("normalize").and_then(Value::as_array) {
            for case in items {
                let id = case.get("id").and_then(Value::as_str).unwrap_or_default();
                out.insert(
                    format!("normalize::{id}"),
                    config::normalize_config(case.get("config")),
                );
            }
        }
        if let Some(items) = cases.get("validate").and_then(Value::as_array) {
            for case in items {
                let id = case.get("id").and_then(Value::as_str).unwrap_or_default();
                let check_files = case
                    .get("check_files")
                    .and_then(Value::as_bool)
                    .unwrap_or(true);
                out.insert(
                    format!("validate::{id}"),
                    Value::Array(config::validate_config_detailed(
                        case.get("config"),
                        check_files,
                    )),
                );
            }
        }
        println!("CONFIG_PARITY={}", Value::Object(out));
    }

    /// 与 Python 版逐字段对照用：设 `ITV_LIB_DIR` 指向一个素材库根目录（含 BGM/水印）。
    #[test]
    fn parity_dump_library_snapshot() {
        let Ok(dir) = std::env::var("ITV_LIB_DIR") else {
            return;
        };
        let params = json!({
            "bgm_dir": format!("{dir}/BGM"),
            "watermark_dir": format!("{dir}/水印"),
        });
        let result = snapshot::snapshot(params.as_object().expect("params"));
        println!("LIB_PARITY={}", result);
    }

    /// 与 Python 版逐字段对照用：`ITV_IMPORT_DIR` 素材库根目录、`ITV_IMPORT_SOURCES` 源文件 JSON 数组。
    #[test]
    fn parity_dump_library_import() {
        let (Ok(dir), Ok(sources)) = (
            std::env::var("ITV_IMPORT_DIR"),
            std::env::var("ITV_IMPORT_SOURCES"),
        ) else {
            return;
        };
        let params = json!({
            "kind": "bgm",
            "paths": serde_json::from_str::<Value>(&sources).unwrap_or_else(|_| json!([])),
            "bgm_dir": format!("{dir}/BGM"),
            "watermark_dir": format!("{dir}/水印"),
            "folder": "",
        });
        let result = match write_ops::import_files(params.as_object().expect("params")) {
            Ok(value) => value,
            Err(message) => json!({ "error": message }),
        };
        println!("IMPORT_PARITY={}", result);
    }

    /// 与 Python 版对照移动 / 元数据 / 标签汇总：`ITV_OPS_DIR` 指向准备好的素材库。
    #[test]
    fn parity_dump_library_ops() {
        let Ok(dir) = std::env::var("ITV_OPS_DIR") else {
            return;
        };
        let base = json!({
            "kind": "bgm",
            "bgm_dir": format!("{dir}/BGM"),
            "watermark_dir": format!("{dir}/水印"),
        });
        let mut object = base.as_object().expect("base").clone();

        let mut move_params = object.clone();
        move_params.insert(
            "paths".to_string(),
            json!([format!("{dir}/BGM/a.wav")]),
        );
        move_params.insert("folder".to_string(), json!("精选"));
        let moved = write_ops::move_items(&move_params);

        let mut metadata_params = object.clone();
        metadata_params.insert("path".to_string(), json!(format!("{dir}/BGM/b.wav")));
        metadata_params.insert("tags".to_string(), json!(["轻快", "人声", "轻快"]));
        metadata_params.insert("starred".to_string(), json!(true));
        metadata_params.insert("note".to_string(), json!("测试备注"));
        let metadata = write_ops::set_metadata(&metadata_params);

        object.insert("kind".to_string(), json!("bgm"));
        let tags = write_ops::get_tags(&object);

        println!(
            "OPS_PARITY={}",
            json!({
                "move": moved.unwrap_or_else(|error| json!({"error": error})),
                "metadata": metadata.unwrap_or_else(|error| json!({"error": error})),
                "tags": tags.unwrap_or_else(|error| json!({"error": error})),
            })
        );
    }

    #[test]
    fn scan_images_reports_total_count_and_limit() {
        let params = json!({ "input_dir": "", "limit": 5 });
        let response = dispatch("scan_images", Some(params));
        assert!(response.handled);
        let result = response.result.expect("result");
        assert_eq!(result["count"], 0);
        assert_eq!(result["images"].as_array().map(Vec::len), Some(0));
    }

    /// 与 Python 版逐字段对照用：设 `ITV_PARITY_DIR` 指向同一批素材，
    /// 打印与 `scan_images` / `scan_subfolders` 完全同构的 JSON。
    #[test]
    fn parity_dump_for_external_fixture() {
        let Ok(dir) = std::env::var("ITV_PARITY_DIR") else {
            return;
        };
        let images = scan::scan_images(&dir);
        let sub = scan::scan_subfolders(&dir);
        let payload = json!({
            "images": images,
            "groups": sub
                .groups
                .iter()
                .map(|group| json!({
                    "name": group.name,
                    "count": group.images.len(),
                    "images": group.images,
                }))
                .collect::<Vec<_>>(),
            "skipped": sub.skipped,
            "library_dirs": library::dirs(),
        });
        println!("PARITY={}", payload);
    }
}
