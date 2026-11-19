//! 图片特效（40 种），对齐 `src/render/effects.py` 的 `apply_single_image_effect`。
//!
//! 所有特效都是「围绕画面中心做仿射变换」的变体，核心是三个东西：
//! 1. `rotation_matrix(center, angle, scale)` —— 对应 `cv2.getRotationMatrix2D`；
//! 2. `warp_affine(matrix, 边界模式)` —— 对应 `cv2.warpAffine`，默认 `BORDER_REFLECT`；
//! 3. `center_crop` —— 缩放后裁回原尺寸。
//!
//! ⚠️ `cv2.getRotationMatrix2D` 的角度是**度**，逆时针为正；矩阵是
//! `[[α, β, (1-α)*cx - β*cy], [-β, α, β*cx + (1-α)*cy]]`，其中
//! `α = scale*cos(angle)`、`β = scale*sin(angle)`。
//!
//! 边界模式 `BORDER_REFLECT` 是**镜像**（`gfedcb|abcdefgh|gfedcba`），
//! 不是 `BORDER_REFLECT_101`（`fedcb|abcdefgh|gfedcb`）。两者差一个像素，
//! 旋转时边缘会差一圈。

use std::f64::consts::PI;

use super::pixels::BgrFrame;

/// 仿射矩阵（2x3）。
#[derive(Debug, Clone, Copy)]
pub struct Affine {
    pub m00: f64,
    pub m01: f64,
    pub m02: f64,
    pub m10: f64,
    pub m11: f64,
    pub m12: f64,
}

/// 与 `cv2.getRotationMatrix2D((cx, cy), angle_deg, scale)` 等价。
pub fn rotation_matrix(center_x: f64, center_y: f64, angle_deg: f64, scale: f64) -> Affine {
    let angle = angle_deg * PI / 180.0;
    let alpha = scale * angle.cos();
    let beta = scale * angle.sin();
    Affine {
        m00: alpha,
        m01: beta,
        m02: (1.0 - alpha) * center_x - beta * center_y,
        m10: -beta,
        m11: alpha,
        m12: beta * center_x + (1.0 - alpha) * center_y,
    }
}

impl Affine {
    /// 追加平移（对应 Python 的 `M[0,2] += tx`）。
    pub fn translated(mut self, tx: f64, ty: f64) -> Self {
        self.m02 += tx;
        self.m12 += ty;
        self
    }
}

/// 边界填充方式。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BorderMode {
    /// `BORDER_REFLECT`：`gfedcb|abcdefgh|gfedcba`（镜像，含边缘像素）
    Reflect,
    /// `BORDER_REPLICATE`：`aaaaaa|abcdefgh|hhhhhhh`
    Replicate,
    /// `BORDER_CONSTANT`：填黑
    Constant,
}

/// 与 `cv2.warpAffine` 等价的**反向映射 + 双线性**实现。
///
/// OpenCV 的做法是「对每个目标像素，用逆矩阵找回源坐标，再双线性插值」。
/// 这里照同一思路实现 —— 若改成正向映射（把源像素推到目标），
/// 会出现空洞和锯齿，与 OpenCV 完全不同。
pub fn warp_affine(source: &BgrFrame, matrix: Affine, border: BorderMode) -> BgrFrame {
    let width = source.width as i64;
    let height = source.height as i64;
    let mut result = BgrFrame::black(source.width, source.height);

    // 逆矩阵
    let determinant = matrix.m00 * matrix.m11 - matrix.m01 * matrix.m10;
    if determinant.abs() < 1e-12 {
        return result;
    }
    let inv_det = 1.0 / determinant;
    let i00 = matrix.m11 * inv_det;
    let i01 = -matrix.m01 * inv_det;
    let i02 = (matrix.m01 * matrix.m12 - matrix.m11 * matrix.m02) * inv_det;
    let i10 = -matrix.m10 * inv_det;
    let i11 = matrix.m00 * inv_det;
    let i12 = (matrix.m10 * matrix.m02 - matrix.m00 * matrix.m12) * inv_det;

    for y in 0..height {
        for x in 0..width {
            let fx = x as f64;
            let fy = y as f64;
            let sx = i00 * fx + i01 * fy + i02;
            let sy = i10 * fx + i11 * fy + i12;
            let value = sample_bilinear(source, sx, sy, border);
            result.set_pixel(x as u32, y as u32, value);
        }
    }
    result
}

