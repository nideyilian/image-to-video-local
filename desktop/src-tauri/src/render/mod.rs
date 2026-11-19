//! 渲染内核（Rust 版）：对齐 `src/render/`。
//!
//! 分四层，自下而上：
//! - `process`：ffprobe 探测、子进程守护、安全替换
//! - `codec`：扩展名 → muxer / 编码器 / 音频编码器
//! - `audio`：BGM 选曲与混入
//! - 后续：`encoder`（rawvideo 管道）、`postprocess`、`compositor`、`pixels`
//!
//! ⚠️ 这些模块已实现并通过与 Python 的逐项对照，但**导出流程仍由旧引擎编排**
//! （worker 还是 `python -m src.render.worker`）。等 `compositor` 完全接管后，
//! 入口会被 `engine::jobs` 调起来，届时可以删掉下面的 `allow(dead_code)`。
#![allow(dead_code)]

pub mod audio;
pub mod codec;
pub mod compositor;
pub mod effects;
pub mod encoder;
pub mod imageinfo;
pub mod pixels;
pub mod plan;
pub mod postprocess;
pub mod process;
pub mod transitions;
pub mod watermark;

#[cfg(test)]
mod parity {
    use super::*;
    use serde_json::{json, Map, Value};

    /// codec 决策对照：`ITV_CODEC_PARITY=1` 时打印全部解析结果。
    /// 与 `src/render/codec.py` 的同名函数逐项比对（见 tools/render_codec_parity.py）。
    #[test]
    fn parity_dump_codec() {
        if std::env::var("ITV_CODEC_PARITY").is_err() {
            return;
        }
        let paths = [
            "a.mp4", "b.MKV", "c.mov", "d.avi", "e.webm", "f.ts", "no_ext", "g.MP4",
        ];
        let mut out = Map::new();
        for path in paths {
            out.insert(format!("ext|{path}"), json!(codec::output_extension(path)));
            out.insert(
                format!("temp|{path}"),
                json!(codec::temp_output_path(path, "_tmp")),
            );
            out.insert(
                format!("muxer|{path}"),
                json!(codec::muxer_for_output(path)),
            );
            out.insert(
                format!("acod|{path}"),
                json!(codec::container_acodec(path)),
            );
            for selected in ["XVID", "H264", "MJPG", "mp4v", "不存在的编码器"] {
                out.insert(
                    format!("vcodec|{path}|{selected}"),
                    json!(codec::ffmpeg_vcodec(selected)),
                );
                out.insert(
                    format!("strict|{path}|{selected}"),
                    json!(codec::strict_vcodec(path, selected)),
                );
            }
        }
        for path in ["a.mp4", "b.MKV", "d.avi"] {
            for preferred in [None, Some("libx264"), Some("libxvid")] {
                out.insert(
                    format!("cands|{path}|{preferred:?}"),
                    json!(codec::container_vcodecs(path, preferred)),
                );
            }
        }
        println!("CODEC_PARITY={}", Value::Object(out));
    }
}

#[cfg(test)]
mod parity_audio {
    use super::*;
    use serde_json::{json, Map, Value};

    /// BGM 选曲对照：`ITV_AUDIO_PARITY` 指向素材目录，`ITV_AUDIO_CASES` 指向用例 JSON。
    #[test]
    fn parity_dump_audio_selection() {
        let Ok(dir) = std::env::var("ITV_AUDIO_PARITY") else {
            return;
        };
        let Ok(cases_path) = std::env::var("ITV_AUDIO_CASES") else {
            return;
        };
        let Ok(raw) = std::fs::read_to_string(cases_path) else {
            return;
        };
        let cases: Vec<Value> = serde_json::from_str(&raw).unwrap_or_default();

        let mut out = Map::new();
        for case in cases {
            let id = case
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or("?")
                .to_string();
            let mut config = audio::JsonConfig::new(case.get("config").unwrap_or(&Value::Null));
            config.0.insert(
                "bgm_dir".to_string(),
                json!(format!("{dir}/BGM")),
            );
            if let Some(index) = case.get("video_index").and_then(Value::as_u64) {
                config
                    .0
                    .insert("_current_video_index".to_string(), json!(index));
            }

            let candidates: Vec<String> = audio::resolve_bgm_candidates(&config)
                .into_iter()
                .map(|path| {
                    path.file_name()
                        .map(|value| value.to_string_lossy().into_owned())
                        .unwrap_or_default()
                })
                .collect();
            let picked = audio::select_bgm_file(&config, None, |_| 0).map(|path| {
                path.file_name()
                    .map(|value| value.to_string_lossy().into_owned())
                    .unwrap_or_default()
            });
            out.insert(
                id,
                json!({ "candidates": candidates, "picked": picked }),
            );
        }
        println!("AUDIO_PARITY={}", Value::Object(out));
    }
}

