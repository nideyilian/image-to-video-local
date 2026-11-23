//! 特效/转场演示素材（对齐 `src/engine/effect_preview.py` 的资产部分）。
//!
//! 只有三件事：生成内置演示图、读写自定义图清单、清理自定义图。
//! 渲染类接口（`preview_effect_frame` / `effect_preview_animation`）不在这里 —— 它们依赖
//! 全部 40 种特效与水印视频帧，见 `mod.rs` 的分发注释。
//!
//! 目录固定为 `%TEMP%/image-to-video-engine/effect-library`，与旧引擎共用同一份缓存，
//! 这样用户在两个引擎之间切换时看到的演示图不会来回变。

use std::path::{Path, PathBuf};

use serde_json::{json, Map, Value};

/// 自定义图清单文件名。
const MANIFEST_NAME: &str = ".user-assets.json";

/// 演示图尺寸（与 Python 的 `Image.new("RGB", (480, 270))` 一致）。
const WIDTH: u32 = 480;
const HEIGHT: u32 = 270;

fn preview_dir() -> PathBuf {
    std::env::temp_dir()
        .join("image-to-video-engine")
        .join("effect-library")
}

/// 读取自定义图清单；损坏或缺失时返回空清单。
fn load_user_assets(dir: &Path) -> Map<String, Value> {
    let Ok(raw) = std::fs::read_to_string(dir.join(MANIFEST_NAME)) else {
        return Map::new();
    };
    let Ok(Value::Object(data)) = serde_json::from_str::<Value>(&raw) else {
        return Map::new();
    };
    let mut result = Map::new();
    for slot in ["a", "b"] {
        let Some(entry) = data.get(slot).and_then(Value::as_object) else {
            continue;
        };
        let file = entry.get("file").and_then(Value::as_str);
        let source = entry.get("source").and_then(Value::as_str);
        if let (Some(file), Some(source)) = (file, source) {
            result.insert(slot.to_string(), json!({ "file": file, "source": source }));
        }
    }
    result
}

/// 写清单：先写临时文件再替换（Windows 上 rename 不能覆盖，失败再删再写）。
fn save_user_assets(dir: &Path, manifest: &Map<String, Value>) -> Result<(), String> {
    let text = serde_json::to_string(&Value::Object(manifest.clone()))
        .map_err(|error| error.to_string())?;
    let target = dir.join(MANIFEST_NAME);
    let temporary = dir.join(format!(".{MANIFEST_NAME}.{}.tmp", std::process::id()));
    std::fs::write(&temporary, text).map_err(|error| error.to_string())?;
    // Windows 上 rename 不能覆盖已有文件，走项目的安全替换（失败则删目标再写）
    let replaced = crate::render::process::safe_replace_file(
        &temporary.to_string_lossy(),
        &target.to_string_lossy(),
    );
    if replaced {
        Ok(())
    } else {
        let _ = std::fs::remove_file(&temporary);
        Err(format!("无法写入 {}", target.to_string_lossy()))
    }
}

/// 返回可用的自定义演示图路径；临时目录被清理时尝试从原始路径恢复。
fn resolve_user_asset(dir: &Path, entry: Option<&Value>) -> Option<PathBuf> {
    let entry = entry?.as_object()?;
    let file = entry.get("file")?.as_str()?;
    let user_file = dir.join(file);
    if !user_file.is_file() {
        let source = PathBuf::from(entry.get("source").and_then(Value::as_str).unwrap_or(""));
        if source.is_file() && std::fs::copy(&source, &user_file).is_err() {
            return None;
        }
    }
    if user_file.is_file() {
        Some(user_file)
    } else {
        None
    }
}

/// 线性插值取色。
fn lerp_channel(top: u8, bottom: u8, ratio: f64) -> u8 {
    let value = top as f64 + (bottom as f64 - top as f64) * ratio;
    value.clamp(0.0, 255.0) as u8
}

