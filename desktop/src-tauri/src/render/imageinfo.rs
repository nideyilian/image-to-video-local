//! 从文件头读图片尺寸，不解码像素。
//!
//! 后处理算水印几何时只需要「这张图多宽多高」，Python 版用
//! `cv2.imdecode(...).shape` 拿尺寸，等于把整张图解码进内存。
//! Rust 侧只解析文件头，快且零风险 —— 尺寸读错只影响水印大小，不会影响像素。
//!
//! 覆盖格式：PNG / JPEG / GIF / BMP / WEBP（含 VP8 / VP8L / VP8X）。

use std::fs::File;
use std::io::SeekFrom;
use std::io::{Read, Seek};
use std::path::Path;

/// 图片尺寸。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ImageSize {
    pub width: i64,
    pub height: i64,
}

/// 读图片尺寸；不认识的格式或读失败返回 None。
pub fn image_size(path: &Path) -> Option<ImageSize> {
    let mut file = File::open(path).ok()?;
    let mut head = [0u8; 32];
    let read = file.read(&mut head).ok()?;
    if read < 8 {
        return None;
    }

    if head[..8] == [0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A] {
        return png_size(&mut file);
    }
    if head[..2] == [0xFF, 0xD8] {
        return jpeg_size(&mut file);
    }
    if &head[..6] == b"GIF87a" || &head[..6] == b"GIF89a" {
        return Some(ImageSize {
            width: u16::from_le_bytes([head[6], head[7]]) as i64,
            height: u16::from_le_bytes([head[8], head[9]]) as i64,
        });
    }
    if &head[..2] == b"BM" {
        let width = i32::from_le_bytes([head[18], head[19], head[20], head[21]]);
        let height = i32::from_le_bytes([head[22], head[23], head[24], head[25]]);
        return Some(ImageSize {
            width: width.unsigned_abs() as i64,
            height: height.unsigned_abs() as i64,
        });
    }
    if &head[..4] == b"RIFF" && &head[8..12] == b"WEBP" {
        return webp_size(&mut file);
    }
    None
}

fn png_size(file: &mut File) -> Option<ImageSize> {
    // PNG：8 字节签名 + 4 字节长度 + 4 字节类型 + IHDR 宽高（大端）
    // 调用方已经读过前 32 字节，这里回到偏移 12 只读「类型 + 宽 + 高」共 12 字节，
    // 不依赖文件还有多少尾巴（最小合法 PNG 也不止 24 字节，但少读一点更稳）。
    file.seek(SeekFrom::Start(12)).ok()?;
    let mut buffer = [0u8; 12];
    file.read_exact(&mut buffer).ok()?;
    if &buffer[..4] != b"IHDR" {
        return None;
    }
    Some(ImageSize {
        width: u32::from_be_bytes([buffer[4], buffer[5], buffer[6], buffer[7]]) as i64,
        height: u32::from_be_bytes([buffer[8], buffer[9], buffer[10], buffer[11]]) as i64,
    })
}