#[cfg(test)]
mod parity_bgm {
    use super::*;
    use serde_json::json;

    /// 真实混音对照：`ITV_BGM_VIDEO` / `ITV_BGM_AUDIO` / `ITV_BGM_OUT` / `ITV_BGM_LOOP`。
    #[test]
    fn parity_dump_bgm_mix() {
        let (Ok(video), Ok(audio), Ok(out)) = (
            std::env::var("ITV_BGM_VIDEO"),
            std::env::var("ITV_BGM_AUDIO"),
            std::env::var("ITV_BGM_OUT"),
        ) else {
            return;
        };
        let loop_bgm = std::env::var("ITV_BGM_LOOP").unwrap_or_else(|_| "1".to_string()) == "1";
        let volume: f64 = std::env::var("ITV_BGM_VOLUME")
            .ok()
            .and_then(|text| text.parse().ok())
            .unwrap_or(0.5);

        std::fs::copy(&video, &out).expect("复制待处理视频");
        let config = audio::JsonConfig::new(&json!({ "loop_bgm": loop_bgm }));
        let ffmpeg = crate::engine::system::resolve_ffmpeg(None).expect("ffmpeg");
        let ffprobe = crate::engine::system::resolve_ffprobe(None, Some(ffmpeg.as_path()));
        let mut lines: Vec<String> = Vec::new();
        let ok = audio::add_audio_with_ffmpeg(
            &out,
            &audio,
            volume,
            &config,
            &ffmpeg.to_string_lossy(),
            ffprobe.as_deref(),
            |line| lines.push(line.to_string()),
        );
        println!(
            "BGM_PARITY={}",
            json!({ "ok": ok, "log": lines, "loop": loop_bgm, "volume": volume })
        );
    }
}

#[cfg(test)]
mod parity_plan {
    use super::*;
    use serde_json::{json, Map, Value};

    /// 帧计划对照：覆盖 .5 边界、超短时长、大帧率等易错组合。
    #[test]
    fn parity_dump_frame_plan() {
        if std::env::var("ITV_PLAN_PARITY").is_err() {
            return;
        }
        let mut out = Map::new();
        let transitions = [(0i64, "无转场"), (8, "无转场"), (8, "淡入淡出"), (999, "淡入淡出")];
        for images in [1i64, 2, 3, 5, 7, 20] {
            for duration in [0.01, 0.1, 0.2, 0.5, 1.0, 1.7, 2.5, 3.3333, 10.0] {
                for fps in [1i64, 24, 25, 30, 60] {
                    for (frames, kind) in transitions {
                        let plan =
                            plan::compute_video_frame_plan(images, duration, fps, frames, kind);
                        out.insert(
                            format!("{images}|{duration}|{fps}|{frames}|{kind}"),
                            json!({
                                "frames_per_img": plan.frames_per_img,
                                "transition_frames": plan.transition_frames,
                                "display_frames_per_img": plan.display_frames_per_img,
                                "last_img_frames": plan.last_img_frames,
                            }),
                        );
                    }
                }
            }
        }
        println!("PLAN_PARITY={}", Value::Object(out));
    }
}

#[cfg(test)]
mod parity_encode {
    use super::*;
    use serde_json::json;

