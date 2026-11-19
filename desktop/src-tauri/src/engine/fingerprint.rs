//! BGM 音频指纹，逐位对齐 `src/engine/library.py` 的 `_rms_signature`。
//!
//! 用途：识别「同一首歌的不同码率/格式副本」。指纹不一致 → 同一首歌被判成两首，
//! 导入去重和「查找重复」全部失效。所以这里的采样率、声道、样本宽度、
//! 每秒切块方式、除以 32768 的缩放都必须与 Python 一字不差。
//!
//! 解码参数：16 kHz / 单声道 / s16le / 最多前 180 秒；
//! 每秒一块算 RMS；`duration = 秒数`（不是精确媒体时长）。

use std::path::Path;
use std::process::Command;

use super::system;

pub const SAMPLE_RATE: usize = 16000;
pub const CHANNELS: usize = 1;
pub const SAMPLE_WIDTH: usize = 2;
pub const MAX_SECONDS: u32 = 180;

#[derive(Debug, Clone, PartialEq)]
pub struct Fingerprint {
    pub duration: f64,
    pub signature: Vec<f64>,
}

/// 与 `compute_audio_fingerprint()` 等价：无 ffmpeg / 解码失败 / 音频过短返回 None。
pub fn compute(ffmpeg: Option<&Path>, path: &Path) -> Option<Fingerprint> {
    let ffmpeg = ffmpeg?;
    if !path.is_file() {
        return None;
    }
    let path_text = path.to_string_lossy().into_owned();
    let max_seconds = MAX_SECONDS.to_string();
    let channels = CHANNELS.to_string();
    let sample_rate = SAMPLE_RATE.to_string();
    let mut command = Command::new(ffmpeg);
    command.args([
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-t",
        max_seconds.as_str(),
        "-i",
        path_text.as_str(),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        channels.as_str(),
        "-ar",
        sample_rate.as_str(),
        "-f",
        "s16le",
        "-",
    ]);
    system::hide_console(&mut command);

    let output = command.output().ok()?;
    if !output.status.success() || output.stdout.is_empty() {
        return None;
    }
    let signature = rms_signature(&output.stdout);
    if signature.is_empty() {
        return None;
    }
    Some(Fingerprint { duration: signature.len() as f64, signature })
}

/// 把 16 位小端 PCM 切成每秒一块，返回每秒 RMS（0..1）。
pub fn rms_signature(pcm: &[u8]) -> Vec<f64> {
    let bytes_per_second = SAMPLE_RATE * SAMPLE_WIDTH;
    let second_count = pcm.len() / bytes_per_second;
    if second_count < 1 {
        return Vec::new();
    }
    let mut signature = Vec::with_capacity(second_count);
    for index in 0..second_count {
        let chunk = &pcm[index * bytes_per_second..(index + 1) * bytes_per_second];
        let sample_count = chunk.len() / SAMPLE_WIDTH;
        if sample_count == 0 {
            signature.push(0.0);
            continue;
        }
        let mut sum = 0.0f64;
        for sample_index in 0..sample_count {
            let low = chunk[sample_index * SAMPLE_WIDTH] as u16;
            let high = chunk[sample_index * SAMPLE_WIDTH + 1] as u16;
            let value = (low | (high << 8)) as i16 as f64;
            sum += value * value;
        }
        let mean_square = sum / sample_count as f64;
        signature.push(mean_square.sqrt() / 32768.0);
    }
    signature
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pcm_from(samples: &[i16]) -> Vec<u8> {
        samples
            .iter()
            .flat_map(|sample| sample.to_le_bytes())
            .collect()
    }

    #[test]
    fn silent_audio_gives_zero_rms() {
        let pcm = pcm_from(&vec![0i16; SAMPLE_RATE]);
        let signature = rms_signature(&pcm);
        assert_eq!(signature.len(), 1);
        assert_eq!(signature[0], 0.0);
    }

    #[test]
    fn full_scale_audio_approaches_one() {
        let pcm = pcm_from(&vec![i16::MAX; SAMPLE_RATE]);
        let signature = rms_signature(&pcm);
        assert_eq!(signature.len(), 1);
        assert!((signature[0] - (i16::MAX as f64 / 32768.0)).abs() < 1e-12);
    }

    #[test]
    fn splits_per_second_and_keeps_partial_tail_out() {
        // 1.5 秒：只保留整秒，与 Python 的 `len(pcm) // bytes_per_second` 一致
        let mut samples = vec![0i16; SAMPLE_RATE];
        samples.extend(vec![i16::MAX; SAMPLE_RATE / 2]);
        let signature = rms_signature(&pcm_from(&samples));
        assert_eq!(signature.len(), 1);
    }

    #[test]
    fn too_short_audio_has_no_signature() {
        let signature = rms_signature(&pcm_from(&vec![0i16; SAMPLE_RATE / 2]));
        assert!(signature.is_empty());
    }

    #[test]
    fn missing_file_or_ffmpeg_returns_none() {
        assert!(compute(None, Path::new("nope.mp3")).is_none());
        assert!(compute(Some(Path::new("ffmpeg")), Path::new("nope.mp3")).is_none());
    }
}
