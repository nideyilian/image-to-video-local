//! 预览类接口，对齐 `src/engine/server.py` 的 `_preview_thumbnail` / `_preview_bgm` /
//! `library_preview_audio` / `library_preview_video` / `library_audio_cover`。
//!
//! 这些都是「用 ffmpeg 生成一个缓存文件，再把路径返回给前端」，
//! 不涉及逐帧像素运算，所以可以做到与旧版完全一致。
//!
//! 缓存键统一是 `sha1(描述串)`，与 Python 的 `hashlib.sha1(...).hexdigest()` 一致 ——
//! 缓存键不同会导致「每次都重新转码」，虽然结果对但很慢。

// 部分辅助函数（preview_sequence / is_audio 等）留给后续「渲染类预览接口」使用，
// 当前通过 dispatch 暴露的是子集，故先允许未使用。
#![allow(dead_code)]

use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use super::hash;
use super::library;
use super::system;
use crate::render::audio;
use crate::render::imageinfo;
use crate::render::pixels;
use crate::render::process::{probe_video_meta, run_with_retry};

const VIDEO_EXTENSIONS: [&str; 14] = [
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm", ".m4v", ".ts", ".mpg", ".mpeg",
    ".3gp", ".rmvb", ".f4v",
];

fn has_video_extension(path: &Path) -> bool {
    path.extension()
        .map(|value| format!(".{}", value.to_string_lossy().to_lowercase()))
        .map(|ext| VIDEO_EXTENSIONS.contains(&ext.as_str()))
        .unwrap_or(false)
}

/// 缓存目录（与 Python 的 `tempfile.gettempdir()/image-to-video-engine/<sub>` 一致）。
pub fn cache_dir(sub: &str) -> PathBuf {
    std::env::temp_dir().join("image-to-video-engine").join(sub)
}

/// 文件修改时间（纳秒），与 Python 的 `st_mtime_ns` 同量级。
fn mtime_ns(path: &Path) -> i64 {
    std::fs::metadata(path)
        .ok()
        .map(|meta| crate::engine::snapshot::modified_ns(&meta))
        .unwrap_or(0)
}

/// sha1 的十六进制串（Python 用 `hashlib.sha1(...).hexdigest()`）。
fn sha1_hex(text: &str) -> String {
    hash::sha1_hex(text.as_bytes())
}

/// 预览参数。
pub struct ThumbnailParams {
    pub source: String,
    pub input_dir: String,
    pub max_width: u32,
    pub max_height: u32,
}

impl ThumbnailParams {
    pub fn from_params(params: &serde_json::Map<String, Value>) -> Self {
        let source = params
            .get("path")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim()
            .to_string();
        let input_dir = params
            .get("input_dir")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim()
            .to_string();
        let clamp = |value: Option<&Value>, default: u32, low: u32, high: u32| -> u32 {
            let raw = value
                .and_then(Value::as_i64)
                .unwrap_or(default as i64);
            raw.clamp(low as i64, high as i64) as u32
        };
        ThumbnailParams {
            source,
            input_dir,
            max_width: clamp(params.get("max_width"), 960, 64, 1920),
            max_height: clamp(params.get("max_height"), 540, 64, 1080),
        }
    }
}

