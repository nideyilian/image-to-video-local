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
mod dedup;
mod effect_assets;
mod extract;
mod fingerprint;
mod hash;
pub(crate) mod jobs;
mod library;
mod paths;
mod preview;
mod preview_random;
mod scan;
mod snapshot;
mod sort;
mod sysinfo;
pub(crate) mod system;
mod taint;
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

// ---------- 任务队列的全局状态 ----------

/// Tauri 的 AppHandle，用于把任务事件推给前端。
/// 在 `lib.rs` 的 setup 里注入；测试环境下为 None（事件被丢弃，状态机照常工作）。
static APP_HANDLE: std::sync::OnceLock<tauri::AppHandle> = std::sync::OnceLock::new();

/// 前端监听的事件名。
pub const EVENT_NAME: &str = "engine-event";

pub fn set_app_handle(handle: tauri::AppHandle) {
    let _ = APP_HANDLE.set(handle);
}

/// 事件出口：有 AppHandle 就 emit 给前端，否则丢弃。
fn job_sink() -> jobs::EventSink {
    std::sync::Arc::new(|event: &str, payload: Value| {
        if let Some(handle) = APP_HANDLE.get() {
            use tauri::Emitter;
            let message = serde_json::json!({
                "type": "event",
                "event": event,
                "payload": payload,
            });
            let _ = handle.emit(EVENT_NAME, message);
        }
    })
}

