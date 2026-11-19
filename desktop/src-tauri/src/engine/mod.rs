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

mod library;
mod paths;
mod scan;
mod sort;

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
}

pub fn dispatch(method: &str, params: Option<Value>) -> DispatchResponse {
    let object = params
        .and_then(|value| value.as_object().cloned())
        .unwrap_or_else(Map::new);

    match method {
        "library_dirs" => DispatchResponse::ok(library::dirs()),
        "scan_images" => scan_images(&object),
        "scan_subfolders" => scan_subfolders(&object),
        "scan_subfolder_groups" => scan_subfolder_groups(&object),
        _ => DispatchResponse::unhandled(),
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
        let response = dispatch("library_snapshot", None);
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
