//! 合成调度，对齐 `src/render/compositor.py` 的 `create_video()`。
//!
//! 这是**上层编排**：按帧计划把「读图 → 缩放 → 跟随水印 → 特效 / 转场」逐帧算出，
//! 再写进 `encoder` 的 ffmpeg 管道；最后交给 `postprocess` 做固定图层/视频水印/BGM。
//!
//! 与 Python 版的结构一一对应：
//! - 静态帧：每张图写 `display_frames_per_img` 帧，最后一张写 `last_img_frames` 帧
//! - 转场帧：夹在两张图之间，帧数取 `transition_frames`
//! - 特效：开启时静态帧逐帧调 `apply_single_image_effect`（替代重复写同一帧）
//! - 图片加载失败：用上一张成功帧补位，保证总时长不变

use std::path::Path;

use super::audio::RenderConfig;
use super::codec;
use super::effects::{self, EffectParams};
use super::encoder::{self, EncodeOptions};
use super::pixels::{self, BgrFrame};
use super::plan;
use super::transitions;
use super::watermark;

/// 合成参数（对应 `create_video()` 的形参）。
#[derive(Debug, Clone)]
pub struct ComposeOptions {
    pub images: Vec<String>,
    pub output_path: String,
    pub duration: f64,
    pub fps: i64,
    pub width: u32,
    pub height: u32,
    pub resize_mode: String,
    pub transition_frames: i64,
    pub transition_type: String,
    pub target_bitrate: i64,
    pub selected_codec: String,
    /// 覆盖配置里的特效类型（None 表示读配置）
    pub effect_override: Option<String>,
}

/// 合成过程中的进度回调与取消判断。
pub trait ComposeHooks {
    fn progress(&mut self, written: i64, total: i64);
    /// 返回 true 表示用户取消
    fn cancelled(&mut self) -> bool;
    fn log(&mut self, message: &str);
}

/// 什么都不做的钩子（测试与直接调用时用）。
pub struct QuietHooks;

impl ComposeHooks for QuietHooks {
    fn progress(&mut self, _written: i64, _total: i64) {}
    fn cancelled(&mut self) -> bool {
        false
    }
    fn log(&mut self, _message: &str) {}
}

#[derive(Debug)]
pub enum ComposeError {
    NoImages,
    FirstImageFailed(String),
    IncompatibleCodec(String),
    Encode(String),
    Cancelled,
}

impl std::fmt::Display for ComposeError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ComposeError::NoImages => write!(formatter, "没有选择图片或输出路径"),
            ComposeError::FirstImageFailed(path) => write!(formatter, "无法加载图片: {path}"),
            ComposeError::IncompatibleCodec(message) => write!(formatter, "{message}"),
            ComposeError::Encode(message) => write!(formatter, "{message}"),
            ComposeError::Cancelled => write!(formatter, "已取消当前视频生成"),
        }
    }
}

impl std::error::Error for ComposeError {}

/// 合成结果。
#[derive(Debug, Clone, PartialEq)]
pub struct ComposeResult {
    pub frames_written: i64,
    pub total_frames: i64,
    pub width: u32,
    pub height: u32,
}

/// 读图并缩放到目标尺寸（对应 `load_processed_frame` 去掉跟随水印那段）。
///
/// 跟随水印（`follow_layers`）需要在像素层做 alpha 合成，属于 `watermark` 模块的
/// 像素部分，这里先留出钩子：`decorate` 会在缩放后、写帧前调用。
pub fn load_frame(
    path: &str,
    width: u32,
    height: u32,
    resize_mode: &str,
) -> Option<BgrFrame> {
    let frame = pixels::read_image_bgr(Path::new(path))?;
    let resized = pixels::resize_image(&frame, width, height, resize_mode);
    Some(pixels::ensure_even_frame(&resized))
}