    /// 管道编码对照：`ITV_ENCODE_OUT` 指定输出，
    /// `ITV_ENCODE_FRAMES` 指定帧数，`ITV_ENCODE_CODEC` 指定编码器，`ITV_ENCODE_SIZE` 形如 320x240。
    /// 帧内容用确定性算法生成（第 i 帧填 i%256），两边一致。
    #[test]
    fn parity_dump_encode_pipeline() {
        let Ok(out) = std::env::var("ITV_ENCODE_OUT") else {
            return;
        };
        let frames: i64 = std::env::var("ITV_ENCODE_FRAMES")
            .ok()
            .and_then(|text| text.parse().ok())
            .unwrap_or(30);
        let codec_name =
            std::env::var("ITV_ENCODE_CODEC").unwrap_or_else(|_| "H264".to_string());
        let size = std::env::var("ITV_ENCODE_SIZE").unwrap_or_else(|_| "320x240".to_string());
        let fps: i64 = std::env::var("ITV_ENCODE_FPS")
            .ok()
            .and_then(|text| text.parse().ok())
            .unwrap_or(30);
        let bitrate: i64 = std::env::var("ITV_ENCODE_BITRATE")
            .ok()
            .and_then(|text| text.parse().ok())
            .unwrap_or(1000);

        let (width, height) = size.split_once('x').expect("尺寸格式 320x240");
        let width: i64 = width.parse().expect("宽");
        let height: i64 = height.parse().expect("高");

        let options = encoder::EncodeOptions {
            output_path: out.clone(),
            selected_codec: codec_name.clone(),
            width,
            height,
            fps,
            target_bitrate: bitrate,
        };
        let ffmpeg = crate::engine::system::resolve_ffmpeg(None).expect("ffmpeg");
        let mut session = encoder::EncodeSession::open(&options, &ffmpeg.to_string_lossy())
            .unwrap_or_else(|error| panic!("打开管道失败: {error}"));

        let frame_bytes = (width * height * 3) as usize;
        let mut buffer = vec![0u8; frame_bytes];
        for index in 0..frames {
            // 确定性图案：整帧填充同一个值，随帧号递增
            let value = (index % 256) as u8;
            buffer.iter_mut().for_each(|byte| *byte = value);
            session.write_frame(&buffer).expect("写帧");
        }
        let written = session.finish().expect("结束管道");
        println!(
            "ENCODE_PARITY={}",
            json!({
                "frames": written,
                "valid": encoder::output_is_valid(&out),
                "size": std::fs::metadata(&out).map(|m| m.len()).unwrap_or(0),
            })
        );
    }
}

#[cfg(test)]
mod parity_watermark {
    use super::*;
    use serde_json::{json, Map, Value};

    /// 叠加几何对照：覆盖各尺寸模式、各位置、极端比例。
    #[test]
    fn parity_dump_overlay_geometry() {
        if std::env::var("ITV_GEOMETRY_PARITY").is_err() {
            return;
        }
        let mut out = Map::new();
        let mains = [(1920i64, 1080i64), (1080, 1920), (1000, 1000), (1, 1), (999, 333)];
        let watermarks = [(400i64, 100i64), (100, 400), (500, 500), (1, 1000), (3000, 200)];
        let modes = ["自适应覆盖", "完全覆盖", "固定比例"];
        let positions = ["左上", "右上", "左下", "右下", "中心", "未知位置"];
        let scales = [0.0f64, 5.0, 20.0, 33.3, 100.0, 250.0];
        for (mw, mh) in mains {
            for (ww, wh) in watermarks {
                for mode in modes {
                    for position in positions {
                        for scale in scales {
                            let geometry = watermark::calc_overlay_geometry(
                                mw, mh, ww, wh, mode, scale, position,
                            );
                            out.insert(
                                format!("{mw}x{mh}|{ww}x{wh}|{mode}|{position}|{scale}"),
                                json!({
                                    "target_w": geometry.target_w,
                                    "target_h": geometry.target_h,
                                    "x": geometry.x,
                                    "y": geometry.y,
                                }),
                            );
                        }
                    }
                }
            }
        }
        println!("GEOMETRY_PARITY={}", Value::Object(out));
    }
}

#[cfg(test)]
mod parity_imageinfo {
    use super::*;
    use serde_json::{json, Map, Value};

    /// 图片尺寸对照：`ITV_IMGSIZE_DIR` 指向一个图片目录。
    #[test]
    fn parity_dump_image_size() {
        let Ok(dir) = std::env::var("ITV_IMGSIZE_DIR") else {
            return;
        };
        let mut files: Vec<_> = std::fs::read_dir(&dir)
            .map(|entries| entries.flatten().map(|entry| entry.path()).collect())
            .unwrap_or_default();
        files.sort();
        let mut out = Map::new();
        for path in files {
            if !path.is_file() {
                continue;
            }
            let name = path
                .file_name()
                .map(|value| value.to_string_lossy().into_owned())
                .unwrap_or_default();
            let size = imageinfo::image_size(&path);
            out.insert(
                name,
                json!(size.map(|value| json!({ "w": value.width, "h": value.height }))),
            );
        }
        println!("IMGSIZE_PARITY={}", Value::Object(out));
    }
}

