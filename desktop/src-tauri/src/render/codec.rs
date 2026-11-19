//! 编码器与容器解析，对齐 `src/render/codec.py`。
//!
//! 这里只保留**纯解析**部分（扩展名 → muxer / 编码器 / 音频编码器、临时文件名）。
//! Python 版的 `check_codec_availability()` 用 `cv2.VideoWriter` 试探编码器，
//! Rust 不走 OpenCV，改为问 ffmpeg 自己的编码器列表 —— 见 [`available_vcodecs`]。
//! `resolve_cv_fourcc()` 一类只服务 OpenCV 的函数不迁移，因为 Rust 侧没有 cv2 路径。

use std::path::Path;

/// 用户可选的编码器名 → ffmpeg 编码器名。默认 `libx264`。
pub fn ffmpeg_vcodec(selected: &str) -> &'static str {
    match selected {
        "H264" => "libx264",
        "XVID" => "libxvid",
        "MJPG" => "mjpeg",
        "mp4v" => "mpeg4",
        _ => "libx264",
    }
}

/// 输出扩展名（小写）；无扩展名时按 `.mp4` 处理。
pub fn output_extension(output_path: &str) -> String {
    let ext = Path::new(output_path)
        .extension()
        .map(|value| format!(".{}", value.to_string_lossy().to_lowercase()))
        .unwrap_or_default();
    if ext.is_empty() {
        ".mp4".to_string()
    } else {
        ext
    }
}

/// 按目标扩展名生成临时文件路径：`<base>.<suffix><ext>`。
///
/// ⚠️ 这里必须做**纯字符串**处理，不能用 `Path::join`：Python 是
/// `os.path.splitext()` 拼 f-string，输入 `C:/out/v.mp4` 得到 `C:/out/v._tmp.mp4`
/// （保留正斜杠）；用 `Path` 拼接会被换成反斜杠，返回值就和旧版不一致了。
pub fn temp_output_path(output_path: &str, suffix: &str) -> String {
    let ext = output_extension(output_path);
    // 去掉末尾的扩展名（`.` 之前的部分整体保留，包含目录里的点也不影响，因为只砍最后一段）
    let without_ext = if output_path.len() >= ext.len()
        && output_path[output_path.len() - ext.len()..].eq_ignore_ascii_case(&ext)
    {
        &output_path[..output_path.len() - ext.len()]
    } else {
        output_path
    };
    format!("{without_ext}.{suffix}{ext}")
}

/// 扩展名 → ffmpeg muxer；未知扩展名返回 None（交给 ffmpeg 自行推断）。
pub fn muxer_for_output(output_path: &str) -> Option<&'static str> {
    match output_extension(output_path).as_str() {
        ".mp4" => Some("mp4"),
        ".m4v" => Some("mp4"),
        ".mov" => Some("mov"),
        ".avi" => Some("avi"),
        ".mkv" => Some("matroska"),
        _ => None,
    }
}

/// 指定容器兼容的视频编码器候选；`preferred` 命中则提到首位。
pub fn container_vcodecs(output_path: &str, preferred: Option<&str>) -> Vec<String> {
    let ext = output_extension(output_path);
    let mut candidates: Vec<String> = match ext.as_str() {
        ".mp4" => vec!["libx264", "mpeg4"],
        ".m4v" => vec!["libx264", "mpeg4"],
        ".mov" => vec!["libx264", "mpeg4", "prores_ks"],
        ".avi" => vec!["libxvid", "mpeg4", "mjpeg"],
        ".mkv" => vec!["libx264", "mpeg4", "libxvid", "mjpeg"],
        _ => vec!["libx264", "mpeg4", "libxvid", "mjpeg"],
    }
    .into_iter()
    .map(str::to_string)
    .collect();
    if let Some(preferred) = preferred {
        if let Some(index) = candidates.iter().position(|item| item == preferred) {
            let value = candidates.remove(index);
            candidates.insert(0, value);
        }
    }
    candidates
}

/// 指定容器兼容的音频编码器。
pub fn container_acodec(output_path: &str) -> &'static str {
    if output_extension(output_path) == ".avi" {
        "mp3"
    } else {
        "aac"
    }
}

/// 严格编码器：必须是用户所选、且与目标容器兼容；否则返回 None（调用方应报错而非回退）。
pub fn strict_vcodec(output_path: &str, selected: &str) -> Option<&'static str> {
    let wanted = ffmpeg_vcodec(selected);
    let compatible = container_vcodecs(output_path, None);
    compatible
        .iter()
        .find(|item| item.as_str() == wanted)
        .map(|_| wanted)
}

