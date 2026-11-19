//! 后处理：固定图层 / 视频水印 / BGM 尽量一次 ffmpeg 完成。
//!
//! 对齐 `src/render/postprocess.py` 的 `run_unified_postprocess_ffmpeg()`。
//!
//! 核心是**拼出一条 `filter_complex` 字符串**，这串东西直接决定画面，
//! 所以每个片段都按 Python 的 f-string 逐字符复刻（含 `:.3f` / `:.6f` 的小数位）。
//! 滤镜标签名字（`v_wm_1` / `roi_base_1` …）也必须一致 —— 标签不一致会导致
//! ffmpeg 报「找不到标签」，而不是画面差异，属于一眼能发现的错误，但仍照抄。

use std::path::Path;

use serde_json::Value;

use super::audio::{select_bgm_file, RenderConfig};
use super::codec;
use super::imageinfo;
use super::process::{probe_video_meta, run_with_retry, safe_replace_file};
use super::watermark;

/// 视频水印的配置快照（避免在拼接过程中反复取值）。
#[derive(Debug, Clone)]
pub struct WatermarkPlan {
    pub path: String,
    pub match_method: String,
    pub blend_mode: String,
    pub alpha: f64,
    pub target_w: i64,
    pub target_h: i64,
    pub x: i64,
    pub y: i64,
    pub looped: bool,
    /// 「拉伸」模式下的时间拉伸倍率；None 表示不需要拉伸。
    pub stretch_ratio: Option<f64>,
}

/// 一个固定图片图层在 ffmpeg 里的样子。
#[derive(Debug, Clone)]
pub struct FixedLayerPlan {
    pub path: String,
    pub target_w: i64,
    pub target_h: i64,
    pub x: i64,
    pub y: i64,
    pub opacity: f64,
}

/// BGM 在 ffmpeg 里的样子。
#[derive(Debug, Clone)]
pub struct BgmPlan {
    pub path: String,
    pub volume: f64,
    pub looped: bool,
}

/// 后处理要走的那条 ffmpeg 命令。
#[derive(Debug, Clone, PartialEq)]
pub struct PostprocessCommand {
    pub args: Vec<String>,
    pub temp_output: String,
}

/// 统一的 `:.3f` 格式化（Python 的 f-string 行为：四舍六入五成双、负零保留）。
pub fn fixed3(value: f64) -> String {
    format!("{value:.3}")
}

/// 统一的 `:.6f` 格式化。
pub fn fixed6(value: f64) -> String {
    format!("{value:.6}")
}

/// 按配置算出视频水印的完整计划；不需要加视频水印时返回 None。
///
/// 与 `run_unified_postprocess_ffmpeg()` 的前半段等价：探测主视频与水印尺寸，
/// 算叠加几何，决定循环/拉伸与混合模式。
pub fn plan_video_watermark(
    config: &dyn RenderConfig,
    main_width: i64,
    main_height: i64,
    main_duration: f64,
    watermark_position: &str,
    probe: impl Fn(&str) -> Option<(i64, i64, f64)>,
) -> Option<WatermarkPlan> {
    if !config.bool_of("use_watermark", false) {
        return None;
    }
    if config.text_of("watermark_type", "视频") != "视频" {
        return None;
    }
    let base_path = config.get("watermark_path")?.as_str()?.to_string();
    if base_path.is_empty() || !Path::new(&base_path).exists() {
        return None;
    }
    let selected = select_video_watermark_file(config, &base_path)?;
    let (wm_w, wm_h, wm_duration) = probe(&selected)?;

    let match_method = config.text_of("watermark_match_method", "循环");
    let looped = match_method == "循环";
    let size_mode = config.text_of("watermark_size_mode", "自适应覆盖");
    let scale = config.f64_of("watermark_scale", 20.0);
    let geometry = watermark::calc_overlay_geometry(
        main_width,
        main_height,
        wm_w,
        wm_h,
        &size_mode,
        scale,
        watermark_position,
    );
    let blend_mode = config.text_of("watermark_blend_mode", "正常");
    let alpha = watermark::blend_alpha(&blend_mode);
    let stretch_ratio = if match_method == "拉伸" && wm_duration > 0.0 && main_duration > 0.0 {
        Some(main_duration / wm_duration)
    } else {
        None
    };

    Some(WatermarkPlan {
        path: selected,
        match_method,
        blend_mode,
        alpha,
        target_w: geometry.target_w,
        target_h: geometry.target_h,
        x: geometry.x,
        y: geometry.y,
        looped,
        stretch_ratio,
    })
}