/// 生成缩略图（图片走 image crate，视频走 ffmpeg 抽中段一帧）。
///
/// 返回结构与 `_preview_thumbnail` 一致：
/// `{source, preview_path, width, height, kind, duration}`。
pub fn preview_thumbnail(
    params: &ThumbnailParams,
    ffmpeg: Option<&Path>,
    ffprobe: Option<&Path>,
) -> Result<Value, String> {
    let mut source = params.source.clone();
    if source.is_empty() {
        // 没指定就取输入目录的第一张
        let candidates = super::scan::scan_images(&params.input_dir);
        source = candidates.first().cloned().unwrap_or_default();
    }
    if source.is_empty() || !Path::new(&source).is_file() {
        return Err("没有可预览的素材".to_string());
    }

    let source_path = PathBuf::from(&source);
    let is_video = has_video_extension(&source_path);
    let preview_dir = cache_dir("previews");
    std::fs::create_dir_all(&preview_dir).map_err(|error| error.to_string())?;

    let cache_key = format!(
        "{}:{}:{}x{}",
        crate::engine::paths::display(&crate::engine::paths::absolute(&source_path)),
        mtime_ns(&source_path),
        params.max_width,
        params.max_height
    );
    let preview_path = preview_dir.join(format!("{}.jpg", sha1_hex(&cache_key)));

    let mut width = 0u32;
    let mut height = 0u32;
    let mut duration: Option<f64> = None;

    if is_video {
        let ffmpeg = ffmpeg.ok_or_else(|| "未找到 FFmpeg，无法预览视频素材".to_string())?;
        duration = probe_video_meta(&source, ffprobe).map(|meta| meta.duration);
        if !preview_path.exists() {
            let seek = ((duration.unwrap_or(0.0) / 2.0) - 0.05).max(0.0);
            let temporary = preview_path.with_file_name(format!(
                ".{}-{}.tmp.jpg",
                preview_path
                    .file_stem()
                    .map(|value| value.to_string_lossy().into_owned())
                    .unwrap_or_default(),
                std::process::id()
            ));
            let args: Vec<String> = vec![
                "-hide_banner".into(),
                "-loglevel".into(),
                "error".into(),
                "-nostdin".into(),
                "-y".into(),
                "-ss".into(),
                format!("{seek:.3}"),
                "-i".into(),
                source.clone(),
                "-frames:v".into(),
                "1".into(),
                "-vf".into(),
                format!(
                    "scale='min({},iw)':'min({},ih)':force_original_aspect_ratio=decrease",
                    params.max_width, params.max_height
                ),
                temporary.to_string_lossy().into_owned(),
            ];
            let outcome = run_with_retry(
                &ffmpeg.to_string_lossy(),
                &args,
                "THUMB",
                60,
                1,
                |_message| {},
            );
            let ok = outcome
                .as_ref()
                .map(|value| value.code == Some(0))
                .unwrap_or(false);
            if !ok || !temporary.is_file() {
                let detail = outcome
                    .map(|value| {
                        value
                            .stderr
                            .lines()
                            .rev()
                            .find(|line| !line.trim().is_empty())
                            .unwrap_or("")
                            .trim()
                            .to_string()
                    })
                    .unwrap_or_default();
                let _ = std::fs::remove_file(&temporary);
                return Err(format!(
                    "视频预览失败：{}",
                    if detail.is_empty() {
                        source_path
                            .file_name()
                            .map(|value| value.to_string_lossy().into_owned())
                            .unwrap_or_default()
                    } else {
                        detail
                    }
                ));
            }
            std::fs::rename(&temporary, &preview_path).map_err(|error| error.to_string())?;
        }
        // 读回尺寸
        if let Some(size) = imageinfo::image_size(&preview_path) {
            width = size.width as u32;
            height = size.height as u32;
        }
    } else {
        // 图片：等比缩到 max 之内（对应 PIL 的 thumbnail + LANCZOS）
        let frame = pixels::read_image_bgr(&source_path)
            .ok_or_else(|| "没有可预览的素材".to_string())?;
        let scale = f64::min(
            params.max_width as f64 / frame.width as f64,
            params.max_height as f64 / frame.height as f64,
        );
        let (target_w, target_h) = if scale < 1.0 {
            (
                ((frame.width as f64 * scale) as u32).max(1),
                ((frame.height as f64 * scale) as u32).max(1),
            )
        } else {
            (frame.width, frame.height)
        };
        width = target_w;
        height = target_h;
        if !preview_path.exists() {
            let resized = pixels::resize(
                &frame,
                target_w,
                target_h,
                pixels::ResizeFilter::Area,
            );
            let image = resized.to_rgb();
            // JPEG 质量 88（与 Python 的 quality=88 一致）
            let mut buffer: Vec<u8> = Vec::new();
            let mut encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut buffer, 88);
            encoder
                .encode(
                    image.as_raw(),
                    image.width(),
                    image.height(),
                    image::ExtendedColorType::Rgb8,
                )
                .map_err(|error| error.to_string())?;
            std::fs::write(&preview_path, &buffer).map_err(|error| error.to_string())?;
        }
    }

    Ok(json!({
        "source": crate::engine::paths::display(&crate::engine::paths::absolute(&source_path)),
        "preview_path": crate::engine::paths::display(&crate::engine::paths::absolute(&preview_path)),
        "width": width,
        "height": height,
        "kind": if is_video { "video" } else { "image" },
        "duration": duration,
    }))
}

