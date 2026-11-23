//! 水印叠加相关：几何计算、混合模式映射、固定图层规格。
//!
//! 对齐 `src/render/watermark.py` 中的**纯计算**部分。像素级混合
//! （`apply_blend_mode` 的 numpy 运算）不放这里，见 `pixels` 模块。
//!
//! 两个易错点：
//! 1. `int()` 在 Python 里是**向零截断**，不是四舍五入；负数也一样（`int(-2.7) == -2`）。
//! 2. 位置计算用 `//` 整除，负数同样是向下取整（`-3 // 2 == -2`），与 Rust 的 `/` 不同。

use std::path::{Path, PathBuf};

use serde_json::Value;

use super::audio::RenderConfig;
use super::pixels::BgrFrame;

/// 叠加尺寸与位置。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct OverlayGeometry {
    pub target_w: i64,
    pub target_h: i64,
    pub x: i64,
    pub y: i64,
}

/// Python 的 `int()`：向零截断。
fn py_int(value: f64) -> i64 {
    if !value.is_finite() {
        return 0;
    }
    value.trunc() as i64
}

/// Python 的 `//`：向下取整（floor division）。
fn py_floor_div(numerator: i64, denominator: i64) -> i64 {
    if denominator == 0 {
        return 0;
    }
    let quotient = numerator / denominator;
    if (numerator % denominator != 0) && ((numerator < 0) != (denominator < 0)) {
        quotient - 1
    } else {
        quotient
    }
}

/// 与 `calc_overlay_geometry()` 逐字等价。
pub fn calc_overlay_geometry(
    main_w: i64,
    main_h: i64,
    wm_w: i64,
    wm_h: i64,
    size_mode: &str,
    scale_value: f64,
    position: &str,
) -> OverlayGeometry {
    let wm_ratio = wm_w as f64 / (1i64.max(wm_h)) as f64;
    let main_ratio = main_w as f64 / (1i64.max(main_h)) as f64;

    let (target_w, target_h) = if size_mode == "自适应覆盖" {
        if wm_ratio > main_ratio {
            let target_h = main_h;
            (py_int(target_h as f64 * wm_ratio), target_h)
        } else {
            let target_w = main_w;
            (target_w, py_int(target_w as f64 / wm_ratio))
        }
    } else if size_mode == "完全覆盖" {
        (main_w, main_h)
    } else {
        let target_w = 1i64.max(py_int(main_w as f64 * (scale_value / 100.0)));
        (target_w, 1i64.max(py_int(target_w as f64 / wm_ratio)))
    };

    let margin = if size_mode == "固定比例" { 10 } else { 0 };
    let (x, y) = match position {
        "左上" => (margin, margin),
        "右上" => (main_w - target_w - margin, margin),
        "左下" => (margin, main_h - target_h - margin),
        "中心" => (
            py_floor_div(main_w - target_w, 2),
            py_floor_div(main_h - target_h, 2),
        ),
        _ => (main_w - target_w - margin, main_h - target_h - margin),
    };
    OverlayGeometry {
        target_w,
        target_h,
        x,
        y,
    }
}

/// 混合模式 → 默认强度。
pub fn blend_alpha(blend_mode: &str) -> f64 {
    match blend_mode {
        "正常" => 0.50,
        "滤色" => 1.00,
        "叠加" => 0.90,
        "正片叠底" => 0.85,
        "变亮" => 0.90,
        "变暗" => 0.90,
        "相加" => 0.95,
        _ => 0.50,
    }
}

/// 混合模式 → ffmpeg `blend` 滤镜模式；「正常」与未知模式返回 None。
pub fn ffmpeg_blend_mode(blend_mode: &str) -> Option<&'static str> {
    match blend_mode {
        "滤色" => Some("screen"),
        "叠加" => Some("overlay"),
        "正片叠底" => Some("multiply"),
        "变亮" => Some("lighten"),
        "变暗" => Some("darken"),
        "相加" => Some("addition"),
        _ => None,
    }
}

/// 一个可由 ffmpeg 一次性处理的固定图片图层。
#[derive(Debug, Clone, PartialEq)]
pub struct FixedLayerSpec {
    pub path: String,
    pub position: String,
    pub size_mode: String,
    pub scale: f64,
    pub blend_mode: String,
    pub opacity: f64,
}

