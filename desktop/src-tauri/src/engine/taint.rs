//! 假字幕轨/异常数据轨的体检与清洗。
//!
//! 与 `src/engine/library.py` 的 `_probe_streams` / `_taint_reason` /
//! `_tainted_indexes` / `_clean_tainted_file` 及 `src/engine/mp4_strip.py` 逐条对齐。
//!
//! 清洗分两条路：
//! - mp4/mov 系（moov 容器）：box 级删除 trak 与 tref 引用，媒体数据一个字节不动；
//! - 其它容器：FFmpeg 流复制重封装，只保留正常音视频轨。

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::{json, Value};

use super::library;
use super::paths;
use super::snapshot::{self, AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS};
use super::system;
use super::write_ops;

/// 水印库同时接受图片与视频素材（与 Python 的 `IMAGE_EXTENSIONS | VIDEO_EXTENSIONS` 一致）。
fn is_watermark_extension(path: &Path) -> bool {
    has_extension(path, &IMAGE_EXTENSIONS) || has_extension(path, &VIDEO_EXTENSIONS)
}

const BOX_HEADER: usize = 8;

const MOOV_CONTAINERS: [&str; 7] = [".mp4", ".mov", ".m4a", ".m4v", ".3gp", ".f4v", ".qt"];

// ---------- ffprobe ----------

/// 探测全部流。失败返回空列表（调用方按「无法探测」处理，不阻断扫描）。
pub(crate) fn probe_streams(ffprobe: Option<&Path>, path: &Path) -> Vec<Value> {
    let Some(ffprobe) = ffprobe else {
        return Vec::new();
    };
    if !path.is_file() {
        return Vec::new();
    }
    let mut command = Command::new(ffprobe);
    command.args([
        "-v",
        "error",
        "-show_entries",
        "stream=index,codec_type,codec_name,duration:stream_disposition=attached_pic",
        "-of",
        "json",
    ]);
    command.arg(path);
    system::hide_console(&mut command);
    let output = match command.output() {
        Ok(output) => output,
        Err(_) => return Vec::new(),
    };
    let text = String::from_utf8_lossy(&output.stdout);
    let data: Value = match serde_json::from_str(&text) {
        Ok(value) => value,
        Err(_) => return Vec::new(),
    };
    let mut streams = Vec::new();
    for raw in data
        .get("streams")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
    {
        if !raw.is_object() {
            continue;
        }
        let attached_pic = raw
            .get("disposition")
            .and_then(|value| value.get("attached_pic"))
            .map(is_truthy)
            .unwrap_or(false);
        streams.push(json!({
            "index": raw.get("index").and_then(Value::as_i64).unwrap_or(0),
            "codec_type": raw.get("codec_type").and_then(Value::as_str).unwrap_or(""),
            "codec_name": raw.get("codec_name").and_then(Value::as_str).unwrap_or(""),
            "duration": raw.get("duration").cloned().unwrap_or(Value::Null),
            "attached_pic": attached_pic,
        }));
    }
    streams
}

fn is_truthy(value: &Value) -> bool {
    match value {
        Value::Bool(flag) => *flag,
        Value::Number(number) => number.as_f64().map(|v| v != 0.0).unwrap_or(false),
        Value::String(text) => !text.is_empty(),
        _ => false,
    }
}

fn codec_type(stream: &Value) -> &str {
    stream.get("codec_type").and_then(Value::as_str).unwrap_or("")
}

fn codec_name(stream: &Value) -> &str {
    stream.get("codec_name").and_then(Value::as_str).unwrap_or("")
}

/// Python 里 `duration` 只在是数字时才格式化，ffprobe 的 JSON 给的是字符串，
/// 所以这里同样保留字符串形态、文案落「未知时长」。
fn duration_text(stream: &Value) -> String {
    match stream.get("duration").and_then(Value::as_f64) {
        Some(seconds) => format!("{seconds:.1} 秒"),
        None => "未知时长".to_string(),
    }
}

