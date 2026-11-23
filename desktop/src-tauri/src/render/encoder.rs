//! 视频编码管道，对齐 `src/render/encoder.py` 的 `create_video_with_ffmpeg()`。
//!
//! 结构与 Python 版一致：开一个 `ffmpeg -f rawvideo -pix_fmt bgr24 -i -` 子进程，
//! 逐帧把 BGR 像素写进它的 stdin，由 ffmpeg 编码。
//!
//! 这里刻意**不**做像素运算 —— 帧从哪来（读图缩放、转场、特效）由上层 `pixels` 决定，
//! 本模块只负责「把给定尺寸的 BGR 帧写进管道并按计划计数」。

use std::io::Write;
use std::process::{Child, Command, Stdio};

use super::codec;

/// 管道编码参数。
#[derive(Debug, Clone)]
pub struct EncodeOptions {
    pub output_path: String,
    /// 用户选择的编码器名（`H264` / `XVID` / `MJPG` / `mp4v`）。
    pub selected_codec: String,
    pub width: i64,
    pub height: i64,
    pub fps: i64,
    pub target_bitrate: i64,
}

/// 组装 ffmpeg 命令行。独立成函数是为了能对参数**逐字对照** Python 版。
pub fn build_encode_args(options: &EncodeOptions, strict_codec: &str) -> Vec<String> {
    let mut args: Vec<String> = vec![
        "-y".into(),
        "-f".into(),
        "rawvideo".into(),
        "-pix_fmt".into(),
        "bgr24".into(),
        "-s".into(),
        format!("{}x{}", options.width, options.height),
        "-r".into(),
        options.fps.to_string(),
        "-i".into(),
        "-".into(),
        "-an".into(),
        "-c:v".into(),
        strict_codec.to_string(),
        "-b:v".into(),
        format!("{}k", options.target_bitrate),
        "-maxrate".into(),
        format!("{}k", (options.target_bitrate as f64 * 1.1) as i64),
        "-bufsize".into(),
        format!("{}k", (options.target_bitrate as f64 * 1.5) as i64),
        "-pix_fmt".into(),
        "yuv420p".into(),
        "-r".into(),
        options.fps.to_string(),
    ];
    if strict_codec == "libx264" {
        args.extend(["-preset".into(), "medium".into()]);
    }
    if let Some(muxer) = codec::muxer_for_output(&options.output_path) {
        args.extend(["-f".into(), muxer.to_string()]);
    }
    args.push(options.output_path.clone());
    args
}

/// 编码器不可用时返回的错误（与 Python 的 `return False` + 日志等价）。
#[derive(Debug)]
pub enum EncodeError {
    /// 用户选的编码器与容器不兼容。
    IncompatibleCodec { selected: String, extension: String },
    /// 无法启动 ffmpeg。
    Spawn(String),
    /// 写管道失败（多为 ffmpeg 提前退出）。
    Pipe(String),
    /// ffmpeg 退出码非 0。
    Failed { code: Option<i32>, stderr: String },
    /// 输出文件不存在或过小。
    InvalidOutput(String),
}

impl std::fmt::Display for EncodeError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EncodeError::IncompatibleCodec {
                selected,
                extension,
            } => write!(
                formatter,
                "编码器与容器不兼容: codec={selected}, ext={extension}"
            ),
            EncodeError::Spawn(message) => write!(formatter, "无法启动 ffmpeg: {message}"),
            EncodeError::Pipe(message) => write!(formatter, "FFmpeg管道写入失败: {message}"),
            EncodeError::Failed { code, stderr } => {
                write!(formatter, "FFmpeg管道编码失败，错误码: {code:?}，{stderr}")
            }
            EncodeError::InvalidOutput(path) => {
                write!(formatter, "FFmpeg管道编码结束但输出文件无效: {path}")
            }
        }
    }
}

impl std::error::Error for EncodeError {}

/// 一个正在运行的管道编码会话。
pub struct EncodeSession {
    child: Child,
    pub strict_codec: &'static str,
    pub frames_written: i64,
}

impl EncodeSession {
    /// 打开管道。编码器与容器不兼容时立即报错（与 Python 一致，不静默回退）。
    pub fn open(options: &EncodeOptions, ffmpeg: &str) -> Result<EncodeSession, EncodeError> {
        let strict_codec = codec::strict_vcodec(&options.output_path, &options.selected_codec)
            .ok_or_else(|| EncodeError::IncompatibleCodec {
                selected: options.selected_codec.clone(),
                extension: codec::output_extension(&options.output_path),
            })?;
        let args = build_encode_args(options, strict_codec);
        let mut command = Command::new(ffmpeg);
        command.args(&args);
        command.stdin(Stdio::piped());
        command.stdout(Stdio::null());
        command.stderr(Stdio::piped());
        crate::engine::system::hide_console(&mut command);
        let child = command
            .spawn()
            .map_err(|error| EncodeError::Spawn(error.to_string()))?;
        Ok(EncodeSession {
            child,
            strict_codec,
            frames_written: 0,
        })
    }