/// 主合成入口。
///
/// `decorate` 用于「跟随水印」等需要逐图处理的像素操作；
/// 传 `None` 表示不做（与 Python 的 `follow_layers` 为空等价）。
pub fn create_video(
    options: &ComposeOptions,
    config: &dyn RenderConfig,
    ffmpeg: &str,
    hooks: &mut dyn ComposeHooks,
    mut decorate: Option<&mut dyn FnMut(&BgrFrame, usize) -> Option<BgrFrame>>,
) -> Result<ComposeResult, ComposeError> {
    if options.images.is_empty() || options.output_path.is_empty() {
        return Err(ComposeError::NoImages);
    }
    let total_images = options.images.len() as i64;

    // ---- 帧计划 ----
    let frame_plan = plan::compute_video_frame_plan(
        total_images,
        options.duration,
        options.fps,
        options.transition_frames,
        &options.transition_type,
    );
    let total_frames = (total_images - 1) * frame_plan.frames_per_img + frame_plan.last_img_frames;
    let transition_frames = frame_plan.transition_frames;
    hooks.log(&format!(
        "每张图片总时长: {}秒 (静态: {:.2}秒 + 转场: {:.2}秒), 总帧数: {}, 实际视频时长: {:.2}秒",
        options.duration,
        frame_plan.display_frames_per_img as f64 / options.fps as f64,
        transition_frames as f64 / options.fps as f64,
        total_frames,
        total_frames as f64 / options.fps.max(1) as f64
    ));

    // ---- 首图与输出尺寸 ----
    let first = pixels::read_image_bgr(Path::new(&options.images[0]))
        .ok_or_else(|| ComposeError::FirstImageFailed(options.images[0].clone()))?;
    let (out_w, out_h) = if options.resize_mode == "原始尺寸" {
        (first.width, first.height)
    } else {
        (options.width, options.height)
    };
    let (out_w, out_h) = (make_even(out_w), make_even(out_h));

    // ---- 打开编码管道 ----
    let encode_options = EncodeOptions {
        output_path: options.output_path.clone(),
        selected_codec: options.selected_codec.clone(),
        width: out_w as i64,
        height: out_h as i64,
        fps: options.fps,
        target_bitrate: options.target_bitrate,
    };
    let mut session = encoder::EncodeSession::open(&encode_options, ffmpeg).map_err(|error| {
        match error {
            encoder::EncodeError::IncompatibleCodec { selected, extension } => {
                ComposeError::IncompatibleCodec(format!(
                    "编码器与容器不兼容: codec={selected}, ext={extension}"
                ))
            }
            other => ComposeError::Encode(other.to_string()),
        }
    })?;
    hooks.log(&format!(
        "统一编排：主渲染使用FFmpeg，编码器={}，目标码率={} kbps",
        session.strict_codec, options.target_bitrate
    ));

    // ---- 特效判定 ----
    let effect_type = options
        .effect_override
        .clone()
        .filter(|name| !name.is_empty())
        .unwrap_or_else(|| config.text_of("video_effect_type", "无特效"));
    let effect_enabled = config.bool_of("use_video_effect", false) && effect_type != "无特效";
    let intensity = config.f64_of("video_effect_intensity", 100.0);
    let speed = config.f64_of("video_effect_speed", 1.0);
    let transition = transitions::parse(&options.transition_type);

    let mut last_good: Option<BgrFrame> = None;
    let mut written: i64 = 0;

    for (image_index, image_path) in options.images.iter().enumerate() {
        if hooks.cancelled() {
            session.abort();
            return Err(ComposeError::Cancelled);
        }
        hooks.log(&format!(
            "处理图片 {}/{}: {}",
            image_index + 1,
            total_images,
            Path::new(image_path)
                .file_name()
                .map(|value| value.to_string_lossy().into_owned())
                .unwrap_or_default()
        ));

        let mut current = match load_frame(image_path, out_w, out_h, &options.resize_mode) {
            Some(frame) => {
                let decorated = match decorate.as_mut() {
                    Some(decorate) => match decorate(&frame, image_index) {
                        Some(value) => value,
                        None => {
                            hooks.log(&format!("跟随水印处理失败，使用原帧: {image_path}"));
                            frame
                        }
                    },
                    None => frame,
                };
                Some(decorated)
            }
            None => None,
        }
        .or_else(|| {
            // 图片加载失败：用上一张成功帧补位，保证总时长严格按设置
            last_good.clone().inspect(|_| {
                hooks.log(&format!("图片加载失败，用相邻帧补位保持时长: {image_path}"));
            })
        })
        .ok_or_else(|| ComposeError::FirstImageFailed(image_path.clone()))?;

        last_good = Some(current.clone());

        let is_last = image_index as i64 == total_images - 1;
        let static_frames = if is_last {
            frame_plan.last_img_frames
        } else {
            frame_plan.display_frames_per_img
        };

        if effect_enabled && static_frames > 0 {
            // 逐帧算特效（代替重复写同一帧）
            let effect_frames = static_frames.max(1);
            let duration_sec = (effect_frames as f64 / options.fps.max(1) as f64).max(0.001);
            for frame_index in 0..effect_frames {
                if hooks.cancelled() {
                    session.abort();
                    return Err(ComposeError::Cancelled);
                }
                let params = EffectParams {
                    effect_type: effect_type.clone(),
                    time_sec: frame_index as f64 / options.fps.max(1) as f64,
                    duration_sec,
                    intensity,
                    speed,
                };
                let frame = effects::apply_single_image_effect(&current, &params);
                write_or_abort(&mut session, &frame, &mut written, total_frames, hooks)?;
            }
        } else {
            for _ in 0..static_frames.max(0) {
                if hooks.cancelled() {
                    session.abort();
                    return Err(ComposeError::Cancelled);
                }
                write_or_abort(&mut session, &current, &mut written, total_frames, hooks)?;
            }
        }

        // 转场（最后一张之后没有）
        if !is_last && transition_frames > 0 && options.transition_type != "无转场" {
            let next_path = &options.images[image_index + 1];
            let next_frame = load_frame(next_path, out_w, out_h, &options.resize_mode)
                .map(|frame| match decorate.as_mut() {
                    Some(decorate) => decorate(&frame, image_index + 1).unwrap_or(frame),
                    None => frame,
                })
                .unwrap_or_else(|| {
                    hooks.log(&format!("下一张图加载失败，用当前帧占位: {next_path}"));
                    current.clone()
                });
            let frames = transitions::generate_frames(
                &current,
                &next_frame,
                transition,
                transition_frames as usize,
            );
            for frame in frames {
                if hooks.cancelled() {
                    session.abort();
                    return Err(ComposeError::Cancelled);
                }
                write_or_abort(&mut session, &frame, &mut written, total_frames, hooks)?;
            }
        }
        // 避免未使用告警：current 在转场后不再需要
        let _ = &mut current;
    }

    hooks.progress(written, total_frames);
    let frames_written = session
        .finish()
        .map_err(|error| ComposeError::Encode(error.to_string()))?;
    hooks.log(&format!("FFmpeg管道写入完成，共输出 {frames_written} 帧"));

    if !encoder::output_is_valid(&options.output_path) {
        return Err(ComposeError::Encode(format!(
            "FFmpeg管道编码结束但输出文件无效: {}",
            options.output_path
        )));
    }
    hooks.log(&format!("视频文件创建成功: {}", options.output_path));

    Ok(ComposeResult {
        frames_written,
        total_frames,
        width: out_w,
        height: out_h,
    })
}