/// 把一个音频文件转成可直接播放的 mp3 缓存，返回缓存路径。
pub fn audio_preview_cache(
    source: &str,
    ffmpeg: Option<&Path>,
    cache_sub: &str,
    key_prefix: &str,
) -> Result<PathBuf, String> {
    let path = PathBuf::from(source);
    if !path.is_file() {
        return Err("音频文件不存在".to_string());
    }
    let ffmpeg = ffmpeg.ok_or_else(|| "未找到 FFmpeg，无法读取音频预览".to_string())?;
    let size = std::fs::metadata(&path).map(|meta| meta.len()).unwrap_or(0);
    let cache_key = format!(
        "{key_prefix}:{}:{}:{size}",
        crate::engine::paths::display(&crate::engine::paths::absolute(&path)),
        mtime_ns(&path)
    );
    let preview_dir = cache_dir(cache_sub);
    std::fs::create_dir_all(&preview_dir).map_err(|error| error.to_string())?;
    let preview_path = preview_dir.join(format!("{}.mp3", sha1_hex(&cache_key)));
    if preview_path.exists() {
        return Ok(preview_path);
    }

    let temporary = preview_path.with_file_name(format!(
        ".{}-{}.tmp.mp3",
        preview_path
            .file_stem()
            .map(|value| value.to_string_lossy().into_owned())
            .unwrap_or_default(),
        std::process::id()
    ));
    let args: Vec<String> = vec![
        "-hide_banner".into(),
        "-loglevel".into(),
        "error".into(),
        "-nostdin".into(),
        "-y".into(),
        "-i".into(),
        source.to_string(),
        "-vn".into(),
        "-c:a".into(),
        "libmp3lame".into(),
        "-q:a".into(),
        "4".into(),
        temporary.to_string_lossy().into_owned(),
    ];
    let outcome = run_with_retry(
        &ffmpeg.to_string_lossy(),
        &args,
        "AUDIO-PREVIEW",
        120,
        1,
        |_message| {},
    );
    let ok = outcome
        .as_ref()
        .map(|value| value.code == Some(0))
        .unwrap_or(false);
    if !ok || !temporary.is_file() {
        let _ = std::fs::remove_file(&temporary);
        return Err("音频预览生成失败".to_string());
    }
    std::fs::rename(&temporary, &preview_path).map_err(|error| error.to_string())?;
    Ok(preview_path)
}

