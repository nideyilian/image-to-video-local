//! 任务队列，对齐 `src/engine/runner.py` 的 `JobManager`。
//!
//! 与 Python 版结构一致：把配置写成 JSON、spawn 一个 worker 进程、
//! 逐行读它的 stdout（每行一个 JSON）、写 control 文件控制暂停/取消。
//!
//! ⚠️ **这一步只搬「任务管理」，worker 仍是 Python**（`python -m src.render.worker`）。
//! 原因：渲染内核还有 29 种特效、跟随水印的像素合成、图片列表选取没迁完，
//! worker 现在还离不开 Python。等那些补完，把 [`WorkerCommand`] 换成
//! 「起 Rust 线程跑 compositor」即可，**接口和事件协议一行都不用改**。
//!
//! 事件通过 `EventSink` 回调发出，由调用方（Tauri 命令）转成前端事件。

use std::collections::HashMap;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};

use serde_json::{json, Map, Value};

use crate::render::compositor::ComposeHooks;

/// 事件出口：`(event, payload)`，对应 Python 的 `callback({"type":"event",...})`。
pub type EventSink = Arc<dyn Fn(&str, Value) + Send + Sync>;

/// 任务状态。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum JobStatus {
    /// 预留：批量排队（当前 start 直接进 Running，与旧引擎一致）。
    #[allow(dead_code)]
    Queued,
    Running,
    Paused,
    Cancelling,
    Completed,
    Failed,
    Cancelled,
}

impl JobStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            JobStatus::Queued => "queued",
            JobStatus::Running => "running",
            JobStatus::Paused => "paused",
            JobStatus::Cancelling => "cancelling",
            JobStatus::Completed => "completed",
            JobStatus::Failed => "failed",
            JobStatus::Cancelled => "cancelled",
        }
    }

    pub fn is_active(&self) -> bool {
        matches!(
            self,
            JobStatus::Running | JobStatus::Paused | JobStatus::Cancelling
        )
    }
}

/// 一个任务的内部状态。
pub struct JobRecord {
    pub job_id: String,
    pub status: JobStatus,
    pub paused: bool,
    pub cancel_requested: bool,
    pub progress: i64,
    pub overall: i64,
    pub speed: Option<String>,
    pub message: String,
    pub started_at: Option<f64>,
    pub finished_at: Option<f64>,
    pub return_code: Option<i32>,
    pub config_path: PathBuf,
    pub control_path: PathBuf,
    pub child: Option<Child>,
}

impl JobRecord {
    /// 与 `JobRecord.public_state()` 逐字段一致。
    pub fn public_state(&self) -> Value {
        json!({
            "job_id": self.job_id,
            "status": self.status.as_str(),
            "paused": self.paused,
            "cancel_requested": self.cancel_requested,
            "progress": self.progress,
            "overall": self.overall,
            "speed": self.speed,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "return_code": self.return_code,
        })
    }
}

/// worker 的启动方式。
#[derive(Debug, Clone)]
pub enum WorkerCommand {
    /// `python -m src.render.worker --config ... --control ...`（源码模式）
    PythonModule { python: String, project_root: PathBuf },
    /// `exe --legacy-worker --config ... --control ...`（打包模式）
    Packaged { executable: PathBuf },
    /// 直接在本进程里跑 Rust 导出（`render::batch::run_batch`）。
    ///
    /// 这条路径不需要 Python：选图、逐帧渲染、后处理全在 Rust 里完成。
    /// 保留上面两个变体是为了灰度 —— 一旦 Rust 导出出问题，改回 PythonModule 即可。
    Native,
}

impl WorkerCommand {
    fn build(&self, config_path: &Path, control_path: &Path) -> (String, Vec<String>, PathBuf) {
        match self {
            WorkerCommand::PythonModule {
                python,
                project_root,
            } => (
                python.clone(),
                vec![
                    "-m".to_string(),
                    "src.render.worker".to_string(),
                    "--config".to_string(),
                    config_path.to_string_lossy().into_owned(),
                    "--control".to_string(),
                    control_path.to_string_lossy().into_owned(),
                ],
                project_root.clone(),
            ),
            // 不会走到：start() 已先分流到 start_native
            WorkerCommand::Native => (String::new(), Vec::new(), std::env::temp_dir()),
            WorkerCommand::Packaged { executable } => (
                executable.to_string_lossy().into_owned(),
                vec![
                    "--legacy-worker".to_string(),
                    "--config".to_string(),
                    config_path.to_string_lossy().into_owned(),
                    "--control".to_string(),
                    control_path.to_string_lossy().into_owned(),
                ],
                executable
                    .parent()
                    .map(Path::to_path_buf)
                    .unwrap_or_default(),
            ),
        }
    }
}