fn make_even(value: u32) -> u32 {
    if value % 2 == 0 {
        value
    } else {
        value + 1
    }
}

fn write_or_abort(
    session: &mut encoder::EncodeSession,
    frame: &BgrFrame,
    written: &mut i64,
    total: i64,
    hooks: &mut dyn ComposeHooks,
) -> Result<(), ComposeError> {
    session
        .write_frame(&frame.data)
        .map_err(|error| ComposeError::Encode(error.to_string()))?;
    *written += 1;
    hooks.progress(*written, total);
    Ok(())
}

/// 完整导出：合成 + 后处理（对应 `create_video()` 里「主渲染成功 → 后处理」那一段）。
pub fn create_video_and_postprocess(
    options: &ComposeOptions,
    config: &dyn RenderConfig,
    ffmpeg: &str,
    ffprobe: Option<&Path>,
    watermark_position: &str,
    hooks: &mut dyn ComposeHooks,
    decorate: Option<&mut dyn FnMut(&BgrFrame, usize) -> Option<BgrFrame>>,
) -> Result<ComposeResult, ComposeError> {
    let result = create_video(options, config, ffmpeg, hooks, decorate)?;
    // 后处理失败不视为致命（Python 版也是「回退兼容链路，不中断任务」）
    let ok = super::postprocess::run_unified_postprocess(
        &options.output_path,
        watermark_position,
        config,
        ffmpeg,
        ffprobe,
        |message| hooks.log(message),
    );
    if !ok {
        hooks.log("统一后处理失败，回退到兼容链路（不中断任务）");
    }
    Ok(result)
}

