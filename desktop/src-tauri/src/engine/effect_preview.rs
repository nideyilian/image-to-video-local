//! 特效预览帧（对齐 `src/engine/effect_preview.py` 的 `render_effect_preview`）。
//!
//! **能力边界由 `render/catalog.rs` 决定**：目录里声明了的特效/转场就一定能画，
//! 判定在 [`supports_effect`] / [`supports_transition`]，且必须在读图之前完成。
//!
//! 已支持：图片缩放（适应/拉伸）+ 两类水印 + 全部 46 种特效 + 33 种转场 + 调色，
//! 顺序与导出完全一致（水印 → 转场/特效 → 调色 → 视频水印）。
//!
//! ⚠️ 这条路径和导出（`render/compositor.rs`）是**两套独立实现**。任何作用于画面的
//! 改动必须两边一起改，否则会出现「导出对、预览不动」——用户看到的就是「功能没做」。

use std::path::PathBuf;

use serde_json::{json, Map, Value};

use super::preview_random;
use crate::engine::paths;
use crate::engine::scan;
use crate::render::effects;
use crate::render::pixels;
use crate::render::transitions;

/// 某个特效能不能画 —— 判据是**声明式目录**，不是另抄一份清单。
///
/// ⚠️ 这里原本是一份手写的 `SUPPORTED_EFFECTS: [&str; 44]` 数组。
/// 2026-11-20 加「色差分离 / 色调分离 / 半调网点」时改全了 catalog、effects.rs、
/// constants.ts，**唯独漏了这个数组** —— 后果是这三个特效一选中，预览接口就返回
/// `handled: false`，而 sidecar 早已移除，前端只能报「本地引擎不支持
/// preview_effect_frame」，预览区空白。导出完全正常，所以特别难被发现。
///
/// 现在改为直接查 `catalog::EFFECTS`：`catalog_parity` 已保证「目录里的每一条都有
/// 实现」，于是「目录里有的 = 能画的」这个等式不再需要人工维护。
/// 加特效只改 catalog + effects.rs 两处。
fn supports_effect(name: &str) -> bool {
    name == "无特效"
        || crate::render::catalog::EFFECTS
            .iter()
            .any(|item| item.id == name || item.aliases.contains(&name))
}

/// 转场同上：目录里声明了就等于能画。
fn supports_transition(name: &str) -> bool {
    name == "无转场"
        || crate::render::catalog::TRANSITIONS
            .iter()
            .any(|item| item.id == name || item.aliases.contains(&name))
}

fn text(config: &Map<String, Value>, key: &str, default: &str) -> String {
    config
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or(default)
        .to_string()
}

fn number(config: &Map<String, Value>, key: &str, default: f64) -> f64 {
    match config.get(key) {
        Some(Value::Number(value)) => value.as_f64().unwrap_or(default),
        Some(Value::String(value)) => value.trim().parse().unwrap_or(default),
        _ => default,
    }
}

fn flag(config: &Map<String, Value>, key: &str, default: bool) -> bool {
    match config.get(key) {
        Some(Value::Bool(value)) => *value,
        Some(Value::Number(value)) => value.as_f64().unwrap_or(0.0) != 0.0,
        Some(Value::String(value)) => !value.is_empty() && value != "0",
        _ => default,
    }
}

/// `_target_size`：先从配置读宽高（分辨率预设优先），再按上限等比缩放并取偶数。
fn target_size(config: &Map<String, Value>, max_width: i64, max_height: i64) -> (u32, u32) {
    let mut width = number(config, "width", 0.0) as i64;
    let mut height = number(config, "height", 0.0) as i64;

    // 预设形如 "1080x1920"，允许 x/X/× 与大写
    let preset = text(config, "resolution_preset", "");
    if let Some((left, right)) = split_preset(&preset) {
        width = left;
        height = right;
    }
    if width <= 0 || height <= 0 {
        width = 1280;
        height = 720;
    }
    let scale = (1.0_f64)
        .min(max_width as f64 / width as f64)
        .min(max_height as f64 / height as f64);
    let scaled_w = ((width as f64 * scale) as i64).max(2) / 2 * 2;
    let scaled_h = ((height as f64 * scale) as i64).max(2) / 2 * 2;
    (scaled_w as u32, scaled_h as u32)
}

/// 从预设串里抠出宽高，支持 `1080x1920` / `1080X1920` / `1080×1920`。
fn split_preset(preset: &str) -> Option<(i64, i64)> {
    let normalized = preset.replace(['×', 'X'], "x");
    let (left, right) = normalized.split_once('x')?;
    let width: i64 = left.trim().parse().ok()?;
    let height: i64 = right.trim().parse().ok()?;
    if width > 0 && height > 0 {
        Some((width, height))
    } else {
        None
    }
}