/// `preview_bgm`：按配置挑出本次会用到的 BGM，返回可播放缓存。
pub fn preview_bgm(
    config: &dyn audio::RenderConfig,
    ffmpeg: Option<&Path>,
    sequence: i64,
    pick_first_only: bool,
) -> Result<Value, String> {
    if !config.bool_of("use_bgm", false) {
        return Ok(json!({ "enabled": false, "reason": "BGM 已关闭" }));
    }
    let strategy = config.text_of("watermark_audio", "使用BGM");
    if strategy != "使用BGM" && strategy != "两者混合" {
        return Ok(json!({ "enabled": false, "reason": format!("声音策略：{strategy}") }));
    }

    let raw_explicit: Vec<String> = config
        .string_list("bgm_files")
        .into_iter()
        .filter(|path| !path.trim().is_empty())
        .collect();
    let explicit: Vec<String> = raw_explicit
        .iter()
        .filter(|path| Path::new(path).is_file())
        .cloned()
        .collect();

    let candidates: Vec<String> = if !explicit.is_empty() {
        explicit.clone()
    } else if !raw_explicit.is_empty() {
        return Err("所选 BGM 文件已不存在，请重新在素材库中选择".to_string());
    } else {
        let bgm_dir = config.text_of("bgm_dir", "");
        if bgm_dir.is_empty() || !Path::new(&bgm_dir).is_dir() {
            return Err("BGM目录不存在，请重新选择".to_string());
        }
        let mut files: Vec<String> = audio::get_audio_files(&bgm_dir)
            .into_iter()
            .map(|path| {
                crate::engine::paths::display(&crate::engine::paths::absolute(&path))
            })
            .collect();
        // ⚠️ 必须用自然排序（数字段按数值比），与 `scan_audio_files` 一致。
        // 用字典序会让 10-xxx 排到 2-xxx 前面，选出的曲子与旧引擎不同。
        files.sort_by_key(|value| super::sort::natural_sort_key(value));
        files
    };
    if candidates.is_empty() {
        return Err("BGM目录中没有可用音频".to_string());
    }

    // 选曲：序号优先，其次随机（随机种子与 Python 一致，用 sha1 前 4 字节）
    let mut source = candidates[0].clone();
    if sequence > 0 {
        if let Some(chosen) =
            super::preview_random::preview_choice(&candidates, sequence, "bgm")
        {
            source = chosen;
        }
    } else if config.bool_of("random_bgm", false) && candidates.len() > 1 {
        let seed_source = if !explicit.is_empty() {
            explicit.join("|")
        } else {
            crate::engine::paths::display(&crate::engine::paths::absolute(Path::new(
                &config.text_of("bgm_dir", ""),
            )))
        };
        let digest = hash::sha1_digest(seed_source.as_bytes());
        let index = u32::from_be_bytes([digest[0], digest[1], digest[2], digest[3]]) as usize
            % candidates.len();
        source = candidates[index].clone();
    }
    let _ = pick_first_only;

    let preview_path = audio_preview_cache(&source, ffmpeg, "audio-previews", "mp3-v1")?;
    Ok(json!({
        "enabled": true,
        "source": crate::engine::paths::display(&crate::engine::paths::absolute(Path::new(&source))),
        "preview_path": crate::engine::paths::display(&crate::engine::paths::absolute(&preview_path)),
        "name": Path::new(&source).file_name().map(|v| v.to_string_lossy().into_owned()).unwrap_or_default(),
        "mime_type": "audio/mpeg",
        "random": config.bool_of("random_bgm", false),
    }))
}

/// `library_audio_cover`：抽取音频内嵌封面，没有就返回 None。
pub fn audio_cover(path: &str, ffmpeg: Option<&Path>) -> Result<Value, String> {
    let source = PathBuf::from(path);
    if !source.is_file() {
        return Ok(json!({ "cover_path": null }));
    }
    let Some(ffmpeg) = ffmpeg else {
        return Ok(json!({ "cover_path": null }));
    };
    let size = std::fs::metadata(&source).map(|meta| meta.len()).unwrap_or(0);
    let cache_key = format!(
        "cover:{}:{}:{size}",
        crate::engine::paths::display(&crate::engine::paths::absolute(&source)),
        mtime_ns(&source)
    );
    let cover_dir = cache_dir("library-covers");
    std::fs::create_dir_all(&cover_dir).map_err(|error| error.to_string())?;
    let cover_path = cover_dir.join(format!("{}.jpg", sha1_hex(&cache_key)));
    let cached = std::fs::metadata(&cover_path)
        .map(|meta| meta.len() > 0)
        .unwrap_or(false);
    if cached {
        return Ok(json!({ "cover_path": crate::engine::paths::display(&crate::engine::paths::absolute(&cover_path)) }));
    }

    // ⚠️ 必须 `-map 0:v:0 -frames:v 1 -c:v copy`：Python 是原样拷贝封面字节
    // （png 数据直接写进 .jpg 文件），用 `-f image2` 会强制重编码成 mjpeg，
    // 输出字节不同 → 与旧缓存不通用，且画质有损。
    let args: Vec<String> = vec![
        "-hide_banner".into(),
        "-loglevel".into(),
        "error".into(),
        "-nostdin".into(),
        "-y".into(),
        "-i".into(),
        path.to_string(),
        "-an".into(),
        "-map".into(),
        "0:v:0".into(),
        "-frames:v".into(),
        "1".into(),
        "-c:v".into(),
        "copy".into(),
        cover_path.to_string_lossy().into_owned(),
    ];
    let outcome = run_with_retry(
        &ffmpeg.to_string_lossy(),
        &args,
        "COVER",
        30,
        1,
        |_message| {},
    );
    let ok = outcome
        .as_ref()
        .map(|value| value.code == Some(0))
        .unwrap_or(false);
    let non_empty = std::fs::metadata(&cover_path)
        .map(|meta| meta.len() > 0)
        .unwrap_or(false);
    if !ok || !non_empty {
        let _ = std::fs::remove_file(&cover_path);
        return Ok(json!({ "cover_path": null }));
    }
    Ok(json!({ "cover_path": crate::engine::paths::display(&crate::engine::paths::absolute(&cover_path)) }))
}