/// 从配置里读出合成所需的默认参数。
pub fn options_from_config(
    config: &dyn RenderConfig,
    images: Vec<String>,
    output_path: String,
) -> ComposeOptions {
    ComposeOptions {
        images,
        output_path,
        duration: config.f64_of("duration", 2.0),
        fps: config.i64_of("fps", 30),
        width: config.i64_of("width", 1080).max(1) as u32,
        height: config.i64_of("height", 1920).max(1) as u32,
        resize_mode: config.text_of("resize_mode", "适应"),
        transition_frames: config.i64_of("transition_frames", 15),
        transition_type: config.text_of("transition_type", "淡入淡出"),
        target_bitrate: config.i64_of("bitrate", 5000),
        selected_codec: config.text_of("_selected_codec", "XVID"),
        effect_override: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Map, Value};

    struct MapConfig(Map<String, Value>);
    impl RenderConfig for MapConfig {
        fn get(&self, key: &str) -> Option<Value> {
            self.0.get(key).cloned()
        }
    }

    fn config(pairs: Vec<(&str, Value)>) -> MapConfig {
        let mut map = Map::new();
        for (key, value) in pairs {
            map.insert(key.to_string(), value);
        }
        MapConfig(map)
    }

    #[test]
    fn even_dimensions_are_rounded_up() {
        assert_eq!(make_even(1080), 1080);
        assert_eq!(make_even(1081), 1082);
        assert_eq!(make_even(1), 2);
    }

    #[test]
    fn options_read_from_config_with_defaults() {
        let options = options_from_config(&config(vec![]), vec!["a.png".into()], "out.mp4".into());
        assert_eq!(options.duration, 2.0);
        assert_eq!(options.fps, 30);
        assert_eq!(options.width, 1080);
        assert_eq!(options.height, 1920);
        assert_eq!(options.resize_mode, "适应");
        assert_eq!(options.transition_frames, 15);
        assert_eq!(options.transition_type, "淡入淡出");
        assert_eq!(options.target_bitrate, 5000);
        assert_eq!(options.selected_codec, "XVID");
    }

    #[test]
    fn options_override_every_field() {
        let options = options_from_config(
            &config(vec![
                ("duration", json!(1.5)),
                ("fps", json!(25)),
                ("width", json!(640)),
                ("height", json!(360)),
                ("resize_mode", json!("拉伸")),
                ("transition_frames", json!(6)),
                ("transition_type", json!("左右滑动")),
                ("bitrate", json!(2000)),
                ("_selected_codec", json!("H264")),
            ]),
            vec!["a.png".into()],
            "out.mp4".into(),
        );
        assert_eq!(options.duration, 1.5);
        assert_eq!(options.fps, 25);
        assert_eq!(options.width, 640);
        assert_eq!(options.height, 360);
        assert_eq!(options.resize_mode, "拉伸");
        assert_eq!(options.transition_frames, 6);
        assert_eq!(options.transition_type, "左右滑动");
        assert_eq!(options.target_bitrate, 2000);
        assert_eq!(options.selected_codec, "H264");
    }

    #[test]
    fn empty_images_is_rejected() {
        let options = options_from_config(&config(vec![]), Vec::new(), "out.mp4".into());
        let mut hooks = QuietHooks;
        let error = create_video(&options, &config(vec![]), "ffmpeg", &mut hooks, None)
            .expect_err("应报错");
        assert!(matches!(error, ComposeError::NoImages));
    }

    #[test]
    fn missing_first_image_is_reported() {
        let options = ComposeOptions {
            images: vec!["C:/definitely/missing.png".into()],
            output_path: std::env::temp_dir()
                .join(format!("itv-compose-missing-{}.mp4", std::process::id()))
                .to_string_lossy()
                .into_owned(),
            duration: 1.0,
            fps: 30,
            width: 320,
            height: 240,
            resize_mode: "适应".into(),
            transition_frames: 0,
            transition_type: "无转场".into(),
            target_bitrate: 1000,
            selected_codec: "H264".into(),
            effect_override: None,
        };
        let mut hooks = QuietHooks;
        let error = create_video(&options, &config(vec![]), "ffmpeg", &mut hooks, None)
            .expect_err("应报错");
        assert!(matches!(error, ComposeError::FirstImageFailed(_)));
    }
}