//! 水印叠加相关：几何计算、混合模式映射、固定图层规格。
//!
//! 对齐 `src/render/watermark.py` 中的**纯计算**部分。像素级混合
//! （`apply_blend_mode` 的 numpy 运算）不放这里，见 `pixels` 模块。
//!
//! 两个易错点：
//! 1. `int()` 在 Python 里是**向零截断**，不是四舍五入；负数也一样（`int(-2.7) == -2`）。
//! 2. 位置计算用 `//` 整除，负数同样是向下取整（`-3 // 2 == -2`），与 Rust 的 `/` 不同。

use serde_json::Value;

use super::audio::RenderConfig;

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