    /// 写一帧 BGR 数据。调用方保证 `bytes.len() == width * height * 3`。
    pub fn write_frame(&mut self, bytes: &[u8]) -> Result<(), EncodeError> {
        let stdin = self
            .child
            .stdin
            .as_mut()
            .ok_or_else(|| EncodeError::Pipe("stdin 已关闭".to_string()))?;
        stdin
            .write_all(bytes)
            .map_err(|error| EncodeError::Pipe(error.to_string()))?;
        self.frames_written += 1;
        Ok(())
    }

    /// 关闭管道并等待 ffmpeg 结束，返回最终帧数。
    pub fn finish(mut self) -> Result<i64, EncodeError> {
        // 先 drop stdin 让 ffmpeg 收到 EOF
        self.child.stdin.take();
        let output = self
            .child
            .wait_with_output()
            .map_err(|error| EncodeError::Pipe(error.to_string()))?;
        if !output.status.success() {
            return Err(EncodeError::Failed {
                code: output.status.code(),
                stderr: String::from_utf8_lossy(&output.stderr)
                    .chars()
                    .take(300)
                    .collect(),
            });
        }
        Ok(self.frames_written)
    }

    /// 中途放弃：关掉 stdin 并杀掉进程（对应 Python 的 `terminate()`）。
    pub fn abort(mut self) {
        self.child.stdin.take();
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// 输出文件有效（存在且 > 1000 字节），与 Python 的判据一致。
pub fn output_is_valid(path: &str) -> bool {
    std::fs::metadata(path)
        .map(|meta| meta.len() > 1000)
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn options(output: &str, codec: &str) -> EncodeOptions {
        EncodeOptions {
            output_path: output.to_string(),
            selected_codec: codec.to_string(),
            width: 1920,
            height: 1080,
            fps: 30,
            target_bitrate: 5000,
        }
    }

    #[test]
    fn args_match_the_python_pipeline_verbatim() {
        let args = build_encode_args(&options("C:/out/v.mp4", "H264"), "libx264");
        let expected = vec![
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            "1920x1080",
            "-r",
            "30",
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-b:v",
            "5000k",
            "-maxrate",
            "5500k",
            "-bufsize",
            "7500k",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-preset",
            "medium",
            "-f",
            "mp4",
            "C:/out/v.mp4",
        ];
        assert_eq!(args, expected);
    }

    #[test]
    fn non_x264_omits_preset() {
        let args = build_encode_args(&options("C:/out/v.avi", "XVID"), "libxvid");
        assert!(!args.iter().any(|item| item == "-preset"));
        assert!(args.windows(2).any(|pair| pair == ["-f", "avi"]));
    }

    #[test]
    fn unknown_container_omits_muxer_and_keeps_output_last() {
        let args = build_encode_args(&options("C:/out/v.webm", "H264"), "libx264");
        assert!(!args.windows(2).any(|pair| pair == ["-f", "matroska"]));
        assert_eq!(args.last().unwrap(), "C:/out/v.webm");
    }

    #[test]
    fn bitrate_derivatives_truncate_like_python_int() {
        let mut opts = options("a.mp4", "H264");
        opts.target_bitrate = 3333;
        let args = build_encode_args(&opts, "libx264");
        let index = args.iter().position(|item| item == "-maxrate").unwrap();
        // 3333 * 1.1 = 3666.3 → int() 截断为 3666
        assert_eq!(args[index + 1], "3666k");
        let index = args.iter().position(|item| item == "-bufsize").unwrap();
        // 3333 * 1.5 = 4999.5 → int() 截断为 4999
        assert_eq!(args[index + 1], "4999k");
    }

    #[test]
    fn incompatible_codec_is_rejected_before_spawning() {
        let opts = options("C:/out/v.mp4", "XVID");
        match EncodeSession::open(&opts, "ffmpeg") {
            Err(EncodeError::IncompatibleCodec {
                selected,
                extension,
            }) => {
                assert_eq!(selected, "XVID");
                assert_eq!(extension, ".mp4");
            }
            other => panic!(
                "应报编码器不兼容，实际 {:?}",
                other.err().map(|e| e.to_string())
            ),
        }
    }

    #[test]
    fn invalid_output_detection() {
        let dir = std::env::temp_dir().join(format!("itv-encode-valid-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let small = dir.join("small.mp4");
        std::fs::write(&small, b"x").unwrap();
        assert!(!output_is_valid(&small.to_string_lossy()));
        let big = dir.join("big.mp4");
        std::fs::write(&big, vec![0u8; 2000]).unwrap();
        assert!(output_is_valid(&big.to_string_lossy()));
        assert!(!output_is_valid("C:/definitely/missing.mp4"));
    }
}