/// 与 `_taint_reason()` 一致：返回异常原因，正常返回 None。
pub(crate) fn taint_reason(streams: &[Value], kind: &str) -> Option<String> {
    for stream in streams {
        let kind_type = codec_type(stream);
        let name = codec_name(stream);
        let text = duration_text(stream);
        if kind_type == "subtitle" {
            return Some(format!("含字幕轨（{name}，{text}）"));
        }
        if kind_type == "data" || name == "bin_data" || name == "text" {
            let shown_name = if name.is_empty() { kind_type } else { name };
            return Some(format!("含异常数据轨（{shown_name}，{text}）"));
        }
        if kind == "bgm" && kind_type == "video" && !is_truthy(stream.get("attached_pic").unwrap_or(&Value::Null)) {
            return Some(format!("音频文件含视频轨（{name}，{text}）"));
        }
    }
    None
}

/// 与 `_tainted_indexes()` 一致：异常流的序号集合。
fn tainted_indexes(streams: &[Value], kind: &str) -> BTreeSet<i64> {
    let mut indexes = BTreeSet::new();
    for stream in streams {
        let kind_type = codec_type(stream);
        let name = codec_name(stream);
        let index = stream.get("index").and_then(Value::as_i64).unwrap_or(0);
        if kind_type == "subtitle" {
            indexes.insert(index);
        } else if kind_type == "data" || name == "bin_data" || name == "text" {
            indexes.insert(index);
        } else if kind == "bgm"
            && kind_type == "video"
            && !is_truthy(stream.get("attached_pic").unwrap_or(&Value::Null))
        {
            indexes.insert(index);
        }
    }
    indexes
}

// ---------- mp4 box 解析 ----------

fn read_u32(data: &[u8], offset: usize) -> Option<u64> {
    let slice = data.get(offset..offset + 4)?;
    Some(u32::from_be_bytes([slice[0], slice[1], slice[2], slice[3]]) as u64)
}

fn read_u64(data: &[u8], offset: usize) -> Option<u64> {
    let slice = data.get(offset..offset + 8)?;
    let mut bytes = [0u8; 8];
    bytes.copy_from_slice(slice);
    Some(u64::from_be_bytes(bytes))
}

/// 迭代 [start, end) 内的 box，产出 (start, end, 类型)。
fn box_iter(data: &[u8], start: usize, end: usize) -> Vec<(usize, usize, [u8; 4])> {
    let mut boxes = Vec::new();
    let mut offset = start;
    while offset + BOX_HEADER <= end {
        let mut size = match read_u32(data, offset) {
            Some(value) => value as usize,
            None => break,
        };
        let mut box_type = [0u8; 4];
        box_type.copy_from_slice(&data[offset + 4..offset + 8]);
        let mut header = BOX_HEADER;
        if size == 1 {
            size = match read_u64(data, offset + 8) {
                Some(value) => value as usize,
                None => break,
            };
            header = 16;
        } else if size == 0 {
            size = end - offset;
        }
        if size < header || offset + size > end {
            break;
        }
        boxes.push((offset, offset + size, box_type));
        offset += size;
    }
    boxes
}

fn find_box(data: &[u8], start: usize, end: usize, target: &[u8; 4]) -> Option<(usize, usize)> {
    box_iter(data, start, end)
        .into_iter()
        .find(|(_, _, box_type)| box_type == target)
        .map(|(box_start, box_end, _)| (box_start, box_end))
}

/// 读取 trak 内 mdia/hdlr 的 handler 类型（vide/soun/text/…）。
fn handler_of_trak(data: &[u8], trak_start: usize, trak_end: usize) -> Option<String> {
    let (mdia_start, mdia_end) = find_box(data, trak_start + BOX_HEADER, trak_end, b"mdia")?;
    let (hdlr_start, hdlr_end) = find_box(data, mdia_start + BOX_HEADER, mdia_end, b"hdlr")?;
    if hdlr_end - hdlr_start < 24 {
        return None;
    }
    let raw = data.get(hdlr_start + 16..hdlr_start + 20)?;
    Some(raw.iter().map(|byte| *byte as char).collect())
}

/// 读取 trak 内 mdhd 的时长（秒）；失败返回 0。
fn trak_seconds(data: &[u8], trak_start: usize, trak_end: usize) -> f64 {
    let Some((mdia_start, mdia_end)) = find_box(data, trak_start + BOX_HEADER, trak_end, b"mdia") else {
        return 0.0;
    };
    let Some((mdhd_start, mdhd_end)) = find_box(data, mdia_start + BOX_HEADER, mdia_end, b"mdhd") else {
        return 0.0;
    };
    if mdhd_end - mdhd_start < 32 {
        return 0.0;
    }
    let version = data[mdhd_start + 8];
    let base = mdhd_start + 12;
    let (timescale, duration) = if version == 1 {
        (read_u32(data, base + 16), read_u64(data, base + 20))
    } else {
        (read_u32(data, base + 8), read_u32(data, base + 12))
    };
    let (Some(timescale), Some(duration)) = (timescale, duration) else {
        return 0.0;
    };
    if timescale == 0 {
        return 0.0;
    }
    duration as f64 / timescale as f64
}