/// 全局任务管理器（首次使用时初始化）。
fn job_manager() -> &'static jobs::JobManager {
    static MANAGER: std::sync::OnceLock<jobs::JobManager> = std::sync::OnceLock::new();
    MANAGER.get_or_init(|| {
        // 打包模式（frozen）用 exe 自己当 worker；源码模式用 python -m
        let worker = if let Ok(executable) = std::env::var("ITV_PACKAGED_WORKER") {
            jobs::WorkerCommand::Packaged {
                executable: std::path::PathBuf::from(executable),
            }
        } else {
            let project_root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../..")
                .canonicalize()
                .unwrap_or_else(|_| std::path::PathBuf::from("."));
            let python = std::env::var("ITV_PYTHON")
                .unwrap_or_else(|_| "python".to_string());
            jobs::WorkerCommand::PythonModule {
                python,
                project_root,
            }
        };
        jobs::JobManager::new(job_sink(), worker)
    })
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
        "library_rename_batch" => match write_ops::rename_batch(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        // 只有 BGM 查重走 Rust；水印查重依赖 PIL 的 dHash，整体交回旧引擎。
        "library_find_duplicates" => {
            if object.get("kind").and_then(Value::as_str) == Some("bgm") {
                match dedup::find_duplicates(&object) {
                    Ok(result) => DispatchResponse::ok(result),
                    Err(message) => DispatchResponse::failed(message),
                }
            } else {
                DispatchResponse::unhandled()
            }
        }
        "library_scan_tainted" => match taint::scan_tainted(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "library_clean_tainted" => match taint::clean_tainted(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        // ---------- 任务队列 ----------
        "start_job" => {
            let raw = object.get("config").cloned().unwrap_or(Value::Null);
            let normalized = config::normalize_config(Some(&raw));
            let errors = config::validate_config(Some(&normalized), false);
            if let Some(first) = errors.first() {
                return DispatchResponse::failed(first.clone());
            }
            let job_id = object
                .get("job_id")
                .and_then(Value::as_str)
                .map(str::to_string);
            let config_object = normalized.as_object().cloned().unwrap_or_default();
            match job_manager().start(&config_object, job_id) {
                Ok(state) => DispatchResponse::ok(state),
                Err(message) => DispatchResponse::failed(message),
            }
        }
        "pause_job" => match job_manager().pause(&text(&object, "job_id")) {
            Ok(state) => DispatchResponse::ok(state),
            Err(message) => DispatchResponse::failed(message),
        },
        "resume_job" => match job_manager().resume(&text(&object, "job_id")) {
            Ok(state) => DispatchResponse::ok(state),
            Err(message) => DispatchResponse::failed(message),
        },
        "cancel_job" => match job_manager().cancel(&text(&object, "job_id")) {
            Ok(state) => DispatchResponse::ok(state),
            Err(message) => DispatchResponse::failed(message),
        },
        "list_jobs" => match job_manager().list() {
            Ok(state) => DispatchResponse::ok(state),
            Err(message) => DispatchResponse::failed(message),
        },
        // ---------- 拆 BGM（后台任务 + 进度事件，事件走 Tauri emit） ----------
        "library_extract_bgm" => {
            let (ffmpeg, ffprobe) = preview::ffmpeg_pair();
            match extract::start(&object, job_sink(), ffmpeg, ffprobe) {
                Ok(result) => DispatchResponse::ok(result),
                Err(message) => DispatchResponse::failed(message),
            }
        }
        "library_extract_cancel" => match extract::cancel(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        // ---------- 特效资产（渲染类接口仍走 Python，见下方说明） ----------
        "effect_library_assets" => match effect_assets::ensure_assets() {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "effect_library_set_asset" => match effect_assets::set_asset(&object) {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        "effect_library_reset_assets" => match effect_assets::reset_assets() {
            Ok(result) => DispatchResponse::ok(result),
            Err(message) => DispatchResponse::failed(message),
        },
        // ---------- 预览类 ----------
        "preview_thumbnail" => {
            let params = preview::ThumbnailParams::from_params(&object);
            let (ffmpeg, ffprobe) = preview::ffmpeg_pair();
            match preview::preview_thumbnail(&params, ffmpeg.as_deref(), ffprobe.as_deref()) {
                Ok(result) => DispatchResponse::ok(result),
                Err(message) => DispatchResponse::failed(message),
            }
        }
        "preview_bgm" => {
            let normalized = config::normalize_config(object.get("config"));
            let render_config = crate::render::audio::JsonConfig::new(&normalized);
            let (ffmpeg, _) = preview::ffmpeg_pair();
            let sequence = object
                .get("preview_sequence")
                .and_then(Value::as_i64)
                .unwrap_or(0);
            match preview::preview_bgm(&render_config, ffmpeg.as_deref(), sequence, false) {
                Ok(result) => DispatchResponse::ok(result),
                Err(message) => DispatchResponse::failed(message),
            }
        }
        "library_preview_audio" => {
            let path = text(&object, "path");
            let (ffmpeg, _) = preview::ffmpeg_pair();
            match preview::preview_audio(&path, ffmpeg.as_deref()) {
                Ok(result) => DispatchResponse::ok(result),
                Err(message) => DispatchResponse::failed(message),
            }
        }
        "library_preview_video" => {
            let path = text(&object, "path");
            let (ffmpeg, ffprobe) = preview::ffmpeg_pair();
            match preview::preview_video(&path, ffmpeg.as_deref(), ffprobe.as_deref()) {
                Ok(result) => DispatchResponse::ok(result),
                Err(message) => DispatchResponse::failed(message),
            }
        }
        "library_audio_cover" => {
            let path = text(&object, "path");
            let (ffmpeg, _) = preview::ffmpeg_pair();
            match preview::audio_cover(&path, ffmpeg.as_deref()) {
                Ok(result) => DispatchResponse::ok(result),
                Err(message) => DispatchResponse::failed(message),
            }
        }
        // ---------- 系统信息 ----------
        "system_snapshot" => {
            let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../..")
                .canonicalize()
                .map(|path| path.to_string_lossy().into_owned())
                .unwrap_or_default();
            let output_dir = text(&object, "output_dir");
            let ffmpeg = system::resolve_ffmpeg(None);
            DispatchResponse::ok(sysinfo::snapshot_payload(
                &root,
                &output_dir,
                ffmpeg.as_deref(),
            ))
        }
        "optimize_memory" => DispatchResponse::ok(sysinfo::optimize_memory()),
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

    /// 防呆：前端 `NATIVE_METHODS` 里列的每个方法，Rust 都必须真的接管。
    /// 写错一个名字（比如把 `library_scan_tainted` 写成 `scan_tainted`）不会报错，
    /// 只会每次都静默回落 Python —— 这个测试就是为此存在的。
    #[test]
    fn every_whitelisted_method_is_handled() {
        let source = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../src/engine.ts"
        ))
        .expect("读不到 desktop/src/engine.ts");
        let start = source.find("const NATIVE_METHODS").expect("找不到 NATIVE_METHODS");
        let end = source[start..]
            .find("]);")
            .map(|index| start + index)
            .expect("NATIVE_METHODS 未闭合");
        let block = &source[start..end];

        let methods: Vec<String> = block
            .lines()
            .filter_map(|line| {
                let line = line.trim();
                if !line.starts_with('"') {
                    return None;
                }
                line[1..].split('"').next().map(str::to_string)
            })
            .collect();
        assert!(methods.len() >= 20, "白名单解析异常：{methods:?}");

        for method in methods {
            let params = if method == "library_find_duplicates" {
                json!({ "kind": "bgm" })
            } else {
                json!({})
            };
            let response = dispatch(&method, Some(params));
            assert!(
                response.handled,
                "{method} 在前端白名单里，但 Rust 没接管 —— 每次调用都会白跑一趟再回落 Python"
            );
        }
    }

    #[test]
    fn unknown_method_is_left_to_the_python_engine() {
        // health 的语义是「sidecar 是否活着」，必须留给 Python
        let response = dispatch("health", None);
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

    /// 体检对照：`ITV_TAINT_DIR` 指向素材库根（含 BGM 与 水印 两目录）。
    #[test]
    fn parity_dump_taint() {
        let Ok(dir) = std::env::var("ITV_TAINT_DIR") else {
            return;
        };
        let mut bgm = serde_json::Map::new();
        bgm.insert("kind".to_string(), json!("bgm"));
        bgm.insert("bgm_dir".to_string(), json!(format!("{dir}/BGM")));
        bgm.insert("watermark_dir".to_string(), json!(format!("{dir}/水印")));
        let mut watermark = bgm.clone();
        watermark.insert("kind".to_string(), json!("watermark"));

        let payload = json!({
            "bgm": taint::scan_tainted(&bgm).expect("bgm 体检"),
            "watermark": taint::scan_tainted(&watermark).expect("水印体检"),
        });
        println!("TAINT_PARITY={}", payload);
    }

    /// 清洗对照：`ITV_CLEAN_DIR` 指向素材库根，`ITV_CLEAN_TARGETS` 是要清洗的绝对路径数组。
    #[test]
    fn parity_dump_clean_tainted() {
        let Ok(dir) = std::env::var("ITV_CLEAN_DIR") else {
            return;
        };
        let Ok(raw) = std::env::var("ITV_CLEAN_TARGETS") else {
            return;
        };
        let targets: Vec<String> = serde_json::from_str(&raw).unwrap_or_default();
        let mut params = serde_json::Map::new();
        params.insert("paths".to_string(), json!(targets));
        params.insert("bgm_dir".to_string(), json!(format!("{dir}/BGM")));
        params.insert("watermark_dir".to_string(), json!(format!("{dir}/水印")));
        let payload = taint::clean_tainted(&params).expect("清洗");
        println!("CLEAN_PARITY={}", payload);
    }

    /// BGM 查重对照：`ITV_DUP_DIR` 指向素材库根。
    #[test]
    fn parity_dump_duplicates() {
        let Ok(dir) = std::env::var("ITV_DUP_DIR") else {
            return;
        };
        let mut params = serde_json::Map::new();
        params.insert("kind".to_string(), json!("bgm"));
        params.insert("bgm_dir".to_string(), json!(format!("{dir}/BGM")));
        params.insert("watermark_dir".to_string(), json!(format!("{dir}/水印")));
        let payload = dedup::find_duplicates(&params).expect("查重");
        println!("DUP_PARITY={}", payload);
    }

    /// 批量重命名对照：`ITV_RENAME_DIR` 指向素材库根，
    /// `ITV_RENAME_TARGETS_FILE` 指向一个 JSON 数组文件（走文件避免 shell 转义干扰）。
    #[test]
    fn parity_dump_rename_batch() {
        let Ok(dir) = std::env::var("ITV_RENAME_DIR") else {
            return;
        };
        let Some(raw) = std::env::var("ITV_RENAME_TARGETS_FILE")
            .ok()
            .and_then(|path| std::fs::read_to_string(path).ok())
        else {
            return;
        };
        let targets: Vec<String> = serde_json::from_str(&raw).unwrap_or_default();
        let mut params = serde_json::Map::new();
        params.insert("kind".to_string(), json!("bgm"));
        params.insert("bgm_dir".to_string(), json!(format!("{dir}/BGM")));
        params.insert("watermark_dir".to_string(), json!(format!("{dir}/水印")));
        params.insert("paths".to_string(), json!(targets));
        params.insert("pattern".to_string(), json!("{n}-{name}"));
        let payload = write_ops::rename_batch(&params).expect("批量重命名");
        println!("RENAME_PARITY={}", payload);
    }
}

#[cfg(test)]
mod parity_jobs {
    use super::*;

    /// 真实任务启动：`ITV_JOB_INPUT` 图片目录，`ITV_JOB_OUTPUT` 输出目录。
    /// 验证 Rust 的 JobManager 能真的把 Python worker 拉起来并收到事件。
    #[test]
    fn run_real_job_with_python_worker() {
        let (Ok(input), Ok(output)) = (
            std::env::var("ITV_JOB_INPUT"),
            std::env::var("ITV_JOB_OUTPUT"),
        ) else {
            return;
        };
        let events: std::sync::Arc<std::sync::Mutex<Vec<(String, Value)>>> =
            std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let captured = events.clone();
        let sink: jobs::EventSink = std::sync::Arc::new(move |event: &str, payload: Value| {
            if let Ok(mut guard) = captured.lock() {
                guard.push((event.to_string(), payload));
            }
        });
        let project_root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .expect("project root");
        let python = std::env::var("ITV_PYTHON").unwrap_or_else(|_| "python".to_string());
        let manager = jobs::JobManager::new(
            sink,
            jobs::WorkerCommand::PythonModule {
                python,
                project_root,
            },
        );

        let mut config = config::default_config();
        let object = config.as_object_mut().expect("配置应为对象");
        object.insert("input_dir".to_string(), json!(input));
        object.insert("output_dir".to_string(), json!(output));
        object.insert("num_images".to_string(), json!(2));
        object.insert("video_count".to_string(), json!(1));
        object.insert("duration".to_string(), json!(0.5));
        object.insert("fps".to_string(), json!(10));
        object.insert("resolution_preset".to_string(), json!("640x360"));
        object.insert("image_selection_mode".to_string(), json!("按名称排序"));
        object.insert("transition_type".to_string(), json!("淡入淡出"));
        object.insert("transition_frames".to_string(), json!(4));
        object.insert("use_bgm".to_string(), json!(false));
        object.insert("use_watermark".to_string(), json!(false));

        let normalized = config::normalize_config(Some(&config));
        let config_object = normalized.as_object().cloned().unwrap_or_default();
        let started = manager
            .start(&config_object, Some("itv-real-job".to_string()))
            .expect("任务应能启动");
        assert_eq!(started["status"], "running");

        // 等任务结束（最多 90 秒）
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(90);
        loop {
            std::thread::sleep(std::time::Duration::from_millis(300));
            let list = manager.list().expect("list_jobs");
            let status = list
                .as_array()
                .and_then(|items| items.first())
                .and_then(|item| item.get("status"))
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            // ⚠️ 不能只看 status：watcher 先改状态、后发 job.finished，
            // 直接读会偶发拿不到事件（我第一次就撞上了）。等事件到齐再断言。
            let finished_seen = events
                .lock()
                .map(|guard| guard.iter().any(|(name, _)| name == "job.finished"))
                .unwrap_or(false);
            if matches!(status.as_str(), "completed" | "failed" | "cancelled") && finished_seen {
                let captured = events.lock().unwrap();
                let names: Vec<&str> = captured.iter().map(|(name, _)| name.as_str()).collect();
                println!(
                    "JOB_RESULT={}",
                    json!({
                        "status": status,
                        "events": names,
                        "event_count": captured.len(),
                    })
                );
                assert!(
                    names.contains(&"job.started"),
                    "应收到 job.started，实际: {names:?}"
                );
                assert!(
                    names.contains(&"job.finished"),
                    "应收到 job.finished，实际: {names:?}"
                );
                assert_eq!(status, "completed", "任务应成功完成");
                return;
            }
            if std::time::Instant::now() > deadline {
                panic!("任务超时未结束");
            }
        }
    }
}

#[cfg(test)]
mod parity_preview_random {
    use super::*;
    use serde_json::{json, Value};

    /// 确定性洗牌对照：`ITV_SHUFFLE_CASES` 指向用例 JSON（每项 {items, domain, sequence}）。
    #[test]
    fn parity_dump_shuffle() {
        let Ok(path) = std::env::var("ITV_SHUFFLE_CASES") else {
            return;
        };
        let Ok(raw) = std::fs::read_to_string(path) else {
            return;
        };
        let cases: Vec<Value> = serde_json::from_str(&raw).unwrap_or_default();
        let mut out = Vec::new();
        for (index, case) in cases.iter().enumerate() {
            let items: Vec<String> = case
                .get("items")
                .and_then(Value::as_array)
                .map(|values| {
                    values
                        .iter()
                        .filter_map(|value| value.as_str().map(str::to_string))
                        .collect()
                })
                .unwrap_or_default();
            let domain = case.get("domain").and_then(Value::as_str).unwrap_or("images");
            let sequence = case.get("sequence").and_then(Value::as_i64).unwrap_or(1);
            let count = case.get("count").and_then(Value::as_i64).unwrap_or(0);

            out.push(json!({
                "index": index,
                "shuffled": preview_random::shuffled(&items, domain),
                "choice": preview_random::preview_choice(&items, sequence, domain),
                "sample": if count > 0 {
                    Value::Array(
                        preview_random::preview_sample(&items, count, sequence, domain)
                            .into_iter()
                            .map(Value::String)
                            .collect(),
                    )
                } else {
                    Value::Null
                },
            }));
        }
        println!("SHUFFLE_PARITY={}", Value::Array(out));
    }
}

#[cfg(test)]
mod parity_preview {
    use super::*;
    use serde_json::{json, Value};

    /// 缩略图对照：`ITV_PREVIEW_CASES` 指向用例 JSON（{path, max_width, max_height}）。
    #[test]
    fn parity_dump_thumbnail() {
        let Ok(path) = std::env::var("ITV_PREVIEW_CASES") else {
            return;
        };
        let Ok(raw) = std::fs::read_to_string(path) else {
            return;
        };
        let cases: Vec<Value> = serde_json::from_str(&raw).unwrap_or_default();
        let mut out = Vec::new();
        for case in cases {
            let params = preview::ThumbnailParams {
                source: case
                    .get("path")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string(),
                input_dir: String::new(),
                max_width: case.get("max_width").and_then(Value::as_i64).unwrap_or(960) as u32,
                max_height: case.get("max_height").and_then(Value::as_i64).unwrap_or(540) as u32,
            };
            let (ffmpeg, ffprobe) = preview::ffmpeg_pair();
            out.push(match preview::preview_thumbnail(&params, ffmpeg.as_deref(), ffprobe.as_deref()) {
                Ok(result) => json!({ "ok": true, "result": result }),
                Err(message) => json!({ "ok": false, "error": message }),
            });
        }
        println!("THUMB_PARITY={}", Value::Array(out));
    }
}

#[cfg(test)]
mod parity_preview_bgm {
    use super::*;
    use serde_json::{json, Value};

    /// BGM 预览对照：`ITV_BGMPV_DIR` 指向素材库根，`ITV_BGMPV_CASES` 指向用例 JSON。
    #[test]
    fn parity_dump_preview_bgm() {
        let (Ok(dir), Ok(cases_path)) = (
            std::env::var("ITV_BGMPV_DIR"),
            std::env::var("ITV_BGMPV_CASES"),
        ) else {
            return;
        };
        let Ok(raw) = std::fs::read_to_string(cases_path) else {
            return;
        };
        let cases: Vec<Value> = serde_json::from_str(&raw).unwrap_or_default();
        let mut out = Vec::new();
        for case in cases {
            // 用例里的 config 是相对素材库的，这里补上 bgm_dir
            let mut params = case.clone();
            if let Some(object) = params.as_object_mut() {
                if let Some(config) = object.get_mut("config").and_then(Value::as_object_mut) {
                    if config.get("bgm_dir").and_then(Value::as_str) == Some("<BGM>") {
                        config.insert("bgm_dir".to_string(), json!(format!("{dir}/BGM")));
                    }
                    for path in config
                        .get("bgm_files")
                        .and_then(Value::as_array)
                        .cloned()
                        .unwrap_or_default()
                    {
                        let _ = path;
                    }
                }
            }
            let response = dispatch("preview_bgm", Some(params));
            out.push(match (response.handled, response.result, response.error) {
                (true, Some(result), _) => json!({ "ok": true, "result": result }),
                (_, _, Some(error)) => json!({ "ok": false, "error": error }),
                _ => json!({ "ok": false, "error": "unhandled" }),
            });
        }
        println!("BGMPV_PARITY={}", Value::Array(out));
    }
}

#[cfg(test)]
mod parity_preview_audio {
    use super::*;
    use serde_json::{json, Value};

    /// 素材库音频预览对照：`ITV_LIBPV_CASES` 指向用例 JSON（每项一个音频路径）。
    #[test]
    fn parity_dump_preview_audio() {
        let Ok(cases_path) = std::env::var("ITV_LIBPV_CASES") else {
            return;
        };
        let Ok(raw) = std::fs::read_to_string(cases_path) else {
            return;
        };
        let cases: Vec<Value> = serde_json::from_str(&raw).unwrap_or_default();
        let mut out = Vec::new();
        for case in cases {
            let response = dispatch("library_preview_audio", Some(case));
            out.push(match (response.handled, response.result, response.error) {
                (true, Some(result), _) => json!({ "ok": true, "result": result }),
                (_, _, Some(error)) => json!({ "ok": false, "error": error }),
                _ => json!({ "ok": false, "error": "unhandled" }),
            });
        }
        println!("LIBPV_PARITY={}", Value::Array(out));
    }
}

#[cfg(test)]
mod parity_preview_video {
    use super::*;
    use serde_json::{json, Value};

    /// 视频预览对照：`ITV_VIDPV_CASES` 指向用例 JSON（每项 {path}）。
    #[test]
    fn parity_dump_preview_video() {
        let Ok(cases_path) = std::env::var("ITV_VIDPV_CASES") else {
            return;
        };
        let Ok(raw) = std::fs::read_to_string(cases_path) else {
            return;
        };
        let cases: Vec<Value> = serde_json::from_str(&raw).unwrap_or_default();
        let mut out = Vec::new();
        for case in cases {
            let response = dispatch("library_preview_video", Some(case));
            out.push(match (response.handled, response.result, response.error) {
                (true, Some(result), _) => json!({ "ok": true, "result": result }),
                (_, _, Some(error)) => json!({ "ok": false, "error": error }),
                _ => json!({ "ok": false, "error": "unhandled" }),
            });
        }
        println!("VIDPV_PARITY={}", Value::Array(out));
    }
}

#[cfg(test)]
mod parity_audio_cover {
    use super::*;
    use serde_json::{json, Value};

    /// 音频封面对照：`ITV_COVER_CASES` 指向用例 JSON（每项 {path}）。
    #[test]
    fn parity_dump_audio_cover() {
        let Ok(cases_path) = std::env::var("ITV_COVER_CASES") else {
            return;
        };
        let Ok(raw) = std::fs::read_to_string(cases_path) else {
            return;
        };
        let cases: Vec<Value> = serde_json::from_str(&raw).unwrap_or_default();
        let mut out = Vec::new();
        for case in cases {
            let response = dispatch("library_audio_cover", Some(case));
            let result = response.result.unwrap_or(Value::Null);
            // 一并把生成文件的字节数报出来，便于与 Python 侧比对
            let size = result
                .get("cover_path")
                .and_then(Value::as_str)
                .and_then(|path| std::fs::metadata(path).ok())
                .map(|meta| meta.len())
                .unwrap_or(0);
            let head = result
                .get("cover_path")
                .and_then(Value::as_str)
                .and_then(|path| std::fs::read(path).ok())
                .map(|bytes| bytes.iter().take(4).map(|b| *b).collect::<Vec<u8>>())
                .unwrap_or_default();
            out.push(json!({ "result": result, "size": size, "head": head }));
        }
        println!("COVER_PARITY={}", Value::Array(out));
    }
}

#[cfg(test)]
mod parity_effect_assets {
    use super::*;
    use serde_json::{json, Value};

    /// 特效资产对照：`ITV_ASSET_CASES` 指向操作序列 JSON。
    #[test]
    fn parity_dump_effect_assets() {
        let Ok(cases_path) = std::env::var("ITV_ASSET_CASES") else {
            return;
        };
        let Ok(raw) = std::fs::read_to_string(cases_path) else {
            return;
        };
        let cases: Vec<Value> = serde_json::from_str(&raw).unwrap_or_default();
        let mut out = Vec::new();
        for case in cases {
            let method = case.get("method").and_then(Value::as_str).unwrap_or("");
            let params = case
                .get("params")
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            let response = dispatch(method, Some(Value::Object(params)));
            let mut result = response.result.unwrap_or(Value::Null);
            // 报告生成文件的尺寸，便于确认真的是有效图片
            for key in ["source_a", "source_b"] {
                let size = result
                    .get(key)
                    .and_then(Value::as_str)
                    .and_then(|path| image::image_dimensions(path).ok())
                    .map(|(w, h)| json!([w, h]));
                if let (Some(object), Some(size)) = (result.as_object_mut(), size) {
                    object.insert(format!("{key}_size"), size);
                }
            }
            out.push(json!({
                "method": method,
                "handled": response.handled,
                "result": result,
                "error": response.error,
            }));
        }
        println!("ASSET_PARITY={}", Value::Array(out));
    }
}

#[cfg(test)]
mod parity_extract {
    use super::*;
    use serde_json::json;

    /// 拆 BGM 对照：`ITV_EXTRACT_DIR` 素材库根，`ITV_EXTRACT_SOURCES` 视频目录。
    /// 起任务后等 library.extract.done，把结果与事件序列打印出来。
    #[test]
    fn parity_run_extract_bgm() {
        let (Ok(bgm_dir), Ok(sources)) = (
            std::env::var("ITV_EXTRACT_DIR"),
            std::env::var("ITV_EXTRACT_SOURCES"),
        ) else {
            return;
        };
        let events: std::sync::Arc<std::sync::Mutex<Vec<(String, Value)>>> =
            std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let captured = events.clone();
        let sink: jobs::EventSink = std::sync::Arc::new(move |event: &str, payload: Value| {
            if let Ok(mut guard) = captured.lock() {
                guard.push((event.to_string(), payload));
            }
        });

        let mut paths: Vec<String> = std::fs::read_dir(&sources)
            .map(|entries| {
                entries
                    .flatten()
                    .map(|entry| entry.path())
                    .filter(|path| {
                        path.extension()
                            .map(|ext| ext.to_string_lossy().to_lowercase() == "mp4")
                            .unwrap_or(false)
                    })
                    .map(|path| path.to_string_lossy().into_owned())
                    .collect()
            })
            .unwrap_or_default();
        paths.sort();

        let ffmpeg = system::resolve_ffmpeg(None);
        let ffprobe = system::resolve_ffprobe(None, ffmpeg.as_deref());
        let mut params = serde_json::Map::new();
        params.insert("bgm_dir".into(), json!(bgm_dir));
        params.insert("paths".into(), json!(paths));
        params.insert("options".into(), json!({ "avoid_duplicates": true }));
        let started = extract::start(&params, sink, ffmpeg, ffprobe).expect("启动拆解");
        assert!(started["task_id"].is_string());

        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(180);
        loop {
            std::thread::sleep(std::time::Duration::from_millis(200));
            let done = events
                .lock()
                .map(|guard| guard.iter().any(|(name, _)| name == "library.extract.done"))
                .unwrap_or(false);
            if done {
                break;
            }
            if std::time::Instant::now() > deadline {
                panic!("拆 BGM 超时");
            }
        }

        let captured = events.lock().unwrap();
        let names: Vec<&str> = captured.iter().map(|(name, _)| name.as_str()).collect();
        let done_payload = captured
            .iter()
            .find(|(name, _)| name == "library.extract.done")
            .map(|(_, payload)| payload.clone())
            .unwrap_or(Value::Null);
        let progress: Vec<Value> = captured
            .iter()
            .filter(|(name, _)| name == "library.extract.progress")
            .map(|(_, payload)| {
                json!({
                    "done": payload.get("done"),
                    "total": payload.get("total"),
                    "current": payload.get("current"),
                })
            })
            .collect();
        println!(
            "EXTRACT_PARITY={}",
            json!({
                "task_total": started["total"],
                "event_names": names,
                "progress": progress,
                "summary": done_payload.get("summary"),
                "results": done_payload.get("results"),
            })
        );
    }
}