/// `library_preview_video`：把素材库视频准备为 WebView 可播放的预览。
///
/// 与 `LibraryManager.preview_video` 对齐（写错会静默失效）：
/// - 缓存键 `video-preview-v1:{abs}:{mtime_ns}:{size}`，目录 `video-previews`
/// - 可播放判定见 `webview_playable_plan`，可播放的**直接拷贝**（保留 mtime）
/// - 返回字段名是 `preview_path`（前端只读这个，写成 `path` 会拿到 undefined）
pub fn preview_video(path: &str, ffmpeg: Option<&Path>, ffprobe: Option<&Path>) -> Result<Value, String> {
    let source = PathBuf::from(path);
    if !source.is_file() {
        return Err("视频文件不存在".to_string());
    }
    let size = std::fs::metadata(&source).map(|meta| meta.len()).unwrap_or(0);
    let cache_key = format!(
        "video-preview-v1:{}:{}:{size}",
        crate::engine::paths::display(&crate::engine::paths::absolute(&source)),
        mtime_ns(&source)
    );
    let preview_dir = cache_dir("video-previews");
    std::fs::create_dir_all(&preview_dir)
        .map_err(|error| format!("无法创建视频预览目录：{error}"))?;

    let (playable, output_ext) = webview_playable_plan(&source, ffprobe);
    let preview_path = preview_dir.join(format!("{}{output_ext}", sha1_hex(&cache_key)));

    let exists = std::fs::metadata(&preview_path)
        .map(|meta| meta.len() > 0)
        .unwrap_or(false);
    if exists {
        return Ok(json!({
            "preview_path": crate::engine::paths::display(&crate::engine::paths::absolute(&preview_path)),
            "transcoded": !playable,
        }));
    }

    if playable {
        std::fs::copy(&source, &preview_path).map_err(|error| format!("视频预览失败：{error}"))?;
    } else {
        let ffmpeg = ffmpeg.ok_or_else(|| "未找到 FFmpeg，无法生成视频预览".to_string())?;
        let args: Vec<String> = vec![
            "-hide_banner".into(),
            "-loglevel".into(),
            "error".into(),
            "-nostdin".into(),
            "-y".into(),
            "-i".into(),
            path.to_string(),
            "-map".into(),
            "0:v:0".into(),
            "-c:v".into(),
            "libx264".into(),
            "-preset".into(),
            "veryfast".into(),
            "-crf".into(),
            "23".into(),
            "-pix_fmt".into(),
            "yuv420p".into(),
            "-an".into(),
            "-movflags".into(),
            "+faststart".into(),
            preview_path.to_string_lossy().into_owned(),
        ];
        let outcome = run_with_retry(
            &ffmpeg.to_string_lossy(),
            &args,
            "VIDEO-PREVIEW",
            300,
            1,
            |_message| {},
        );
        let ok = outcome
            .as_ref()
            .map(|value| value.code == Some(0))
            .unwrap_or(false);
        let non_empty = std::fs::metadata(&preview_path)
            .map(|meta| meta.len() > 0)
            .unwrap_or(false);
        if !ok || !non_empty {
            let _ = std::fs::remove_file(&preview_path);
            return Err("视频预览转换失败".to_string());
        }
    }

    Ok(json!({
        "preview_path": crate::engine::paths::display(&crate::engine::paths::absolute(&preview_path)),
        "transcoded": !playable,
    }))
}

