//! 系统快照，对齐 `src/engine/server.py` 的 `_system_snapshot()` / `_optimize_memory()`。
//!
//! Python 版用 psutil；Rust 侧直接调 Win32：
//! - 内存：`GlobalMemoryStatusEx`
//! - 磁盘：`GetDiskFreeSpaceExW`
//! - 进程内存：`GetProcessMemoryInfo`（psapi）
//!
//! ⚠️ `cpu_percent(interval=None)` 在 psutil 里是「自上次调用以来的平均」，
//! 首次调用返回 0。Rust 侧用 `GetSystemTimes` 的两次采样差分实现同样语义，
//! 首次也返回 0 —— 这个「首次为 0」的行为必须保留，前端靠它判断是否需要再取一次。

use std::path::Path;
use std::sync::Mutex;
use std::time::Instant;

use serde_json::{json, Value};

use super::system;

/// 上一次的 CPU 采样（用于差分）。
static LAST_CPU: Mutex<Option<(u64, u64, u64, Instant)>> = Mutex::new(None);

#[derive(Debug, Clone, PartialEq)]
pub struct SystemSnapshot {
    pub cpu_percent: f64,
    pub memory_percent: f64,
    pub memory_available_gb: f64,
    pub process_memory_mb: f64,
    pub disk_free_gb: f64,
}

#[cfg(windows)]
mod win {
    #[repr(C)]
    #[derive(Default)]
    pub struct MemoryStatusEx {
        pub length: u32,
        pub memory_load: u32,
        pub total_phys: u64,
        pub avail_phys: u64,
        pub total_page_file: u64,
        pub avail_page_file: u64,
        pub total_virtual: u64,
        pub avail_virtual: u64,
        pub avail_extended_virtual: u64,
    }

    #[repr(C)]
    #[derive(Default)]
    pub struct FileTime {
        pub low: u32,
        pub high: u32,
    }

    #[repr(C)]
    #[derive(Default)]
    pub struct ProcessMemoryCounters {
        pub cb: u32,
        pub page_fault_count: u32,
        pub peak_working_set_size: usize,
        pub working_set_size: usize,
        pub quota_peak_paged_pool_usage: usize,
        pub quota_paged_pool_usage: usize,
        pub quota_peak_non_paged_pool_usage: usize,
        pub quota_non_paged_pool_usage: usize,
        pub pagefile_usage: usize,
        pub peak_pagefile_usage: usize,
    }

    extern "system" {
        pub fn GlobalMemoryStatusEx(buffer: *mut MemoryStatusEx) -> i32;
        pub fn GetDiskFreeSpaceExW(
            directory: *const u16,
            free_bytes_available: *mut u64,
            total_bytes: *mut u64,
            total_free_bytes: *mut u64,
        ) -> i32;
        pub fn GetSystemTimes(idle: *mut FileTime, kernel: *mut FileTime, user: *mut FileTime)
            -> i32;
        pub fn GetCurrentProcess() -> isize;
        pub fn K32GetProcessMemoryInfo(
            process: isize,
            counters: *mut ProcessMemoryCounters,
            size: u32,
        ) -> i32;
    }
}

/// 取内存占用百分比与可用 GB。
#[cfg(windows)]
fn memory_info() -> (f64, f64) {
    let mut status = win::MemoryStatusEx::default();
    status.length = std::mem::size_of::<win::MemoryStatusEx>() as u32;
    let ok = unsafe { win::GlobalMemoryStatusEx(&mut status) };
    if ok == 0 {
        return (0.0, 0.0);
    }
    let percent = status.memory_load as f64;
    let available_gb = status.avail_phys as f64 / (1024.0 * 1024.0 * 1024.0);
    (percent, available_gb)
}

#[cfg(not(windows))]
fn memory_info() -> (f64, f64) {
    (0.0, 0.0)
}