/// 与 `select_video_watermark_file()` 等价：单文件直接用，文件夹按视频序号轮转。
pub fn select_video_watermark_file(config: &dyn RenderConfig, base_path: &str) -> Option<String> {
    let mode = config.text_of("watermark_mode", "单文件");
    let path = Path::new(base_path);
    if mode == "文件夹" && path.is_dir() {
        let files = video_files_in_dir(base_path);
        if files.is_empty() {
            return None;
        }
        let index = config.i64_of("_current_video_index", 0).max(0) as usize;
        return Some(files[index % files.len()].clone());
    }
    if path.is_file() {
        return Some(base_path.to_string());
    }
    None
}

const VIDEO_EXTENSIONS: [&str; 14] = [
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm", ".m4v", ".ts", ".mpg", ".mpeg",
    ".3gp", ".rmvb", ".f4v",
];

fn video_files_in_dir(directory: &str) -> Vec<String> {
    let mut files = Vec::new();
    let Ok(entries) = std::fs::read_dir(directory) else {
        return files;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let lower = path
            .file_name()
            .map(|value| value.to_string_lossy().to_lowercase())
            .unwrap_or_default();
        if VIDEO_EXTENSIONS.iter().any(|ext| lower.ends_with(ext)) {
            files.push(path.to_string_lossy().into_owned());
        }
    }
    files.sort();
    files
}

/// 判断是否需要走后处理（固定图层 / 视频水印 / BGM 任一存在）。
pub fn has_postprocess_work(config: &dyn RenderConfig, has_fixed_layers: bool) -> bool {
    if has_fixed_layers {
        return true;
    }
    let has_video_wm = config.bool_of("use_watermark", false)
        && config.text_of("watermark_type", "视频") == "视频"
        && config
            .get("watermark_path")
            .and_then(|value| value.as_str().map(str::to_string))
            .map(|path| !path.is_empty() && Path::new(&path).exists())
            .unwrap_or(false);
    let has_bgm = config.bool_of("use_bgm", false)
        && (!config.string_list("_bgm_files").is_empty()
            || config
                .get("bgm_dir")
                .and_then(|value| value.as_str().map(str::to_string))
                .map(|dir| !dir.is_empty() && Path::new(&dir).exists())
                .unwrap_or(false));
    has_video_wm || has_bgm
}