#[cfg(test)]
mod parity_postprocess {
    use super::*;
    use serde_json::{json, Map, Value};

    /// 后处理命令对照：`ITV_POST_CASES` 指向用例 JSON，
    /// `ITV_POST_MAIN` 形如 1920x1080x5.0（主视频宽高时长）。
    #[test]
    fn parity_dump_postprocess_command() {
        let Ok(cases_path) = std::env::var("ITV_POST_CASES") else {
            return;
        };
        let Ok(raw) = std::fs::read_to_string(cases_path) else {
            return;
        };
        let cases: Vec<Value> = serde_json::from_str(&raw).unwrap_or_default();
        let main = std::env::var("ITV_POST_MAIN").unwrap_or_else(|_| "1920x1080x5.0".to_string());
        let parts: Vec<&str> = main.split('x').collect();
        let main_meta = (
            parts[0].parse::<i64>().unwrap_or(1920),
            parts[1].parse::<i64>().unwrap_or(1080),
            parts[2].parse::<f64>().unwrap_or(5.0),
        );

        let mut out = Map::new();
        for case in cases {
            let id = case
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or("?")
                .to_string();
            let plan = case.get("watermark").and_then(|value| {
                if value.is_null() {
                    None
                } else {
                    Some(postprocess::WatermarkPlan {
                        path: value.get("path")?.as_str()?.to_string(),
                        match_method: value
                            .get("match_method")
                            .and_then(Value::as_str)
                            .unwrap_or("循环")
                            .to_string(),
                        blend_mode: value
                            .get("blend_mode")
                            .and_then(Value::as_str)
                            .unwrap_or("正常")
                            .to_string(),
                        alpha: value.get("alpha").and_then(Value::as_f64).unwrap_or(0.5),
                        target_w: value.get("target_w").and_then(Value::as_i64).unwrap_or(384),
                        target_h: value.get("target_h").and_then(Value::as_i64).unwrap_or(192),
                        x: value.get("x").and_then(Value::as_i64).unwrap_or(1526),
                        y: value.get("y").and_then(Value::as_i64).unwrap_or(878),
                        looped: value
                            .get("looped")
                            .and_then(Value::as_bool)
                            .unwrap_or(true),
                        stretch_ratio: value.get("stretch_ratio").and_then(Value::as_f64),
                    })
                }
            });
            let layers: Vec<postprocess::FixedLayerPlan> = case
                .get("fixed_layers")
                .and_then(Value::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(|item| {
                            Some(postprocess::FixedLayerPlan {
                                path: item.get("path")?.as_str()?.to_string(),
                                target_w: item.get("target_w")?.as_i64()?,
                                target_h: item.get("target_h")?.as_i64()?,
                                x: item.get("x")?.as_i64()?,
                                y: item.get("y")?.as_i64()?,
                                opacity: item.get("opacity")?.as_f64()?,
                            })
                        })
                        .collect()
                })
                .unwrap_or_default();
            let bgm = case.get("bgm").and_then(|value| {
                if value.is_null() {
                    None
                } else {
                    Some(postprocess::BgmPlan {
                        path: value.get("path")?.as_str()?.to_string(),
                        volume: value.get("volume").and_then(Value::as_f64).unwrap_or(0.5),
                        looped: value
                            .get("looped")
                            .and_then(Value::as_bool)
                            .unwrap_or(true),
                    })
                }
            });
            let output = case
                .get("output")
                .and_then(Value::as_str)
                .unwrap_or("C:/out/v.mp4");
            let codec = case
                .get("codec")
                .and_then(Value::as_str)
                .unwrap_or("libx264");

            let command = postprocess::build_command(
                output,
                main_meta,
                plan.as_ref(),
                &layers,
                bgm.as_ref(),
                codec,
            );
            out.insert(
                id,
                json!({
                    "args": command.args,
                    "temp_output": command.temp_output,
                }),
            );
        }
        println!("POST_PARITY={}", Value::Object(out));
    }
}

#[cfg(test)]
mod parity_post_run {
    use super::*;
    use serde_json::{json, Value};