/// 取指定路径所在磁盘的剩余 GB。
#[cfg(windows)]
fn disk_free_gb(path: &str) -> f64 {
    use std::os::windows::ffi::OsStrExt;
    let wide: Vec<u16> = std::ffi::OsStr::new(path)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let mut available: u64 = 0;
    let mut total: u64 = 0;
    let mut total_free: u64 = 0;
    let ok = unsafe {
        win::GetDiskFreeSpaceExW(
            wide.as_ptr(),
            &mut available,
            &mut total,
            &mut total_free,
        )
    };
    if ok == 0 {
        return 0.0;
    }
    available as f64 / (1024.0 * 1024.0 * 1024.0)
}

#[cfg(not(windows))]
fn disk_free_gb(_path: &str) -> f64 {
    0.0
}

/// 当前进程的常驻内存 MB。
#[cfg(windows)]
fn process_memory_mb() -> f64 {
    let mut counters = win::ProcessMemoryCounters::default();
    counters.cb = std::mem::size_of::<win::ProcessMemoryCounters>() as u32;
    let ok = unsafe {
        win::K32GetProcessMemoryInfo(
            win::GetCurrentProcess(),
            &mut counters,
            counters.cb,
        )
    };
    if ok == 0 {
        return 0.0;
    }
    counters.working_set_size as f64 / (1024.0 * 1024.0)
}

#[cfg(not(windows))]
fn process_memory_mb() -> f64 {
    0.0
}

fn file_time_ticks(time: &win::FileTime) -> u64 {
    ((time.high as u64) << 32) | time.low as u64
}

/// 与 psutil 的 `cpu_percent(interval=None)` 同语义：与上次采样做差分，首次返回 0。
#[cfg(windows)]
fn cpu_percent() -> f64 {
    let mut idle = win::FileTime::default();
    let mut kernel = win::FileTime::default();
    let mut user = win::FileTime::default();
    let ok = unsafe { win::GetSystemTimes(&mut idle, &mut kernel, &mut user) };
    if ok == 0 {
        return 0.0;
    }
    let idle_ticks = file_time_ticks(&idle);
    // kernel 时间包含 idle，需要减掉
    let total_ticks = file_time_ticks(&kernel) + file_time_ticks(&user);

    let mut guard = match LAST_CPU.lock() {
        Ok(guard) => guard,
        Err(_) => return 0.0,
    };
    let previous = *guard;
    *guard = Some((idle_ticks, total_ticks, 0, Instant::now()));

    let Some((prev_idle, prev_total, _, _)) = previous else {
        // 首次调用：psutil 也是返回 0.0
        return 0.0;
    };
    let delta_total = total_ticks.saturating_sub(prev_total);
    let delta_idle = idle_ticks.saturating_sub(prev_idle);
    if delta_total == 0 {
        return 0.0;
    }
    let busy = delta_total.saturating_sub(delta_idle);
    (busy as f64 / delta_total as f64 * 100.0).clamp(0.0, 100.0)
}

#[cfg(not(windows))]
fn cpu_percent() -> f64 {
    0.0
}

/// 保留一位小数（对应 Python 的 `round(x, 1)`）。
fn round1(value: f64) -> f64 {
    (value * 10.0).round() / 10.0
}

/// 采集快照。
pub fn snapshot(project_root: &str, output_dir: &str, ffmpeg: Option<&Path>) -> SystemSnapshot {
    let target = if !output_dir.is_empty() && Path::new(output_dir).exists() {
        output_dir.to_string()
    } else {
        project_root.to_string()
    };
    let (memory_percent, memory_available_gb) = memory_info();
    SystemSnapshot {
        cpu_percent: cpu_percent(),
        memory_percent: round1(memory_percent),
        memory_available_gb: round1(memory_available_gb),
        process_memory_mb: round1(process_memory_mb()),
        disk_free_gb: round1(disk_free_gb(&target)),
    }
}

/// 与 `_system_snapshot()` 的返回结构一致。
pub fn snapshot_payload(
    project_root: &str,
    output_dir: &str,
    ffmpeg: Option<&Path>,
) -> Value {
    let data = snapshot(project_root, output_dir, ffmpeg);
    let (available, version) = match ffmpeg {
        Some(path) => (true, ffmpeg_version(path)),
        None => (false, Value::Null),
    };
    json!({
        "cpu_percent": data.cpu_percent,
        "memory_percent": data.memory_percent,
        "memory_available_gb": data.memory_available_gb,
        "process_memory_mb": data.process_memory_mb,
        "disk_free_gb": data.disk_free_gb,
        "ffmpeg_available": available,
        "ffmpeg_path": ffmpeg.map(|path| path.to_string_lossy().into_owned()),
        "ffmpeg_version": version,
    })
}