/// 拼装 `filter_complex` 与参数。与 Python 的 `build_cmd()` 逐字符对齐。
pub fn build_command(
    output_path: &str,
    main_meta: (i64, i64, f64),
    watermark: Option<&WatermarkPlan>,
    fixed_layers: &[FixedLayerPlan],
    bgm: Option<&BgmPlan>,
    strict_codec: &str,
) -> PostprocessCommand {
    let (main_w, main_h, main_duration) = main_meta;
    let mut args: Vec<String> = vec!["-y".into(), "-i".into(), output_path.to_string()];
    let mut filters: Vec<String> = Vec::new();
    let mut current_label = "[0:v]".to_string();
    let mut input_idx = 1;
    let mut audio_label: Option<String> = None;

    // ---- 视频水印 ----
    if let Some(plan) = watermark {
        if plan.looped {
            args.extend(["-stream_loop".into(), "-1".into()]);
        }
        args.extend(["-i".into(), plan.path.clone()]);

        let wm_label = format!("wmv_{input_idx}");
        let mut chain = match plan.stretch_ratio {
            Some(ratio) => format!(
                "[{input_idx}:v]setpts={}*PTS,scale={}:{}",
                fixed6(ratio),
                plan.target_w,
                plan.target_h
            ),
            None => format!(
                "[{input_idx}:v]setpts=PTS-STARTPTS,scale={}:{}",
                plan.target_w, plan.target_h
            ),
        };
        if plan.blend_mode == "正常" {
            chain.push_str(&format!(
                ",format=rgba,colorchannelmixer=aa={}",
                fixed3(plan.alpha)
            ));
        }
        filters.push(format!("{chain}[{wm_label}]"));

        let next_label = format!("v_wm_{input_idx}");
        if plan.blend_mode == "正常" {
            let overlay_mode = if plan.looped {
                "shortest=1"
            } else {
                "eof_action=pass"
            };
            filters.push(format!(
                "{current_label}[{wm_label}]overlay=x={}:y={}:{overlay_mode}[{next_label}]",
                plan.x, plan.y
            ));
            current_label = format!("[{next_label}]");
        } else if let Some(blend_filter) = watermark::ffmpeg_blend_mode(&plan.blend_mode) {
            // 仅在 ROI 区域做 blend，避免整帧色彩空间副作用（修复色偏）
            let x_clip = plan.x.max(0).min(0i64.max(main_w - plan.target_w));
            let y_clip = plan.y.max(0).min(0i64.max(main_h - plan.target_h));
            let roi_base = format!("roi_base_{input_idx}");
            let wm_src = format!("wm_src_{input_idx}");
            let roi_blend = format!("roi_blend_{input_idx}");
            let sync_opts = if plan.looped {
                "shortest=1"
            } else {
                "eof_action=pass:repeatlast=0"
            };
            filters.push(format!(
                "{current_label}crop={}:{}:{x_clip}:{y_clip},format=gbrp[{roi_base}]",
                plan.target_w, plan.target_h
            ));
            filters.push(format!("[{wm_label}]format=gbrp[{wm_src}]"));
            filters.push(format!(
                "[{roi_base}][{wm_src}]blend=all_mode={blend_filter}:all_opacity={}:{sync_opts}[{roi_blend}]",
                fixed3(plan.alpha)
            ));
            let overlay_mode = if plan.looped {
                "shortest=1"
            } else {
                "eof_action=pass"
            };
            filters.push(format!(
                "{current_label}[{roi_blend}]overlay=x={x_clip}:y={y_clip}:{overlay_mode}[{next_label}]"
            ));
            current_label = format!("[{next_label}]");
        }
        input_idx += 1;
    }

    // ---- 固定图片图层 ----
    for (index, layer) in fixed_layers.iter().enumerate() {
        args.extend(["-loop".into(), "1".into(), "-i".into(), layer.path.clone()]);
        let fix_label = format!("fix_{index}");
        filters.push(format!(
            "[{input_idx}:v]format=rgba,colorchannelmixer=aa={},scale={}:{}[{fix_label}]",
            fixed3(layer.opacity),
            layer.target_w,
            layer.target_h
        ));
        let next_label = format!("v_fix_{index}");
        filters.push(format!(
            "{current_label}[{fix_label}]overlay=x={}:y={}:shortest=1[{next_label}]",
            layer.x, layer.y
        ));
        current_label = format!("[{next_label}]");
        input_idx += 1;
    }

    // ---- BGM ----
    if let Some(plan) = bgm {
        if plan.looped {
            args.extend(["-stream_loop".into(), "-1".into()]);
        }
        args.extend(["-i".into(), plan.path.clone()]);
        let label = "bgm_a".to_string();
        filters.push(format!("[{input_idx}:a]volume={}[{label}]", fixed2(plan.volume)));
        audio_label = Some(label);
        input_idx += 1;
    }
    let _ = input_idx;

    let temp_output = codec::temp_output_path(output_path, "pipeline_temp");
    if !filters.is_empty() {
        args.extend(["-filter_complex".into(), filters.join(";")]);
    }
    let video_map = if current_label == "[0:v]" {
        "0:v".to_string()
    } else {
        current_label.clone()
    };
    args.extend(["-map".into(), video_map]);

    if let Some(label) = audio_label.as_ref() {
        let acodec = codec::container_acodec(output_path);
        args.extend([
            "-map".into(),
            format!("[{label}]"),
            "-c:a".into(),
            acodec.to_string(),
            "-b:a".into(),
            "192k".into(),
        ]);
        let looped = bgm.map(|plan| plan.looped).unwrap_or(true);
        if looped {
            args.push("-shortest".into());
        } else if main_duration > 0.0 {
            args.extend(["-t".into(), format!("{main_duration:.3}")]);
        } else {
            args.push("-shortest".into());
        }
    } else {
        args.extend(["-map".into(), "0:a?".into(), "-c:a".into(), "copy".into()]);
    }

    args.extend(["-c:v".into(), strict_codec.to_string()]);
    if strict_codec == "libx264" {
        args.extend(["-preset".into(), "medium".into()]);
    }
    args.extend([
        "-filter_threads".into(),
        "0".into(),
        "-threads".into(),
        "0".into(),
    ]);
    // 后处理保持源视频时基，不强制改写 FPS，避免短视频被拉长
    args.extend(["-pix_fmt".into(), "yuv420p".into()]);
    if let Some(muxer) = codec::muxer_for_output(output_path) {
        args.extend(["-f".into(), muxer.to_string()]);
    }
    args.push(temp_output.clone());

    PostprocessCommand {
        args,
        temp_output,
    }
}