fn jpeg_size(file: &mut File) -> Option<ImageSize> {
    // 逐段扫描，找到 SOFn（0xC0..0xCF 除 C4/C8/CC）里的宽高
    file.seek(SeekFrom::Start(0)).ok()?;
    let mut byte = [0u8; 1];
    file.read_exact(&mut byte).ok()?;
    if byte[0] != 0xFF {
        return None;
    }
    file.read_exact(&mut byte).ok()?;
    if byte[0] != 0xD8 {
        return None;
    }
    loop {
        // 找段标记
        let mut marker = [0u8; 1];
        loop {
            if file.read_exact(&mut marker).is_err() {
                return None;
            }
            if marker[0] == 0xFF {
                break;
            }
        }
        let mut code = [0u8; 1];
        loop {
            if file.read_exact(&mut code).is_err() {
                return None;
            }
            if code[0] != 0xFF {
                break;
            }
        }
        match code[0] {
            // 无参数段
            0x01 | 0xD0..=0xD9 => continue,
            // 带长度段
            _ => {}
        }
        let mut length_bytes = [0u8; 2];
        file.read_exact(&mut length_bytes).ok()?;
        let length = u16::from_be_bytes(length_bytes) as i64;
        if length < 2 {
            return None;
        }
        let is_sof = (0xC0..=0xCF).contains(&code[0])
            && code[0] != 0xC4
            && code[0] != 0xC8
            && code[0] != 0xCC;
        if is_sof {
            let mut frame = [0u8; 5];
            file.read_exact(&mut frame).ok()?;
            return Some(ImageSize {
                width: u16::from_be_bytes([frame[3], frame[4]]) as i64,
                height: u16::from_be_bytes([frame[1], frame[2]]) as i64,
            });
        }
        // 跳过本段剩余内容（长度含自身 2 字节）
        let skip = length - 2;
        if skip > 0 {
            let mut sink = std::io::sink();
            let copied = std::io::copy(&mut file.by_ref().take(skip as u64), &mut sink).ok()?;
            if copied != skip as u64 {
                return None;
            }
        }
    }
}

fn webp_size(file: &mut File) -> Option<ImageSize> {
    // RIFF(4) size(4) WEBP(4) chunk(4) chunk_size(4) payload
    file.seek(SeekFrom::Start(0)).ok()?;
    let mut header = [0u8; 30];
    let read = file.read(&mut header).ok()?;
    if read < 30 {
        return None;
    }
    let chunk = &header[12..16];
    if chunk == b"VP8X" {
        let width = 1 + (header[24] as i64 | (header[25] as i64) << 8 | (header[26] as i64) << 16);
        let height = 1 + (header[27] as i64 | (header[28] as i64) << 8 | (header[29] as i64) << 16);
        return Some(ImageSize { width, height });
    }
    if chunk == b"VP8 " {
        // lossy: 3 字节帧标签后是 3 字节起始码 0x9D 0x01 0x2A，再 2+2 字节宽高（14 位）
        if header[23] != 0x9D || header[24] != 0x01 || header[25] != 0x2A {
            return None;
        }
        let width = (u16::from_le_bytes([header[26], header[27]]) & 0x3FFF) as i64;
        let height = (u16::from_le_bytes([header[28], header[29]]) & 0x3FFF) as i64;
        return Some(ImageSize { width, height });
    }
    if chunk == b"VP8L" {
        // lossless: 1 字节签名 0x2F，然后 14 位宽 / 14 位高
        if header[20] != 0x2F {
            return None;
        }
        let bits = u32::from_le_bytes([header[21], header[22], header[23], header[24]]);
        let width = (bits & 0x3FFF) as i64 + 1;
        let height = ((bits >> 14) & 0x3FFF) as i64 + 1;
        return Some(ImageSize { width, height });
    }
    None
}