/// `preview_phase_timing`：静态段与转场段的时长分配。
///
/// 与导出器的帧分配一致 —— 转场最多 15 帧、且不超过总帧数的 1/3；
/// 静态段不足半秒时优先保证静态段。
pub fn phase_timing(config: &Map<String, Value>, duration_sec: f64, has_next: bool) -> (f64, f64) {
    let fps = number(config, "fps", 30.0).max(1.0) as i64;
    let total_frames = (duration_sec.max(0.001) * fps as f64) as i64;
    let total_frames = total_frames.max(1);

    let mut transition_frames = 0i64;
    if has_next && flag(config, "use_transition", false) {
        transition_frames = 15.min(total_frames / 3);
        let display_frames = total_frames - transition_frames;
        let minimum_display_frames = total_frames.min((fps / 2).max(1));
        if display_frames < minimum_display_frames {
            transition_frames = (total_frames - minimum_display_frames).max(0);
        }
    }
    let display_frames = total_frames - transition_frames;
    (
        display_frames as f64 / fps as f64,
        transition_frames as f64 / fps as f64,
    )
}

/// 本次请求能否由 Rust 完整处理；不能就返回原因（给报错信息用）。
///
/// 能力缺口只剩「名字根本不在目录里」（旧预设、拼错的字）。判定点统一放在这里，
/// 将来真需要回落某个能力时也从这里下手。
fn unhandled_reason(
    // 视频水印与图片水印都已迁移，暂时不需要读 config；
    // 保留参数是为了将来加新能力时不用改所有调用点。
    _config: &Map<String, Value>,
    effect_type: &str,
    effect_enabled: bool,
    transition_type: &str,
    transition_will_run: bool,
) -> Option<&'static str> {
    // 视频水印与图片水印都已迁移，这里不再有需要回落的能力缺口。
    // 保留这个函数是为了将来加新能力时有统一的判定点。
    if effect_enabled && !supports_effect(effect_type) {
        return Some("该特效尚未实现");
    }
    if transition_will_run && !supports_transition(transition_type) {
        return Some("该转场尚未实现");
    }
    None
}