/// 任务管理器。
pub struct JobManager {
    jobs: Mutex<HashMap<String, Arc<Mutex<JobRecord>>>>,
    sink: EventSink,
    worker: WorkerCommand,
}

fn now_secs() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_secs_f64())
        .unwrap_or(0.0)
}

fn runtime_dir() -> PathBuf {
    std::env::temp_dir().join("image-to-video-engine")
}

impl JobManager {
    pub fn new(sink: EventSink, worker: WorkerCommand) -> Self {
        JobManager {
            jobs: Mutex::new(HashMap::new()),
            sink,
            worker,
        }
    }

    fn emit(&self, event: &str, payload: Value) {
        (self.sink)(event, payload);
    }

    /// 与 `JobManager.start()` 等价。配置必须是**已归一化并校验过**的。
    pub fn start(&self, config: &Map<String, Value>, job_id: Option<String>) -> Result<Value, String> {
        let resolved = job_id.unwrap_or_else(|| format!("job-{}", (now_secs() * 1000.0) as i64));

        {
            let jobs = self.jobs.lock().map_err(|_| "任务表锁定失败")?;
            if let Some(existing) = jobs.get(&resolved) {
                let record = existing.lock().map_err(|_| "任务记录锁定失败")?;
                if record.status.is_active() {
                    return Err("任务正在运行".to_string());
                }
            }
        }

        let dir = runtime_dir();
        std::fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
        let config_path = dir.join(format!("{resolved}.config.json"));
        let control_path = dir.join(format!("{resolved}.control.json"));
        let config_text = serde_json::to_string_pretty(&Value::Object(config.clone()))
            .map_err(|error| error.to_string())?;
        std::fs::write(&config_path, config_text).map_err(|error| error.to_string())?;
        std::fs::write(
            &control_path,
            serde_json::to_string(&json!({ "paused": false, "cancel": false }))
                .map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())?;

        if matches!(self.worker, WorkerCommand::Native) {
            return self.start_native(&resolved, config, config_path, control_path);
        }

        let (program, args, cwd) = self.worker.build(&config_path, &control_path);
        let mut command = Command::new(&program);
        command.args(&args);
        command.current_dir(&cwd);
        command.stdin(Stdio::null());
        command.stdout(Stdio::piped());
        command.stderr(Stdio::piped());
        command.env("PYTHONIOENCODING", "utf-8");
        command.env("PYTHONUTF8", "1");
        crate::engine::system::hide_console(&mut command);

        let child = match command.spawn() {
            Ok(child) => child,
            Err(error) => {
                let _ = std::fs::remove_file(&config_path);
                let _ = std::fs::remove_file(&control_path);
                return Err(format!("无法启动渲染进程: {error}"));
            }
        };

        let record = Arc::new(Mutex::new(JobRecord {
            job_id: resolved.clone(),
            status: JobStatus::Running,
            paused: false,
            cancel_requested: false,
            progress: 0,
            overall: 0,
            speed: None,
            message: "开始处理".to_string(),
            started_at: Some(now_secs()),
            finished_at: None,
            return_code: None,
            config_path,
            control_path,
            child: Some(child),
        }));

        {
            let mut jobs = self.jobs.lock().map_err(|_| "任务表锁定失败")?;
            jobs.insert(resolved.clone(), record.clone());
        }

        // 起三个线程：读 stdout / 读 stderr / 等退出
        self.spawn_reader(record.clone(), true);
        self.spawn_reader(record.clone(), false);
        self.spawn_watcher(record.clone());

        let state = record
            .lock()
            .map_err(|_| "任务记录锁定失败")?
            .public_state();
        self.emit("job.started", state.clone());
        Ok(state)
    }

