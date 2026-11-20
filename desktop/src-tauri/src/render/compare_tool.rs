//! 改前改后对比工具：把某个特效/转场在多档参数下各渲一帧，拼成一张对照图。
//!
//! ## 为什么需要它
//!
//! 改渲染代码时，验证方式一直是「导出视频 → ffmpeg 抽帧 → 逐像素比对」，
//! 中间要做五六个手工步骤，而且每次换特效都要重来。更麻烦的是看不出
//! 「两档参数到底差在哪」—— 数字告诉你平均差 12.4，但那意味着什么？
//!
//! 这个工具一次做三件事：
//! 1. 把参数按档位排版（默认 3 档：低、默认、高）
//! 2. 每档渲一帧
//! 3. **拼成一张带分界线的对照图**，直接看
//!
//! ## 怎么用
//!
//! ```sh
//! # 特效：3 档强度（会自动找该特效声明的第一个数字参数）
//! ITV_COMPARE=故障抖动 cargo test --release --offline --lib compare_tool -- --nocapture
//!
//! # 转场
//! ITV_COMPARE=百叶窗 cargo test --release --offline --lib compare_tool -- --nocapture
//!
//! # 指定参数与档位
//! ITV_COMPARE=波浪 ITV_COMPARE_KEY=amplitude ITV_COMPARE_VALUES=5,20,80 \
//!     cargo test --release --offline --lib compare_tool -- --nocapture
//! ```
//!
//! 输出：`%TEMP%/itv-compare-<名字>.png`，路径会打印出来。
//!
//! 没设 `ITV_COMPARE` 时这个测试直接跳过，不影响正常跑测试。

use super::catalog;
use super::effects::{self, EffectParams};
use super::pixels::BgrFrame;
use super::transitions;

/// 测试图：带渐变、色块和高频细节，能同时看出位移、模糊、形变。
fn pattern(width: u32, height: u32) -> BgrFrame {
    let mut frame = BgrFrame::new(width, height);
    for y in 0..height {
        for x in 0..width {
            // 棋盘底 + 对角渐变 + 中心圆，三种特征各管一类效果
            let checker = if (x / 16 + y / 16) % 2 == 0 { 40 } else { 200 };
            let gradient = ((x * 80) / width.max(1)) as u8;
            let dx = x as i64 - width as i64 / 2;
            let dy = y as i64 - height as i64 / 2;
            let in_circle = dx * dx + dy * dy < ((width.min(height) / 4) as i64).pow(2);
            let value = if in_circle { 240 } else { checker };
            frame.set_pixel(x, y, [value, gradient.max(20), 255 - value]);
        }
    }
    frame
}

/// 第二张图（转场需要两张）：与第一张明显不同。
fn pattern_b(width: u32, height: u32) -> BgrFrame {
    let mut frame = BgrFrame::new(width, height);
    for y in 0..height {
        for x in 0..width {
            let stripe = if (x / 12) % 2 == 0 { 210 } else { 30 };
            let wave = ((y * 60) / height.max(1)) as u8;
            frame.set_pixel(x, y, [30, stripe, wave]);
        }
    }
    frame
}

/// 横向拼接多帧，中间画 2px 白色分隔线。
fn tile(frames: &[BgrFrame]) -> Option<BgrFrame> {
    let first = frames.first()?;
    let width = first.width;
    let height = first.height;
    let gap = 2u32;
    let total_width = width * frames.len() as u32 + gap * (frames.len() as u32 - 1);
    let mut out = BgrFrame::new(total_width, height);
    for (index, frame) in frames.iter().enumerate() {
        let offset = index as u32 * (width + gap);
        for y in 0..height {
            for x in 0..width {
                if let Some(pixel) = frame.pixel(x, y) {
                    out.set_pixel(offset + x, y, pixel);
                }
            }
            // 分隔线
            if index + 1 < frames.len() {
                for g in 0..gap {
                    out.set_pixel(offset + width + g, y, [255, 255, 255]);
                }
            }
        }
    }
    Some(out)
}