/// 把 moov 内 mvhd 的 duration 改写为给定秒数（timescale 单位）。
fn patch_mvhd_duration(moov: &[u8], seconds: f64) -> Vec<u8> {
    let mut result = moov.to_vec();
    let Some((mvhd_start, mvhd_end)) = find_box(&result, BOX_HEADER, result.len(), b"mvhd") else {
        return result;
    };
    let _ = mvhd_end;
    let version = result[mvhd_start + 8];
    let (timescale, duration_offset) = if version == 1 {
        (
            read_u32(&result, mvhd_start + 12 + 16),
            mvhd_start + 12 + 20,
        )
    } else {
        (read_u32(&result, mvhd_start + 12 + 8), mvhd_start + 12 + 12)
    };
    let Some(timescale) = timescale else {
        return result;
    };
    if timescale == 0 {
        return result;
    }
    let new_duration = (seconds * timescale as f64).round().max(0.0) as u64;
    if version == 1 {
        if duration_offset + 8 <= result.len() {
            result[duration_offset..duration_offset + 8].copy_from_slice(&new_duration.to_be_bytes());
        }
    } else {
        let capped = new_duration.min(u32::MAX as u64) as u32;
        if duration_offset + 4 <= result.len() {
            result[duration_offset..duration_offset + 4].copy_from_slice(&capped.to_be_bytes());
        }
    }
    result
}

pub(crate) fn has_moov_container(suffix: &str) -> bool {
    MOOV_CONTAINERS.contains(&suffix.to_lowercase().as_str())
}

/// 与 `strip_tainted_tracks()` 一致：删除指定 acc 轨与章节引用，写入 target。
fn strip_tainted_tracks(source: &Path, tainted: &BTreeSet<i64>, target: &Path) -> Result<String, String> {
    let data = fs::read(source).map_err(|error| format!("读取失败: {error}"))?;
    if data.is_empty() {
        return Err("文件为空".to_string());
    }
    let Some((moov_start, moov_end)) = find_box(&data, 0, data.len(), b"moov") else {
        return Err("未找到 moov（可能不是 MP4/MOV 文件）".to_string());
    };
    let moov = &data[moov_start..moov_end];
    let moov_header = &moov[..BOX_HEADER];
    let body_start = BOX_HEADER;

    let traks: Vec<(usize, usize)> = box_iter(moov, body_start, moov.len())
        .into_iter()
        .filter(|(_, _, box_type)| box_type == b"trak")
        .map(|(start, end, _)| (start, end))
        .collect();
    if traks.is_empty() {
        return Err("moov 中没有 trak".to_string());
    }
    let drop_indexes: BTreeSet<i64> = tainted
        .iter()
        .copied()
        .filter(|index| *index >= 0 && (*index as usize) < traks.len())
        .collect();
    if drop_indexes.is_empty() {
        return Err("未找到需要删除的轨道".to_string());
    }

    let mut rebuilt: Vec<u8> = Vec::new();
    let mut kept_seconds: Vec<f64> = Vec::new();
    let mut trak_pos: i64 = 0;
    for (box_start, box_end, box_type) in box_iter(moov, body_start, moov.len()) {
        if box_type != *b"trak" {
            rebuilt.extend_from_slice(&moov[box_start..box_end]);
            continue;
        }
        let index = trak_pos;
        trak_pos += 1;
        let handler = handler_of_trak(moov, box_start, box_end);
        let is_text = handler
            .as_deref()
            .map(|value| value.to_lowercase() == "text")
            .unwrap_or(false);
        if drop_indexes.contains(&index) || is_text {
            continue;
        }
        kept_seconds.push(trak_seconds(moov, box_start, box_end));
        let chunk = &moov[box_start..box_end];
        let mut body: Vec<u8> = Vec::new();
        let mut removed_tref = false;
        for (sub_start, sub_end, sub_type) in box_iter(chunk, BOX_HEADER, chunk.len()) {
            if sub_type == *b"tref" {
                removed_tref = true;
                continue;
            }
            body.extend_from_slice(&chunk[sub_start..sub_end]);
        }
        if removed_tref {
            let size = (BOX_HEADER + body.len()) as u32;
            rebuilt.extend_from_slice(&size.to_be_bytes());
            rebuilt.extend_from_slice(&chunk[4..BOX_HEADER]);
            rebuilt.extend_from_slice(&body);
        } else {
            rebuilt.extend_from_slice(chunk);
        }
    }

    let mut new_moov: Vec<u8> = moov_header.to_vec();
    new_moov.extend_from_slice(&rebuilt);
    let new_moov_len = new_moov.len() as u32;
    new_moov[..4].copy_from_slice(&new_moov_len.to_be_bytes());
    if let Some(max_seconds) = kept_seconds.iter().copied().fold(None::<f64>, |acc, value| {
        Some(match acc {
            Some(current) => current.max(value),
            None => value,
        })
    }) {
        if max_seconds > 0.0 {
            new_moov = patch_mvhd_duration(&new_moov, max_seconds);
        }
    }

    // 原位替换 moov，剩余空间补 free box（保持布局与 mdat 偏移不变，stco 依然有效）
    let moov_len = moov_end - moov_start;
    if new_moov.len() > moov_len {
        return Err("重建后 moov 变大（异常），已中止".to_string());
    }
    let padding = moov_len - new_moov.len();
    if padding > 8 {
        new_moov.extend_from_slice(&(padding as u32).to_be_bytes());
        new_moov.extend_from_slice(b"free");
        new_moov.extend(std::iter::repeat(0u8).take(padding - 8));
    } else if padding > 0 {
        new_moov.extend(std::iter::repeat(0u8).take(padding));
    }

    let mut output: Vec<u8> = Vec::with_capacity(data.len());
    output.extend_from_slice(&data[..moov_start]);
    output.extend_from_slice(&new_moov);
    output.extend_from_slice(&data[moov_end..]);
    fs::write(target, &output).map_err(|error| format!("写入失败: {error}"))?;
    Ok(format!("已删除 {} 条异常轨并移除章节引用", drop_indexes.len()))
}