/// 双线性采样 + 边界处理。坐标为「像素中心」约定（与 OpenCV 一致）。
fn sample_bilinear(source: &BgrFrame, x: f64, y: f64, border: BorderMode) -> [u8; 3] {
    let x0 = x.floor();
    let y0 = y.floor();
    let dx = x - x0;
    let dy = y - y0;
    let x0 = x0 as i64;
    let y0 = y0 as i64;

    let mut total = [0.0f64; 3];
    for (offset_x, weight_x) in [(0i64, 1.0 - dx), (1, dx)] {
        if weight_x == 0.0 {
            continue;
        }
        for (offset_y, weight_y) in [(0i64, 1.0 - dy), (1, dy)] {
            let weight = weight_x * weight_y;
            if weight == 0.0 {
                continue;
            }
            let pixel = fetch(source, x0 + offset_x, y0 + offset_y, border);
            for channel in 0..3 {
                total[channel] += pixel[channel] as f64 * weight;
            }
        }
    }
    let mut out = [0u8; 3];
    for channel in 0..3 {
        // OpenCV 的 saturate_cast<uchar> 是四舍五入
        out[channel] = total[channel].round().clamp(0.0, 255.0) as u8;
    }
    out
}

/// 按边界模式取像素。
fn fetch(source: &BgrFrame, x: i64, y: i64, border: BorderMode) -> [u8; 3] {
    let width = source.width as i64;
    let height = source.height as i64;
    let (px, py) = match border {
        BorderMode::Constant => {
            if x < 0 || y < 0 || x >= width || y >= height {
                return [0, 0, 0];
            }
            (x, y)
        }
        BorderMode::Replicate => (x.clamp(0, width - 1), y.clamp(0, height - 1)),
        BorderMode::Reflect => (reflect_index(x, width), reflect_index(y, height)),
    };
    source.pixel(px as u32, py as u32).unwrap_or([0, 0, 0])
}

/// `BORDER_REFLECT` 的坐标映射：`fedcba|abcdefgh|hgfedcb`。
///
/// ⚠️ 注意区分（OpenCV 有两个极易混淆的模式）：
/// - `BORDER_REFLECT`（**代码用的这个**）：`fedcba|abcdefgh|hgfedcb`，边缘像素**重复**一次，
///   所以 `-1 → 0`、`8 → 7`。
/// - `BORDER_REFLECT_101`（`BORDER_DEFAULT`）：`gfedcb|abcdefgh|gfedcba`，边缘不重复，
///   `-1 → 1`、`8 → 6`。
/// 我第一版把注释和测试按 101 写了，但代码用的是 REFLECT —— 二者差一个像素，
/// 旋转时整个边缘会差一圈，所以这里必须认准。
pub fn reflect_index(value: i64, size: i64) -> i64 {
    if size <= 0 {
        return 0;
    }
    if size == 1 {
        return 0;
    }
    let period = 2 * size;
    let index = value.rem_euclid(period);
    // index ∈ [0, 2*size)：前半段直接取，后半段折回
    if index < size {
        index
    } else {
        period - index - 1
    }
}

/// 从中心裁剪；源比目标小时先拉伸（对应 `_center_crop`）。
pub fn center_crop(source: &BgrFrame, target_w: u32, target_h: u32) -> BgrFrame {
    if source.width < target_w || source.height < target_h {
        return super::pixels::resize(
            source,
            target_w,
            target_h,
            super::pixels::ResizeFilter::Bilinear,
        );
    }
    let x = ((source.width - target_w) / 2) as i64;
    let y = ((source.height - target_h) / 2) as i64;
    super::pixels::crop(source, x, y, target_w, target_h)
}

/// 特效参数（对应 `apply_single_image_effect` 的入参）。
#[derive(Debug, Clone)]
pub struct EffectParams {
    pub effect_type: String,
    pub time_sec: f64,
    pub duration_sec: f64,
    /// 强度百分比（默认 100）。
    pub intensity: f64,
    pub speed: f64,
}