/// 从 `ffmpeg -encoders` 的输出里解析可用视频编码器名。
pub fn parse_encoder_list(text: &str) -> Vec<String> {
    let mut names = Vec::new();
    for line in text.lines() {
        let trimmed = line.trim_start();
        // 形如 " V..... libx264              H.264 / AVC ..."
        if !trimmed.starts_with('V') {
            continue;
        }
        let rest = trimmed[1..].trim_start();
        // 跳过类型标记（F/S/X/B/D 等）直到名字
        let mut parts = rest.split_whitespace();
        let Some(first) = parts.next() else { continue };
        let name = if first.chars().all(|ch| "FSXBD.".contains(ch)) {
            match parts.next() {
                Some(value) => value,
                None => continue,
            }
        } else {
            first
        };
        if name.starts_with('=') {
            continue;
        }
        names.push(name.to_string());
    }
    names
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extension_is_lowercased_and_defaults_to_mp4() {
        assert_eq!(output_extension("a.mp4"), ".mp4");
        assert_eq!(output_extension("b.MKV"), ".mkv");
        assert_eq!(output_extension("no_ext"), ".mp4");
        assert_eq!(output_extension("g.MP4"), ".mp4");
    }

    #[test]
    fn temp_path_keeps_target_extension() {
        assert_eq!(temp_output_path("C:/out/v.mp4", "_tmp"), "C:/out/v._tmp.mp4");
        assert_eq!(temp_output_path("v.mkv", "temp"), "v.temp.mkv");
        assert_eq!(temp_output_path("no_ext", "_x"), "no_ext._x.mp4");
    }

    #[test]
    fn muxer_mapping_matches_python() {
        assert_eq!(muxer_for_output("a.mp4"), Some("mp4"));
        assert_eq!(muxer_for_output("a.m4v"), Some("mp4"));
        assert_eq!(muxer_for_output("a.mov"), Some("mov"));
        assert_eq!(muxer_for_output("a.avi"), Some("avi"));
        assert_eq!(muxer_for_output("a.mkv"), Some("matroska"));
        assert_eq!(muxer_for_output("a.webm"), None);
    }

    #[test]
    fn acodec_is_mp3_only_for_avi() {
        assert_eq!(container_acodec("a.avi"), "mp3");
        assert_eq!(container_acodec("a.mp4"), "aac");
        assert_eq!(container_acodec("a.mkv"), "aac");
    }

    #[test]
    fn container_codecs_follow_the_python_table() {
        assert_eq!(container_vcodecs("a.mp4", None), vec!["libx264", "mpeg4"]);
        assert_eq!(
            container_vcodecs("a.mov", None),
            vec!["libx264", "mpeg4", "prores_ks"]
        );
        assert_eq!(
            container_vcodecs("a.avi", None),
            vec!["libxvid", "mpeg4", "mjpeg"]
        );
        assert_eq!(
            container_vcodecs("a.webm", None),
            vec!["libx264", "mpeg4", "libxvid", "mjpeg"]
        );
    }

    #[test]
    fn preferred_codec_moves_to_front_only_when_compatible() {
        assert_eq!(
            container_vcodecs("a.mp4", Some("mpeg4")),
            vec!["mpeg4", "libx264"]
        );
        // mjpeg 不在 mp4 的兼容列表里，顺序不变
        assert_eq!(
            container_vcodecs("a.mp4", Some("mjpeg")),
            vec!["libx264", "mpeg4"]
        );
    }

    #[test]
    fn strict_codec_rejects_incompatible_selection() {
        // 用户选 XVID（libxvid），mp4 容器不支持 → None
        assert_eq!(strict_vcodec("a.mp4", "XVID"), None);
        assert_eq!(strict_vcodec("a.avi", "XVID"), Some("libxvid"));
        assert_eq!(strict_vcodec("a.mp4", "H264"), Some("libx264"));
        // 未知编码器名默认落到 libx264
        assert_eq!(strict_vcodec("a.mp4", "不存在的编码器"), Some("libx264"));
    }

    #[test]
    fn encoder_list_parsing_skips_flags_and_headers() {
        let sample = "\
Encoders:
 V..... = Video
 ------
 V....D libx264              H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D libxvid              libxvidcore MPEG-4 part 2 (codec mpeg4)
 V....D mjpeg                MJPEG (Motion JPEG)
 A....D aac                  AAC (Advanced Audio Coding)
";
        let names = parse_encoder_list(sample);
        assert!(names.contains(&"libx264".to_string()));
        assert!(names.contains(&"libxvid".to_string()));
        assert!(names.contains(&"mjpeg".to_string()));
        assert!(!names.contains(&"aac".to_string()));
        assert!(!names.contains(&"=".to_string()));
    }
}