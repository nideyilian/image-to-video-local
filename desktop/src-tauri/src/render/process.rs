//! 媒体探测与进程执行，对齐 `src/render/process.py`。
//!
//! 与 Python 版的差别只有一处：OpenCV 回退路径没有（Rust 侧不引入 OpenCV）。
//! ffprobe 拿不到时返回 None，由调用方决定如何降级 —— Python 那边会用 cv2 再试一次，
//! 实际场景里 ffprobe 与 ffmpeg 同目录分发，缺失概率极低。

use std::io::Read;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::Value;

use crate::engine::system;

/// 视频元信息。
#[derive(Debug, Clone, PartialEq)]
pub struct VideoMeta {
    pub width: i64,
    pub height: i64,
    pub fps: f64,
    pub frames: i64,
    pub duration: f64,
}

fn safe_float(value: Option<&Value>) -> f64 {
    match value {
        Some(Value::Number(number)) => number.as_f64().unwrap_or(0.0),
        Some(Value::String(text)) => text.trim().parse::<f64>().unwrap_or(0.0),
        _ => 0.0,
    }
}

fn safe_int(value: Option<&Value>) -> i64 {
    match value {
        Some(Value::Number(number)) => number
            .as_i64()
            .or_else(|| number.as_f64().map(|v| v as i64))
            .unwrap_or(0),
        Some(Value::String(text)) => text.trim().parse::<f64>().map(|v| v as i64).unwrap_or(0),
        _ => 0,
    }
}

/// 解析 `avg_frame_rate` / `r_frame_rate` 的 `num/den` 形式。
pub fn parse_fps(value: Option<&Value>) -> f64 {
    let text = match value {
        Some(Value::String(text)) => text.trim().to_string(),
        Some(Value::Number(number)) => return number.as_f64().unwrap_or(0.0),
        _ => String::new(),
    };
    if text.is_empty() || text == "0/0" || text == "N/A" {
        return 0.0;
    }
    if let Some((num, den)) = text.split_once('/') {
        let num: f64 = num.trim().parse().unwrap_or(0.0);
        let den: f64 = den.trim().parse().unwrap_or(0.0);
        if den > 0.0 {
            return num / den;
        }
        return 0.0;
    }
    text.parse::<f64>().unwrap_or(0.0)
}

/// 与 `probe_video_meta()` 的 ffprobe 分支等价。
pub fn probe_video_meta(video_path: &str, ffprobe: Option<&Path>) -> Option<VideoMeta> {
    // 没有独立 ffprobe 时用 ffmpeg 的 stderr 兜底 —— 安装包里只带了 ffmpeg，
    // 不带 ffprobe（每个都 80MB+，两个一起比原来整个安装包还大）。
    let Some(ffprobe) = ffprobe else {
        return probe_via_ffmpeg(video_path);
    };
    let mut command = Command::new(ffprobe);
    command.args([
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=width,height,avg_frame_rate,r_frame_rate,nb_frames",
        "-select_streams",
        "v:0",
        "-of",
        "json",
    ]);
    command.arg(video_path);
    system::hide_console(&mut command);
    let output = command.output().ok()?;
    if !output.status.success() {
        return None;
    }
    let payload: Value = serde_json::from_slice(&output.stdout).ok()?;
    let stream = payload.get("streams")?.as_array()?.first()?.clone();
    let width = safe_int(stream.get("width"));
    let height = safe_int(stream.get("height"));
    let mut fps = parse_fps(stream.get("avg_frame_rate"));
    if fps <= 0.0 {
        fps = parse_fps(stream.get("r_frame_rate"));
    }
    let mut frames = safe_int(stream.get("nb_frames"));
    let mut duration = safe_float(
        payload
            .get("format")
            .and_then(|value| value.get("duration")),
    );

    if duration <= 0.0 && fps > 0.0 && frames > 0 {
        duration = frames as f64 / fps;
    }
    if frames <= 0 && fps > 0.0 && duration > 0.0 {
        frames = (fps * duration).round() as i64;
    }
    if width <= 0 || height <= 0 {
        return None;
    }
    Some(VideoMeta {
        width,
        height,
        fps,
        frames: frames.max(0),
        duration: duration.max(0.0),
    })
}

/// 命令执行结果（只要退出码与 stderr，stdout 丢弃以省内存）。
pub struct CommandOutcome {
    pub code: Option<i32>,
    pub stderr: String,
    pub timed_out: bool,
}