/// 极简 PNG 编码（BGR → RGB，无压缩以外的花活）。
fn write_png(frame: &BgrFrame, path: &std::path::Path) -> std::io::Result<()> {
    fn crc32(data: &[u8]) -> u32 {
        let mut table = [0u32; 256];
        for (index, entry) in table.iter_mut().enumerate() {
            let mut value = index as u32;
            for _ in 0..8 {
                value = if value & 1 == 1 { 0xEDB88320 ^ (value >> 1) } else { value >> 1 };
            }
            *entry = value;
        }
        let mut crc = 0xFFFF_FFFFu32;
        for byte in data {
            crc = table[((crc ^ *byte as u32) & 0xFF) as usize] ^ (crc >> 8);
        }
        crc ^ 0xFFFF_FFFF
    }

    fn chunk(kind: &[u8], data: &[u8]) -> Vec<u8> {
        let mut out = Vec::with_capacity(data.len() + 12);
        out.extend_from_slice(&(data.len() as u32).to_be_bytes());
        let mut body = Vec::with_capacity(data.len() + 4);
        body.extend_from_slice(kind);
        body.extend_from_slice(data);
        out.extend_from_slice(&body);
        out.extend_from_slice(&crc32(&body).to_be_bytes());
        out
    }

    // 原始扫描线：每行前面加一个 filter 字节（0 = None）
    let mut raw = Vec::with_capacity((frame.width * 3 + 1) as usize * frame.height as usize);
    for y in 0..frame.height {
        raw.push(0);
        for x in 0..frame.width {
            let pixel = frame.pixel(x, y).unwrap_or([0, 0, 0]);
            raw.extend_from_slice(&[pixel[2], pixel[1], pixel[0]]);
        }
    }

    // zlib 包装：header + deflate(stored) + adler32
    fn adler32(data: &[u8]) -> u32 {
        let (mut a, mut b) = (1u32, 0u32);
        for byte in data {
            a = (a + *byte as u32) % 65521;
            b = (b + a) % 65521;
        }
        (b << 16) | a
    }
    let mut zlib = vec![0x78, 0x01];
    let mut remaining = raw.as_slice();
    while !remaining.is_empty() {
        let take = remaining.len().min(65535);
        let block = &remaining[..take];
        let last = take == remaining.len();
        zlib.push(if last { 1 } else { 0 });
        zlib.extend_from_slice(&(take as u16).to_le_bytes());
        zlib.extend_from_slice(&(!(take as u16)).to_le_bytes());
        zlib.extend_from_slice(block);
        remaining = &remaining[take..];
    }
    zlib.extend_from_slice(&adler32(&raw).to_be_bytes());

    let mut png = vec![0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A];
    let mut ihdr = Vec::new();
    ihdr.extend_from_slice(&frame.width.to_be_bytes());
    ihdr.extend_from_slice(&frame.height.to_be_bytes());
    ihdr.extend_from_slice(&[8, 2, 0, 0, 0]); // 8 位、真彩、无隔行
    png.extend_from_slice(&chunk(b"IHDR", &ihdr));
    png.extend_from_slice(&chunk(b"IDAT", &zlib));
    png.extend_from_slice(&chunk(b"IEND", &[]));
    std::fs::write(path, png)
}

/// 默认档位：低 / 声明默认值 / 高。
fn default_values(spec: &catalog::ParamSpec) -> Vec<f64> {
    if spec.kind == catalog::ParamKind::Choice {
        return spec.choices.iter().enumerate().map(|(i, _)| i as f64).collect();
    }
    let span = (spec.max - spec.min).max(1.0);
    vec![
        (spec.default - span * 0.3).clamp(spec.min, spec.max),
        spec.default,
        (spec.default + span * 0.3).clamp(spec.min, spec.max),
    ]
}

#[test]
fn compare_tool() {
    let Ok(name) = std::env::var("ITV_COMPARE") else {
        // 没设环境变量就跳过 —— 这条测试是工具，不是回归检查
        return;
    };

    let is_effect = catalog::find_effect(&name).is_some();
    let item = catalog::find_effect(&name).or_else(|| catalog::find_transition(&name));
    let Some(item) = item else {
        panic!("目录里找不到「{name}」，可用名字见 catalog.rs");
    };

    // 参数：显式指定的优先，否则取该条目声明的第一个参数
    let key = std::env::var("ITV_COMPARE_KEY")
        .ok()
        .or_else(|| item.params.first().map(|spec| spec.key.to_string()));
    let spec = key
        .as_ref()
        .and_then(|key| item.params.iter().find(|spec| &spec.key.to_string() == key));

    let values: Vec<f64> = match std::env::var("ITV_COMPARE_VALUES") {
        Ok(raw) => raw
            .split(',')
            .filter_map(|part| part.trim().parse().ok())
            .collect(),
        Err(_) => match spec {
            Some(spec) => default_values(spec),
            // 该条目没有参数时，渲一档默认的就行（用于看「纯粹长什么样」）
            None => vec![0.0],
        },
    };

    let width = 320u32;
    let height = 200u32;
    let first = pattern(width, height);
    let second = pattern_b(width, height);
    let mut rendered = Vec::new();

    for value in &values {
        let mut extra = serde_json::Map::new();
        if let Some(key) = &key {
            extra.insert(key.clone(), serde_json::json!(value));
        }
        let frame = if is_effect {
            let params = EffectParams {
                effect_type: item.id.to_string(),
                time_sec: 0.5,
                duration_sec: 3.0,
                intensity: 100.0,
                speed: 1.0,
                extra,
            };
            effects::apply_single_image_effect(&first, &params)
        } else {
            // 转场取中间那一步，最能看出形状
            let parsed = transitions::parse(item.id);
            let frames = transitions::generate_frames(&first, &second, parsed, 5, &extra);
            frames.get(2).cloned().unwrap_or_else(|| first.clone())
        };
        rendered.push(frame);
    }

    let combined = tile(&rendered).expect("至少一帧");
    let out = std::env::temp_dir().join(format!("itv-compare-{}.png", item.id));
    write_png(&combined, &out).expect("写 PNG 失败");

    let labels: Vec<String> = values.iter().map(|v| format!("{v}")).collect();
    println!(
        "对照图已生成：{}\n  条目：{name}（{}）\n  参数：{} = [{}]\n  从左到右依次是上面这些档位",
        out.display(),
        if is_effect { "特效" } else { "转场" },
        key.as_deref().unwrap_or("（无参数，仅看默认效果）"),
        labels.join(", ")
    );
}