    /// 真实执行后处理：`ITV_POST_RUN_CASES` 指向用例 JSON。
    /// 每条用例里给出 args（不含 ffmpeg 自身与输出路径替换），
    /// 这里把输入复制到 rs_ 前缀再跑，便于与 Python 侧产物比对。
    #[test]
    fn parity_run_postprocess() {
        let Ok(cases_path) = std::env::var("ITV_POST_RUN_CASES") else {
            return;
        };
        let Ok(raw) = std::fs::read_to_string(cases_path) else {
            return;
        };
        let cases: Vec<Value> = serde_json::from_str(&raw).unwrap_or_default();
        let ffmpeg = crate::engine::system::resolve_ffmpeg(None).expect("ffmpeg");
        let mut results = Vec::new();

        for case in cases {
            let id = case.get("id").and_then(Value::as_str).unwrap_or("?").to_string();
            let source = case.get("source").and_then(Value::as_str).unwrap_or("");
            let output = case.get("output").and_then(Value::as_str).unwrap_or("");
            let args: Vec<String> = case
                .get("args")
                .and_then(Value::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(|item| item.as_str().map(str::to_string))
                        .collect()
                })
                .unwrap_or_default();

            std::fs::copy(source, output).expect("复制源视频");
            let mut log_lines: Vec<String> = Vec::new();
            let outcome = process::run_with_retry(
                &ffmpeg.to_string_lossy(),
                &args,
                "POST",
                900,
                1,
                |line| log_lines.push(line.to_string()),
            );
            let temp = postprocess::build_temp_output_path_from(output);
            let size = std::fs::metadata(&temp).map(|m| m.len()).unwrap_or(0);
            if size > 1000 {
                let _ = process::safe_replace_file(&temp, output);
            }
            results.push(json!({
                "id": id,
                "code": outcome.as_ref().and_then(|value| value.code),
                "size": size,
            }));
        }
        println!("POST_RUN={}", json!(results));
    }
}

#[cfg(test)]
mod parity_pixels {
    use super::*;
    use serde_json::{json, Value};

    /// 缩放对照：`ITV_PIXEL_DIR` 图片目录，`ITV_PIXEL_OUT` 输出目录。
    /// 对每张图做三种缩放，各写一张结果 + 打印差异统计。
    #[test]
    fn parity_dump_resize() {
        let (Ok(dir), Ok(out_dir)) =
            (std::env::var("ITV_PIXEL_DIR"), std::env::var("ITV_PIXEL_OUT"))
        else {
            return;
        };
        let mut files: Vec<_> = std::fs::read_dir(&dir)
            .map(|entries| entries.flatten().map(|entry| entry.path()).collect())
            .unwrap_or_default();
        files.sort();
        std::fs::create_dir_all(&out_dir).ok();

        let mut report = Vec::new();
        for path in files {
            if !path.is_file() {
                continue;
            }
            let name = path
                .file_stem()
                .map(|value| value.to_string_lossy().into_owned())
                .unwrap_or_default();
            let Some(frame) = pixels::read_image_bgr(&path) else {
                continue;
            };
            let source = (frame.width, frame.height);

            for (label, target) in [
                ("fit_1080x1920", (1080u32, 1920u32)),
                ("fit_1920x1080", (1920, 1080)),
                ("stretch", (640, 360)),
            ] {
                let result = if label == "stretch" {
                    pixels::resize_image(&frame, target.0, target.1, "拉伸")
                } else {
                    pixels::resize_with_aspect_ratio(&frame, target.0, target.1)
                };
                let file_name = format!("{name}__{label}.png");
                result.to_rgb().save(std::path::Path::new(&out_dir).join(&file_name)).ok();
                report.push(json!({
                    "file": file_name,
                    "source": [source.0, source.1],
                    "target": [result.width, result.height],
                    "checksum": checksum(&result.data),
                }));
            }
        }
        println!("RESIZE_PARITY={}", Value::Array(report));
    }

    fn checksum(data: &[u8]) -> u64 {
        // 简单校验和，只用来快速确认「是不是同一张图」，不用于像素比对
        let mut sum: u64 = 0;
        for (index, byte) in data.iter().enumerate() {
            sum = sum.wrapping_mul(31).wrapping_add((*byte as u64) + index as u64);
        }
        sum
    }
}

#[cfg(test)]
mod parity_filter_probe {
    use super::*;

