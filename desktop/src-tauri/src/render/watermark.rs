//! 水印叠加相关：几何计算、混合模式映射、固定图层规格。
//!
//! 对齐 `src/render/watermark.py` 中的**纯计算**部分。像素级混合
//! （`apply_blend_mode` 的 numpy 运算）不放这里，见 `pixels` 模块。
//!
//! 两个易错点：
//! 1. `int()` 在 Python 里是**向零截断**，不是四舍五入；负数也一样（`int(-2.7) == -2`）。
//! 2. 位置计算用 `//` 整除，负数同样是向下取整（`-3 // 2 == -2`），与 Rust 的 `/` 不同。

use std::path::Path;

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
            } else if object.get("folder_random_single").map(truthy).unwrap_or(false) {
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
            scale: object
                .get("scale")
                .and_then(Value::as_f64)
                .unwrap_or(20.0),
            blend_mode: object
                .get("blend_mode")
                .and_then(Value::as_str)
                .unwrap_or("正常")
                .to_string(),
            opacity: object
                .get("opacity")
                .and_then(Value::as_f64)
                .unwrap_or(0.5),
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
        let right_bottom = calc_overlay_geometry(args.0, args.1, args.2, args.3, args.4, args.5, "右下");
        let center = calc_overlay_geometry(args.0, args.1, args.2, args.3, args.4, args.5, "中心");
        let right_top = calc_overlay_geometry(args.0, args.1, args.2, args.3, args.4, args.5, "右上");
        let left_bottom = calc_overlay_geometry(args.0, args.1, args.2, args.3, args.4, args.5, "左下");
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
        assert!(specs[0].path.ends_with("a.png"), "排序后取第一个：{}", specs[0].path);

        let mut map = serde_json::Map::new();
        map.insert(
            "_watermark_layers".to_string(),
            json!([{"type": "图片", "fixed": true, "path": dir.to_string_lossy(),
                    "folder_random_single": true}]),
        );
        // pick 返回 1 → 排序后的第二个
        let specs = collect_fixed_layers(&MapConfig(map), |_| 1);
        assert!(specs[0].path.ends_with("b.png"), "随机取第二个：{}", specs[0].path);
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
        for channel in 0..self.channels {
            out[channel] = self.data[index + channel];
        }
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

/// `apply_blend_mode`：7 种混合模式 + alpha。
///
/// 除「正常」外，所有模式都是先算混合公式 `mixed`，再
/// `result = bg*(1-alpha) + mixed*alpha`；`bg`/`fg` 都先归一化到 0..1。
/// 漏掉这一步会把「滤色」做成一团白。
pub fn apply_blend_mode(
    background: &[u8],
    foreground: &[u8],
    mode: &str,
    alpha: f64,
) -> Vec<u8> {
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
pub fn prepare_image_layers(layers: &[Value], pick: &mut dyn FnMut(usize) -> usize) -> Vec<ImageLayer> {
    let mut prepared = Vec::new();
    for layer in layers {
        let Some(object) = layer.as_object() else {
            continue;
        };
        if !object.get("enabled").map(truthy).unwrap_or(true) {
            continue;
        }
        if object
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or("图片")
            != "图片"
        {
            continue;
        }
        let path = object.get("path").and_then(Value::as_str).unwrap_or("");
        if path.is_empty() {
            continue;
        }
        let mut files: Vec<String> = if Path::new(path).is_dir() {
            let mut found = image_files_in_dir(path);
            if !found.is_empty() && object.get("folder_random_single").map(truthy).unwrap_or(false) {
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

    let margin = if layer.size_mode == "固定比例" { 10.0 } else { 0.0 };
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
        for pixel in 0..alpha_mask.len() {
            let alpha = alpha_mask[pixel];
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