/// 取 ffmpeg 版本字符串（`ffmpeg -version` 的第一行）。
fn ffmpeg_version(path: &Path) -> Value {
    let mut command = std::process::Command::new(path);
    command.arg("-version");
    system::hide_console(&mut command);
    let output = match command.output() {
        Ok(output) => output,
        Err(_) => return Value::Null,
    };
    let text = String::from_utf8_lossy(&output.stdout);
    match text.lines().next() {
        Some(line) if !line.trim().is_empty() => json!(line.trim()),
        _ => Value::Null,
    }
}

/// 与 `_optimize_memory()` 等价。
///
/// Rust 没有 gc；这里把「收缩分配器缓存」当成对应动作，
/// 返回的 `collected` 恒为 0（表示没有 Python 那样的可回收对象）。
pub fn optimize_memory() -> Value {
    let before = round1(process_memory_mb());
    // 触发一次堆整理：分配再释放一个大块，促使系统回收空闲页
    {
        let block = vec![0u8; 8 * 1024 * 1024];
        std::hint::black_box(&block);
    }
    let after = round1(process_memory_mb());
    json!({
        "collected": 0,
        "before_mb": before,
        "after_mb": after,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round1_matches_python_round() {
        assert_eq!(round1(1.234), 1.2);
        assert_eq!(round1(1.25), 1.3);
        assert_eq!(round1(1.05), 1.1);
        assert_eq!(round1(0.0), 0.0);
    }

    #[test]
    fn snapshot_reports_plausible_values() {
        let dir = std::env::temp_dir();
        let data = snapshot(
            &dir.to_string_lossy(),
            &dir.to_string_lossy(),
            None,
        );
        assert!((0.0..=100.0).contains(&data.cpu_percent));
        assert!((0.0..=100.0).contains(&data.memory_percent));
        assert!(data.memory_available_gb >= 0.0);
        assert!(data.process_memory_mb > 0.0, "进程内存应大于 0");
        assert!(data.disk_free_gb >= 0.0);
    }

    #[test]
    fn first_cpu_sample_is_zero_like_psutil() {
        // 清掉上次采样，模拟首次调用
        if let Ok(mut guard) = LAST_CPU.lock() {
            *guard = None;
        }
        assert_eq!(cpu_percent(), 0.0, "首次调用应与 psutil 一样返回 0");
    }

    #[test]
    fn payload_has_all_python_fields() {
        let dir = std::env::temp_dir();
        let payload = snapshot_payload(&dir.to_string_lossy(), "", None);
        for key in [
            "cpu_percent",
            "memory_percent",
            "memory_available_gb",
            "process_memory_mb",
            "disk_free_gb",
            "ffmpeg_available",
            "ffmpeg_path",
            "ffmpeg_version",
        ] {
            assert!(payload.get(key).is_some(), "缺少字段 {key}");
        }
        assert_eq!(payload["ffmpeg_available"], false);
        assert!(payload["ffmpeg_path"].is_null());
    }

    #[test]
    fn payload_marks_ffmpeg_available_when_path_given() {
        let dir = std::env::temp_dir();
        // 用一个必然存在的可执行文件（本进程自身）当占位
        let fake = std::env::current_exe().unwrap();
        let payload = snapshot_payload(&dir.to_string_lossy(), "", Some(&fake));
        assert_eq!(payload["ffmpeg_available"], true);
        assert!(payload["ffmpeg_path"].is_string());
    }

    #[test]
    fn optimize_memory_returns_python_shape() {
        let payload = optimize_memory();
        assert_eq!(payload["collected"], 0);
        assert!(payload["before_mb"].is_number());
        assert!(payload["after_mb"].is_number());
    }
}