/// 画一张演示图（垂直渐变 + 一个几何体）。
///
/// 与 Python 的 `draw_demo` 对应，但**不画那行中文标签**：PIL 用的是内置位图字体，
/// Rust 侧没有等价字体且这行字对功能没有影响。画面主体（渐变、圆/三角、内部小圆）一致。
fn draw_demo(
    path: &Path,
    top: (u8, u8, u8),
    bottom: (u8, u8, u8),
    shape: &str,
) -> Result<(), String> {
    let mut image = image::RgbImage::new(WIDTH, HEIGHT);

    // 垂直渐变：Python 是逐行 line()，行内颜色相同
    for y in 0..HEIGHT {
        let ratio = y as f64 / (HEIGHT - 1) as f64;
        let color = [
            lerp_channel(top.0, bottom.0, ratio),
            lerp_channel(top.1, bottom.1, ratio),
            lerp_channel(top.2, bottom.2, ratio),
        ];
        for x in 0..WIDTH {
            image.put_pixel(x, y, image::Rgb(color));
        }
    }

    if shape == "circle" {
        // 椭圆 [140,60]-[340,210]，白色填充 + 深色描边 6px
        fill_ellipse(&mut image, 140, 60, 340, 210, [255, 255, 255]);
        stroke_ellipse(&mut image, 140, 60, 340, 210, [20, 30, 60], 6);
        fill_ellipse(&mut image, 210, 120, 270, 180, [30, 50, 90]);
    } else {
        // 三角形 (240,50) (380,220) (100,220)
        fill_polygon(
            &mut image,
            &[(240, 50), (380, 220), (100, 220)],
            [255, 255, 255],
        );
        stroke_polygon(
            &mut image,
            &[(240, 50), (380, 220), (100, 220)],
            [60, 30, 20],
            6,
        );
        fill_ellipse(&mut image, 200, 95, 280, 175, [90, 50, 30]);
    }

    image.save(path).map_err(|error| error.to_string())
}

/// 用椭圆方程填充（包住边界的像素都填）。
fn fill_ellipse(image: &mut image::RgbImage, x0: i64, y0: i64, x1: i64, y1: i64, color: [u8; 3]) {
    let cx = (x0 + x1) as f64 / 2.0;
    let cy = (y0 + y1) as f64 / 2.0;
    let rx = ((x1 - x0) as f64 / 2.0).max(0.5);
    let ry = ((y1 - y0) as f64 / 2.0).max(0.5);
    for y in y0.max(0)..=y1.min(image.height() as i64 - 1) {
        for x in x0.max(0)..=x1.min(image.width() as i64 - 1) {
            let dx = (x as f64 - cx) / rx;
            let dy = (y as f64 - cy) / ry;
            if dx * dx + dy * dy <= 1.0 {
                image.put_pixel(x as u32, y as u32, image::Rgb(color));
            }
        }
    }
}

/// 椭圆描边：只画「在内但在内缩 width 之外」的一圈。
fn stroke_ellipse(
    image: &mut image::RgbImage,
    x0: i64,
    y0: i64,
    x1: i64,
    y1: i64,
    color: [u8; 3],
    width: i64,
) {
    let cx = (x0 + x1) as f64 / 2.0;
    let cy = (y0 + y1) as f64 / 2.0;
    let rx = ((x1 - x0) as f64 / 2.0).max(0.5);
    let ry = ((y1 - y0) as f64 / 2.0).max(0.5);
    let inner_rx = (rx - width as f64).max(0.1);
    let inner_ry = (ry - width as f64).max(0.1);
    for y in y0.max(0)..=y1.min(image.height() as i64 - 1) {
        for x in x0.max(0)..=x1.min(image.width() as i64 - 1) {
            let dx = (x as f64 - cx) / rx;
            let dy = (y as f64 - cy) / ry;
            let outer = dx * dx + dy * dy <= 1.0;
            let idx = (x as f64 - cx) / inner_rx;
            let idy = (y as f64 - cy) / inner_ry;
            let inner = idx * idx + idy * idy <= 1.0;
            if outer && !inner {
                image.put_pixel(x as u32, y as u32, image::Rgb(color));
            }
        }
    }
}