/// 按输出路径算后处理临时文件名（与 `build_command` 内部一致）。
pub fn build_temp_output_path_from(output_path: &str) -> String {
    codec::temp_output_path(output_path, "pipeline_temp")
}

/// Python 的 `:.2f`（用于 BGM 音量）。
pub fn fixed2(value: f64) -> String {
    format!("{value:.2}")
}

/// 执行统一后处理。成功返回 true；需要回退时返回 false（调用方走兼容链路）。
pub fn run_unified_postprocess(
    output_path: &str,
    watermark_position: &str,
    config: &dyn RenderConfig,
    ffmpeg: &str,
    ffprobe: Option<&Path>,
    mut log: impl FnMut(&str),
) -> bool {
    if !Path::new(output_path).is_file() {
        return false;
    }
    let Some(meta) = probe_video_meta(output_path, ffprobe) else {
        return false;
    };
    let main_meta = (meta.width, meta.height, meta.duration);

    let watermark_plan = plan_video_watermark(
        config,
        meta.width,
        meta.height,
        meta.duration,
        watermark_position,
        |path| {
            let size = imageinfo::image_size(Path::new(path));
            let duration = probe_video_meta(path, ffprobe)
                .map(|value| value.duration)
                .unwrap_or(0.0);
            size.map(|value| (value.width, value.height, duration))
        },
    );

    let bgm_path = select_bgm_file(config, None, |len| (len / 2).min(len.saturating_sub(1)));
    let bgm_plan = bgm_path.map(|path| BgmPlan {
        path: path.to_string_lossy().into_owned(),
        volume: config.f64_of("bgm_volume", 0.5),
        looped: config.bool_of("loop_bgm", true),
    });

    let layer_specs = watermark::collect_fixed_layers(config, |_| 0);
    let mut fixed_plans: Vec<FixedLayerPlan> = Vec::new();
    for spec in &layer_specs {
        let Some(size) = imageinfo::image_size(Path::new(&spec.path)) else {
            continue;
        };
        let geometry = watermark::calc_overlay_geometry(
            meta.width,
            meta.height,
            size.width,
            size.height,
            &spec.size_mode,
            spec.scale,
            &spec.position,
        );
        fixed_plans.push(FixedLayerPlan {
            path: spec.path.clone(),
            target_w: geometry.target_w,
            target_h: geometry.target_h,
            x: geometry.x,
            y: geometry.y,
            opacity: spec.opacity,
        });
    }

    if watermark_plan.is_none() && bgm_plan.is_none() && fixed_plans.is_empty() {
        return true;
    }

    // 高级混合模式只要 ffmpeg 支持就走快速路径；不支持则回退（返回 false）
    if let Some(plan) = watermark_plan.as_ref() {
        if plan.blend_mode != "正常" && watermark::ffmpeg_blend_mode(&plan.blend_mode).is_none()
        {
            log(&format!(
                "[PIPELINE][POST-SKIP] 视频水印混合模式={} 暂不支持FFmpeg快速路径，回退OpenCV",
                plan.blend_mode
            ));
            return false;
        }
    }
    if layer_specs.iter().any(|spec| spec.blend_mode != "正常") {
        log("[PIPELINE][POST-SKIP] 检测到图片水印高级混合模式，回退OpenCV以保证混合模式生效");
        return false;
    }

    let selected = config.text_of("_selected_codec", "XVID");
    let Some(strict_codec) = codec::strict_vcodec(output_path, &selected) else {
        log(&format!(
            "[PIPELINE][POST-FAIL] 编码器与容器不兼容: codec={}, ext={}",
            selected,
            codec::output_extension(output_path)
        ));
        return false;
    };

    log(&format!(
        "[PIPELINE][POST-START] 输入={output_path}, 帧数={}, 编排={{固定图层:{}, 视频水印:{}, BGM:{}}}",
        meta.frames,
        fixed_plans.len(),
        watermark_plan.is_some(),
        bgm_plan.is_some()
    ));

    let command = build_command(
        output_path,
        main_meta,
        watermark_plan.as_ref(),
        &fixed_plans,
        bgm_plan.as_ref(),
        strict_codec,
    );
    log(&format!("[PIPELINE][POST-RUN] 尝试编码器={strict_codec}"));
    log(&format!("执行命令: {ffmpeg} {}", command.args.join(" ")));

    let Some(outcome) = run_with_retry(ffmpeg, &command.args, "POST", 900, 2, &mut log) else {
        log("[PIPELINE][POST-FAIL] 无可用执行结果");
        let _ = std::fs::remove_file(&command.temp_output);
        return false;
    };
    if outcome.code != Some(0) {
        log(&format!(
            "[PIPELINE][POST-FAIL] 编码器={strict_codec}, 错误码={:?}, 原因={}",
            outcome.code,
            outcome.stderr.chars().take(200).collect::<String>()
        ));
        let _ = std::fs::remove_file(&command.temp_output);
        return false;
    }
    let size = std::fs::metadata(&command.temp_output)
        .map(|value| value.len())
        .unwrap_or(0);
    if size <= 1000 {
        log("[PIPELINE][POST-FAIL] 输出文件无效");
        let _ = std::fs::remove_file(&command.temp_output);
        return false;
    }
    if !safe_replace_file(&command.temp_output, output_path) {
        log("[PIPELINE][POST-FAIL] 文件替换失败");
        return false;
    }
    log(&format!("[PIPELINE][POST-OK] 输出={output_path}, 编码器={strict_codec}"));
    true
}