/// 判断视频能否被 WebView2 直接播放，返回 `(可直接拷贝, 目标扩展名)`。
///
/// 与 `_webview_playable_plan` 一致：
/// - `.webm` 一律可播
/// - 不在 {mp4, mov, m4v, mkv} 的容器一律转码
/// - 探测不到编码名时按「可播」处理（拷贝原文件，播放失败由前端提示）
fn webview_playable_plan(path: &Path, ffprobe: Option<&Path>) -> (bool, &'static str) {
    let suffix = path
        .extension()
        .map(|value| value.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    // 用 &'static str 会把 suffix 丢掉，这里改为分支返回具体值
    match suffix.as_str() {
        "webm" => return (true, ".webm"),
        "mp4" => {}
        "mov" => {}
        "m4v" => {}
        "mkv" => {}
        _ => return (false, ".mp4"),
    }
    let codec = probe_video_codec(path, ffprobe);
    if codec.is_empty() || matches!(codec.as_str(), "h264" | "vp8" | "vp9" | "hevc") {
        return (true, match suffix.as_str() {
            "mp4" => ".mp4",
            "mov" => ".mov",
            "m4v" => ".m4v",
            _ => ".mkv",
        });
    }
    (false, ".mp4")
}

/// 读取首个视频流的编码名；不可用时返回空字符串（对应 `_probe_video_codec`）。
fn probe_video_codec(path: &Path, ffprobe: Option<&Path>) -> String {
    let Some(ffprobe) = ffprobe else {
        return String::new();
    };
    let path_text = path.to_string_lossy().into_owned();
    let mut command = std::process::Command::new(ffprobe);
    command.args([
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "csv=p=0",
        path_text.as_str(),
    ]);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let Ok(output) = command.output() else {
        return String::new();
    };
    String::from_utf8_lossy(&output.stdout).trim().to_lowercase()
}

/// 浏览器可直接播放的音频封装（与 `_AUDIO_PLAYABLE_EXTENSIONS` 一致）。
/// 这些格式不转码、直接拷贝，既省时间也不会二次损失音质。
const AUDIO_PLAYABLE_EXTENSIONS: [&str; 6] = [".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"];

/// `library_preview_audio`：音频预览缓存。
///
/// 与 `_library_preview_audio` 对齐的要点（写错会静默失效）：
/// - 缓存目录 `audio-previews`、键前缀 `audio-v2`（与 Python 共用同一份缓存）
/// - 可播放格式**直接拷贝**，只有 wma/aiff 之类才转 mp3
/// - 返回字段名是 `preview_path`（前端 `MaterialLibrary.tsx:1063` 只读这个）
pub fn preview_audio(path: &str, ffmpeg: Option<&Path>) -> Result<Value, String> {
    let source = PathBuf::from(path);
    if !source.is_file() {
        return Err("音频文件不存在".to_string());
    }
    let size = std::fs::metadata(&source).map(|meta| meta.len()).unwrap_or(0);
    let suffix = source
        .extension()
        .map(|value| format!(".{}", value.to_string_lossy().to_lowercase()))
        .unwrap_or_default();
    let playable = AUDIO_PLAYABLE_EXTENSIONS.contains(&suffix.as_str());

    let cache_key = format!(
        "audio-v2:{}:{}:{size}",
        crate::engine::paths::display(&crate::engine::paths::absolute(&source)),
        mtime_ns(&source)
    );
    let preview_dir = cache_dir("audio-previews");
    std::fs::create_dir_all(&preview_dir).map_err(|error| error.to_string())?;
    let output_ext = if playable { suffix.as_str() } else { ".mp3" };
    let preview_path = preview_dir.join(format!("{}{output_ext}", sha1_hex(&cache_key)));

    let missing = !preview_path.exists()
        || std::fs::metadata(&preview_path).map(|meta| meta.len()).unwrap_or(0) == 0;
    if missing {
        if playable {
            // 直接拷贝：Python 用 shutil.copy2（保留 mtime），这里同样保留
            std::fs::copy(&source, &preview_path).map_err(|error| error.to_string())?;
        } else {
            let transcoded =
                audio_preview_cache(&source.to_string_lossy(), ffmpeg, "audio-previews", "audio-v2")?;
            if transcoded != preview_path {
                std::fs::copy(&transcoded, &preview_path).map_err(|error| error.to_string())?;
            }
        }
    }

    Ok(json!({
        "preview_path": crate::engine::paths::display(&crate::engine::paths::absolute(&preview_path)),
        "name": source.file_name().map(|value| value.to_string_lossy().into_owned()).unwrap_or_default(),
        "transcoded": !playable,
    }))
}

/// `preview_sequence`：把洗牌后的序列返回给前端（前端拿它渲染「换一组」）。
pub fn preview_sequence(items: &[String], sequence: i64, domain: &str, count: i64) -> Value {
    let sample = if count > 0 {
        super::preview_random::preview_sample(items, count, sequence, domain)
    } else {
        super::preview_random::shuffled(items, domain)
    };
    json!({
        "sequence": sequence,
        "domain": domain,
        "items": sample,
        "count": sample.len(),
    })
}

/// 便捷：拿到 ffmpeg/ffprobe（带缓存）。
pub fn ffmpeg_pair() -> (Option<PathBuf>, Option<PathBuf>) {
    let ffmpeg = system::resolve_ffmpeg(None);
    let ffprobe = system::resolve_ffprobe(None, ffmpeg.as_deref());
    (ffmpeg, ffprobe)
}

/// 供 `library_*` 用：判断扩展名是否是音频。
pub fn is_audio(path: &Path) -> bool {
    library::is_audio_extension(path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sha1_matches_known_vector() {
        // "abc" 的 sha1
        assert_eq!(
            sha1_hex("abc"),
            "a9993e364706816aba3e25717850c26c9cd0d89d"
        );
        assert_eq!(
            sha1_hex(""),
            "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        );
    }

    #[test]
    fn thumbnail_params_clamp_bounds() {
        let mut params = serde_json::Map::new();
        params.insert("max_width".into(), json!(5000));
        params.insert("max_height".into(), json!(1));
        let parsed = ThumbnailParams::from_params(&params);
        assert_eq!(parsed.max_width, 1920);
        assert_eq!(parsed.max_height, 64);
    }

    #[test]
    fn thumbnail_params_defaults() {
        let parsed = ThumbnailParams::from_params(&serde_json::Map::new());
        assert_eq!(parsed.max_width, 960);
        assert_eq!(parsed.max_height, 540);
        assert!(parsed.source.is_empty());
    }

    #[test]
    fn missing_source_errors() {
        let params = ThumbnailParams {
            source: "C:/definitely/missing.png".into(),
            input_dir: String::new(),
            max_width: 960,
            max_height: 540,
        };
        assert!(preview_thumbnail(&params, None, None).is_err());
    }

    #[test]
    fn video_extension_detection() {
        assert!(has_video_extension(Path::new("a.MP4")));
        assert!(has_video_extension(Path::new("a.mkv")));
        assert!(!has_video_extension(Path::new("a.png")));
        assert!(!has_video_extension(Path::new("a")));
    }

    #[test]
    fn cache_dirs_follow_python_layout() {
        let dir = cache_dir("previews");
        assert!(dir.ends_with("image-to-video-engine/previews")
            || dir.to_string_lossy().contains("image-to-video-engine"));
    }

    #[test]
    fn audio_cover_without_file_returns_null() {
        let value = audio_cover("C:/definitely/missing.mp3", None).unwrap();
        assert!(value["cover_path"].is_null());
    }

    #[test]
    fn preview_video_rejects_missing_file() {
        assert!(preview_video("C:/definitely/missing.mp4", None, None).is_err());
    }

    #[test]
    fn preview_sequence_returns_all_when_count_zero() {
        let items: Vec<String> = ["a", "b", "c"].iter().map(|s| s.to_string()).collect();
        let value = preview_sequence(&items, 1, "images", 0);
        assert_eq!(value["count"], 3);
    }

    #[test]
    fn preview_sequence_honours_count() {
        let items: Vec<String> = ["a", "b", "c"].iter().map(|s| s.to_string()).collect();
        let value = preview_sequence(&items, 2, "images", 2);
        assert_eq!(value["count"], 2);
        assert_eq!(value["sequence"], 2);
    }
}