/// 与 `collect_fixed_layer_specs_for_ffmpeg()` 等价。
///
/// 目录型图层：排序后取第一个；勾了「文件夹随机单张」则随机抽一张。
/// `pick` 由调用方注入（对照测试里给固定值），返回下标。
pub fn collect_fixed_layers(
    config: &dyn RenderConfig,
    mut pick: impl FnMut(usize) -> usize,
) -> Vec<FixedLayerSpec> {
    let layers = match config.get("_watermark_layers") {
        Some(Value::Array(items)) => items,
        _ => Vec::new(),
    };
    let mut specs = Vec::new();
    for layer in layers {
        let Some(object) = layer.as_object() else {
            continue;
        };
        if !object.get("enabled").map(truthy).unwrap_or(true) {
            continue;
        }
        if object.get("type").and_then(Value::as_str).unwrap_or("图片") != "图片" {
            continue;
        }
        if !object.get("fixed").map(truthy).unwrap_or(false) {
            continue;
        }
        let Some(path) = object.get("path").and_then(Value::as_str) else {
            continue;
        };
        if path.is_empty() {
            continue;
        }

        let selected = if std::path::Path::new(path).is_dir() {
            let mut files = image_files_in_dir(path);
            files.sort();
            if files.is_empty() {
                None
            } else if object
                .get("folder_random_single")
                .map(truthy)
                .unwrap_or(false)
            {
                let index = pick(files.len()).min(files.len() - 1);
                Some(files[index].clone())
            } else {
                Some(files[0].clone())
            }
        } else if std::path::Path::new(path).is_file() {
            Some(path.to_string())
        } else {
            None
        };
        let Some(selected) = selected else {
            continue;
        };

        specs.push(FixedLayerSpec {
            path: selected,
            position: object
                .get("position")
                .and_then(Value::as_str)
                .unwrap_or("右下")
                .to_string(),
            size_mode: object
                .get("size_mode")
                .and_then(Value::as_str)
                .unwrap_or("自适应覆盖")
                .to_string(),
            scale: object.get("scale").and_then(Value::as_f64).unwrap_or(20.0),
            blend_mode: object
                .get("blend_mode")
                .and_then(Value::as_str)
                .unwrap_or("正常")
                .to_string(),
            opacity: object.get("opacity").and_then(Value::as_f64).unwrap_or(0.5),
        });
    }
    specs
}

fn truthy(value: &Value) -> bool {
    match value {
        Value::Bool(flag) => *flag,
        Value::Number(number) => number.as_f64().map(|v| v != 0.0).unwrap_or(false),
        Value::String(text) => !text.is_empty() && text != "0" && text != "false",
        Value::Null => false,
        Value::Array(items) => !items.is_empty(),
        Value::Object(map) => !map.is_empty(),
    }
}