/// 扫描线填充多边形。
fn fill_polygon(image: &mut image::RgbImage, points: &[(i64, i64)], color: [u8; 3]) {
    if points.len() < 3 {
        return;
    }
    let min_y = points.iter().map(|(_, y)| *y).min().unwrap_or(0).max(0);
    let max_y = points
        .iter()
        .map(|(_, y)| *y)
        .max()
        .unwrap_or(0)
        .min(image.height() as i64 - 1);
    for y in min_y..=max_y {
        let mut crossings: Vec<f64> = Vec::new();
        for index in 0..points.len() {
            let (x0, y0) = points[index];
            let (x1, y1) = points[(index + 1) % points.len()];
            if (y0 as f64 <= y as f64 && y1 as f64 > y as f64)
                || (y1 as f64 <= y as f64 && y0 as f64 > y as f64)
            {
                let ratio = (y as f64 - y0 as f64) / (y1 as f64 - y0 as f64);
                crossings.push(x0 as f64 + (x1 - x0) as f64 * ratio);
            }
        }
        crossings.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        for pair in crossings.chunks(2) {
            if pair.len() < 2 {
                break;
            }
            let start = pair[0].round().max(0.0) as i64;
            let end = pair[1].round().min(image.width() as f64 - 1.0) as i64;
            for x in start..=end {
                if x >= 0 && x < image.width() as i64 {
                    image.put_pixel(x as u32, y as u32, image::Rgb(color));
                }
            }
        }
    }
}

/// 多边形描边：逐条边按粗线画圆点。
fn stroke_polygon(image: &mut image::RgbImage, points: &[(i64, i64)], color: [u8; 3], width: i64) {
    let radius = width as f64 / 2.0;
    for index in 0..points.len() {
        let (x0, y0) = points[index];
        let (x1, y1) = points[(index + 1) % points.len()];
        let steps = ((x1 - x0).abs().max((y1 - y0).abs())).max(1);
        for step in 0..=steps {
            let ratio = step as f64 / steps as f64;
            let cx = x0 as f64 + (x1 - x0) as f64 * ratio;
            let cy = y0 as f64 + (y1 - y0) as f64 * ratio;
            let x_start = (cx - radius).floor().max(0.0) as i64;
            let x_end = (cx + radius).ceil().min(image.width() as f64 - 1.0) as i64;
            let y_start = (cy - radius).floor().max(0.0) as i64;
            let y_end = (cy + radius).ceil().min(image.height() as f64 - 1.0) as i64;
            for y in y_start..=y_end {
                for x in x_start..=x_end {
                    let dx = x as f64 - cx;
                    let dy = y as f64 - cy;
                    if dx * dx + dy * dy <= radius * radius {
                        image.put_pixel(x as u32, y as u32, image::Rgb(color));
                    }
                }
            }
        }
    }
}

/// `effect_library_assets`：生成（或复用）演示图并返回路径。
pub fn ensure_assets() -> Result<Value, String> {
    let dir = preview_dir();
    std::fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    let source_a = dir.join("source-a.png");
    let source_b = dir.join("source-b.png");

    let manifest = load_user_assets(&dir);
    let user_a = resolve_user_asset(&dir, manifest.get("a"));
    let user_b = resolve_user_asset(&dir, manifest.get("b"));

    if !source_a.is_file() || !source_b.is_file() {
        draw_demo(&source_a, (40, 90, 200), (120, 40, 160), "circle")?;
        draw_demo(&source_b, (200, 90, 40), (160, 40, 120), "triangle")?;
    }

    let chosen_a = user_a.clone().unwrap_or_else(|| source_a.clone());
    let chosen_b = user_b.clone().unwrap_or_else(|| source_b.clone());
    Ok(json!({
        "source_a": crate::engine::paths::display(&crate::engine::paths::absolute(&chosen_a)),
        "source_b": crate::engine::paths::display(&crate::engine::paths::absolute(&chosen_b)),
        "custom_a": user_a.is_some(),
        "custom_b": user_b.is_some(),
        "user_path_a": if user_a.is_some() {
            manifest.get("a").and_then(|v| v.get("source")).and_then(Value::as_str).unwrap_or("")
        } else { "" },
        "user_path_b": if user_b.is_some() {
            manifest.get("b").and_then(|v| v.get("source")).and_then(Value::as_str).unwrap_or("")
        } else { "" },
    }))
}