    /// 用本进程内的 Rust 渲染跑一个任务。
    ///
    /// 事件协议与 Python worker 完全一致（`job.log` / `job.progress` / `job.done`），
    /// 所以前端一行都不用改。暂停/取消仍然走 control 文件 —— 渲染线程每帧读一次。
    fn start_native(
        &self,
        job_id: &str,
        config: &Map<String, Value>,
        config_path: PathBuf,
        control_path: PathBuf,
    ) -> Result<Value, String> {
        let record = Arc::new(Mutex::new(JobRecord {
            job_id: job_id.to_string(),
            status: JobStatus::Running,
            paused: false,
            cancel_requested: false,
            progress: 0,
            overall: 0,
            speed: None,
            message: "开始处理".to_string(),
            started_at: Some(now_secs()),
            finished_at: None,
            return_code: None,
            config_path: config_path.clone(),
            control_path: control_path.clone(),
            child: None,
        }));

        {
            let mut jobs = self.jobs.lock().map_err(|_| "任务表锁定失败")?;
            jobs.insert(job_id.to_string(), record.clone());
        }

        let state = record.lock().map_err(|_| "任务记录锁定失败")?.public_state();
        self.emit("job.started", state.clone());

        let sink = self.sink.clone();
        let config_value = Value::Object(config.clone());
        let thread_record = record.clone();
        let thread_control = control_path.clone();
        let thread_sink = sink.clone();
        let thread_job_id = job_id.to_string();

        std::thread::spawn(move || {
            let mut hooks = NativeHooks {
                record: thread_record.clone(),
                sink: thread_sink.clone(),
                control_path: thread_control,
                job_id: thread_job_id.clone(),
                last_progress: -1,
            };
            let ffmpeg = crate::engine::system::resolve_ffmpeg(None);
            let outcome = match ffmpeg {
                Some(ffmpeg) => {
                    crate::render::batch::run_batch(&config_value, &ffmpeg, &mut hooks)
                }
                None => Err("未找到 FFmpeg，无法开始渲染".to_string()),
            };

            let cancelled = hooks.cancelled();
            if let Ok(mut guard) = thread_record.lock() {
                guard.finished_at = Some(now_secs());
                if cancelled {
                    guard.status = JobStatus::Cancelled;
                    guard.message = "已取消".to_string();
                } else {
                    match &outcome {
                        Ok(result) => {
                            guard.status = JobStatus::Completed;
                            guard.progress = 100;
                            guard.overall = 100;
                            guard.message = format!(
                                "处理完成（成功 {} / 共 {}）",
                                result.success, result.total
                            );
                        }
                        Err(error) => {
                            guard.status = JobStatus::Failed;
                            guard.message = error.clone();
                        }
                    }
                }
            }
            let final_state = thread_record
                .lock()
                .map(|guard| guard.public_state())
                .unwrap_or(Value::Null);

            // 与 Python worker 的收尾事件保持一致
            thread_sink(
                "job.done",
                match &outcome {
                    Ok(result) => json!({
                        "job_id": thread_job_id,
                        "success": result.success,
                        "total": result.total,
                        "outputs": result.outputs,
                    }),
                    Err(error) => json!({
                        "job_id": thread_job_id,
                        "success": 0,
                        "error": error,
                    }),
                },
            );
            let _ = std::fs::remove_file(&thread_record
                .lock()
                .map(|guard| guard.config_path.clone())
                .unwrap_or_default());
            thread_sink("job.finished", final_state);
        });

        Ok(state)
    }

    fn spawn_reader(&self, record: Arc<Mutex<JobRecord>>, is_stdout: bool) {
        let sink = self.sink.clone();
        std::thread::spawn(move || {
            let pipe: Option<Box<dyn std::io::Read + Send>> = {
                let mut guard = match record.lock() {
                    Ok(guard) => guard,
                    Err(_) => return,
                };
                let child = match guard.child.as_mut() {
                    Some(child) => child,
                    None => return,
                };
                if is_stdout {
                    child
                        .stdout
                        .take()
                        .map(|pipe| Box::new(pipe) as Box<dyn std::io::Read + Send>)
                } else {
                    child
                        .stderr
                        .take()
                        .map(|pipe| Box::new(pipe) as Box<dyn std::io::Read + Send>)
                }
            };
            let Some(pipe) = pipe else { return };
            let reader = BufReader::new(pipe);
            for line in reader.lines() {
                let Ok(line) = line else { break };
                let trimmed = line.trim();
                if trimmed.is_empty() {
                    continue;
                }
                if !is_stdout {
                    sink(
                        "job.log",
                        json!({ "stream": "stderr", "message": trimmed }),
                    );
                    continue;
                }
                match serde_json::from_str::<Value>(trimmed) {
                    Ok(payload) => apply_worker_payload(&record, &sink, payload),
                    Err(_) => {
                        let job_id = record
                            .lock()
                            .map(|guard| guard.job_id.clone())
                            .unwrap_or_default();
                        sink(
                            "job.log",
                            json!({ "job_id": job_id, "stream": "stdout", "message": trimmed }),
                        );
                    }
                }
            }
        });
    }