const IMAGE_EXTENSIONS: [&str; 7] = [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"];

/// 目录里的图片文件（不递归）。
fn image_files_in_dir(directory: &str) -> Vec<String> {
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
        if IMAGE_EXTENSIONS.iter().any(|ext| lower.ends_with(ext)) {
            files.push(path.to_string_lossy().into_owned());
        }
    }
    files
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn py_int_truncates_toward_zero() {
        assert_eq!(py_int(2.7), 2);
        assert_eq!(py_int(-2.7), -2);
        assert_eq!(py_int(0.9), 0);
        assert_eq!(py_int(-0.9), 0);
    }

    #[test]
    fn py_floor_div_rounds_down_for_negatives() {
        assert_eq!(py_floor_div(10, 2), 5);
        assert_eq!(py_floor_div(-3, 2), -2);
        assert_eq!(py_floor_div(-4, 2), -2);
        assert_eq!(py_floor_div(3, 2), 1);
        assert_eq!(py_floor_div(0, 0), 0);
    }

    #[test]
    fn adaptive_cover_stretches_by_ratio() {
        // 水印比画面更宽：高度对齐，宽度按比例放大
        let geometry = calc_overlay_geometry(1920, 1080, 400, 100, "自适应覆盖", 20.0, "右下");
        assert_eq!(geometry.target_h, 1080);
        assert_eq!(geometry.target_w, 4320);
        assert_eq!(geometry.x, 1920 - 4320);
        assert_eq!(geometry.y, 1080 - 1080);

        // 水印比画面更高：宽度对齐
        let geometry = calc_overlay_geometry(1920, 1080, 100, 400, "自适应覆盖", 20.0, "右下");
        assert_eq!(geometry.target_w, 1920);
        assert_eq!(geometry.target_h, 7680);
    }

    #[test]
    fn full_cover_ignores_ratio() {
        let geometry = calc_overlay_geometry(1920, 1080, 100, 100, "完全覆盖", 20.0, "中心");
        assert_eq!((geometry.target_w, geometry.target_h), (1920, 1080));
        assert_eq!((geometry.x, geometry.y), (0, 0));
    }

    #[test]
    fn fixed_ratio_adds_ten_pixel_margin() {
        let geometry = calc_overlay_geometry(1920, 1080, 200, 100, "固定比例", 20.0, "左上");
        assert_eq!(geometry.target_w, 384);
        assert_eq!(geometry.target_h, 192);
        assert_eq!((geometry.x, geometry.y), (10, 10));

        let geometry = calc_overlay_geometry(1920, 1080, 200, 100, "固定比例", 20.0, "右下");
        assert_eq!(geometry.x, 1920 - 384 - 10);
        assert_eq!(geometry.y, 1080 - 192 - 10);
    }

    #[test]
    fn all_four_corners_and_center() {
        let args = (1920, 1080, 400, 200, "自适应覆盖", 20.0);
        let right_bottom =
            calc_overlay_geometry(args.0, args.1, args.2, args.3, args.4, args.5, "右下");
        let center = calc_overlay_geometry(args.0, args.1, args.2, args.3, args.4, args.5, "中心");
        let right_top =
            calc_overlay_geometry(args.0, args.1, args.2, args.3, args.4, args.5, "右上");
        let left_bottom =
            calc_overlay_geometry(args.0, args.1, args.2, args.3, args.4, args.5, "左下");
        assert_eq!(center.x, (1920 - right_bottom.target_w) / 2);
        assert_eq!(right_top.y, 0);
        assert_eq!(left_bottom.x, 0);
        // 未知位置按右下处理
        let unknown = calc_overlay_geometry(args.0, args.1, args.2, args.3, args.4, args.5, "??");
        assert_eq!(unknown, right_bottom);
    }

    #[test]
    fn alpha_defaults_match_the_python_table() {
        assert_eq!(blend_alpha("正常"), 0.50);
        assert_eq!(blend_alpha("滤色"), 1.00);
        assert_eq!(blend_alpha("正片叠底"), 0.85);
        assert_eq!(blend_alpha("未知"), 0.50);
    }

    #[test]
    fn ffmpeg_blend_mapping_excludes_normal() {
        assert_eq!(ffmpeg_blend_mode("滤色"), Some("screen"));
        assert_eq!(ffmpeg_blend_mode("相加"), Some("addition"));
        assert_eq!(ffmpeg_blend_mode("正常"), None);
        assert_eq!(ffmpeg_blend_mode("不存在"), None);
    }

    struct MapConfig(serde_json::Map<String, Value>);
    impl RenderConfig for MapConfig {
        fn get(&self, key: &str) -> Option<Value> {
            self.0.get(key).cloned()
        }
    }

    #[test]
    fn fixed_layer_collection_filters_and_fills_defaults() {
        let mut map = serde_json::Map::new();
        map.insert(
            "_watermark_layers".to_string(),
            json!([
                {"type": "图片", "fixed": true, "path": "C:/wm/a.png"},
                {"type": "图片", "fixed": false, "path": "C:/wm/b.png"},
                {"type": "视频", "fixed": true, "path": "C:/wm/c.mov"},
                {"type": "图片", "fixed": true, "enabled": false, "path": "C:/wm/d.png"},
                {"type": "图片", "fixed": true, "path": ""},
                {"type": "图片", "fixed": true, "path": "C:/wm/missing.png"},
                {"type": "图片", "fixed": true, "path": "C:/wm/a.png",
                 "position": "左上", "size_mode": "固定比例", "scale": 33.0,
                 "blend_mode": "滤色", "opacity": 0.8}
            ]),
        );
        let config = MapConfig(map);
        let dir = std::env::temp_dir().join(format!("itv-fixed-layers-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("a.png"), b"x").unwrap();
        std::fs::write(dir.join("b.png"), b"x").unwrap();
        // 把不存在的路径换成真实存在的文件，只保留一条「缺失」用例
        let mut map = serde_json::Map::new();
        map.insert(
            "_watermark_layers".to_string(),
            json!([
                {"type": "图片", "fixed": true, "path": dir.join("a.png").to_string_lossy()},
                {"type": "图片", "fixed": false, "path": dir.join("b.png").to_string_lossy()},
                {"type": "视频", "fixed": true, "path": dir.join("a.png").to_string_lossy()},
                {"type": "图片", "fixed": true, "enabled": false, "path": dir.join("a.png").to_string_lossy()},
                {"type": "图片", "fixed": true, "path": ""},
                {"type": "图片", "fixed": true, "path": "C:/wm/missing.png"},
                {"type": "图片", "fixed": true, "path": dir.join("a.png").to_string_lossy(),
                 "position": "左上", "size_mode": "固定比例", "scale": 33.0,
                 "blend_mode": "滤色", "opacity": 0.8}
            ]),
        );
        let specs = collect_fixed_layers(&MapConfig(map), |_| 0);
        assert_eq!(specs.len(), 2, "只保留两个启用且固定的图片图层：{specs:?}");
        assert_eq!(specs[0].position, "右下");
        assert_eq!(specs[0].size_mode, "自适应覆盖");
        assert_eq!(specs[0].scale, 20.0);
        assert_eq!(specs[0].blend_mode, "正常");
        assert_eq!(specs[0].opacity, 0.5);
        assert_eq!(specs[1].position, "左上");
        assert_eq!(specs[1].scale, 33.0);
        assert_eq!(specs[1].blend_mode, "滤色");
        assert_eq!(specs[1].opacity, 0.8);
        let _ = config;
    }

    #[test]
    fn directory_layer_takes_sorted_first_or_random() {
        let dir = std::env::temp_dir().join(format!("itv-layer-dir-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        for name in ["b.png", "a.png", "c.txt"] {
            std::fs::write(dir.join(name), b"x").unwrap();
        }
        let mut map = serde_json::Map::new();
        map.insert(
            "_watermark_layers".to_string(),
            json!([{"type": "图片", "fixed": true, "path": dir.to_string_lossy()}]),
        );
        let specs = collect_fixed_layers(&MapConfig(map), |_| 0);
        assert_eq!(specs.len(), 1);
        assert!(
            specs[0].path.ends_with("a.png"),
            "排序后取第一个：{}",
            specs[0].path
        );

        let mut map = serde_json::Map::new();
        map.insert(
            "_watermark_layers".to_string(),
            json!([{"type": "图片", "fixed": true, "path": dir.to_string_lossy(),
                    "folder_random_single": true}]),
        );
        // pick 返回 1 → 排序后的第二个
        let specs = collect_fixed_layers(&MapConfig(map), |_| 1);
        assert!(
            specs[0].path.ends_with("b.png"),
            "随机取第二个：{}",
            specs[0].path
        );
    }

    /// **「跟随水印」与「固定图层」必须严格互补，一个图层只能进其中一边。**
    ///
    /// 两边都进 → 视频里贴两遍；两边都不进 → 静默丢水印（2026-11-20 就是后者：
    /// `batch.rs` 把合成器的 decorate 写死 `None`，跟随水印整类图层不生效）。
    #[test]
    fn follow_layers_are_separated_from_fixed() {
        // 必须用真实文件：两条收集路径都会检查 path 是否存在，
        // 用假路径会得到「两边都空」的假阳性，什么也证明不了。
        let dir = std::env::temp_dir().join(format!("itv-split-wm-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let png = dir.join("a.png");
        image::RgbaImage::from_pixel(8, 8, image::Rgba([255, 0, 0, 255]))
            .save(&png)
            .unwrap();
        let real = png.to_string_lossy().into_owned();

        let layers = json!([
            {"type": "图片", "fixed": true,  "path": real, "enabled": true},
            {"type": "图片", "fixed": false, "path": real, "enabled": true},
            {"type": "图片",                     "path": real, "enabled": true},
            {"type": "图片", "fixed": true,  "path": real, "enabled": false},
            {"type": "视频", "fixed": false, "path": real, "enabled": true},
        ]);
        let items = layers.as_array().unwrap().to_vec();

        let fixed = collect_fixed_layers(&MapConfig(serde_json::Map::new()), |_| 0);
        assert!(fixed.is_empty(), "空配置不该有固定图层");

        let mut map = serde_json::Map::new();
        map.insert("_watermark_layers".to_string(), layers.clone());
        let fixed = collect_fixed_layers(&MapConfig(map.clone()), |_| 0);
        assert_eq!(
            fixed.len(),
            1,
            "只有「显式 fixed:true 且 enabled 的图片」才算固定图层，实际 {}",
            fixed.len()
        );

        let follow = follow_image_layers(&items, &mut |_| 0);
        assert_eq!(
            follow.len(),
            2,
            "fixed:false 与未写 fixed 的图片都算跟随水印（视频图层不算），实际 {}",
            follow.len()
        );

        // 互补性：两条路径加起来正好覆盖 3 个有效图片图层（第 4 个被 enabled 过滤，
        // 第 5 个是视频）。任何一边多算或漏算，这里的等式就崩。
        assert_eq!(fixed.len() + follow.len(), 3);

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 跟随水印每贴一层都必须真的改变像素 —— 否则等于没接上。
    #[test]
    fn follow_layer_application_changes_pixels() {
        let dir = std::env::temp_dir().join(format!("itv-follow-wm-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let wm_path = dir.join("wm.png");
        let mut wm = image::RgbaImage::new(40, 30);
        for pixel in wm.pixels_mut() {
            *pixel = image::Rgba([255, 0, 0, 255]);
        }
        wm.save(&wm_path).unwrap();

        let layers = json!([{
            "type": "图片", "fixed": false, "enabled": true,
            "path": wm_path.to_string_lossy(),
            "position": "左上", "size_mode": "固定比例", "scale": 20.0,
            "blend_mode": "正常", "opacity": 1.0,
        }]);
        let items = layers.as_array().unwrap().to_vec();
        let follow = follow_image_layers(&items, &mut |_| 0);
        assert_eq!(follow.len(), 1);

        // 全绿底图
        let mut frame = BgrFrame::new(160, 120);
        for y in 0..120 {
            for x in 0..160 {
                frame.set_pixel(x, y, [0, 200, 0]);
            }
        }
        let out = apply_image_layer(&frame, &follow[0], &mut |_| 0);
        assert_eq!(out.width, frame.width);
        assert_eq!(out.height, frame.height);
        assert_ne!(out.data, frame.data, "贴了水印却没变像素 = 没接上");

        // 左上角应出现红色（BGR 里红色在通道 2）。
        // 「固定比例」模式下留 10px 边距，所以取 (12,12) 而不是 (2,2)。
        let corner = out.pixel(12, 12).expect("(12,12) 在画面内");
        assert!(
            corner[2] > 150 && corner[0] < 100,
            "左上角应该是红色水印，实际 {:?}",
            corner
        );
    }
}
// ---------- 水印像素合成（对应 `apply_blend_mode` / `apply_image_watermark_layer`） ----------

/// 一张水印图（可能就是带 alpha 的 RGBA）。
pub struct WatermarkImage {
    pub width: u32,
    pub height: u32,
    /// 每像素 3 字节（BGR）或 4 字节（BGRA）。
    pub data: Vec<u8>,
    pub channels: usize,
}

impl WatermarkImage {
    fn pixel(&self, x: u32, y: u32) -> Option<[u8; 4]> {
        if x >= self.width || y >= self.height {
            return None;
        }
        let index = ((y * self.width + x) as usize) * self.channels;
        let mut out = [255u8; 4];
        out[..self.channels].copy_from_slice(&self.data[index..(self.channels + index)]);
        Some(out)
    }
}

/// 读图片并保留透明通道（对应 `safe_read_image_with_alpha`）。
pub fn read_image_with_alpha(path: &Path) -> Option<WatermarkImage> {
    let image = image::open(path).ok()?;
    let rgba = image.to_rgba8();
    let (width, height) = (rgba.width(), rgba.height());
    let mut data = Vec::with_capacity((width * height * 4) as usize);
    for pixel in rgba.pixels() {
        let [r, g, b, a] = pixel.0;
        data.push(b);
        data.push(g);
        data.push(r);
        data.push(a);
    }
    Some(WatermarkImage {
        width,
        height,
        data,
        channels: 4,
    })
}

/// 把一帧 BGR 包成水印图（视频水印取到的帧用这个）。
pub fn from_bgr(frame: &BgrFrame) -> WatermarkImage {
    WatermarkImage {
        width: frame.width,
        height: frame.height,
        data: frame.data.clone(),
        channels: 3,
    }
}

/// `apply_blend_mode`：7 种混合模式 + alpha。
///
/// 除「正常」外，所有模式都是先算混合公式 `mixed`，再
/// `result = bg*(1-alpha) + mixed*alpha`；`bg`/`fg` 都先归一化到 0..1。
/// 漏掉这一步会把「滤色」做成一团白。
pub fn apply_blend_mode(background: &[u8], foreground: &[u8], mode: &str, alpha: f64) -> Vec<u8> {
    let mut out = vec![0u8; background.len()];
    for index in 0..background.len() {
        let bg = background[index] as f64 / 255.0;
        let fg = foreground[index] as f64 / 255.0;
        let value = match mode {
            "滤色" => bg * (1.0 - alpha) + (1.0 - (1.0 - bg) * (1.0 - fg)) * alpha,
            "叠加" => {
                let mixed = if bg < 0.5 {
                    2.0 * bg * fg
                } else {
                    1.0 - 2.0 * (1.0 - bg) * (1.0 - fg)
                };
                bg * (1.0 - alpha) + mixed * alpha
            }
            "正片叠底" => bg * (1.0 - alpha) + (bg * fg) * alpha,
            "变亮" => bg * (1.0 - alpha) + bg.max(fg) * alpha,
            "变暗" => bg * (1.0 - alpha) + bg.min(fg) * alpha,
            "相加" => bg * (1.0 - alpha) + (bg + fg).min(1.0) * alpha,
            // 「正常」与未知模式：直接线性混合
            _ => bg * (1.0 - alpha) + fg * alpha,
        };
        out[index] = (value * 255.0).clamp(0.0, 255.0) as u8;
    }
    out
}

/// 一层图片水印的运行时规格（对应 `prepare_image_watermark_layers` 的产物）。
pub struct ImageLayer {
    pub images: Vec<WatermarkImage>,
    pub position: String,
    pub size_mode: String,
    pub scale: f64,
    pub blend_mode: String,
    pub opacity: f64,
}

/// 从配置里的 `watermark_layers` 准备图层（目录会展开成多张图）。
///
/// `pick` 用于「目录多图」时挑一张：传入一个 `[0,1)` 的随机数即可，
/// 这样调用方（导出用固定序列、预览用随机）都能控制可复现性。
pub fn prepare_image_layers(
    layers: &[Value],
    pick: &mut dyn FnMut(usize) -> usize,
) -> Vec<ImageLayer> {
    let mut prepared = Vec::new();
    for layer in layers {
        let Some(object) = layer.as_object() else {
            continue;
        };
        if !object.get("enabled").map(truthy).unwrap_or(true) {
            continue;
        }
        if object.get("type").and_then(Value::as_str).unwrap_or("图片") != "图片" {
            continue;
        }
        let path = object.get("path").and_then(Value::as_str).unwrap_or("");
        if path.is_empty() {
            continue;
        }
        let mut files: Vec<String> = if Path::new(path).is_dir() {
            let mut found = image_files_in_dir(path);
            if !found.is_empty()
                && object
                    .get("folder_random_single")
                    .map(truthy)
                    .unwrap_or(false)
            {
                let index = pick(found.len());
                found = vec![found[index.min(found.len() - 1)].clone()];
            }
            found
        } else {
            vec![path.to_string()]
        };
        files.retain(|file| !file.is_empty());
        let images: Vec<WatermarkImage> = files
            .iter()
            .filter_map(|file| read_image_with_alpha(Path::new(file)))
            .collect();
        if images.is_empty() {
            continue;
        }
        prepared.push(ImageLayer {
            images,
            position: object
                .get("position")
                .and_then(Value::as_str)
                .unwrap_or("右下")
                .to_string(),
            size_mode: object
                .get("size_mode")
                .and_then(Value::as_str)
                .unwrap_or("自适应覆盖")
                .to_string(),
            scale: object.get("scale").and_then(Value::as_f64).unwrap_or(20.0),
            blend_mode: object
                .get("blend_mode")
                .and_then(Value::as_str)
                .unwrap_or("正常")
                .to_string(),
            opacity: object.get("opacity").and_then(Value::as_f64).unwrap_or(0.5),
        });
    }
    prepared
}

/// 只保留**跟随水印**（未勾「固定图层」）的图层。
///
/// 两类图层的处理阶段完全不同，这是与 Python `compositor.py:119` 一致的分工：
/// - **固定图层**（`fixed: true`）：合成完成后由后处理用 ffmpeg overlay 一次贴上，
///   整段视频位置不变 → [`collect_fixed_layers`]
/// - **跟随水印**（`fixed: false`）：必须在**每张图缩放之后、转场之前**逐帧贴，
///   这样水印会跟着图片一起缩放、跟着转场一起淡入淡出 → 本函数
///
/// ⚠️ 2026-11-20 发现 `batch.rs` 把合成器的 `decorate` 参数写死成 `None`，
/// 于是「跟随水印」在导出里**完全不存在**，且没有任何报错（日志只显示
/// 「固定图层:0」，看起来像「用户没设水印」）。这类静默丢失最难发现，
/// 所以这个函数独立出来，并有 `follow_layers_are_separated_from_fixed` 守着。
pub fn follow_image_layers(
    layers: &[Value],
    pick: &mut dyn FnMut(usize) -> usize,
) -> Vec<ImageLayer> {
    let follow: Vec<Value> = layers
        .iter()
        .filter(|layer| {
            let Some(object) = layer.as_object() else {
                return false;
            };
            // 与 `collect_fixed_layers` 的判据正好互补：没勾 fixed 就是跟随水印
            !object.get("fixed").map(truthy).unwrap_or(false)
        })
        .cloned()
        .collect();
    prepare_image_layers(&follow, pick)
}

/// `apply_image_watermark_layer`：把一层水印贴到主画面上。
pub fn apply_image_layer(
    frame: &BgrFrame,
    layer: &ImageLayer,
    pick: &mut dyn FnMut(usize) -> usize,
) -> BgrFrame {
    if layer.images.is_empty() {
        return frame.clone();
    }
    let chosen = if layer.images.len() == 1 {
        &layer.images[0]
    } else {
        let index = pick(layer.images.len());
        &layer.images[index.min(layer.images.len() - 1)]
    };

    let main_w = frame.width as f64;
    let main_h = frame.height as f64;
    let watermark_ratio = chosen.width as f64 / 1.0f64.max(chosen.height as f64);
    let main_ratio = main_w / 1.0f64.max(main_h);

    let (target_w, target_h) = match layer.size_mode.as_str() {
        "自适应覆盖" => {
            if watermark_ratio > main_ratio {
                let h = main_h as i64;
                (py_int(h as f64 * watermark_ratio), h)
            } else {
                let w = main_w as i64;
                (w, py_int(w as f64 / watermark_ratio))
            }
        }
        "完全覆盖" => (main_w as i64, main_h as i64),
        _ => {
            let size = py_int(main_w * (layer.scale / 100.0));
            let w = size.max(1);
            (w, ((w as f64 / watermark_ratio) as i64).max(1))
        }
    };
    let target_w = target_w.max(1);
    let target_h = target_h.max(1);

    // 缩放水印（带 alpha 一起缩）
    let resized = resize_watermark(chosen, target_w as u32, target_h as u32);

    let margin = if layer.size_mode == "固定比例" {
        10.0
    } else {
        0.0
    };
    let (x_pos, y_pos) = match layer.position.as_str() {
        "左上" => (margin, margin),
        "右上" => (main_w - target_w as f64 - margin, margin),
        "左下" => (margin, main_h - target_h as f64 - margin),
        "中心" => (
            (main_w - target_w as f64) / 2.0,
            (main_h - target_h as f64) / 2.0,
        ),
        _ => (
            main_w - target_w as f64 - margin,
            main_h - target_h as f64 - margin,
        ),
    };
    // Python 这里已经是 int（因为 w/h 是 int），保持截断语义
    let x_pos = py_int(x_pos);
    let y_pos = py_int(y_pos);

    let src_x = (-x_pos).max(0);
    let src_y = (-y_pos).max(0);
    let dst_x = x_pos.max(0);
    let dst_y = y_pos.max(0);
    let actual_w = (target_w - src_x).min(frame.width as i64 - dst_x);
    let actual_h = (target_h - src_y).min(frame.height as i64 - dst_y);
    if actual_w <= 0 || actual_h <= 0 {
        return frame.clone();
    }

    let mut result = frame.clone();
    let mut roi: Vec<u8> = Vec::with_capacity((actual_w * actual_h * 3) as usize);
    for y in 0..actual_h {
        for x in 0..actual_w {
            if let Some(pixel) = frame.pixel((dst_x + x) as u32, (dst_y + y) as u32) {
                roi.extend_from_slice(&pixel);
            } else {
                roi.extend_from_slice(&[0, 0, 0]);
            }
        }
    }

    let mut foreground: Vec<u8> = Vec::with_capacity((actual_w * actual_h * 3) as usize);
    let mut alpha_mask: Vec<f64> = Vec::with_capacity((actual_w * actual_h) as usize);
    for y in 0..actual_h {
        for x in 0..actual_w {
            let pixel = resized
                .pixel((src_x + x) as u32, (src_y + y) as u32)
                .unwrap_or([0, 0, 0, 255]);
            foreground.extend_from_slice(&pixel[0..3]);
            // 带 alpha 通道时，alpha 乘以图层不透明度
            alpha_mask.push(if resized.channels == 4 {
                (pixel[3] as f64 / 255.0) * layer.opacity
            } else {
                layer.opacity
            });
        }
    }

    let blended = if resized.channels == 4 {
        // 有 alpha：先用不透明混合算出"完全覆盖"的结果，再按 alpha 蒙版合成
        let full = apply_blend_mode(&roi, &foreground, &layer.blend_mode, 1.0);
        let mut out = vec![0u8; full.len()];
        for (pixel, alpha) in alpha_mask.iter().enumerate() {
            let alpha = *alpha;
            for channel in 0..3 {
                let index = pixel * 3 + channel;
                out[index] = (roi[index] as f64 * (1.0 - alpha) + full[index] as f64 * alpha)
                    .clamp(0.0, 255.0) as u8;
            }
        }
        out
    } else {
        apply_blend_mode(&roi, &foreground, &layer.blend_mode, layer.opacity)
    };

    for y in 0..actual_h {
        for x in 0..actual_w {
            let index = ((y * actual_w + x) * 3) as usize;
            result.set_pixel(
                (dst_x + x) as u32,
                (dst_y + y) as u32,
                [blended[index], blended[index + 1], blended[index + 2]],
            );
        }
    }
    result
}

/// 缩放水印图（BGR 用双线性，alpha 单独最近邻，避免边缘出现半透明边）。
fn resize_watermark(source: &WatermarkImage, width: u32, height: u32) -> WatermarkImage {
    if source.width == width && source.height == height {
        return WatermarkImage {
            width: source.width,
            height: source.height,
            data: source.data.clone(),
            channels: source.channels,
        };
    }
    let mut data = vec![0u8; (width * height) as usize * source.channels];
    let scale_x = source.width as f64 / width as f64;
    let scale_y = source.height as f64 / height as f64;
    for y in 0..height {
        for x in 0..width {
            let sx = ((x as f64 + 0.5) * scale_x - 0.5).max(0.0);
            let sy = ((y as f64 + 0.5) * scale_y - 0.5).max(0.0);
            let x0 = sx.floor() as i64;
            let y0 = sy.floor() as i64;
            let fx = sx - x0 as f64;
            let fy = sy - y0 as f64;
            let mut out = [0f64; 4];
            for (dx, wx) in [(0i64, 1.0 - fx), (1, fx)] {
                for (dy, wy) in [(0i64, 1.0 - fy), (1, fy)] {
                    let weight = wx * wy;
                    if weight == 0.0 {
                        continue;
                    }
                    let px = (x0 + dx).clamp(0, source.width as i64 - 1) as u32;
                    let py = (y0 + dy).clamp(0, source.height as i64 - 1) as u32;
                    if let Some(pixel) = source.pixel(px, py) {
                        for channel in 0..source.channels {
                            out[channel] += pixel[channel] as f64 * weight;
                        }
                    }
                }
            }
            let index = ((y * width + x) as usize) * source.channels;
            for channel in 0..source.channels {
                data[index + channel] = out[channel].round().clamp(0.0, 255.0) as u8;
            }
        }
    }
    WatermarkImage {
        width,
        height,
        data,
        channels: source.channels,
    }
}

#[cfg(test)]
mod blend_tests {
    use super::*;

    #[test]
    fn normal_mode_is_linear_blend() {
        let bg = [0u8, 0, 0];
        let fg = [255u8, 255, 255];
        let out = apply_blend_mode(&bg, &fg, "正常", 0.5);
        assert_eq!(out, vec![127, 127, 127]);
    }

    #[test]
    fn screen_mode_brightens() {
        // 滤色：1-(1-0.2)*(1-0.6) = 1-0.32 = 0.68 → 173
        let bg = [51u8, 51, 51];
        let fg = [153u8, 153, 153];
        let out = apply_blend_mode(&bg, &fg, "滤色", 1.0);
        assert_eq!(out[0], 173, "滤色结果 {out:?}");
    }

    #[test]
    fn multiply_mode_darkens() {
        // 正片叠底：0.2*0.6 = 0.12 → 30
        let bg = [51u8, 51, 51];
        let fg = [153u8, 153, 153];
        let out = apply_blend_mode(&bg, &fg, "正片叠底", 1.0);
        assert_eq!(out[0], 30, "正片叠底结果 {out:?}");
    }

    #[test]
    fn add_mode_clips_at_white() {
        let bg = [200u8, 200, 200];
        let fg = [200u8, 200, 200];
        let out = apply_blend_mode(&bg, &fg, "相加", 1.0);
        assert_eq!(out[0], 255);
    }

    #[test]
    fn overlay_switches_on_background_luminance() {
        // bg=0.2 <0.5 → 2*0.2*0.8=0.32 → 81.6，`astype(uint8)` 截断得 81
        // （这里我一开始断言 82 —— 是四舍五入的结果，Python 用的是截断）
        let dark = apply_blend_mode(&[51u8], &[204u8], "叠加", 1.0);
        assert_eq!(dark[0], 81);
        // bg=0.8 >0.5 → 1-2*0.2*0.2 = 0.92 → 235
        let bright = apply_blend_mode(&[204u8], &[204u8], "叠加", 1.0);
        assert_eq!(bright[0], 234, "实际 {}", bright[0]);
    }

    #[test]
    fn missing_file_returns_none() {
        assert!(read_image_with_alpha(Path::new("C:/definitely-missing.png")).is_none());
    }
}

// ---------- 视频水印：按时间取帧 ----------

/// 视频水印按混合模式取的固定不透明度（`VIDEO_WATERMARK_ALPHA`）。
pub fn video_watermark_alpha(blend_mode: &str) -> f64 {
    match blend_mode {
        "滤色" => 1.00,
        "叠加" => 0.90,
        "正片叠底" => 0.85,
        "变亮" => 0.90,
        "变暗" => 0.90,
        "相加" => 0.95,
        _ => 0.50,
    }
}

/// 解析视频水印文件：单文件直接用，目录按自然排序取第一张（或按序号洗牌）。
pub fn resolve_video_watermark(path_value: &str, sequence: i64) -> Option<PathBuf> {
    let path = PathBuf::from(path_value.trim());
    const VIDEO_EXT: [&str; 7] = [".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".webm"];
    let is_video = |candidate: &Path| {
        candidate
            .extension()
            .map(|value| format!(".{}", value.to_string_lossy().to_lowercase()))
            .map(|ext| VIDEO_EXT.contains(&ext.as_str()))
            .unwrap_or(false)
    };
    if path.is_file() && is_video(&path) {
        return Some(path);
    }
    if path.is_dir() {
        let mut candidates: Vec<PathBuf> = std::fs::read_dir(&path)
            .map(|entries| {
                entries
                    .flatten()
                    .map(|entry| entry.path())
                    .filter(|candidate| candidate.is_file() && is_video(candidate))
                    .collect()
            })
            .unwrap_or_default();
        candidates.sort_by_key(|candidate| {
            crate::engine::sort::natural_sort_key(&candidate.to_string_lossy())
        });
        if candidates.is_empty() {
            return None;
        }
        if sequence > 0 {
            let index = crate::engine::preview_random::preview_choice(
                &candidates
                    .iter()
                    .map(|candidate| candidate.to_string_lossy().into_owned())
                    .collect::<Vec<_>>(),
                sequence,
                "video-watermark",
            )
            .and_then(|chosen| {
                candidates
                    .iter()
                    .position(|candidate| candidate.to_string_lossy() == chosen)
            })
            .unwrap_or(0);
            return Some(candidates[index].clone());
        }
        return Some(candidates[0].clone());
    }
    None
}

/// 按时间取水印视频的一帧。
///
/// 时间映射与 `_read_video_watermark_frame` 一致：
/// - `循环`：`t % 源时长`
/// - `拉伸`：`t / 输出时长 * 源时长`
/// - 其它（单次）：`t >= 源时长` 时返回 None
///
/// 实现用 ffmpeg 的 `-ss` 精确定位后取一帧（水印视频通常只有几秒，
/// 导出时这条路径每帧一次进程调用会明显变慢，届时应改成一次性解码缓存）。
pub fn read_video_watermark_frame(
    path: &Path,
    time_sec: f64,
    output_duration: f64,
    match_method: &str,
    ffmpeg: &Path,
) -> Option<WatermarkImage> {
    // ⚠️ 必须传 ffprobe：传 None 在找不到 ffprobe 的机器上会直接返回 None，
    // 表现是"水印静默不生效"（第一版就这样，10 个用例的均值完全一样才发现）。
    let ffprobe = crate::engine::system::resolve_ffprobe(None, Some(ffmpeg));
    let meta = super::process::probe_video_meta(&path.to_string_lossy(), ffprobe.as_deref())?;
    let source_duration = meta.duration;
    let mut target_time = time_sec.max(0.0);
    if source_duration > 0.0 {
        match match_method {
            "循环" => target_time %= source_duration,
            "拉伸" => {
                target_time = source_duration
                    .min(target_time / 0.001f64.max(output_duration) * source_duration)
            }
            _ => {
                if target_time >= source_duration {
                    return None;
                }
            }
        }
    }

    let mut command = std::process::Command::new(ffmpeg);
    command.args([
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        &path.to_string_lossy(),
        // `-ss` 放在 `-i` 之后是"精确取帧"（放在前面是按关键帧快进，会取到更早的帧）
        "-ss",
        &format!("{target_time:.6}"),
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        // ⚠️ 必须用 rgba 而不是 bgr24：水印视频常带透明区域，
        // 丢了 alpha 会把透明部分当成黑色一起去混合（整块变暗，肉眼立刻看出）。
        "-pix_fmt",
        "rgba",
        "-",
    ]);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    let output = command.output().ok()?;
    let width = meta.width as usize;
    let height = meta.height as usize;
    let expected = width * height * 4;
    if output.stdout.len() < expected || expected == 0 {
        return None;
    }
    // RGBA → BGRA
    let mut data = Vec::with_capacity(expected);
    for pixel in output.stdout[..expected].as_chunks::<4>().0 {
        data.push(pixel[2]);
        data.push(pixel[1]);
        data.push(pixel[0]);
        data.push(pixel[3]);
    }
    Some(WatermarkImage {
        width: width as u32,
        height: height as u32,
        data,
        channels: 4,
    })
}