// ---------- 清洗单个文件 ----------

fn has_extension(path: &Path, extensions: &[&str]) -> bool {
    path.extension()
        .map(|value| format!(".{}", value.to_string_lossy().to_lowercase()))
        .map(|suffix| extensions.contains(&suffix.as_str()))
        .unwrap_or(false)
}

fn run_ffmpeg(args: &[String], timeout_seconds: u64) -> Option<std::process::Output> {
    use std::time::{Duration, Instant};

    let mut command = Command::new(&args[0]);
    command.args(&args[1..]);
    system::hide_console(&mut command);
    let mut child = command
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .ok()?;
    let deadline = Instant::now() + Duration::from_secs(timeout_seconds);
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return child.wait_with_output().ok(),
            Ok(None) => {}
            Err(_) => return None,
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            return None;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

fn clean_file(ffmpeg: Option<&Path>, ffprobe: Option<&Path>, path: &Path) -> Value {
    let streams = probe_streams(ffprobe, path);
    let kind = if has_extension(path, &AUDIO_EXTENSIONS) {
        "bgm"
    } else {
        "watermark"
    };
    let indexes = tainted_indexes(&streams, kind);
    if indexes.is_empty() {
        return json!({ "ok": false, "reason": "未检测到异常轨，跳过" });
    }

    let suffix = path
        .extension()
        .map(|value| format!(".{}", value.to_string_lossy()))
        .unwrap_or_default();
    let stem = path
        .file_stem()
        .map(|value| value.to_string_lossy().into_owned())
        .unwrap_or_default();
    let temporary: PathBuf = path.with_file_name(format!(
        ".{stem}.clean-{}.tmp{suffix}",
        std::process::id()
    ));

    let cleanup = |temporary: &Path| {
        let _ = fs::remove_file(temporary);
    };

    if has_moov_container(&suffix) {
        match strip_tainted_tracks(path, &indexes, &temporary) {
            Ok(_) => {
                let size = fs::metadata(&temporary).map(|meta| meta.len()).unwrap_or(0);
                if size == 0 {
                    cleanup(&temporary);
                    return json!({ "ok": false, "reason": "清洗失败: 输出为空" });
                }
            }
            Err(message) => {
                cleanup(&temporary);
                return json!({ "ok": false, "reason": format!("清洗失败: {message}") });
            }
        }
    } else {
        let Some(ffmpeg) = ffmpeg else {
            return json!({ "ok": false, "reason": "FFmpeg 不可用" });
        };
        let lower = suffix.to_lowercase();
        let mut args: Vec<String> = vec![
            ffmpeg.to_string_lossy().into_owned(),
            "-y".into(),
            "-i".into(),
            path.to_string_lossy().into_owned(),
        ];
        if AUDIO_EXTENSIONS.contains(&lower.as_str()) {
            args.extend(["-map".into(), "0:a".into(), "-map".into(), "0:v?".into()]);
        } else if VIDEO_EXTENSIONS.contains(&lower.as_str()) {
            args.extend(["-map".into(), "0:v".into(), "-map".into(), "0:a?".into()]);
        } else {
            return json!({ "ok": false, "reason": format!("不支持的文件类型: {lower}") });
        }
        args.extend([
            "-c".into(),
            "copy".into(),
            "-map_metadata".into(),
            "0".into(),
            "-movflags".into(),
            "+faststart".into(),
            temporary.to_string_lossy().into_owned(),
        ]);
        let ok = run_ffmpeg(&args, 240).is_some();
        let size = fs::metadata(&temporary).map(|meta| meta.len()).unwrap_or(0);
        if !ok || size == 0 {
            cleanup(&temporary);
            return json!({ "ok": false, "reason": "重封装失败" });
        }
    }

    if let Err(error) = write_ops::trash_file(path) {
        cleanup(&temporary);
        return json!({ "ok": false, "reason": format!("替换原文件失败: {error}") });
    }
    if let Err(error) = fs::rename(&temporary, path) {
        cleanup(&temporary);
        return json!({ "ok": false, "reason": format!("替换原文件失败: {error}") });
    }
    json!({ "ok": true })
}

// ---------- 对外接口 ----------

pub fn scan_tainted(params: &serde_json::Map<String, Value>) -> Result<Value, String> {
    let kind = text(params, "kind");
    let kind = if kind.is_empty() { "bgm".to_string() } else { kind };
    if kind != "bgm" && kind != "watermark" {
        return Err("kind 必须是 bgm 或 watermark".to_string());
    }
    let (_, bgm, watermark) = library::default_paths();
    let base = if kind == "bgm" {
        snapshot::resolve_dir(params, "bgm_dir", &bgm)
    } else {
        snapshot::resolve_dir(params, "watermark_dir", &watermark)
    };
    if !base.is_dir() {
        return Ok(json!({ "scanned": 0, "tainted": [] }));
    }
    let accepts = |path: &Path| -> bool {
        if kind == "bgm" {
            has_extension(path, &AUDIO_EXTENSIONS)
        } else {
            is_watermark_extension(path)
        }
    };
    let ffprobe = system::resolve_ffprobe(None, system::resolve_ffmpeg(None).as_deref());

    let mut files = Vec::new();
    collect_files(&base, &mut files);
    files.sort();
    let mut scanned = 0usize;
    let mut findings: Vec<Value> = Vec::new();
    for path in files {
        if !path.is_file() || !accepts(&path) {
            continue;
        }
        scanned += 1;
        let streams = probe_streams(ffprobe.as_deref(), &path);
        let Some(taint) = taint_reason(&streams, &kind) else {
            continue;
        };
        let folder = path
            .parent()
            .and_then(|parent| parent.strip_prefix(&base).ok())
            .map(|value| value.to_string_lossy().replace('\\', "/"))
            .unwrap_or_default();
        let size_bytes = fs::metadata(&path).map(|meta| meta.len()).unwrap_or(0);
        findings.push(json!({
            "path": paths::display(&paths::absolute(&path)),
            "name": path.file_name().map(|value| value.to_string_lossy().into_owned()).unwrap_or_default(),
            "folder": folder,
            "size_bytes": size_bytes,
            "taint": taint,
            "streams": streams,
        }));
    }
    Ok(json!({ "scanned": scanned, "tainted": findings }))
}

pub fn clean_tainted(params: &serde_json::Map<String, Value>) -> Result<Value, String> {
    let raw_paths = params
        .get("paths")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if raw_paths.is_empty() {
        return Err("请先选择要清洗的文件".to_string());
    }
    let ffmpeg = system::resolve_ffmpeg(None);
    let ffprobe = system::resolve_ffprobe(None, ffmpeg.as_deref());

    let mut results: Vec<Value> = Vec::new();
    let mut cleaned = 0usize;
    for raw in raw_paths {
        let raw_text = raw.as_str().unwrap_or_default().to_string();
        let path = PathBuf::from(&raw_text);
        if !path.is_file() {
            results.push(json!({ "path": raw_text, "ok": false, "reason": "文件不存在" }));
            continue;
        }
        let outcome = clean_file(ffmpeg.as_deref(), ffprobe.as_deref(), &path);
        if outcome.get("ok").and_then(Value::as_bool).unwrap_or(false) {
            cleaned += 1;
        }
        let mut object = serde_json::Map::new();
        object.insert("path".to_string(), json!(paths::display(&paths::absolute(&path))));
        if let Value::Object(inner) = outcome {
            for (key, value) in inner {
                object.insert(key, value);
            }
        }
        results.push(Value::Object(object));
    }
    Ok(json!({ "results": results, "cleaned": cleaned }))
}

fn text(params: &serde_json::Map<String, Value>, key: &str) -> String {
    params
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_string()
}

fn collect_files(directory: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(directory) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_files(&path, out);
        } else {
            out.push(path);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json as value;

    fn stream(kind: &str, name: &str, index: i64, attached: bool) -> Value {
        value!({
            "index": index,
            "codec_type": kind,
            "codec_name": name,
            "duration": "12.500000",
            "attached_pic": attached,
        })
    }

    #[test]
    fn subtitle_stream_is_tainted() {
        let streams = vec![stream("audio", "aac", 0, false), stream("subtitle", "mov_text", 1, false)];
        let reason = taint_reason(&streams, "bgm").expect("应判为异常");
        assert_eq!(reason, "含字幕轨（mov_text，未知时长）");
        assert_eq!(tainted_indexes(&streams, "bgm"), BTreeSet::from([1]));
    }

    #[test]
    fn embedded_cover_is_not_tainted() {
        let streams = vec![stream("audio", "mp3", 0, false), stream("video", "mjpeg", 1, true)];
        assert!(taint_reason(&streams, "bgm").is_none());
        assert!(tainted_indexes(&streams, "bgm").is_empty());
    }

    #[test]
    fn video_stream_in_bgm_is_tainted_but_ok_in_watermark() {
        let streams = vec![stream("video", "h264", 0, false)];
        assert!(taint_reason(&streams, "bgm").is_some());
        assert!(taint_reason(&streams, "watermark").is_none());
    }

    #[test]
    fn data_stream_and_chapter_text_are_tainted() {
        let streams = vec![stream("data", "bin_data", 2, false)];
        assert!(taint_reason(&streams, "watermark").expect("data 轨异常").contains("异常数据轨"));
        let text_track = vec![stream("audio", "text", 1, false)];
        assert!(taint_reason(&text_track, "watermark").is_some());
    }

    #[test]
    fn numeric_duration_is_formatted() {
        let streams = vec![value!({
            "index": 0,
            "codec_type": "subtitle",
            "codec_name": "srt",
            "duration": 3.25,
            "attached_pic": false,
        })];
        assert_eq!(
            taint_reason(&streams, "watermark").expect("异常"),
            "含字幕轨（srt，3.2 秒）"
        );
    }

    #[test]
    fn box_iter_walks_children_and_stops_on_garbage() {
        let mut data: Vec<u8> = Vec::new();
        data.extend_from_slice(&16u32.to_be_bytes());
        data.extend_from_slice(b"ftyp");
        data.extend_from_slice(b"isomisom");
        data.extend_from_slice(&8u32.to_be_bytes());
        data.extend_from_slice(b"free");
        let boxes = box_iter(&data, 0, data.len());
        assert_eq!(boxes.len(), 2);
        assert_eq!(boxes[0].2, *b"ftyp");
        assert_eq!(boxes[1].2, *b"free");
    }

    #[test]
    fn moov_container_extensions() {
        assert!(has_moov_container(".MP4"));
        assert!(has_moov_container(".m4a"));
        assert!(!has_moov_container(".mkv"));
    }
}
