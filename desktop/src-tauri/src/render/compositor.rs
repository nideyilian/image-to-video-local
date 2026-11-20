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
use super::color;
use super::effect_params;
use super::effects;
use super::encoder::{self, EncodeOptions};
use super::pixels::{self, BgrFrame};
use super::frame_script;
use super::plan;
use super::transitions;

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

    // ---- 帧脚本：先算出「整段视频有哪些帧」 ----
    //
    // 这一段是纯计算，不碰像素。它回答「第 N 帧用第几张图、什么特效参数、
    // 还是某段转场的第几步」。把它抽出来的好处：
    // - 帧数算错时能单独定位（`frame_script` 的测试跑一次就知道）
    // - 改帧策略不用碰下面的像素代码
    // - 两边独立演进，改一边不会悄悄弄坏另一边
    // 调色：对整段一致（不随时间变化），所以在循环外算一次。
    // 全 0 参数时 `apply` 直接返回 None，零开销、不改变既有输出。
    let grade = color::ColorGrade::from_config(config);

    // 转场专属参数（与特效同一条通路）
    let transition_extra = effect_params::resolve_from_config(config, &options.transition_type);

    let script = frame_script::build_script(&frame_script::ScriptOptions {
        total_images: options.images.len(),
        frames_per_img: frame_plan.frames_per_img,
        display_frames_per_img: frame_plan.display_frames_per_img,
        last_img_frames: frame_plan.last_img_frames,
        transition_frames,
        fps: options.fps,
        effect_enabled,
        effect_type: effect_type.clone(),
        effect_intensity: intensity,
        effect_speed: speed,
        // 专属参数：按当前特效 ID 从配置里取，缺的用声明默认值。
        // 这一步统一在这里做，实现代码只管用 `params.param("键", 默认)`。
        effect_extra: effect_params::resolve_from_config(config, &effect_type),
        transition_active: transition_frames > 0 && options.transition_type != "无转场",
    });
    debug_assert_eq!(
        script.len() as i64,
        total_frames,
        "帧脚本长度与帧计划不一致 —— 说明两边算帧数的规则跑偏了"
    );

    // 排查用：把帧脚本的结构转储出来，供两个版本对比「帧序有没有变」。
    // 正常渲染零开销（只在环境变量存在时写入）。
    // 用法：ITV_DUMP_SCRIPT=路径，与 `ITV_BATCH_CONFIG` 配合。
    if let Ok(path) = std::env::var("ITV_DUMP_SCRIPT") {
        let lines: Vec<String> = script
            .steps
            .iter()
            .map(|step| match &step.source {
                frame_script::FrameSource::Still {
                    image_index,
                    frame_in_image,
                } => format!("{}\tStill\t{image_index}\t{frame_in_image}", step.index),
                frame_script::FrameSource::Effect {
                    image_index,
                    frame_in_image,
                    params,
                } => format!(
                    "{}\tEffect\t{image_index}\t{frame_in_image}\t{:.6}",
                    step.index, params.time_sec
                ),
                frame_script::FrameSource::Transition {
                    image_index,
                    step: in_step,
                    total,
                } => format!("{}\tTransition\t{image_index}\t{in_step}\t{total}", step.index),
            })
            .collect();
        let _ = std::fs::write(path, lines.join("\n"));
    }

    let mut last_good: Option<BgrFrame> = None;
    let mut written: i64 = 0;
    // 缓存当前解码好的图，避免同一张图被重复解码
    let mut loaded_index: Option<usize> = None;
    let mut loaded_frame: Option<BgrFrame> = None;
    let mut next_loaded_index: Option<usize> = None;
    let mut next_loaded_frame: Option<BgrFrame> = None;

    // ---- 按脚本执行 ----
    //
    // 逐帧走脚本。转场是一批帧一起算的（`generate_frames` 一次产出整段），
    // 所以遇到 `Transition` 时把该段一次性算完写完，然后跳到下一段。
    let mut cursor = 0usize;
    while cursor < script.steps.len() {
        if hooks.cancelled() {
            session.abort();
            return Err(ComposeError::Cancelled);
        }

        let image_index = script.steps[cursor].source.primary_image();

        // 该图需要时才解码（同图连续帧复用）
        if loaded_index != Some(image_index) {
            hooks.log(&format!(
                "处理图片 {}/{}: {}",
                image_index + 1,
                total_images,
                Path::new(&options.images[image_index])
                    .file_name()
                    .map(|value| value.to_string_lossy().into_owned())
                    .unwrap_or_default()
            ));
            let frame = load_frame(
                &options.images[image_index],
                out_w,
                out_h,
                &options.resize_mode,
            )
            .map(|frame| match decorate.as_mut() {
                Some(decorate) => match decorate(&frame, image_index) {
                    Some(value) => value,
                    None => {
                        hooks.log(&format!(
                            "跟随水印处理失败，使用原帧: {}",
                            options.images[image_index]
                        ));
                        frame
                    }
                },
                None => frame,
            })
            .or_else(|| {
                // 图片加载失败：用上一张成功帧补位，保证总时长严格按设置
                last_good.clone().inspect(|_| {
                    hooks.log(&format!(
                        "图片加载失败，用相邻帧补位保持时长: {}",
                        options.images[image_index]
                    ));
                })
            })
            .ok_or_else(|| ComposeError::FirstImageFailed(options.images[image_index].clone()))?;

            last_good = Some(frame.clone());
            loaded_index = Some(image_index);
            loaded_frame = Some(frame);
        }

        let current = loaded_frame.as_ref().expect("刚解码过，必然存在");

        match &script.steps[cursor].source {
            frame_script::FrameSource::Still { .. } | frame_script::FrameSource::Effect { .. } => {
                // 静态帧 / 特效帧：逐帧算，连续同图帧共享解码结果
                let step = &script.steps[cursor];
                let frame = match &step.source {
                    frame_script::FrameSource::Effect { params, .. } => {
                        effects::apply_single_image_effect(current, params)
                    }
                    _ => current.clone(),
                };
                // 调色放在特效之后：先让画面动起来，再统一色调。
                // 反过来（先调色再特效）会让缩放/旋转把调色边缘一起放大，
                // 出现一圈颜色不同的边框。
                let frame = color::apply(&frame, &grade).unwrap_or(frame);
                write_or_abort(&mut session, &frame, &mut written, total_frames, hooks)?;
                cursor += 1;
            }
            frame_script::FrameSource::Transition { total, .. } => {
                // 转场：一次性把这一段算完
                let next_index = image_index + 1;
                let next_frame = if let (Some(index), Some(frame)) =
                    (next_loaded_index, next_loaded_frame.as_ref())
                {
                    if index == next_index {
                        frame.clone()
                    } else {
                        decode_next(
                            &options.images[next_index],
                            out_w,
                            out_h,
                            &options.resize_mode,
                            &mut decorate,
                            next_index,
                            current,
                            &mut next_loaded_index,
                            &mut next_loaded_frame,
                            hooks,
                        )
                    }
                } else {
                    decode_next(
                        &options.images[next_index],
                        out_w,
                        out_h,
                        &options.resize_mode,
                        &mut decorate,
                        next_index,
                        current,
                        &mut next_loaded_index,
                        &mut next_loaded_frame,
                        hooks,
                    )
                };

                // 转场专属参数：按当前转场 ID 从配置取，缺的用声明默认值。
                // 与特效同一条通路（effect_params），所以「按特效 id 分组存」
                // 的约定对转场也一样成立。
                let frames = transitions::generate_frames(
                    current,
                    &next_frame,
                    transition,
                    *total as usize,
                    &transition_extra,
                );
                for frame in frames {
                    if hooks.cancelled() {
                        session.abort();
                        return Err(ComposeError::Cancelled);
                    }
                    // 转场帧同样要调色，否则转场那段会突然恢复原色
                    let frame = color::apply(&frame, &grade).unwrap_or(frame);
                    write_or_abort(&mut session, &frame, &mut written, total_frames, hooks)?;
                }
                // 转场跑完，下一段一定是下一张图的静态帧。
                // 直接把当前缓存切到下一张，省掉一次「重新解码同一张图」，
                // 也避免 loaded_index 停在旧图上导致后续判断错乱。
                loaded_index = Some(next_index);
                loaded_frame = next_loaded_frame.clone();
                next_loaded_index = None;
                next_loaded_frame = None;
                cursor += *total as usize;
            }
        }
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

/// 解码转场需要的下一张图，并缓存起来供后续复用。
///
/// 加载失败时用当前帧占位（保持时长不跑偏），并把缓存标记为已加载 ——
/// 下一段转场如果还是这张图，就不必再试一次。
#[allow(clippy::too_many_arguments)]
fn decode_next(
    path: &str,
    out_w: u32,
    out_h: u32,
    resize_mode: &str,
    decorate: &mut Option<&mut dyn FnMut(&BgrFrame, usize) -> Option<BgrFrame>>,
    index: usize,
    fallback: &BgrFrame,
    cache_index: &mut Option<usize>,
    cache_frame: &mut Option<BgrFrame>,
    hooks: &mut dyn ComposeHooks,
) -> BgrFrame {
    let frame = load_frame(path, out_w, out_h, resize_mode)
        .map(|frame| match decorate {
            Some(decorate) => decorate(&frame, index).unwrap_or(frame),
            None => frame,
        })
        .unwrap_or_else(|| {
            hooks.log(&format!("下一张图加载失败，用当前帧占位: {path}"));
            fallback.clone()
        });
    *cache_index = Some(index);
    *cache_frame = Some(frame.clone());
    frame
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
/// 收集日志的钩子（对照测试用，便于把渲染日志一起打出来比对）。
#[derive(Default)]
pub struct CollectHooks {
    pub logs: Vec<String>,
    pub last_progress: i64,
}

impl ComposeHooks for CollectHooks {
    fn progress(&mut self, written: i64, total: i64) {
        let percent = if total > 0 { written * 100 / total } else { 0 };
        if percent != self.last_progress {
            self.last_progress = percent;
            self.logs.push(format!("progress {percent}%"));
        }
    }

    fn cancelled(&mut self) -> bool {
        false
    }

    fn log(&mut self, message: &str) {
        self.logs.push(message.to_string());
    }
}