/// 渲染一帧特效预览。
///
/// 返回 `Ok(None)` 表示「这一帧不归 Rust 管，请回落旧引擎」；
/// `Ok(Some(value))` 是正常结果；`Err` 是真正的错误（如图片读不出来）。
pub fn render_frame(params: &Map<String, Value>) -> Result<Option<Value>, String> {
    let raw_config = params.get("config").cloned().unwrap_or(Value::Null);
    let normalized = crate::engine::config::normalize_config(Some(&raw_config));
    let config = normalized.as_object().cloned().unwrap_or_default();

    let source = match params.get("path").and_then(Value::as_str) {
        Some(value) if !value.trim().is_empty() => value.trim().to_string(),
        _ => {
            let input_dir = text(&config, "input_dir", "");
            scan::scan_images(&input_dir)
                .first()
                .cloned()
                .unwrap_or_default()
        }
    };
    let source_path = PathBuf::from(&source);
    if !source_path.is_file() {
        return Err("没有可用于特效预览的图片".to_string());
    }

    let max_width = params
        .get("max_width")
        .and_then(Value::as_i64)
        .unwrap_or(960)
        .clamp(64, 1920);
    let max_height = params
        .get("max_height")
        .and_then(Value::as_i64)
        .unwrap_or(540)
        .clamp(64, 1080);
    let (width, height) = target_size(&config, max_width, max_height);

    let time_sec = params
        .get("time_sec")
        .and_then(Value::as_f64)
        .unwrap_or(0.0)
        .max(0.0);
    let preview_sequence = params
        .get("preview_sequence")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        .max(0);
    let duration_sec = number(&config, "duration", 1.0).max(0.001);

    // 特效名：随机特效按 preview_sequence 洗牌取一个（与 Python 的 preview_choice 一致）
    let mut effect_type = text(&config, "video_effect_type", "无特效");
    if flag(&config, "random_video_effect", false) {
        let enabled_effects: Vec<String> = config
            .get("enabled_video_effects")
            .and_then(Value::as_array)
            .map(|values| {
                values
                    .iter()
                    .filter_map(|value| value.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default();
        if !enabled_effects.is_empty() {
            effect_type = if preview_sequence > 0 {
                preview_random::preview_choice(&enabled_effects, preview_sequence, "effect")
                    .unwrap_or_else(|| enabled_effects[0].clone())
            } else {
                enabled_effects[0].clone()
            };
        }
    }
    let effect_enabled = flag(&config, "use_video_effect", false) && effect_type != "无特效";

    // 第二张图（转场用）
    let next_source = params
        .get("next_path")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_string();
    let next_path = if next_source.is_empty() {
        None
    } else {
        let path = PathBuf::from(&next_source);
        if path.is_file()
            && paths::display(&paths::absolute(&path))
                != paths::display(&paths::absolute(&source_path))
        {
            Some(path)
        } else {
            None
        }
    };

    let (static_duration, transition_duration) =
        phase_timing(&config, duration_sec, next_path.is_some());

    // 转场名：随机转场同样按 sequence 选（提前算出来才能判断是否可接管）
    let mut transition_type = text(&config, "transition_type", "淡入淡出");
    if flag(&config, "random_transition", false) {
        let enabled: Vec<String> = config
            .get("enabled_transitions")
            .and_then(Value::as_array)
            .map(|values| {
                values
                    .iter()
                    .filter_map(|value| value.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default();
        if !enabled.is_empty() {
            transition_type = if preview_sequence > 0 {
                preview_random::preview_choice(&enabled, preview_sequence, "transition")
                    .unwrap_or_else(|| enabled[0].clone())
            } else {
                enabled[0].clone()
            };
        }
    }
    let transition_will_run =
        next_path.is_some() && flag(&config, "use_transition", false) && transition_duration > 0.0;

    if let Some(reason) = unhandled_reason(
        &config,
        &effect_type,
        effect_enabled,
        &transition_type,
        transition_will_run,
    ) {
        // 名字不在目录里（旧预设 / 拼错）：明确报错比半吊子出图好，
        // 也比前端那句「本地引擎不支持 preview_effect_frame」好懂。
        return Err(reason.to_string());
    }

    // ---- 开始渲染 ----
    // 图片水印图层：与 Python 一致，先贴在两张原图上，再做转场/特效
    let layers_value = config
        .get("watermark_layers")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let use_image_watermark =
        flag(&config, "use_image_watermark", false) && !layers_value.is_empty();
    // 「换一组看看」用 sequence 当种子，保证同一组参数结果稳定
    let mut pick = move |count: usize| -> usize {
        if count == 0 {
            return 0;
        }
        (preview_sequence as usize + count) % count
    };
    let prepared_layers = if use_image_watermark {
        crate::render::watermark::prepare_image_layers(&layers_value, &mut pick)
    } else {
        Vec::new()
    };

    let keep_aspect = flag(&config, "keep_aspect_ratio", true);
    let resize_mode = if keep_aspect { "适应" } else { "拉伸" };
    let Some(mut image) = pixels::read_image_bgr(&source_path) else {
        return Err(format!(
            "无法读取预览图片: {}",
            source_path
                .file_name()
                .map(|value| value.to_string_lossy().into_owned())
                .unwrap_or_default()
        ));
    };
    image = pixels::resize_image(&image, width, height, resize_mode);

    let mut next_image = None;
    if let Some(path) = &next_path {
        if let Some(frame) = pixels::read_image_bgr(path) {
            next_image = Some(pixels::resize_image(&frame, width, height, resize_mode));
        }
    }

    // 贴图片水印（对两张图都贴，转场时不会「跳」）
    for layer in &prepared_layers {
        image = crate::render::watermark::apply_image_layer(&image, layer, &mut pick);
        if let Some(second) = next_image.as_mut() {
            *second = crate::render::watermark::apply_image_layer(second, layer, &mut pick);
        }
    }

    // Python 的 `transition_type` 取的是 `_apply_transition_preview` 的**返回值**：
    // 没有第二张图 / 未开转场 / 转场时长 0 时，它会被改写成「无转场」。
    // 直接读 config 会在这里多显示一个转场名（第一版就这样，对照测试抓出来的）。
    let mut transition_active = false;
    let shown_transition = if transition_will_run {
        transition_type.clone()
    } else {
        "无转场".to_string()
    };
    // 转场专属参数：界面**也给转场生成了控件**（Inspector 的「当前转场」下面
    // 就是同一套 EffectParamControls），导出侧在 compositor.rs 里按 `transition_type`
    // 解析后交给 generate_frames。预览这里原来写死 `Default::default()`，
    // 结果拖「百叶窗条数 / 棋盘格边长 / 波浪振幅」预览纹丝不动 —— 又一个
    // 「导出对、预览不动」。所以这里必须走同一条 effect_params 通路。
    let transition_extra = crate::render::effect_params::resolve_from_config(
        &crate::render::audio::JsonConfig(config.clone()),
        &transition_type,
    );

    if transition_will_run {
        if let Some(second) = &next_image {
            if time_sec >= static_duration {
                let progress = ((time_sec - static_duration) / transition_duration).clamp(0.0, 1.0);
                let fps = number(&config, "fps", 30.0).max(1.0) as i64;
                let frame_count =
                    ((transition_duration * fps as f64).round() as i64).max(1) as usize;
                let kind = transitions::parse(&transition_type);
                let frames = transitions::generate_frames(
                    &image,
                    second,
                    kind,
                    frame_count,
                    &transition_extra,
                );
                if !frames.is_empty() {
                    let index = ((progress * frames.len() as f64) as usize).min(frames.len() - 1);
                    image = frames[index].clone();
                    transition_active = true;
                }
            }
        }
    }

    if effect_enabled && !transition_active {
        // 专属参数必须一起带上：否则界面调了「色阶数」之类，预览毫无变化，
        // 用户会以为功能坏了（这正是之前的一个真实误判）。
        let executor = crate::render::audio::JsonConfig(config.clone());
        let effect_params = effects::EffectParams {
            extra: crate::render::effect_params::resolve_from_config(&executor, &effect_type),
            effect_type: effect_type.clone(),
            time_sec,
            duration_sec: static_duration,
            intensity: number(&config, "video_effect_intensity", 100.0),
            speed: number(&config, "video_effect_speed", 1.0),
        };
        image = effects::apply_single_image_effect(&image, &effect_params);
    }

    // ---- 调色（在特效之后，与正式渲染的顺序一致）----
    //
    // ⚠️ 这一道之前漏了：导出有调色、预览没有。用户拖滑杆时预览画面
    // 纹丝不动，自然会判断「调色不生效」。导出路径是对的，错的是预览。
    {
        let executor = crate::render::audio::JsonConfig(config.clone());
        let grade = crate::render::color::ColorGrade::from_config(&executor);
        if let Some(graded) = crate::render::color::apply(&image, &grade) {
            image = graded;
        }
    }

    // ---- 视频水印（在特效之后，与 Python 的调用顺序一致）----
    let mut video_watermark_name = String::new();
    if flag(&config, "use_watermark", false) {
        let path_value = text(&config, "watermark_path", "");
        if !path_value.trim().is_empty() {
            if let Some(path) =
                crate::render::watermark::resolve_video_watermark(&path_value, preview_sequence)
            {
                let match_method = text(&config, "watermark_match_method", "循环");
                let ffmpeg = crate::engine::system::resolve_ffmpeg(None);
                let frame = ffmpeg.as_ref().and_then(|ffmpeg_path| {
                    crate::render::watermark::read_video_watermark_frame(
                        &path,
                        time_sec,
                        duration_sec,
                        &match_method,
                        ffmpeg_path,
                    )
                });
                if let Some(watermark_frame) = frame {
                    let blend_mode = text(&config, "watermark_blend_mode", "正常");
                    let layer = crate::render::watermark::ImageLayer {
                        images: vec![watermark_frame],
                        position: text(&config, "watermark_position", "中心"),
                        size_mode: text(&config, "watermark_size_mode", "自适应覆盖"),
                        scale: number(&config, "watermark_scale", 100.0),
                        blend_mode: blend_mode.clone(),
                        opacity: crate::render::watermark::video_watermark_alpha(&blend_mode),
                    };
                    image = crate::render::watermark::apply_image_layer(&image, &layer, &mut pick);
                    video_watermark_name = path
                        .file_name()
                        .map(|value| value.to_string_lossy().into_owned())
                        .unwrap_or_default();
                }
            }
        }
    }

    // ---- 落盘 ----
    // 缓存键带 `rs-` 前缀：Rust 的 JPEG 编码器与 cv2 不同，字节必然不同，
    // 共用 Python 的键会出现「键相同、内容不同」的脏缓存。
    // ⚠️ 缓存键必须包含**所有影响像素的输入**。
    //
    // 之前漏了调色与特效专属参数：调了滑杆，键没变，于是直接复用旧图 ——
    // 表现就是「拖了没反应」，比报错更难查（因为导出是对的）。
    // 这里把画面相关的配置整体序列化进键，宁可键长一点，也不要脏缓存。
    let grade = crate::render::color::ColorGrade::from_config(&crate::render::audio::JsonConfig(
        config.clone(),
    ));
    let effect_extra = crate::render::effect_params::resolve_from_config(
        &crate::render::audio::JsonConfig(config.clone()),
        &effect_type,
    );
    let grade_key = format!(
        "{}:{}:{}:{}",
        grade.brightness, grade.contrast, grade.saturation, grade.temperature
    );
    let extra_key = serde_json::to_string(&effect_extra).unwrap_or_default();
    // 转场专属参数同样影响像素，漏了就会出现「拖转场滑杆预览不动」。
    let transition_key = serde_json::to_string(&transition_extra).unwrap_or_default();
    let cache_key = format!(
        "rs-effect-preview:{}:{}:{}x{}:{}:{}:{time_sec}:{preview_sequence}:{grade_key}:{extra_key}:{transition_key}",
        paths::display(&paths::absolute(&source_path)),
        effect_type,
        width,
        height,
        transition_type,
        static_duration
    );
    let dir = std::env::temp_dir()
        .join("image-to-video-engine")
        .join("effect-previews");
    std::fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    let preview_path = dir.join(format!(
        "rs-{}.jpg",
        crate::engine::hash::sha1_hex(cache_key.as_bytes())
    ));
    if !preview_path.is_file() {
        let rgb = image.to_rgb();
        let mut buffer: Vec<u8> = Vec::new();
        let mut encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut buffer, 90);
        encoder
            .encode(
                rgb.as_raw(),
                rgb.width(),
                rgb.height(),
                image::ExtendedColorType::Rgb8,
            )
            .map_err(|error| format!("特效预览编码失败：{error}"))?;
        std::fs::write(&preview_path, &buffer).map_err(|error| error.to_string())?;
    }

    Ok(Some(json!({
        "source": paths::display(&paths::absolute(&source_path)),
        "preview_path": paths::display(&paths::absolute(&preview_path)),
        "width": width,
        "height": height,
        "effect_type": if effect_enabled { effect_type } else { "无特效".to_string() },
        "transition_type": shown_transition,
        "transition_active": transition_active,
        "time_sec": time_sec,
        "static_duration": static_duration,
        "transition_duration": transition_duration,
        "video_watermark_name": video_watermark_name,
    })))
}

/// `effect_preview_animation`：渲染一组动画帧（素材库展示用）。
///
/// Python 侧是循环调用 `render_effect_preview`，且**显式关掉两类水印**，
/// 所以这里天然落在支持范围内；只要有一帧不归 Rust 管，整组回落。
pub fn render_animation(params: &Map<String, Value>) -> Result<Option<Value>, String> {
    let kind = params
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_string();
    if kind != "effect" && kind != "transition" {
        return Err("动画类型必须是 effect 或 transition".to_string());
    }
    let name = params
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_string();
    if name.is_empty() {
        return Err("缺少效果名称".to_string());
    }
    let frame_count = params
        .get("frames")
        .and_then(Value::as_i64)
        .unwrap_or(8)
        .clamp(3, 24);
    let width = params
        .get("width")
        .and_then(Value::as_i64)
        .unwrap_or(192)
        .clamp(96, 480);
    let height = params
        .get("height")
        .and_then(Value::as_i64)
        .unwrap_or(108)
        .clamp(54, 270);

    // 名字必须在声明式目录里（= 一定已实现）。不满足时明确报错，而不是
    // 返回 `Ok(None)`：sidecar 已移除，「不归我管」没有下一站，只会变成前端
    // 那句看不懂的「本地引擎不支持 effect_preview_animation」。
    if kind == "effect" && !supports_effect(&name) {
        return Err(format!("特效「{name}」尚未实现"));
    }
    if kind == "transition" && !supports_transition(&name) {
        return Err(format!("转场「{name}」尚未实现"));
    }

    let assets = super::effect_assets::ensure_assets()?;
    let source_a = assets
        .get("source_a")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let source_b = assets
        .get("source_b")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();

    // 与 Python 的 config.update({...}) 一一对应
    let mut config = crate::engine::config::default_config();
    {
        let object = config.as_object_mut().expect("默认配置应为对象");
        object.insert("duration".into(), json!(1.0));
        object.insert("fps".into(), json!(30));
        object.insert(
            "resolution_preset".into(),
            json!(format!("{width}x{height}")),
        );
        object.insert("width".into(), json!(width));
        object.insert("height".into(), json!(height));
        object.insert("use_transition".into(), json!(kind == "transition"));
        object.insert(
            "transition_type".into(),
            json!(if kind == "transition" {
                name.clone()
            } else {
                "淡入淡出".to_string()
            }),
        );
        object.insert("random_transition".into(), json!(false));
        object.insert("use_video_effect".into(), json!(kind == "effect"));
        object.insert(
            "video_effect_type".into(),
            json!(if kind == "effect" {
                name.clone()
            } else {
                "无特效".to_string()
            }),
        );
        object.insert("random_video_effect".into(), json!(false));
        object.insert("use_watermark".into(), json!(false));
        object.insert("use_image_watermark".into(), json!(false));
        object.insert("use_bgm".into(), json!(false));
    }
    let config_object = config.as_object().cloned().unwrap_or_default();
    let (static_duration, transition_duration) =
        phase_timing(&config_object, 1.0, kind == "transition");

    let mut frame_paths: Vec<String> = Vec::new();
    for index in 0..frame_count {
        let ratio = index as f64 / (frame_count.max(2) - 1).max(1) as f64;
        let time_sec = if kind == "transition" && transition_duration > 0.0 {
            static_duration + transition_duration * ratio
        } else {
            static_duration * ratio
        };
        let mut request = Map::new();
        request.insert("path".into(), json!(source_a));
        request.insert(
            "next_path".into(),
            json!(if kind == "transition" {
                source_b.clone()
            } else {
                String::new()
            }),
        );
        request.insert("config".into(), config.clone());
        request.insert("time_sec".into(), json!(time_sec));
        request.insert("max_width".into(), json!(width));
        request.insert("max_height".into(), json!(height));
        let Some(result) = render_frame(&request)? else {
            // 有一帧不归 Rust 管 → 整组交回旧引擎
            return Ok(None);
        };
        frame_paths.push(
            result
                .get("preview_path")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
        );
    }

    Ok(Some(json!({
        "kind": kind,
        "name": name,
        "frames": frame_paths,
        "width": width,
        "height": height,
        "assets": assets,
    })))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config_with(pairs: &[(&str, Value)]) -> Map<String, Value> {
        let mut map = Map::new();
        for (key, value) in pairs {
            map.insert(key.to_string(), value.clone());
        }
        map
    }

    /// **预览必须和导出一致地应用调色。**
    ///
    /// 这条测试来自一个真实误判：导出路径有调色、预览路径漏了，用户
    /// 拖调色滑杆时预览画面纹丝不动，自然判断「调色不生效」。导出其实
    /// 是对的，错的是预览 —— 而这种错只有对比两边的像素才抓得到。
    #[test]
    fn preview_applies_color_grade() {
        use crate::render::color::{self, ColorGrade};
        use crate::render::pixels::BgrFrame;

        let mut frame = BgrFrame::new(32, 32);
        for y in 0..32 {
            for x in 0..32 {
                frame.set_pixel(x, y, [100, 120, 140]);
            }
        }

        // 未调色：apply 返回 None（零开销路径）
        assert!(color::apply(&frame, &ColorGrade::default()).is_none());

        // 调色后必须有变化，且亮度方向正确
        let bright = ColorGrade {
            brightness: 80.0,
            ..Default::default()
        };
        let out = color::apply(&frame, &bright).expect("调色非恒等时必须返回新帧");
        let before: f64 = frame.data.iter().map(|v| *v as f64).sum::<f64>();
        let after: f64 = out.data.iter().map(|v| *v as f64).sum::<f64>();
        assert!(
            after > before,
            "亮度 +80 应该让画面变亮：{before} → {after}"
        );
    }

    /// **缓存键必须随调色参数变化。**
    ///
    /// 预览图按缓存键落盘复用。键里不带调色，就会出现：拖了滑杆 → 后端
    /// 算了新图 → 但缓存键没变 → 直接返回旧图。用户看到的就是「完全不动」，
    /// 而且没有任何报错。这是本次「还是不动」的第二个真凶。
    #[test]
    fn preview_cache_key_includes_color_grade() {
        // 构造两个只有调色不同的配置，序列化后必须不同
        let base = config_with(&[("video_effect_type", json!("无特效"))]);
        let mut warm = base.clone();
        warm.insert("color_temperature".into(), json!(60));
        let mut cold = base.clone();
        cold.insert("color_temperature".into(), json!(-60));

        let key_of = |config: &Map<String, Value>| {
            let grade = crate::render::color::ColorGrade::from_config(
                &crate::render::audio::JsonConfig(config.clone()),
            );
            format!(
                "{}:{}:{}:{}",
                grade.brightness, grade.contrast, grade.saturation, grade.temperature
            )
        };

        assert_ne!(
            key_of(&warm),
            key_of(&cold),
            "调色不同的两个配置产生了相同的缓存键 —— 预览会复用旧图，表现为「拖了不动」"
        );
    }

    /// 预览读到的调色参数必须与配置一致（防止字段名写错导致永远是 0）。
    #[test]
    fn preview_reads_color_fields_from_config() {
        let config = config_with(&[
            ("color_brightness", json!(35)),
            ("color_saturation", json!(-60)),
            ("color_contrast", json!(20)),
            ("color_temperature", json!(-15)),
        ]);
        let executor = crate::render::audio::JsonConfig(config.clone());
        let grade = crate::render::color::ColorGrade::from_config(&executor);
        assert_eq!(grade.brightness, 35.0);
        assert_eq!(grade.saturation, -60.0);
        assert_eq!(grade.contrast, 20.0);
        assert_eq!(grade.temperature, -15.0);
    }

    #[test]
    fn preset_parsing_accepts_all_separators() {
        assert_eq!(split_preset("1080x1920"), Some((1080, 1920)));
        assert_eq!(split_preset("1080X1920"), Some((1080, 1920)));
        assert_eq!(split_preset("1080×1920"), Some((1080, 1920)));
        assert_eq!(split_preset("abc"), None);
        assert_eq!(split_preset("0x100"), None);
    }

    #[test]
    fn target_size_keeps_even_numbers_and_shrinks_to_max() {
        let config = config_with(&[
            ("resolution_preset", json!("1920x1080")),
            ("width", json!(1920)),
            ("height", json!(1080)),
        ]);
        assert_eq!(target_size(&config, 960, 540), (960, 540));
        // 放大不会被放大：上限比原图大时保持原尺寸
        assert_eq!(target_size(&config, 4000, 4000), (1920, 1080));
        // 奇数会被抹成偶数
        let odd = config_with(&[("resolution_preset", json!("641x481"))]);
        assert_eq!(target_size(&odd, 4000, 4000), (640, 480));
    }

    #[test]
    fn target_size_falls_back_to_1280x720() {
        let config = Map::new();
        assert_eq!(target_size(&config, 4000, 4000), (1280, 720));
    }

    #[test]
    fn phase_timing_caps_transition_frames() {
        // 1 秒 30fps = 30 帧，转场上限 min(15, 30/3)=10 帧
        let config = config_with(&[("fps", json!(30)), ("use_transition", json!(true))]);
        let (static_d, trans_d) = phase_timing(&config, 1.0, true);
        assert!((static_d - 20.0 / 30.0).abs() < 1e-9, "static={static_d}");
        assert!((trans_d - 10.0 / 30.0).abs() < 1e-9, "trans={trans_d}");
    }

    #[test]
    fn phase_timing_without_next_image_has_no_transition() {
        let config = config_with(&[("fps", json!(30)), ("use_transition", json!(true))]);
        let (static_d, trans_d) = phase_timing(&config, 1.0, false);
        assert!((static_d - 1.0).abs() < 1e-9);
        assert_eq!(trans_d, 0.0);
    }

    #[test]
    fn unsupported_effect_is_declined() {
        let config = Map::new();
        let reason = unhandled_reason(&config, "旋转扭曲", true, "淡入淡出", false);
        assert_eq!(reason, Some("该特效尚未实现"));
    }

    #[test]
    fn unsupported_transition_is_declined_only_when_it_runs() {
        let config = Map::new();
        // 转场不会生效时不拦
        assert_eq!(
            unhandled_reason(&config, "无特效", false, "旋涡", false),
            None
        );
        assert_eq!(
            unhandled_reason(&config, "无特效", false, "旋涡", true),
            Some("该转场尚未实现")
        );
    }

    #[test]
    fn video_watermark_declines() {
        let config = config_with(&[("use_watermark", json!(true))]);
        // 路径不存在时不算「要用水印」（与 Python 的 `video_watermark is not None` 一致）
        assert_eq!(
            unhandled_reason(&config, "无特效", false, "淡入淡出", false),
            None
        );
    }

    #[test]
    fn image_watermark_layers_are_supported_now() {
        // 图片水印已迁移，不再因此回落（只有视频水印还留在旧引擎）
        let config = config_with(&[
            ("use_image_watermark", json!(true)),
            ("watermark_layers", json!([{ "path": "C:/wm.png" }])),
        ]);
        assert_eq!(
            unhandled_reason(&config, "无特效", false, "淡入淡出", false),
            None
        );
    }

    #[test]
    fn supported_effect_is_accepted() {
        let config = Map::new();
        assert_eq!(
            unhandled_reason(&config, "旋转呼吸", true, "淡入淡出", false),
            None
        );
    }

    /// **目录里声明的每个特效都必须能预览。**
    ///
    /// 2026-11-20 的真实事故：`SUPPORTED_EFFECTS` 是手写数组，新增「色差分离 /
    /// 色调分离 / 半调网点」时它没跟着改，于是这三个特效一选中，预览接口返回
    /// `handled: false`，前端抛「本地引擎不支持 preview_effect_frame」——
    /// 而导出完全正常，看起来就像「功能没做」。这条测试就是那次事故的守门员：
    /// 只要加特效时漏了预览，它立刻红。
    #[test]
    fn every_catalog_effect_is_previewable() {
        for item in crate::render::catalog::EFFECTS {
            assert!(
                supports_effect(item.id),
                "目录里的特效「{}」不能预览 —— 用户在界面上选中它只会得到一句报错",
                item.id
            );
            for alias in item.aliases {
                assert!(
                    supports_effect(alias),
                    "特效别名「{alias}」不能预览（旧预设里可能存的是它）"
                );
            }
        }
    }

    #[test]
    fn every_catalog_transition_is_previewable() {
        for item in crate::render::catalog::TRANSITIONS {
            assert!(
                supports_transition(item.id),
                "目录里的转场「{}」不能预览",
                item.id
            );
            for alias in item.aliases {
                assert!(supports_transition(alias), "转场别名「{alias}」不能预览");
            }
        }
    }

    /// 三个「逐像素」新特效点名钉死 —— 它们就是被漏掉的那三个。
    #[test]
    fn newly_added_per_pixel_effects_are_previewable() {
        let config = Map::new();
        for name in ["色差分离", "色调分离", "半调网点", "灵魂出窍"] {
            assert_eq!(
                unhandled_reason(&config, name, true, "淡入淡出", false),
                None,
                "「{name}」必须能预览"
            );
        }
    }

    /// **转场专属参数必须真的进预览。**
    ///
    /// 界面给「当前转场」也生成了滑杆（Inspector 的 EffectParamControls 对特效和
    /// 转场是同一套），但预览里原来写死 `Default::default()`：拖动百叶窗条数、
    /// 波浪振幅时画面纹丝不动，导出却有变化 —— 和调色那次是同一类错。
    /// 这里用真实图片跑一遍 `render_frame`：只改振幅，画面必须变。
    #[test]
    fn preview_applies_transition_params() {
        let dir = std::env::temp_dir().join(format!(
            "itv-preview-transition-params-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&dir).expect("建临时目录");
        let probe = |name: &str, offset: u8| -> String {
            let path = dir.join(name);
            let mut img = image::RgbImage::new(96, 54);
            for (x, y, pixel) in img.enumerate_pixels_mut() {
                *pixel = image::Rgb([(x * 2) as u8 ^ offset, (y * 4) as u8, ((x + y) * 2) as u8]);
            }
            img.save(&path).expect("写测试图");
            path.to_string_lossy().into_owned()
        };
        let first = probe("a.png", 0);
        let second = probe("b.png", 0x5a);

        let render = |amplitude: f64| -> Vec<u8> {
            let params = json!({
                "path": first,
                "next_path": second,
                "config": {
                    "resolution_preset": "320x180",
                    "duration": 1.0,
                    "fps": 30,
                    "use_video_effect": false,
                    "video_effect_type": "无特效",
                    "use_transition": true,
                    "transition_type": "波浪",
                    "random_transition": false,
                    "effect_params": { "波浪": { "amplitude": amplitude } },
                },
                // 落在转场区间内（static≈0.667s，转场 0.333s）
                "time_sec": 0.8,
                "preview_sequence": 0,
                "max_width": 320,
                "max_height": 180,
            });
            let object = params.as_object().cloned().expect("参数应是对象");
            let result = render_frame(&object)
                .expect("预览应成功")
                .expect("应返回结果");
            let path = result
                .get("preview_path")
                .and_then(Value::as_str)
                .expect("要有 preview_path")
                .to_string();
            std::fs::read(path).expect("读预览图")
        };

        let weak = render(2.0);
        let strong = render(150.0);
        assert_ne!(
            weak, strong,
            "振幅 2 与 150 渲染出了完全相同的图 —— 转场参数没进预览（或没进缓存键）"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }
}