/// 与 `run_process_with_retry()` 等价：超时、重试、失败返回最后一次结果。
pub fn run_with_retry(
    program: &str,
    args: &[String],
    stage: &str,
    timeout_secs: u64,
    retries: u32,
    mut log: impl FnMut(&str),
) -> Option<CommandOutcome> {
    let attempts = retries.max(1);
    let mut last: Option<CommandOutcome> = None;
    for attempt in 0..attempts {
        log(&format!(
            "[{stage}] 执行命令（尝试 {}/{attempts}）",
            attempt + 1
        ));
        match run_once(program, args, timeout_secs) {
            Ok(outcome) => {
                if outcome.code == Some(0) {
                    return Some(outcome);
                }
                let snippet: String = outcome.stderr.chars().take(220).collect();
                log(&format!(
                    "[{stage}] 命令失败: code={:?}, err={snippet}",
                    outcome.code
                ));
                last = Some(outcome);
            }
            Err(error) => {
                log(&format!("[{stage}] 命令异常: {error}"));
            }
        }
    }
    last
}

fn run_once(program: &str, args: &[String], timeout_secs: u64) -> Result<CommandOutcome, String> {
    let mut command = Command::new(program);
    command.args(args);
    command.stdout(Stdio::null());
    command.stderr(Stdio::piped());
    system::hide_console(&mut command);
    let mut child = command.spawn().map_err(|error| error.to_string())?;

    let mut stderr_pipe = child.stderr.take();
    let stderr_handle = std::thread::spawn(move || {
        let mut buffer = Vec::new();
        if let Some(pipe) = stderr_pipe.as_mut() {
            let _ = pipe.read_to_end(&mut buffer);
        }
        buffer
    });

    let deadline = Instant::now() + Duration::from_secs(timeout_secs.max(10));
    let mut timed_out = false;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) => {}
            Err(error) => return Err(error.to_string()),
        }
        if Instant::now() >= deadline {
            timed_out = true;
            let _ = child.kill();
            let _ = child.wait();
            break None;
        }
        std::thread::sleep(Duration::from_millis(50));
    };

    let stderr_bytes = stderr_handle.join().unwrap_or_default();
    Ok(CommandOutcome {
        code: status.and_then(|value| value.code()),
        stderr: String::from_utf8_lossy(&stderr_bytes).into_owned(),
        timed_out,
    })
}