/// 便捷封装：拿不到尺寸时返回 `(0, 0)`（对应 Python 里读图失败的分支）。
pub fn image_size_or_zero(path: &Path) -> (i64, i64) {
    match image_size(path) {
        Some(size) => (size.width, size.height),
        None => (0, 0),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn temp_path(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("itv-img-size-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        dir.join(name)
    }

    fn write_png(path: &Path, width: u32, height: u32) {
        let mut file = File::create(path).unwrap();
        file.write_all(&[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A])
            .unwrap();
        file.write_all(&13u32.to_be_bytes()).unwrap();
        file.write_all(b"IHDR").unwrap();
        file.write_all(&width.to_be_bytes()).unwrap();
        file.write_all(&height.to_be_bytes()).unwrap();
        // 位深 / 颜色类型 / 压缩 / 滤波 / 隔行
        file.write_all(&[8, 6, 0, 0, 0]).unwrap();
        // 真实 PNG 此处还有 IDAT 等数据；补几个字节让 read_exact 不会撞到 EOF
        file.write_all(&[0u8; 16]).unwrap();
    }

    fn write_bmp(path: &Path, width: i32, height: i32) {
        let mut data = vec![0u8; 54];
        data[0] = b'B';
        data[1] = b'M';
        data[18..22].copy_from_slice(&width.to_le_bytes());
        data[22..26].copy_from_slice(&height.to_le_bytes());
        std::fs::write(path, &data).unwrap();
    }

    fn write_gif(path: &Path, width: u16, height: u16) {
        let mut data = Vec::new();
        data.extend_from_slice(b"GIF89a");
        data.extend_from_slice(&width.to_le_bytes());
        data.extend_from_slice(&height.to_le_bytes());
        data.extend_from_slice(&[0u8; 20]);
        std::fs::write(path, &data).unwrap();
    }

    fn write_jpeg(path: &Path, width: u16, height: u16) {
        let mut data: Vec<u8> = vec![0xFF, 0xD8];
        // APP0 段（应被跳过）
        data.extend_from_slice(&[0xFF, 0xE0]);
        data.extend_from_slice(&16u16.to_be_bytes());
        data.extend_from_slice(&[0u8; 14]);
        // SOF0
        data.extend_from_slice(&[0xFF, 0xC0]);
        data.extend_from_slice(&17u16.to_be_bytes());
        data.push(8);
        data.extend_from_slice(&height.to_be_bytes());
        data.extend_from_slice(&width.to_be_bytes());
        data.extend_from_slice(&[3, 1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1]);
        std::fs::write(path, &data).unwrap();
    }

    #[test]
    fn png_size_from_ihdr() {
        let path = temp_path("a.png");
        write_png(&path, 1920, 1080);
        assert_eq!(
            image_size(&path),
            Some(ImageSize {
                width: 1920,
                height: 1080
            })
        );
    }

    #[test]
    fn bmp_size_handles_top_down_negative_height() {
        let path = temp_path("a.bmp");
        write_bmp(&path, 640, -480);
        assert_eq!(
            image_size(&path),
            Some(ImageSize {
                width: 640,
                height: 480
            })
        );
    }

    #[test]
    fn gif_size() {
        let path = temp_path("a.gif");
        write_gif(&path, 320, 200);
        assert_eq!(
            image_size(&path),
            Some(ImageSize {
                width: 320,
                height: 200
            })
        );
    }

    #[test]
    fn jpeg_size_skips_app_segments() {
        let path = temp_path("a.jpg");
        write_jpeg(&path, 800, 600);
        assert_eq!(
            image_size(&path),
            Some(ImageSize {
                width: 800,
                height: 600
            })
        );
    }

    #[test]
    fn unknown_format_returns_none() {
        let path = temp_path("a.txt");
        std::fs::write(&path, b"not an image at all").unwrap();
        assert_eq!(image_size(&path), None);
        assert_eq!(image_size_or_zero(&path), (0, 0));
    }

    #[test]
    fn missing_file_returns_none() {
        assert_eq!(image_size(Path::new("C:/definitely/missing.png")), None);
    }

    #[test]
    fn real_png_written_by_ffmpeg_is_parsed() {
        // 用项目自带的素材（若存在）验证真实文件；不存在则跳过
        let fixture = std::env::temp_dir().join("itv-img-size-real.png");
        let Ok(ffmpeg) = std::env::var("ITV_FFMPEG") else {
            return;
        };
        let status = std::process::Command::new(&ffmpeg)
            .args([
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=333x177:d=1",
                "-frames:v",
                "1",
            ])
            .arg(&fixture)
            .status();
        if status.map(|s| s.success()).unwrap_or(false) {
            assert_eq!(
                image_size(&fixture),
                Some(ImageSize {
                    width: 333,
                    height: 177
                })
            );
        }
    }
}