    /// 滤镜候选实测：同一批图分别用 Triangle / CatmullRom / Nearest 缩小，
    /// 输出到 `ITV_FILTER_OUT`，供外部与 OpenCV 比对选最优。
    #[test]
    fn probe_filter_variants() {
        let (Ok(dir), Ok(out_dir)) =
            (std::env::var("ITV_PIXEL_DIR"), std::env::var("ITV_FILTER_OUT"))
        else {
            return;
        };
        std::fs::create_dir_all(&out_dir).ok();
        let mut files: Vec<_> = std::fs::read_dir(&dir)
            .map(|entries| entries.flatten().map(|entry| entry.path()).collect())
            .unwrap_or_default();
        files.sort();
        for path in files {
            if !path.is_file() {
                continue;
            }
            let name = path
                .file_stem()
                .map(|value| value.to_string_lossy().into_owned())
                .unwrap_or_default();
            let Some(frame) = pixels::read_image_bgr(&path) else {
                continue;
            };
            for (label, filter) in [
                ("triangle", pixels::ResizeFilter::Bilinear),
                ("catmull", pixels::ResizeFilter::Area),
                ("nearest", pixels::ResizeFilter::Nearest),
            ] {
                let resized = pixels::resize(&frame, 640, 360, filter);
                resized
                    .to_rgb()
                    .save(std::path::Path::new(&out_dir).join(format!("{name}__{label}.png")))
                    .ok();
            }
        }
    }
}

#[cfg(test)]
mod parity_transitions {
    use super::*;
    use serde_json::{json, Value};

    /// 转场对照：`ITV_TRANS_DIR` 里放 a.png / b.png，
    /// `ITV_TRANS_OUT` 输出目录。每种转场各存全部帧。
    #[test]
    fn parity_dump_transitions() {
        let (Ok(dir), Ok(out_dir)) =
            (std::env::var("ITV_TRANS_DIR"), std::env::var("ITV_TRANS_OUT"))
        else {
            return;
        };
        let first = match pixels::read_image_bgr(std::path::Path::new(&dir).join("a.png").as_path()) {
            Some(frame) => frame,
            None => return,
        };
        let second = match pixels::read_image_bgr(std::path::Path::new(&dir).join("b.png").as_path()) {
            Some(frame) => frame,
            None => return,
        };
        std::fs::create_dir_all(&out_dir).ok();

        let cases: Vec<(&str, transitions::Transition)> = vec![
            ("淡入淡出", transitions::Transition::Fade),
            ("左右滑动", transitions::Transition::SlideLeft),
            ("上下滑动", transitions::Transition::SlideUp),
            ("交叉溶解", transitions::Transition::Fade),
            ("圆形扩展", transitions::Transition::CircleExpand),
            ("缩放过渡", transitions::Transition::Zoom),
            ("百叶窗", transitions::Transition::Blinds),
            ("像素化", transitions::Transition::Pixelate),
            ("未知转场", transitions::Transition::Fallback),
        ];
        let num_frames = std::env::var("ITV_TRANS_FRAMES")
            .ok()
            .and_then(|text| text.parse::<usize>().ok())
            .unwrap_or(8);

        let mut report = Vec::new();
        for (index, (name, kind)) in cases.iter().enumerate() {
            let frames = transitions::generate_frames(&first, &second, *kind, num_frames);
            for (frame_index, frame) in frames.iter().enumerate() {
                let file = format!("{index:02}__{frame_index:02}.png");
                frame
                    .to_rgb()
                    .save(std::path::Path::new(&out_dir).join(&file))
                    .ok();
            }
            report.push(json!({
                "name": name,
                "index": index,
                "count": frames.len(),
            }));
        }
        println!("TRANS_PARITY={}", Value::Array(report));
    }
}

#[cfg(test)]
mod parity_effects {
    use super::*;
    use serde_json::{json, Value};