/// 供接口层取值：把 JSON 配置转成 `RenderConfig`。
pub fn json_config(value: &Value) -> super::audio::JsonConfig {
    super::audio::JsonConfig::new(value)
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

    fn empty_config() -> MapConfig {
        MapConfig(Map::new())
    }

    fn watermark_plan_normal() -> WatermarkPlan {
        WatermarkPlan {
            path: "C:/wm/wm.mov".into(),
            match_method: "循环".into(),
            blend_mode: "正常".into(),
            alpha: 0.5,
            target_w: 384,
            target_h: 192,
            x: 1526,
            y: 878,
            looped: true,
            stretch_ratio: None,
        }
    }

    #[test]
    fn fixed3_and_fixed6_match_python_formatting() {
        assert_eq!(fixed3(0.5), "0.500");
        assert_eq!(fixed3(0.85), "0.850");
        assert_eq!(fixed3(1.0), "1.000");
        assert_eq!(fixed6(2.0 / 3.0), "0.666667");
        assert_eq!(fixed2(0.5), "0.50");
    }

    #[test]
    fn no_work_means_no_postprocess() {
        let config = empty_config();
        assert!(!has_postprocess_work(&config, false));
        assert!(has_postprocess_work(&config, true));
    }

    #[test]
    fn video_watermark_requires_existing_path() {
        let mut map = Map::new();
        map.insert("use_watermark".into(), json!(true));
        map.insert("watermark_type".into(), json!("视频"));
        map.insert("watermark_path".into(), json!("C:/missing/wm.mov"));
        assert!(!has_postprocess_work(&MapConfig(map), false));

        let dir = std::env::temp_dir().join(format!("itv-wm-exists-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let file = dir.join("wm.mov");
        std::fs::write(&file, b"x").unwrap();
        let mut map = Map::new();
        map.insert("use_watermark".into(), json!(true));
        map.insert("watermark_type".into(), json!("视频"));
        map.insert("watermark_path".into(), json!(file.to_string_lossy()));
        assert!(has_postprocess_work(&MapConfig(map), false));
    }

    #[test]
    fn filter_chain_for_video_watermark_only() {
        let plan = watermark_plan_normal();
        let command = build_command(
            "C:/out/v.mp4",
            (1920, 1080, 5.0),
            Some(&plan),
            &[],
            None,
            "libx264",
        );
        let joined = command.args.join(" ");
        assert!(joined.contains("-stream_loop -1 -i C:/wm/wm.mov"));
        assert!(joined.contains(
            "[1:v]setpts=PTS-STARTPTS,scale=384:192,format=rgba,colorchannelmixer=aa=0.500[wmv_1]"
        ));
        assert!(joined.contains("[0:v][wmv_1]overlay=x=1526:y=878:shortest=1[v_wm_1]"));
        assert!(joined.contains("-map [v_wm_1]"));
        assert!(joined.contains("-c:a copy"));
        assert!(joined.contains("-preset medium"));
        assert!(joined.contains("-f mp4"));
        assert_eq!(command.temp_output, "C:/out/v.pipeline_temp.mp4");
    }

    #[test]
    fn filter_chain_for_blend_mode_uses_roi_crop() {
        let mut plan = watermark_plan_normal();
        plan.blend_mode = "滤色".into();
        plan.alpha = 1.0;
        let command = build_command(
            "C:/out/v.mp4",
            (1920, 1080, 5.0),
            Some(&plan),
            &[],
            None,
            "libx264",
        );
        let joined = command.args.join(" ");
        // ROI 裁剪 + gbrp + blend + 贴回
        assert!(joined.contains("[0:v]crop=384:192:1526:878,format=gbrp[roi_base_1]"));
        assert!(joined.contains("[wmv_1]format=gbrp[wm_src_1]"));
        assert!(joined
            .contains("[roi_base_1][wm_src_1]blend=all_mode=screen:all_opacity=1.000:shortest=1[roi_blend_1]"));
        assert!(joined.contains("[0:v][roi_blend_1]overlay=x=1526:y=878:shortest=1[v_wm_1]"));
        // 混合模式路径不能加水印自己的 alpha 滤镜
        assert!(!joined.contains("colorchannelmixer=aa=1.000["));
    }

    #[test]
    fn roi_is_clipped_to_frame_bounds() {
        let mut plan = watermark_plan_normal();
        plan.blend_mode = "相加".into();
        plan.x = -100;
        plan.y = 2000;
        let command = build_command(
            "C:/out/v.mp4",
            (1920, 1080, 5.0),
            Some(&plan),
            &[],
            None,
            "libx264",
        );
        let joined = command.args.join(" ");
        // x 被夹到 0，y 被夹到 1080-192=888
        assert!(joined.contains("crop=384:192:0:888,format=gbrp"));
        assert!(joined.contains("overlay=x=0:y=888:"));
    }

    #[test]
    fn stretch_mode_sets_pts_multiplier() {
        let mut plan = watermark_plan_normal();
        plan.match_method = "拉伸".into();
        plan.looped = false;
        plan.stretch_ratio = Some(2.5);
        let command = build_command(
            "C:/out/v.mp4",
            (1920, 1080, 5.0),
            Some(&plan),
            &[],
            None,
            "libx264",
        );
        let joined = command.args.join(" ");
        assert!(joined.contains("setpts=2.500000*PTS"));
        // 非循环不加 -stream_loop，overlay 用 eof_action=pass
        assert!(!joined.contains("-stream_loop"));
        assert!(joined.contains("overlay=x=1526:y=878:eof_action=pass"));
    }

    #[test]
    fn fixed_layers_chain_and_input_indexing() {
        let layers = vec![
            FixedLayerPlan {
                path: "C:/wm/a.png".into(),
                target_w: 200,
                target_h: 100,
                x: 10,
                y: 10,
                opacity: 0.8,
            },
            FixedLayerPlan {
                path: "C:/wm/b.png".into(),
                target_w: 300,
                target_h: 150,
                x: 500,
                y: 600,
                opacity: 0.3,
            },
        ];
        let command = build_command(
            "C:/out/v.mp4",
            (1920, 1080, 5.0),
            None,
            &layers,
            None,
            "libx264",
        );
        let joined = command.args.join(" ");
        assert!(joined.contains("-loop 1 -i C:/wm/a.png"));
        assert!(joined.contains("-loop 1 -i C:/wm/b.png"));
        assert!(joined
            .contains("[1:v]format=rgba,colorchannelmixer=aa=0.800,scale=200:100[fix_0]"));
        assert!(joined.contains("[0:v][fix_0]overlay=x=10:y=10:shortest=1[v_fix_0]"));
        assert!(joined
            .contains("[2:v]format=rgba,colorchannelmixer=aa=0.300,scale=300:150[fix_1]"));
        assert!(joined.contains("[v_fix_0][fix_1]overlay=x=500:y=600:shortest=1[v_fix_1]"));
        assert!(joined.contains("-map [v_fix_1]"));
    }

    #[test]
    fn bgm_appends_audio_input_after_video_inputs() {
        let layers = vec![FixedLayerPlan {
            path: "C:/wm/a.png".into(),
            target_w: 200,
            target_h: 100,
            x: 10,
            y: 10,
            opacity: 0.8,
        }];
        let bgm = BgmPlan {
            path: "C:/bgm/song.mp3".into(),
            volume: 0.35,
            looped: true,
        };
        let command = build_command(
            "C:/out/v.mp4",
            (1920, 1080, 5.0),
            None,
            &layers,
            Some(&bgm),
            "libx264",
        );
        let joined = command.args.join(" ");
        // 视频输入 (0) → 图层 (1) → BGM (2)
        assert!(joined.contains("[2:a]volume=0.35[bgm_a]"));
        assert!(joined.contains("-map [bgm_a] -c:a aac -b:a 192k"));
        assert!(joined.contains("-shortest"));
        assert!(!joined.contains("-map 0:a?"));
    }

    #[test]
    fn non_looped_bgm_uses_explicit_duration() {
        let bgm = BgmPlan {
            path: "C:/bgm/song.mp3".into(),
            volume: 0.5,
            looped: false,
        };
        let command = build_command(
            "C:/out/v.mp4",
            (1920, 1080, 7.25),
            None,
            &[],
            Some(&bgm),
            "libx264",
        );
        let joined = command.args.join(" ");
        assert!(!joined.contains("-stream_loop"));
        assert!(joined.contains("-t 7.250"));
        assert!(!joined.contains("-shortest"));
    }

    #[test]
    fn avi_output_uses_mp3_and_avi_muxer() {
        let command = build_command(
            "C:/out/v.avi",
            (1920, 1080, 5.0),
            None,
            &[],
            Some(&BgmPlan {
                path: "C:/bgm/s.mp3".into(),
                volume: 0.5,
                looped: true,
            }),
            "libxvid",
        );
        let joined = command.args.join(" ");
        assert!(joined.contains("-c:a mp3"));
        assert!(joined.contains("-f avi"));
        assert!(!joined.contains("-preset medium"));
    }

    #[test]
    fn unknown_container_has_no_muxer_flag() {
        let command = build_command("C:/out/v.webm", (1920, 1080, 5.0), None, &[], None, "libx264");
        let joined = command.args.join(" ");
        assert!(!joined.contains("-f mp4"));
        assert!(!joined.contains("-f matroska"));
    }

    #[test]
    fn no_filters_still_maps_video_and_copies_audio() {
        let command = build_command("C:/out/v.mp4", (1920, 1080, 5.0), None, &[], None, "libx264");
        let joined = command.args.join(" ");
        assert!(!joined.contains("-filter_complex"));
        assert!(joined.contains("-map 0:v"));
        assert!(joined.contains("-map 0:a? -c:a copy"));
    }

    #[test]
    fn watermark_selection_rotates_in_folder_mode() {
        let dir = std::env::temp_dir().join(format!("itv-wm-folder-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        for name in ["a.mov", "b.mp4", "c.txt"] {
            std::fs::write(dir.join(name), b"x").unwrap();
        }
        let mut map = Map::new();
        map.insert("watermark_mode".into(), json!("文件夹"));
        map.insert("_current_video_index".into(), json!(1));
        let config = MapConfig(map);
        let picked = select_video_watermark_file(&config, &dir.to_string_lossy()).unwrap();
        assert!(picked.ends_with("b.mp4"), "第二个视频应拿第二个水印: {picked}");

        let mut map = Map::new();
        map.insert("watermark_mode".into(), json!("文件夹"));
        map.insert("_current_video_index".into(), json!(4));
        let config = MapConfig(map);
        let picked = select_video_watermark_file(&config, &dir.to_string_lossy()).unwrap();
        assert!(picked.ends_with("a.mov"), "序号 4 % 2 == 0 应回到第一个: {picked}");
    }

    #[test]
    fn watermark_plan_returns_none_without_video_watermark() {
        let config = empty_config();
        let plan = plan_video_watermark(&config, 1920, 1080, 5.0, "右下", |_| {
            Some((100, 100, 5.0))
        });
        assert!(plan.is_none());
    }
}