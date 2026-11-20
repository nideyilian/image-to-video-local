use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

mod engine;
mod render;

/// 引擎接口的原生实现入口。
///
/// 已迁移的 method 直接在此返回结果；未迁移的返回 `handled: false`，
/// 由前端回落到 Python sidecar（见 `src/engine.ts` 的调用路由）。
#[tauri::command]
fn engine_dispatch(method: String, params: Option<serde_json::Value>) -> engine::DispatchResponse {
    engine::dispatch(&method, params)
}

#[tauri::command]
fn project_root() -> Result<String, String> {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .map(|path| path.to_string_lossy().into_owned())
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn read_text_file(path: String) -> Result<String, String> {
    fs::read_to_string(path).map_err(|error| error.to_string())
}

#[tauri::command]
fn write_text_file(path: String, contents: String) -> Result<(), String> {
    fs::write(path, contents).map_err(|error| error.to_string())
}

#[tauri::command]
fn reveal_path(path: String) -> Result<(), String> {
    let target = Path::new(&path);
    if !target.exists() {
        return Err("路径不存在".to_string());
    }

    #[cfg(target_os = "windows")]
    let mut command = {
        let mut value = Command::new("explorer");
        value.arg(target);
        value
    };
    #[cfg(target_os = "macos")]
    let mut command = {
        let mut value = Command::new("open");
        value.arg(target);
        value
    };
    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = {
        let mut value = Command::new("xdg-open");
        value.arg(target);
        value
    };

    command
        .spawn()
        .map(|_| ())
        .map_err(|error| error.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            project_root,
            read_text_file,
            write_text_file,
            reveal_path,
            engine_dispatch,
        ])
        .setup(|app| {
            // 任务队列靠它把 job.* 事件推给前端（前端在 engine.ts 里桥接到订阅者）
            engine::set_app_handle(app.handle().clone());
            // 清掉旧版本释放过的 ffmpeg（升级后旧文件没用了，留着白占 87MB）。
            // 放后台线程：扫一个目录不该拖慢启动。
            std::thread::spawn(engine::embedded_ffmpeg::cleanup_stale);
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