/// 与 `safe_replace_file()` 等价：优先原子替换，失败回退「复制 + 删除」。
pub fn safe_replace_file(src: &str, dst: &str) -> bool {
    let src_path = Path::new(src);
    if !src_path.exists() {
        return false;
    }
    if Path::new(dst).exists() {
        let _ = std::fs::remove_file(dst);
    }
    if std::fs::rename(src_path, dst).is_ok() {
        return true;
    }
    match std::fs::copy(src_path, dst) {
        Ok(_) => std::fs::remove_file(src_path).is_ok(),
        Err(_) => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn fps_parsing_handles_fraction_and_garbage() {
        assert_eq!(parse_fps(Some(&json!("30000/1001"))), 30000.0 / 1001.0);
        assert_eq!(parse_fps(Some(&json!("25/1"))), 25.0);
        assert_eq!(parse_fps(Some(&json!("0/0"))), 0.0);
        assert_eq!(parse_fps(Some(&json!("N/A"))), 0.0);
        assert_eq!(parse_fps(Some(&json!("30"))), 30.0);
        assert_eq!(parse_fps(Some(&json!(24.5))), 24.5);
        assert_eq!(parse_fps(None), 0.0);
    }

    #[test]
    fn safe_int_accepts_string_numbers() {
        assert_eq!(safe_int(Some(&json!("1920"))), 1920);
        assert_eq!(safe_int(Some(&json!("12.9"))), 12);
        assert_eq!(safe_int(Some(&json!(1080))), 1080);
        assert_eq!(safe_int(None), 0);
        assert_eq!(safe_int(Some(&json!("N/A"))), 0);
    }

    #[test]
    fn missing_ffprobe_returns_none_instead_of_panicking() {
        assert!(probe_video_meta("C:/no/such/file.mp4", None).is_none());
    }

    #[test]
    fn safe_replace_moves_file() {
        let dir = std::env::temp_dir().join("itv-safe-replace");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let src = dir.join("a.txt");
        let dst = dir.join("b.txt");
        std::fs::write(&src, b"hello").unwrap();
        assert!(safe_replace_file(
            &src.to_string_lossy(),
            &dst.to_string_lossy()
        ));
        assert!(!src.exists());
        assert_eq!(std::fs::read(&dst).unwrap(), b"hello");
        let _ = std::fs::remove_dir_all(&dir);
    }
}
/// 用 `ffmpeg -i` 的 stderr 解析媒体信息。
///
/// 只在没有 ffprobe 时使用（安装包只带 ffmpeg）。解析的是人类可读输出，形如：
/// ```text
///   Duration: 00:00:02.02, start: 0.000000, bitrate: 195 kb/s
///   Stream #0:0: Video: h264 (High), yuv420p, 320x240 [SAR 1:1 DAR 4:3], 10 fps, 10 tbr
/// ```
/// 参数拿不到时对应字段为 0，调用方按「未知」处理（与 ffprobe 缺失时的语义一致）。
fn probe_via_ffmpeg(video_path: &str) -> Option<VideoMeta> {
    let ffmpeg = crate::engine::system::resolve_ffmpeg(None)?;
    let mut command = Command::new(&ffmpeg);
    command.args(["-hide_banner", "-i", video_path]);
    crate::engine::system::hide_console(&mut command);
    // ffmpeg 没有输出文件时会以非零码退出，这里只看 stderr
    let output = command.output().ok()?;
    let text = String::from_utf8_lossy(&output.stderr);

    let mut width = 0i64;
    let mut height = 0i64;
    let mut fps = 0.0f64;
    let mut duration = 0.0f64;

    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("Duration:") {
            if let Some(value) = trimmed.split("Duration:").nth(1) {
                duration = parse_clock(value.trim());
            }
        }
        if trimmed.contains("Video:") && width == 0 {
            // 形如 `320x240` 的尺寸
            for token in trimmed.split([',', ' ']) {
                let token = token.trim();
                if let Some((left, right)) = token.split_once('x') {
                    if let (Ok(w), Ok(h)) = (left.parse::<i64>(), right.parse::<i64>()) {
                        if w > 0 && h > 0 && w <= 16384 && h <= 16384 {
                            width = w;
                            height = h;
                            break;
                        }
                    }
                }
            }
            // 形如 `10 fps`
            let parts: Vec<&str> = trimmed.split_whitespace().collect();
            for (index, part) in parts.iter().enumerate() {
                if *part == "fps" && index > 0 {
                    if let Ok(value) = parts[index - 1].parse::<f64>() {
                        fps = value;
                        break;
                    }
                }
            }
        }
    }

    if width <= 0 || height <= 0 {
        return None;
    }
    let frames = if fps > 0.0 && duration > 0.0 {
        (fps * duration).round() as i64
    } else {
        0
    };
    Some(VideoMeta {
        width,
        height,
        fps,
        frames,
        duration,
    })
}

/// 解析 `HH:MM:SS.ss`。
fn parse_clock(value: &str) -> f64 {
    let head = value.split(',').next().unwrap_or("").trim();
    let parts: Vec<&str> = head.split(':').collect();
    if parts.len() != 3 {
        return 0.0;
    }
    let hours: f64 = parts[0].trim().parse().unwrap_or(0.0);
    let minutes: f64 = parts[1].trim().parse().unwrap_or(0.0);
    let seconds: f64 = parts[2].trim().parse().unwrap_or(0.0);
    hours * 3600.0 + minutes * 60.0 + seconds
}

#[cfg(test)]
mod fallback_probe_tests {
    use super::*;

    #[test]
    fn clock_parsing() {
        assert!((parse_clock("00:00:02.02, start: 0.0") - 2.02).abs() < 1e-6);
        assert!((parse_clock("01:02:03.50") - 3723.5).abs() < 1e-6);
        assert_eq!(parse_clock("garbage"), 0.0);
    }

    #[test]
    fn ffmpeg_fallback_probes_a_real_file() {
        let fixture = std::env::var("ITV_FALLBACK_PROBE");
        let Ok(path) = fixture else { return };
        let meta = probe_via_ffmpeg(&path).expect("应能解析出尺寸");
        assert!(meta.width > 0 && meta.height > 0, "{meta:?}");
    }
}