    fn spawn_watcher(&self, record: Arc<Mutex<JobRecord>>) {
        let sink = self.sink.clone();
        std::thread::spawn(move || {
            let return_code = {
                let mut guard = match record.lock() {
                    Ok(guard) => guard,
                    Err(_) => return,
                };
                match guard.child.as_mut() {
                    Some(child) => child.wait().ok().and_then(|status| status.code()),
                    None => None,
                }
            };
            let (state, config_path, control_path) = {
                let mut guard = match record.lock() {
                    Ok(guard) => guard,
                    Err(_) => return,
                };
                guard.return_code = return_code;
                guard.finished_at = Some(now_secs());
                if guard.cancel_requested {
                    guard.status = JobStatus::Cancelled;
                    guard.message = "任务已取消".to_string();
                } else if guard.status != JobStatus::Completed && guard.status != JobStatus::Failed {
                    guard.status = if return_code == Some(0) {
                        JobStatus::Completed
                    } else {
                        JobStatus::Failed
                    };
                    guard.message = if return_code == Some(0) {
                        "处理完成".to_string()
                    } else {
                        format!("处理失败（退出码 {}）", return_code.unwrap_or(-1))
                    };
                }
                (
                    guard.public_state(),
                    guard.config_path.clone(),
                    guard.control_path.clone(),
                )
            };
            let _ = std::fs::remove_file(&config_path);
            let _ = std::fs::remove_file(&control_path);
            sink("job.finished", state);
        });
    }

    /// 与 `pause()` 等价。
    pub fn pause(&self, job_id: &str) -> Result<Value, String> {
        self.mutate(job_id, |record| {
            record.paused = true;
            record.status = JobStatus::Paused;
            record.message = "已暂停".to_string();
        })?;
        self.write_control(job_id)?;
        self.emit_state(job_id, "job.status")
    }

    /// 与 `resume()` 等价。
    pub fn resume(&self, job_id: &str) -> Result<Value, String> {
        self.mutate(job_id, |record| {
            record.paused = false;
            record.status = JobStatus::Running;
            record.message = "继续处理".to_string();
        })?;
        self.write_control(job_id)?;
        self.emit_state(job_id, "job.status")
    }

    /// 与 `cancel()` 等价。
    pub fn cancel(&self, job_id: &str) -> Result<Value, String> {
        self.mutate(job_id, |record| {
            record.cancel_requested = true;
            record.paused = false;
            record.status = JobStatus::Cancelling;
            record.message = "正在取消".to_string();
        })?;
        self.write_control(job_id)?;
        self.emit_state(job_id, "job.status")
    }

    /// 与 `list_jobs()` 等价。
    pub fn list(&self) -> Result<Value, String> {
        let jobs = self.jobs.lock().map_err(|_| "任务表锁定失败")?;
        let mut states: Vec<Value> = Vec::new();
        for record in jobs.values() {
            if let Ok(guard) = record.lock() {
                states.push(guard.public_state());
            }
        }
        Ok(Value::Array(states))
    }

    fn find(&self, job_id: &str) -> Result<Arc<Mutex<JobRecord>>, String> {
        let jobs = self.jobs.lock().map_err(|_| "任务表锁定失败")?;
        jobs.get(job_id)
            .cloned()
            .ok_or_else(|| "任务不存在".to_string())
    }

    fn mutate(
        &self,
        job_id: &str,
        change: impl FnOnce(&mut JobRecord),
    ) -> Result<(), String> {
        let record = self.find(job_id)?;
        let mut guard = record.lock().map_err(|_| "任务记录锁定失败")?;
        if !guard.status.is_active() {
            return Err("任务已经结束".to_string());
        }
        change(&mut guard);
        Ok(())
    }