    /// 特效对照：`ITV_EFFECT_DIR` 输入图目录，`ITV_EFFECT_OUT` 输出目录。
    #[test]
    fn parity_dump_effects() {
        let (Ok(dir), Ok(out_dir)) =
            (std::env::var("ITV_EFFECT_DIR"), std::env::var("ITV_EFFECT_OUT"))
        else {
            return;
        };
        std::fs::create_dir_all(&out_dir).ok();
        let source = pixels::read_image_bgr(std::path::Path::new(&dir).join("in.png").as_path());
        let Some(frame) = source else { return };

        let effects = [
            "旋转呼吸",
            "摇摆推拉",
            "圆周漂移",
            "螺旋摆动",
            "双轴呼吸",
            "心跳摇摆",
            "波浪平移",
            "左右晃动",
            "上下浮动",
            "缓慢推近",
            "缓慢拉远",
            "无特效",
        ];
        let times = [0.0f64, 0.35, 0.75, 1.5];
        let mut report = Vec::new();
        for (index, effect) in effects.iter().enumerate() {
            for (time_index, time_sec) in times.iter().enumerate() {
                let params = effects::EffectParams {
                    effect_type: effect.to_string(),
                    time_sec: *time_sec,
                    duration_sec: 3.0,
                    intensity: 100.0,
                    speed: 1.0,
                };
                let result = effects::apply_single_image_effect(&frame, &params);
                let file = format!("{index:02}__{time_index:02}.png");
                result
                    .to_rgb()
                    .save(std::path::Path::new(&out_dir).join(&file))
                    .ok();
                report.push(json!({ "effect": effect, "time": time_sec, "file": file }));
            }
        }
        println!("EFFECT_PARITY={}", Value::Array(report));
    }
}

#[cfg(test)]
mod parity_compose {
    use super::*;
    use serde_json::json;

    /// 端到端导出对照：`ITV_COMPOSE_DIR` 图片目录，`ITV_COMPOSE_OUT` 输出文件。
    #[test]
    fn parity_run_compose() {
        let (Ok(dir), Ok(out)) =
            (std::env::var("ITV_COMPOSE_DIR"), std::env::var("ITV_COMPOSE_OUT"))
        else {
            return;
        };
        let entries: Vec<std::path::PathBuf> = std::fs::read_dir(&dir)
            .map(|items| items.flatten().map(|entry| entry.path()).collect())
            .unwrap_or_default();
        let mut images: Vec<String> = entries
            .into_iter()
            .filter(|path| {
                path.extension()
                    .map(|ext| ext.to_string_lossy().to_lowercase() == "png")
                    .unwrap_or(false)
            })
            .map(|path| path.to_string_lossy().into_owned())
            .collect();
        images.sort();
        if images.is_empty() {
            return;
        }

        let duration: f64 = std::env::var("ITV_COMPOSE_DURATION")
            .ok()
            .and_then(|text| text.parse().ok())
            .unwrap_or(1.0);
        let fps: i64 = std::env::var("ITV_COMPOSE_FPS")
            .ok()
            .and_then(|text| text.parse().ok())
            .unwrap_or(30);
        let transition_frames: i64 = std::env::var("ITV_COMPOSE_TRANS_FRAMES")
            .ok()
            .and_then(|text| text.parse().ok())
            .unwrap_or(8);
        let transition_type =
            std::env::var("ITV_COMPOSE_TRANS").unwrap_or_else(|_| "淡入淡出".to_string());
        let effect = std::env::var("ITV_COMPOSE_EFFECT").unwrap_or_else(|_| "无特效".to_string());
        let use_effect = effect != "无特效";

        let options = compositor::ComposeOptions {
            images,
            output_path: out.clone(),
            duration,
            fps,
            width: 320,
            height: 240,
            resize_mode: "适应".into(),
            transition_frames,
            transition_type,
            target_bitrate: 1000,
            selected_codec: "H264".into(),
            effect_override: Some(effect.clone()),
        };
        let config = audio::JsonConfig::new(&json!({
            "use_video_effect": use_effect,
            "video_effect_type": effect,
            "video_effect_intensity": 100.0,
            "video_effect_speed": 1.0,
        }));
        let ffmpeg = crate::engine::system::resolve_ffmpeg(None).expect("ffmpeg");
        let mut hooks = compositor::QuietHooks;
        let result = compositor::create_video(
            &options,
            &config,
            &ffmpeg.to_string_lossy(),
            &mut hooks,
            None,
        );
        println!(
            "COMPOSE_RESULT={}",
            match result {
                Ok(value) => json!({
                    "ok": true,
                    "frames": value.frames_written,
                    "total": value.total_frames,
                    "width": value.width,
                    "height": value.height,
                    "size": std::fs::metadata(&out).map(|m| m.len()).unwrap_or(0),
                }),
                Err(error) => json!({ "ok": false, "error": error.to_string() }),
            }
        );
    }
}