/// 与 `apply_single_image_effect()` 等价。
///
/// 只实现到「仿射变换」这一类（旋转呼吸 / 摇摆推拉 / 圆周漂移 / 螺旋摆动 /
/// 心跳摇摆 / 波浪平移 / 左右晃动 / 上下浮动 等），
/// 依赖 `cv2.remap`、`cv2.blur`、`cv2.warpPerspective` 的高级特效由 Python 继续负责。
pub fn apply_single_image_effect(frame: &BgrFrame, params: &EffectParams) -> BgrFrame {
    if frame.is_empty() {
        return frame.clone();
    }
    let effect = normalize_effect(&params.effect_type);
    if effect == "无特效" {
        return frame.clone();
    }

    let width = frame.width as f64;
    let height = frame.height as f64;
    let time_sec = params.time_sec.max(0.0);
    let speed = params.speed.max(0.01);
    let intensity_scale = params.intensity.max(1.0) / 100.0;
    let progress = 1.0f64.min(time_sec * speed.max(0.01));

    // 循环相位，不依赖视频总时长
    let p1 = 2.0 * PI * 1.0 * speed * time_sec;
    let p2 = 2.0 * PI * 1.6 * speed * time_sec;
    let p3 = 2.0 * PI * 2.2 * speed * time_sec;

    let affine = |scale: f64, angle: f64, tx: f64, ty: f64| {
        let matrix = rotation_matrix(width * 0.5, height * 0.5, angle, scale).translated(tx, ty);
        warp_affine(frame, matrix, BorderMode::Reflect)
    };

    match effect.as_str() {
        "旋转呼吸" => {
            let scale = 1.02 + 0.06 * intensity_scale * (0.5 - 0.5 * p1.cos());
            let angle = 5.0 * intensity_scale * p2.sin();
            affine(scale, angle, 0.0, 0.0)
        }
        "摇摆推拉" => {
            let scale = 1.04 + 0.10 * intensity_scale * (0.5 - 0.5 * p1.cos());
            let angle = 3.5 * intensity_scale * p2.sin();
            let tx = 0.015 * width * intensity_scale * p3.sin();
            affine(scale, angle, tx, 0.0)
        }
        "圆周漂移" => {
            let scale = 1.08 + 0.03 * intensity_scale;
            let tx = 0.035 * width * intensity_scale * p1.cos();
            let ty = 0.035 * height * intensity_scale * p1.sin();
            affine(scale, 0.0, tx, ty)
        }
        "螺旋摆动" => {
            let radius = (0.015 + 0.02 * (0.5 - 0.5 * p2.cos())) * intensity_scale;
            let tx = radius * width * p1.cos();
            let ty = radius * height * p1.sin();
            let angle = 4.0 * intensity_scale * p3.sin();
            let scale = 1.04 + 0.04 * intensity_scale * (0.5 - 0.5 * p1.cos());
            affine(scale, angle, tx, ty)
        }
        "心跳摇摆" => {
            let beat = (0.5 - 0.5 * p2.cos()).powf(1.7);
            let scale = 1.0 + 0.12 * intensity_scale * beat;
            let angle = 2.5 * intensity_scale * p1.sin();
            affine(scale, angle, 0.0, 0.0)
        }
        "波浪平移" => {
            let scale = 1.08 + 0.03 * intensity_scale;
            let tx = 0.04 * width * intensity_scale * p1.sin();
            let ty = 0.025 * height * intensity_scale * p2.sin();
            affine(scale, 0.0, tx, ty)
        }
        "双轴呼吸" => {
            // 这个是分别缩放 xy，不走仿射
            let sx = 1.0 + 0.07 * intensity_scale * p1.sin();
            let sy = 1.0 + 0.07 * intensity_scale * p2.cos();
            let scaled = super::pixels::resize(
                frame,
                ((width * sx) as i64).max(1) as u32,
                ((height * sy) as i64).max(1) as u32,
                super::pixels::ResizeFilter::Bilinear,
            );
            center_crop(&scaled, frame.width, frame.height)
        }
        "左右晃动" => {
            let scale = 1.04 + 0.06 * intensity_scale;
            let resized = super::pixels::resize(
                frame,
                ((width * scale) as i64).max(1) as u32,
                ((height * scale) as i64).max(1) as u32,
                super::pixels::ResizeFilter::Bilinear,
            );
            let max_x = resized.width.saturating_sub(frame.width) as f64;
            let t = 0.5 - 0.5 * (2.0 * PI * 2.0 * speed * time_sec).cos();
            let x = (max_x * t) as i64;
            let cropped = super::pixels::crop(&resized, x, 0, frame.width, resized.height);
            center_crop(&cropped, frame.width, frame.height)
        }
        "上下浮动" => {
            let scale = 1.04 + 0.06 * intensity_scale;
            let resized = super::pixels::resize(
                frame,
                ((width * scale) as i64).max(1) as u32,
                ((height * scale) as i64).max(1) as u32,
                super::pixels::ResizeFilter::Bilinear,
            );
            let max_y = resized.height.saturating_sub(frame.height) as f64;
            let t = 0.5 - 0.5 * (2.0 * PI * 2.0 * speed * time_sec).cos();
            let y = (max_y * t) as i64;
            let cropped = super::pixels::crop(&resized, 0, y, resized.width, frame.height);
            center_crop(&cropped, frame.width, frame.height)
        }
        "缓慢推近" => {
            let scale = 1.0 + (0.12 * intensity_scale) * progress;
            let resized = super::pixels::resize(
                frame,
                ((width * scale) as i64).max(1) as u32,
                ((height * scale) as i64).max(1) as u32,
                super::pixels::ResizeFilter::Bilinear,
            );
            center_crop(&resized, frame.width, frame.height)
        }
        "缓慢拉远" => {
            let scale = (1.0 + 0.12 * intensity_scale) - (0.12 * intensity_scale) * progress;
            let resized = super::pixels::resize(
                frame,
                ((width * scale) as i64).max(1) as u32,
                ((height * scale) as i64).max(1) as u32,
                super::pixels::ResizeFilter::Bilinear,
            );
            center_crop(&resized, frame.width, frame.height)
        }
        _ => frame.clone(),
    }
}