    fn write_control(&self, job_id: &str) -> Result<(), String> {
        let record = self.find(job_id)?;
        let (paused, cancel, path) = {
            let guard = record.lock().map_err(|_| "任务记录锁定失败")?;
            (
                guard.paused,
                guard.cancel_requested,
                guard.control_path.clone(),
            )
        };
        std::fs::write(
            &path,
            serde_json::to_string(&json!({ "paused": paused, "cancel": cancel }))
                .map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())
    }

    fn emit_state(&self, job_id: &str, event: &str) -> Result<Value, String> {
        let record = self.find(job_id)?;
        let state = record
            .lock()
            .map_err(|_| "任务记录锁定失败")?
            .public_state();
        self.emit(event, state.clone());
        Ok(state)
    }
}

/// 与 `_apply_worker_payload()` 等价：把 worker 的一行 JSON 转成事件。
fn apply_worker_payload(record: &Arc<Mutex<JobRecord>>, sink: &EventSink, payload: Value) {
    let event_type = payload
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let mut guard = match record.lock() {
        Ok(guard) => guard,
        Err(_) => return,
    };
    match event_type.as_str() {
        "progress" => {
            if let Some(percent) = payload.get("percent").and_then(Value::as_i64) {
                guard.progress = percent;
            }
            guard.overall = payload
                .get("overall")
                .and_then(Value::as_i64)
                .unwrap_or(guard.progress);
            guard.speed = payload
                .get("speed")
                .filter(|value| !value.is_null())
                .map(|value| match value {
                    Value::String(text) => text.clone(),
                    other => other.to_string(),
                });
            let phase = payload
                .get("phase")
                .and_then(Value::as_str)
                .unwrap_or("")
                .trim()
                .to_string();
            if !phase.is_empty() {
                guard.message = phase;
            }
            let mut merged = match guard.public_state() {
                Value::Object(map) => map,
                _ => Map::new(),
            };
            if let Value::Object(extra) = payload {
                for (key, value) in extra {
                    merged.insert(key, value);
                }
            }
            sink("job.progress", Value::Object(merged));
        }
        "status" => {
            guard.message = payload
                .get("message")
                .and_then(Value::as_str)
                .unwrap_or("处理中")
                .to_string();
            sink("job.status", guard.public_state());
        }
        "done" => {
            let success = payload
                .get("success")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            guard.status = if success {
                JobStatus::Completed
            } else {
                JobStatus::Failed
            };
            if success {
                guard.progress = 100;
                guard.overall = 100;
            }
            guard.message = if success { "处理完成" } else { "处理失败" }.to_string();
            let mut state = match guard.public_state() {
                Value::Object(map) => map,
                _ => Map::new(),
            };
            state.insert("success".to_string(), json!(success));
            sink("job.done", Value::Object(state));
        }
        _ => {
            let job_id = guard.job_id.clone();
            sink(
                "job.log",
                json!({ "job_id": job_id, "stream": "worker", "message": payload }),
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn silent_sink() -> EventSink {
        Arc::new(|_event: &str, _payload: Value| {})
    }

    fn recording_sink() -> (EventSink, Arc<Mutex<Vec<(String, Value)>>>) {
        let events = Arc::new(Mutex::new(Vec::new()));
        let captured = events.clone();
        let sink: EventSink = Arc::new(move |event: &str, payload: Value| {
            if let Ok(mut guard) = captured.lock() {
                guard.push((event.to_string(), payload));
            }
        });
        (sink, events)
    }

    fn manager(sink: EventSink) -> JobManager {
        JobManager::new(
            sink,
            WorkerCommand::PythonModule {
                python: "python".to_string(),
                project_root: std::env::temp_dir(),
            },
        )
    }

    #[test]
    fn status_strings_match_python() {
        assert_eq!(JobStatus::Queued.as_str(), "queued");
        assert_eq!(JobStatus::Running.as_str(), "running");
        assert_eq!(JobStatus::Paused.as_str(), "paused");
        assert_eq!(JobStatus::Cancelling.as_str(), "cancelling");
        assert_eq!(JobStatus::Completed.as_str(), "completed");
        assert_eq!(JobStatus::Failed.as_str(), "failed");
        assert_eq!(JobStatus::Cancelled.as_str(), "cancelled");
        assert!(JobStatus::Running.is_active());
        assert!(JobStatus::Cancelling.is_active());
        assert!(!JobStatus::Completed.is_active());
        assert!(!JobStatus::Queued.is_active());
    }

    #[test]
    fn public_state_has_all_python_fields() {
        let record = JobRecord {
            job_id: "j1".into(),
            status: JobStatus::Running,
            paused: false,
            cancel_requested: false,
            progress: 10,
            overall: 12,
            speed: Some("1.5x".into()),
            message: "处理中".into(),
            started_at: Some(1.0),
            finished_at: None,
            return_code: None,
            config_path: PathBuf::from("c.json"),
            control_path: PathBuf::from("k.json"),
            child: None,
        };
        let state = record.public_state();
        for key in [
            "job_id",
            "status",
            "paused",
            "cancel_requested",
            "progress",
            "overall",
            "speed",
            "message",
            "started_at",
            "finished_at",
            "return_code",
        ] {
            assert!(state.get(key).is_some(), "缺少字段 {key}");
        }
        assert_eq!(state["status"], "running");
        assert_eq!(state["progress"], 10);
    }

    #[test]
    fn worker_command_for_python_module() {
        let command = WorkerCommand::PythonModule {
            python: "C:/py/python.exe".into(),
            project_root: PathBuf::from("C:/proj"),
        };
        let (program, args, cwd) = command.build(Path::new("c.json"), Path::new("k.json"));
        assert_eq!(program, "C:/py/python.exe");
        assert_eq!(args[0], "-m");
        assert_eq!(args[1], "src.render.worker");
        assert!(args.contains(&"--config".to_string()));
        assert!(args.contains(&"c.json".to_string()));
        assert_eq!(cwd, PathBuf::from("C:/proj"));
    }

    #[test]
    fn worker_command_for_packaged_mode() {
        let command = WorkerCommand::Packaged {
            executable: PathBuf::from("C:/app/engine.exe"),
        };
        let (program, args, cwd) = command.build(Path::new("c.json"), Path::new("k.json"));
        assert!(program.ends_with("engine.exe"));
        assert_eq!(args[0], "--legacy-worker");
        assert_eq!(cwd, PathBuf::from("C:/app"));
    }

    #[test]
    fn progress_payload_merges_extra_fields() {
        let (sink, events) = recording_sink();
        let record = Arc::new(Mutex::new(JobRecord {
            job_id: "j1".into(),
            status: JobStatus::Running,
            paused: false,
            cancel_requested: false,
            progress: 0,
            overall: 0,
            speed: None,
            message: String::new(),
            started_at: None,
            finished_at: None,
            return_code: None,
            config_path: PathBuf::from("c"),
            control_path: PathBuf::from("k"),
            child: None,
        }));
        apply_worker_payload(
            &record,
            &sink,
            json!({ "type": "progress", "percent": 42, "overall": 50, "speed": "2.0x",
                    "phase": "渲染中", "extra": 1 }),
        );
        let guard = record.lock().unwrap();
        assert_eq!(guard.progress, 42);
        assert_eq!(guard.overall, 50);
        assert_eq!(guard.speed.as_deref(), Some("2.0x"));
        assert_eq!(guard.message, "渲染中");
        drop(guard);

        let captured = events.lock().unwrap();
        assert_eq!(captured.len(), 1);
        assert_eq!(captured[0].0, "job.progress");
        // 合并后的 payload 里既有 public_state 字段，也有 worker 原始字段
        assert_eq!(captured[0].1["progress"], 42);
        assert_eq!(captured[0].1["extra"], 1);
    }

    #[test]
    fn done_payload_marks_completed() {
        let (sink, events) = recording_sink();
        let record = Arc::new(Mutex::new(JobRecord {
            job_id: "j1".into(),
            status: JobStatus::Running,
            paused: false,
            cancel_requested: false,
            progress: 60,
            overall: 60,
            speed: None,
            message: String::new(),
            started_at: None,
            finished_at: None,
            return_code: None,
            config_path: PathBuf::from("c"),
            control_path: PathBuf::from("k"),
            child: None,
        }));
        apply_worker_payload(&record, &sink, json!({ "type": "done", "success": true }));
        let guard = record.lock().unwrap();
        assert_eq!(guard.status, JobStatus::Completed);
        assert_eq!(guard.progress, 100);
        drop(guard);

        let captured = events.lock().unwrap();
        assert_eq!(captured[0].0, "job.done");
        assert_eq!(captured[0].1["success"], true);
    }

    #[test]
    fn unknown_payload_becomes_job_log() {
        let (sink, events) = recording_sink();
        let record = Arc::new(Mutex::new(JobRecord {
            job_id: "j1".into(),
            status: JobStatus::Running,
            paused: false,
            cancel_requested: false,
            progress: 0,
            overall: 0,
            speed: None,
            message: String::new(),
            started_at: None,
            finished_at: None,
            return_code: None,
            config_path: PathBuf::from("c"),
            control_path: PathBuf::from("k"),
            child: None,
        }));
        apply_worker_payload(&record, &sink, json!({ "hello": "world" }));
        let captured = events.lock().unwrap();
        assert_eq!(captured[0].0, "job.log");
        assert_eq!(captured[0].1["stream"], "worker");
    }

    #[test]
    fn missing_job_errors_like_python() {
        let manager = manager(silent_sink());
        assert_eq!(manager.pause("nope").unwrap_err(), "任务不存在");
        assert_eq!(manager.resume("nope").unwrap_err(), "任务不存在");
        assert_eq!(manager.cancel("nope").unwrap_err(), "任务不存在");
    }

    #[test]
    fn list_is_empty_initially() {
        let manager = manager(silent_sink());
        assert_eq!(manager.list().unwrap(), json!([]));
    }

    #[test]
    fn start_with_missing_worker_reports_error() {
        let manager = JobManager::new(
            silent_sink(),
            WorkerCommand::PythonModule {
                python: "definitely-not-a-real-python-binary".into(),
                project_root: std::env::temp_dir(),
            },
        );
        let mut config = Map::new();
        config.insert("output_dir".into(), json!(std::env::temp_dir().to_string_lossy()));
        let error = manager.start(&config, Some("t-missing".into())).unwrap_err();
        assert!(error.contains("无法启动渲染进程"), "实际: {error}");
    }
}
/// 把 Rust 渲染的回调翻译成前端熟悉的事件。
///
/// `ComposeHooks` 是渲染内核的抽象，这里实现它并把事件推给 `EventSink`。
/// 取消/暂停**读 control 文件**而不是内存标志 —— 与 Python worker 的机制一致，
/// 也让「任务在另一个线程里跑」这件事对上层透明。
struct NativeHooks {
    record: Arc<Mutex<JobRecord>>,
    sink: EventSink,
    control_path: PathBuf,
    job_id: String,
    last_progress: i64,
}

impl NativeHooks {
    fn read_control(&self) -> (bool, bool) {
        let Ok(text) = std::fs::read_to_string(&self.control_path) else {
            return (false, false);
        };
        let Ok(value) = serde_json::from_str::<Value>(&text) else {
            return (false, false);
        };
        (
            value.get("paused").and_then(Value::as_bool).unwrap_or(false),
            value.get("cancel").and_then(Value::as_bool).unwrap_or(false),
        )
    }
}

impl crate::render::compositor::ComposeHooks for NativeHooks {
    fn progress(&mut self, written: i64, total: i64) {
        // 每帧都会回调，节流成「每 2% 一次」，避免把事件总线打满
        let percent = if total > 0 {
            (written * 100 / total).clamp(0, 100)
        } else {
            0
        };
        if percent == self.last_progress {
            return;
        }
        self.last_progress = percent;
        if let Ok(mut guard) = self.record.lock() {
            guard.progress = percent;
        }
        (self.sink)(
            "job.progress",
            json!({
                "job_id": self.job_id,
                "progress": percent,
                "current": written,
                "total": total,
            }),
        );
    }

    fn cancelled(&mut self) -> bool {
        let (_, cancel) = self.read_control();
        if cancel {
            if let Ok(mut guard) = self.record.lock() {
                guard.cancel_requested = true;
            }
        }
        cancel
    }

    fn log(&mut self, message: &str) {
        if let Ok(mut guard) = self.record.lock() {
            guard.message = message.to_string();
        }
        (self.sink)(
            "job.log",
            json!({ "stream": "stdout", "message": message }),
        );
    }
}