/// `effect_library_set_asset`：把用户选的图片设为演示图（which = a / b）。
pub fn set_asset(params: &Map<String, Value>) -> Result<Value, String> {
    let slot = params
        .get("which")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_lowercase();
    if slot != "a" && slot != "b" {
        return Err("which 必须是 a 或 b".to_string());
    }
    let source = params
        .get("path")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_string();
    let source_path = PathBuf::from(&source);
    if !source_path.is_file() {
        return Err("图片文件不存在，请重新选择".to_string());
    }
    // 与 PIL 的 `image.verify()` 等价：能解码出尺寸才算有效图片
    if image::image_dimensions(&source_path).is_err() {
        return Err(format!(
            "不是有效的图片文件：{}",
            source_path
                .file_name()
                .map(|value| value.to_string_lossy().into_owned())
                .unwrap_or_default()
        ));
    }

    let dir = preview_dir();
    std::fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    let suffix = {
        let raw = source_path
            .extension()
            .map(|value| format!(".{}", value.to_string_lossy().to_lowercase()))
            .unwrap_or_default();
        if [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"].contains(&raw.as_str()) {
            raw
        } else {
            ".png".to_string()
        }
    };
    let user_file = dir.join(format!("user-{slot}{suffix}"));

    let mut manifest = load_user_assets(&dir);
    let previous = manifest
        .get(&slot)
        .and_then(|entry| entry.get("file"))
        .and_then(Value::as_str)
        .map(str::to_string);
    if let Some(previous) = previous {
        if previous
            != user_file
                .file_name()
                .map(|v| v.to_string_lossy().into_owned())
                .unwrap_or_default()
        {
            let _ = std::fs::remove_file(dir.join(&previous));
        }
    }
    let same_path =
        crate::engine::paths::absolute(&source_path) == crate::engine::paths::absolute(&user_file);
    if !same_path {
        std::fs::copy(&source_path, &user_file).map_err(|error| error.to_string())?;
    }
    manifest.insert(
        slot.clone(),
        json!({
            "file": user_file.file_name().map(|v| v.to_string_lossy().into_owned()).unwrap_or_default(),
            "source": crate::engine::paths::display(&crate::engine::paths::absolute(&source_path)),
        }),
    );
    save_user_assets(&dir, &manifest)?;
    ensure_assets()
}

/// `effect_library_reset_assets`：清掉自定义图，回到内置演示图。
pub fn reset_assets() -> Result<Value, String> {
    let dir = preview_dir();
    let manifest = load_user_assets(&dir);
    for entry in manifest.values() {
        if let Some(file) = entry.get("file").and_then(Value::as_str) {
            let _ = std::fs::remove_file(dir.join(file));
        }
    }
    let _ = std::fs::remove_file(dir.join(MANIFEST_NAME));
    ensure_assets()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn demo_images_are_drawn_with_expected_size() {
        let dir = std::env::temp_dir().join(format!("itv-effect-demo-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("demo.png");
        draw_demo(&path, (40, 90, 200), (120, 40, 160), "circle").unwrap();
        let (w, h) = image::image_dimensions(&path).unwrap();
        assert_eq!((w, h), (WIDTH, HEIGHT));
        // 顶部接近 top 色、底部接近 bottom 色
        let image = image::open(&path).unwrap().to_rgb8();
        let top = image.get_pixel(5, 0).0;
        let bottom = image.get_pixel(5, HEIGHT - 1).0;
        assert!(top[2] > 150, "顶部应偏蓝：{top:?}");
        assert!(bottom[0] > 90, "底部应偏红：{bottom:?}");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn manifest_roundtrip_keeps_valid_entries_only() {
        let dir = std::env::temp_dir().join(format!("itv-effect-manifest-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let mut manifest = Map::new();
        manifest.insert(
            "a".into(),
            json!({ "file": "user-a.png", "source": "C:/x.png" }),
        );
        manifest.insert("bad".into(), json!({ "file": 1 }));
        save_user_assets(&dir, &manifest).unwrap();
        let loaded = load_user_assets(&dir);
        assert_eq!(loaded.len(), 1, "只保留 a：{loaded:?}");
        assert_eq!(
            loaded
                .get("a")
                .and_then(|v| v.get("file"))
                .and_then(Value::as_str),
            Some("user-a.png")
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn invalid_slot_is_rejected() {
        let mut params = Map::new();
        params.insert("which".into(), json!("c"));
        params.insert("path".into(), json!("C:/x.png"));
        assert!(set_asset(&params).is_err());
    }

    #[test]
    fn missing_source_is_rejected() {
        let mut params = Map::new();
        params.insert("which".into(), json!("a"));
        params.insert("path".into(), json!("C:/definitely-missing-xyz.png"));
        let error = set_asset(&params).unwrap_err();
        assert!(error.contains("不存在"), "错误文案: {error}");
    }
}