/// 旧特效名 → 新特效名（对应 `legacy_effect_alias`）。
pub fn normalize_effect(name: &str) -> String {
    let alias = match name {
        "心跳跃动" => "心跳跳动",
        "轻微放大" => "镜头呼吸",
        "轻微缩小" => "脉冲放大",
        "左右平移" => "左右晃动",
        "上下平移" => "上下浮动",
        "旋转缩放" => "旋转摆动",
        "缓慢推近" => "摇摆推拉",
        "缓慢拉远" => "双轴呼吸",
        "右下平移" => "圆周漂移",
        "左上平移" => "8字漂移",
        other => other,
    };
    alias.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn solid(width: u32, height: u32, value: [u8; 3]) -> BgrFrame {
        let mut frame = BgrFrame::new(width, height);
        frame.data.chunks_mut(3).for_each(|chunk| {
            chunk.copy_from_slice(&value);
        });
        frame
    }

    fn params(effect: &str, time_sec: f64) -> EffectParams {
        EffectParams {
            effect_type: effect.to_string(),
            time_sec,
            duration_sec: 3.0,
            intensity: 100.0,
            speed: 1.0,
        }
    }

    #[test]
    fn rotation_matrix_matches_opencv_formula() {
        // angle=0, scale=1 → 恒等矩阵
        let identity = rotation_matrix(50.0, 40.0, 0.0, 1.0);
        assert!((identity.m00 - 1.0).abs() < 1e-12);
        assert!(identity.m01.abs() < 1e-12);
        assert!(identity.m02.abs() < 1e-12);
        assert!((identity.m11 - 1.0).abs() < 1e-12);
        assert!(identity.m12.abs() < 1e-12);

        // angle=90, scale=1：cos=0, sin=1 → α=0, β=1
        let rotated = rotation_matrix(10.0, 10.0, 90.0, 1.0);
        assert!(rotated.m00.abs() < 1e-12);
        assert!((rotated.m01 - 1.0).abs() < 1e-12);
        // m02 = (1-0)*10 - 1*10 = 0
        assert!(rotated.m02.abs() < 1e-12);
        assert!((rotated.m10 + 1.0).abs() < 1e-12);
        // m12 = 1*10 + (1-0)*10 = 20
        assert!((rotated.m12 - 20.0).abs() < 1e-12);
    }

    #[test]
    fn reflect_index_matches_opencv_border_reflect() {
        // size=8，BORDER_REFLECT：fedcba | abcdefgh | hgfedcb
        assert_eq!(reflect_index(0, 8), 0);
        assert_eq!(reflect_index(7, 8), 7);
        // 左侧：-1 与 -2 都重复边缘像素 a(0)，-3 → b(1)
        assert_eq!(reflect_index(-1, 8), 0, "BORDER_REFLECT 的 -1 映射到 0（不是 1）");
        assert_eq!(reflect_index(-2, 8), 1);
        assert_eq!(reflect_index(-3, 8), 2);
        // 右侧：8 重复 h(7)，9 → g(6)
        assert_eq!(reflect_index(8, 8), 7, "8 映射到 7");
        assert_eq!(reflect_index(9, 8), 6);
        // 一个完整周期后回到原点
        assert_eq!(reflect_index(16, 8), 0);
        assert_eq!(reflect_index(-16, 8), 0);
        // size=1 是特例
        assert_eq!(reflect_index(5, 1), 0);
    }

    #[test]
    fn identity_warp_returns_same_pixels() {
        let mut frame = BgrFrame::new(6, 5);
        for y in 0..5u32 {
            for x in 0..6u32 {
                frame.set_pixel(x, y, [(x * 30) as u8, (y * 40) as u8, 100]);
            }
        }
        let result = warp_affine(&frame, rotation_matrix(3.0, 2.5, 0.0, 1.0), BorderMode::Reflect);
        // 恒等变换下每个像素都应精确还原（双线性在整数坐标上权重为 1）
        for y in 0..5u32 {
            for x in 0..6u32 {
                assert_eq!(result.pixel(x, y), frame.pixel(x, y), "({x},{y})");
            }
        }
    }

    #[test]
    fn constant_border_fills_black() {
        let frame = solid(4, 4, [200, 200, 200]);
        // 平移 -100 像素，整张图移出画面
        let matrix = Affine { m00: 1.0, m01: 0.0, m02: -100.0, m10: 0.0, m11: 1.0, m12: 0.0 };
        let result = warp_affine(&frame, matrix, BorderMode::Constant);
        assert_eq!(result.pixel(0, 0), Some([0, 0, 0]));
    }

    #[test]
    fn replicate_border_repeats_edge() {
        let frame = solid(4, 4, [123, 45, 67]);
        let matrix = Affine { m00: 1.0, m01: 0.0, m02: -100.0, m10: 0.0, m11: 1.0, m12: 0.0 };
        let result = warp_affine(&frame, matrix, BorderMode::Replicate);
        assert_eq!(result.pixel(0, 0), Some([123, 45, 67]));
    }

    #[test]
    fn reflect_border_mirrors_edge() {
        // 单列渐变，平移后应镜像而不是填黑
        let mut frame = BgrFrame::new(4, 1);
        for x in 0..4u32 {
            frame.set_pixel(x, 0, [(x * 10) as u8, 0, 0]);
        }
        let matrix = Affine { m00: 1.0, m01: 0.0, m02: 1.0, m10: 0.0, m11: 1.0, m12: 0.0 };
        let result = warp_affine(&frame, matrix, BorderMode::Reflect);
        // 右移 1 像素：目标 0 取源 -1 → BORDER_REFLECT 映射到 0 → 值 0
        assert_eq!(result.pixel(0, 0), Some([0, 0, 0]));
        // 目标 1 取源 0 → 0；目标 2 取源 1 → 10
        assert_eq!(result.pixel(2, 0), Some([10, 0, 0]));
    }

    #[test]
    fn no_effect_returns_unchanged() {
        let frame = solid(10, 8, [1, 2, 3]);
        let result = apply_single_image_effect(&frame, &params("无特效", 1.0));
        assert_eq!(result.data, frame.data);
    }

    #[test]
    fn legacy_aliases_are_normalized() {
        assert_eq!(normalize_effect("心跳跃动"), "心跳跳动");
        assert_eq!(normalize_effect("缓慢推近"), "摇摆推拉");
        assert_eq!(normalize_effect("左右平移"), "左右晃动");
        assert_eq!(normalize_effect("旋转呼吸"), "旋转呼吸");
    }

    #[test]
    fn effect_output_keeps_frame_size() {
        let frame = solid(40, 30, [80, 90, 100]);
        for effect in [
            "旋转呼吸",
            "摇摆推拉",
            "圆周漂移",
            "螺旋摆动",
            "心跳摇摆",
            "波浪平移",
            "双轴呼吸",
            "左右晃动",
            "上下浮动",
            "缓慢推近",
            "缓慢拉远",
        ] {
            let result = apply_single_image_effect(&frame, &params(effect, 0.7));
            assert_eq!(
                (result.width, result.height),
                (frame.width, frame.height),
                "{effect} 改变了尺寸"
            );
        }
    }

    #[test]
    fn solid_color_survives_affine_effects() {
        // 纯色图经过仿射变换后应仍是同一颜色（不被边界模式污染成黑）
        let frame = solid(40, 30, [200, 100, 50]);
        for effect in ["旋转呼吸", "圆周漂移", "左右晃动"] {
            let result = apply_single_image_effect(&frame, &params(effect, 0.8));
            for (index, chunk) in result.data.chunks(3).enumerate() {
                assert_eq!(
                    chunk, [200, 100, 50],
                    "{effect} 第 {index} 个像素被污染"
                );
            }
        }
    }

    #[test]
    fn unknown_effect_is_passthrough() {
        let frame = solid(6, 6, [7, 8, 9]);
        let result = apply_single_image_effect(&frame, &params("完全不存在的特效", 1.0));
        assert_eq!(result.data, frame.data);
    }

    #[test]
    fn center_crop_upscales_when_source_is_smaller() {
        let frame = solid(10, 10, [5, 5, 5]);
        let result = center_crop(&frame, 20, 20);
        assert_eq!((result.width, result.height), (20, 20));
    }
}