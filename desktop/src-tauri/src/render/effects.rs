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

/// 剪映 `GESticker_SoulScale` 的 16 帧缩放曲线（`SOUL_OUT_SCALE_CURVE`）。
///
/// ⚠️ 这些数字必须与 `src/core/video_effect_engine.py` 逐位一致。
/// 我第一版是"按感觉"编的（1.0→1.15），实际曲线是 1.63→3.45，差了一个数量级。
const SOUL_OUT_SCALE_CURVE: [f64; 16] = [
    1.6268295, 1.7598855, 1.899264, 2.0450655, 2.1973845, 2.3563155, 2.521950, 2.694381, 2.8736985,
    3.0599925, 3.2533515, 3.453861, 3.453861, 3.453861, 3.453861, 3.453861,
];
/// 同位混合曲线（`SOUL_OUT_MIX_CURVE`）。
const SOUL_OUT_MIX_CURVE: [f64; 16] = [
    0.411498, 0.340743, 0.283781, 0.237625, 0.199993, 0.169133, 0.143688, 0.122599, 0.037117,
    0.028870, 0.022595, 0.017788, 0.010000, 0.010000, 0.010000, 0.010000,
];
/// 曲线采样帧率（`SOUL_OUT_CURVE_FPS`）。注意是 29.85，不是 30。
const SOUL_OUT_CURVE_FPS: f64 = 29.85;

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

    // 每个像素的结果只取决于它自己的坐标，行与行之间没有依赖 ——
    // 因此可以按行切块并行，输出逐字节不变（effects_baseline 守着这一点）。
    //
    // ⚠️ 这里刻意保持「逐像素调 sample_bilinear」的写法。曾试着把 y 方向的
    // 采样点提到行外复用、并绕过 fetch 直接用字节偏移，结果快了几毫秒，
    // 但浮点累加顺序一变，`摇摆推拉` 的输出就变了 —— 基线当场拦住。
    // 这条函数被所有仿射特效共用，不值得为几毫秒冒这个险。
    let row_bytes = source.width as usize * 3;
    super::parallel::par_rows_mut(&mut result, |start_row, rows, chunk| {
        for local_row in 0..rows {
            let y = (start_row + local_row) as i64;
            let fy = y as f64;
            // 预先算好与 x 无关的部分，省掉每个像素一次乘法
            let sx_base = i01 * fy + i02;
            let sy_base = i11 * fy + i12;
            let offset = local_row * row_bytes;
            for x in 0..width {
                let fx = x as f64;
                let sx = i00 * fx + sx_base;
                let sy = i10 * fx + sy_base;
                let value = sample_bilinear(source, sx, sy, border);
                let at = offset + x as usize * 3;
                chunk[at..at + 3].copy_from_slice(&value);
            }
        }
    });
    result
}

/// 双线性采样 + 边界处理。坐标为「像素中心」约定（与 OpenCV 一致）。
pub(crate) fn sample_bilinear(source: &BgrFrame, x: f64, y: f64, border: BorderMode) -> [u8; 3] {
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
///
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
///
/// 实现了 `PartialEq`：`frame_script` 需要比对两帧是否用了相同参数
/// （将来做帧复用优化时要用），而且测试里直接比较参数比逐个字段断言清楚。
#[derive(Debug, Clone, PartialEq)]
pub struct EffectParams {
    pub effect_type: String,
    pub time_sec: f64,
    pub duration_sec: f64,
    /// 强度百分比（默认 100）。
    pub intensity: f64,
    pub speed: f64,
    /// 该特效的**专属参数**（来自 `catalog` 的声明，值由 `effect_params` 解析）。
    ///
    /// 用 `serde_json::Map` 而不是固定字段，是因为每个特效的参数各不相同：
    /// 「故障抖动」要色彩偏移量，「滚动快门」要滚动条数。
    /// 实现代码用 [`EffectParams::param`] 取，取不到就用自己给的默认值 ——
    /// 这样旧配置（没有这个字段）照样能跑。
    pub extra: serde_json::Map<String, serde_json::Value>,
}

impl EffectParams {
    /// 不带专属参数的构造器。测试和预览用它，避免每次都要写一个空 Map。
    pub fn new(
        effect_type: impl Into<String>,
        time_sec: f64,
        duration_sec: f64,
        intensity: f64,
        speed: f64,
    ) -> Self {
        EffectParams {
            effect_type: effect_type.into(),
            time_sec,
            duration_sec,
            intensity,
            speed,
            extra: serde_json::Map::new(),
        }
    }

    /// 取一个专属参数，缺省时用 `fallback`。
    ///
    /// 只接受数字，其它类型（字符串、null）一律当缺省 —— 渲染代码不该
    /// 因为配置里写错一个字就崩。
    pub fn param(&self, key: &str, fallback: f64) -> f64 {
        self.extra
            .get(key)
            .and_then(|value| match value {
                serde_json::Value::Number(number) => number.as_f64(),
                serde_json::Value::Bool(flag) => Some(if *flag { 1.0 } else { 0.0 }),
                _ => None,
            })
            .filter(|value| value.is_finite())
            .unwrap_or(fallback)
    }
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
        // ---------- 第二批：20 个无限循环复合特效 ----------
        "8字漂移" => {
            let scale = 1.08 + 0.03 * intensity_scale;
            let tx = 0.04 * width * intensity_scale * p1.sin();
            let ty = 0.03 * height * intensity_scale * (2.0 * p1).sin();
            affine(scale, 0.0, tx, ty)
        }

        "径向脉冲旋转" => {
            let pulse = 0.5 - 0.5 * p3.cos();
            let scale = 1.03 + 0.10 * intensity_scale * pulse;
            let angle = 8.0 * intensity_scale * p2.sin();
            affine(scale, angle, 0.0, 0.0)
        }

        "镜头抖动呼吸" => {
            let scale = 1.03 + 0.06 * intensity_scale * (0.5 - 0.5 * p1.cos());
            let tx = 0.01 * width * intensity_scale * (8.0 * p1).sin();
            let ty = 0.01 * height * intensity_scale * (7.0 * p1).cos();
            affine(scale, 0.0, tx, ty)
        }

        "反向双旋" => {
            let base = 1.05 + 0.03 * intensity_scale;
            let angle = 6.0 * intensity_scale * p1.sin();
            let first = affine(base, angle, 0.0, 0.0);
            let second = affine(base, -angle, 0.0, 0.0);
            // `cv2.addWeighted(f1, alpha, f2, 1-alpha, 0)` 即 f1*alpha + f2*(1-alpha)；
            // 而 `blend_weighted(a, b, alpha)` 是 a*(1-alpha) + b*alpha —— 权重方向相反，
            // 所以这里要传 1-alpha（第一版传了 alpha，灰阶整个翻转，18% 像素超阈值）。
            let alpha = 0.5 + 0.25 * p2.sin();
            super::pixels::blend_weighted(&first, &second, 1.0 - alpha)
        }

        "呼吸变焦扫光" => {
            let scale = 1.02 + 0.08 * intensity_scale * (0.5 - 0.5 * p1.cos());
            let warped = affine(scale, 0.0, 0.0, 0.0);
            sweep_light(
                &warped,
                0.5 + 0.5 * p2.sin(),
                0.08 + 0.04 * intensity_scale,
                0.15 + 0.22 * intensity_scale,
            )
        }

        "旋摆模糊脉冲" => {
            let angle = 5.0 * intensity_scale * p1.sin();
            let warped = affine(1.04 + 0.04 * intensity_scale, angle, 0.0, 0.0);
            let blur_wave = 0.5 - 0.5 * p2.cos();
            let ksize = kernel_size((1.0 + 8.0 * intensity_scale) * blur_wave);
            let blurred = gaussian_blur(&warped, ksize);
            super::pixels::blend_weighted(&warped, &blurred, 0.25 + 0.45 * blur_wave)
        }

        "透视呼吸摆动" => {
            let intensity_scale_ = intensity_scale;
            let tilt = (0.02 + 0.05 * intensity_scale_) * p1.sin();
            let dx = width * tilt;
            let warped = perspective_tilt(frame, dx);
            let matrix = rotation_matrix(
                width * 0.5,
                height * 0.5,
                2.5 * intensity_scale_ * p2.sin(),
                1.02 + 0.03 * intensity_scale_,
            );
            warp_affine(&warped, matrix, BorderMode::Reflect)
        }

        "涡旋推拉" => {
            // 先漩涡旋转，再叠加缩放+旋转
            let inner = apply_single_image_effect(
                frame,
                &EffectParams {
                    effect_type: "漩涡旋转".to_string(),
                    ..params.clone()
                },
            );
            let scale = 1.03 + 0.08 * intensity_scale * (0.5 - 0.5 * p1.cos());
            let angle = 3.0 * intensity_scale * p2.sin();
            let matrix = rotation_matrix(width * 0.5, height * 0.5, angle, scale);
            warp_affine(&inner, matrix, BorderMode::Reflect)
        }

        "变焦摇移" => {
            let scale = 1.06 + 0.08 * intensity_scale * (0.5 - 0.5 * p1.cos());
            let tx = 0.03 * width * intensity_scale * p2.sin();
            let ty = 0.03 * height * intensity_scale * p2.cos();
            affine(scale, 0.0, tx, ty)
        }

        "旋转漂移闪动" => {
            let angle = 6.0 * intensity_scale * p1.sin();
            let tx = 0.02 * width * intensity_scale * p2.sin();
            let ty = 0.02 * height * intensity_scale * p2.cos();
            let warped = affine(1.05 + 0.03 * intensity_scale, angle, tx, ty);
            let glow = 0.08 + 0.18 * intensity_scale * (0.5 - 0.5 * p3.cos());
            multiply_and_clip(&warped, 1.0 + glow)
        }

        "双频摆动" => {
            let angle = 4.0 * intensity_scale * p1.sin() + 2.0 * intensity_scale * (2.7 * p1).sin();
            let tx = 0.025 * width * intensity_scale * p2.sin();
            affine(1.04 + 0.03 * intensity_scale, angle, tx, 0.0)
        }

        "环形巡航" => {
            let scale = 1.10 + 0.03 * intensity_scale;
            let tx = 0.045 * width * intensity_scale * p1.cos();
            let ty = 0.035 * height * intensity_scale * (1.3 * p1).sin();
            let angle = 2.0 * intensity_scale * p2.sin();
            affine(scale, angle, tx, ty)
        }

        "呼吸鱼眼旋摆" => {
            let fisheye = apply_single_image_effect(
                frame,
                &EffectParams {
                    effect_type: "鱼眼镜头".to_string(),
                    ..params.clone()
                },
            );
            let scale = 1.02 + 0.06 * intensity_scale * (0.5 - 0.5 * p1.cos());
            let angle = 4.0 * intensity_scale * p2.sin();
            let matrix = rotation_matrix(width * 0.5, height * 0.5, angle, scale);
            warp_affine(&fisheye, matrix, BorderMode::Reflect)
        }

        // ---------- 单次/往返类 ----------
        "心跳跳动" => {
            let cycles = 2.0 * speed;
            let wave = 0.5 - 0.5 * (2.0 * PI * cycles * time_sec).cos();
            let scale = 1.0 + (0.10 * intensity_scale) * wave;
            scaled_then_crop(frame, scale)
        }

        "反复缩放" => {
            let cycles = 1.5 * speed;
            let t = 0.5 - 0.5 * (2.0 * PI * cycles * time_sec).cos();
            let scale = (1.0 - 0.05 * intensity_scale) + (0.15 * intensity_scale) * t;
            scaled_then_crop(frame, scale)
        }

        "轻微摇摆" => {
            let angle = (3.0 * intensity_scale) * (2.0 * PI * 1.0 * speed * time_sec).sin();
            let scale = 1.02 + 0.02 * intensity_scale;
            let resized = scaled(frame, scale);
            let matrix = rotation_matrix(
                resized.width as f64 * 0.5,
                resized.height as f64 * 0.5,
                angle,
                1.0,
            );
            let rotated = warp_affine(&resized, matrix, BorderMode::Reflect);
            center_crop(&rotated, frame.width, frame.height)
        }

        "右下平移" => {
            let scale = 1.05 + 0.05 * intensity_scale;
            let resized = scaled(frame, scale);
            let max_x = resized.width.saturating_sub(frame.width);
            let max_y = resized.height.saturating_sub(frame.height);
            let x = (max_x as f64 * progress) as i64;
            let y = (max_y as f64 * progress) as i64;
            super::pixels::crop(&resized, x, y, frame.width, frame.height)
        }

        "左上平移" => {
            let scale = 1.05 + 0.05 * intensity_scale;
            let resized = scaled(frame, scale);
            let max_x = resized.width.saturating_sub(frame.width);
            let max_y = resized.height.saturating_sub(frame.height);
            let x = (max_x as f64 * (1.0 - progress)) as i64;
            let y = (max_y as f64 * (1.0 - progress)) as i64;
            super::pixels::crop(&resized, x, y, frame.width, frame.height)
        }

        "镜头呼吸" => {
            let t = 0.5 - 0.5 * (2.0 * PI * 1.0 * speed * time_sec).cos();
            scaled_then_crop(frame, 1.01 + (0.06 * intensity_scale) * t)
        }

        "脉冲放大" => {
            let t = 0.5 - 0.5 * (2.0 * PI * 3.0 * speed * time_sec).cos();
            scaled_then_crop(frame, 1.0 + (0.08 * intensity_scale) * t)
        }

        "旋转摆动" => {
            let angle = (6.0 * intensity_scale) * (2.0 * PI * 1.5 * speed * time_sec).sin();
            let scale = 1.02 + 0.04 * intensity_scale;
            let resized = scaled(frame, scale);
            let matrix = rotation_matrix(
                resized.width as f64 * 0.5,
                resized.height as f64 * 0.5,
                angle,
                1.0,
            );
            let rotated = warp_affine(&resized, matrix, BorderMode::Reflect);
            center_crop(&rotated, frame.width, frame.height)
        }

        // ---------- remap 类：逐像素坐标映射 ----------
        "水波扭曲" => {
            let center_x = width * 0.5;
            let center_y = height * 0.5;
            let wave_amp = (6.0 + 10.0 * intensity_scale)
                * (0.8 + 0.2 * (2.0 * PI * 0.5 * speed * time_sec).sin());
            let wave_freq = 0.035;
            let wave_phase = 2.0 * PI * speed * time_sec * 2.0;
            let mut map_x = vec![0.0f32; (frame.width * frame.height) as usize];
            let mut map_y = vec![0.0f32; (frame.width * frame.height) as usize];
            for y in 0..frame.height {
                for x in 0..frame.width {
                    let dx = x as f64 - center_x;
                    let dy = y as f64 - center_y;
                    let dist = (dx * dx + dy * dy).sqrt() + 1e-6;
                    let offset = wave_amp * (dist * wave_freq + wave_phase).sin();
                    let index = (y * frame.width + x) as usize;
                    // astype(float32) 是截断到 f32 精度，不是取整
                    map_x[index] = (x as f64 + dx / dist * offset) as f32;
                    map_y[index] = (y as f64 + dy / dist * offset) as f32;
                }
            }
            remap(frame, &map_x, &map_y, BorderMode::Reflect)
        }

        "漩涡旋转" => {
            let center_x = width * 0.5;
            let center_y = height * 0.5;
            let max_r = 1.0f64.max((center_x * center_x + center_y * center_y).sqrt());
            let swirl_strength =
                (2.8 * intensity_scale) * (2.0 * PI * 0.4 * speed * time_sec).sin();
            let mut map_x = vec![0.0f32; (frame.width * frame.height) as usize];
            let mut map_y = vec![0.0f32; (frame.width * frame.height) as usize];
            for y in 0..frame.height {
                for x in 0..frame.width {
                    let px = x as f64 - center_x;
                    let py = y as f64 - center_y;
                    let r = (px * px + py * py).sqrt();
                    let base_theta = py.atan2(px);
                    let ratio = r / max_r;
                    let theta = base_theta + swirl_strength * (1.0 - ratio) * ratio;
                    let index = (y * frame.width + x) as usize;
                    map_x[index] = (center_x + r * theta.cos()) as f32;
                    map_y[index] = (center_y + r * theta.sin()) as f32;
                }
            }
            remap(frame, &map_x, &map_y, BorderMode::Reflect)
        }

        "鱼眼镜头" => {
            let center_x = width * 0.5;
            let center_y = height * 0.5;
            let norm_x = 1.0f64.max(center_x);
            let norm_y = 1.0f64.max(center_y);
            let k = (0.18 * intensity_scale) * (2.0 * PI * 0.6 * speed * time_sec).sin();
            let mut map_x = vec![0.0f32; (frame.width * frame.height) as usize];
            let mut map_y = vec![0.0f32; (frame.width * frame.height) as usize];
            for y in 0..frame.height {
                for x in 0..frame.width {
                    let nx = (x as f64 - center_x) / norm_x;
                    let ny = (y as f64 - center_y) / norm_y;
                    let r2 = nx * nx + ny * ny;
                    let scale_d = 1.0 + k * r2;
                    let index = (y * frame.width + x) as usize;
                    map_x[index] = (center_x + nx * scale_d * center_x) as f32;
                    map_y[index] = (center_y + ny * scale_d * center_y) as f32;
                }
            }
            remap(frame, &map_x, &map_y, BorderMode::Reflect)
        }

        // ---------- 通道 / 模糊 / 边缘类 ----------
        "故障抖动" => {
            // 专属参数（catalog 声明）：错位幅度是百分比，频率是倍数。
            // 缺省值时与改造前完全一致（100% / 3.0 Hz），所以旧配置画面不变。
            let shift_scale = params.param("shift", 100.0) / 100.0;
            let glitch_freq = params.param("freq", 3.0).clamp(0.1, 20.0);
            let shift = ((3.0 + 7.0 * intensity_scale)
                * shift_scale
                * (2.0 * PI * glitch_freq * speed * time_sec).sin()) as i64;
            let mut glitch = frame.clone();
            // B/R 通道反向水平平移（对应 np.roll(r, shift) / np.roll(b, -shift)）
            for y in 0..frame.height {
                for x in 0..frame.width {
                    let src_r = roll_index(x as i64 - shift, frame.width as i64);
                    let src_b = roll_index(x as i64 + shift, frame.width as i64);
                    if let (Some(right), Some(left), Some(center)) = (
                        frame.pixel(src_r as u32, y),
                        frame.pixel(src_b as u32, y),
                        frame.pixel(x, y),
                    ) {
                        // BGR：0=B、1=G、2=R
                        glitch.set_pixel(x, y, [left[0], center[1], right[2]]);
                    }
                }
            }
            // 条带整体位移
            let band_height = 2i64.max((height * 0.06) as i64);
            let band_y = ((0.5 - 0.5 * (2.0 * PI * 1.7 * speed * time_sec).cos())
                * (1.0f64).max(height - band_height as f64)) as i64;
            let band_offset = ((10.0 + 20.0 * intensity_scale)
                * (2.0 * PI * 6.0 * speed * time_sec).sin()) as i64;
            if band_height > 0 && band_y >= 0 && band_y < frame.height as i64 {
                let end = (band_y + band_height).min(frame.height as i64);
                let original = glitch.clone();
                for y in band_y..end {
                    for x in 0..frame.width {
                        let src = roll_index(x as i64 - band_offset, frame.width as i64);
                        if let Some(value) = original.pixel(src as u32, y as u32) {
                            glitch.set_pixel(x, y as u32, value);
                        }
                    }
                }
            }
            glitch
        }

        // ---------- 以下三个参考 Concat 的包名，用 CPU 重写 ----------
        // Concat 的实现是 WGSL 着色器（AGPL-3.0），这里没有照抄代码，
        // 只借了「做什么」的想法，实现是重新写的 CPU 版本。
        "色差分离" => {
            // 红/蓝通道向外扩散，模拟镜头色散。强度越大分离越明显。
            let spread = ((2.0 + 10.0 * intensity_scale)
                * (0.6 + 0.4 * (2.0 * PI * 1.2 * speed * time_sec).sin()))
                as i64;
            let mut out = frame.clone();
            for y in 0..frame.height {
                for x in 0..frame.width {
                    // 半径方向：以画面中心为原点向外推
                    let dx = x as i64 - frame.width as i64 / 2;
                    let dy = y as i64 - frame.height as i64 / 2;
                    let distance = ((dx * dx + dy * dy) as f64).sqrt().max(1.0);
                    // 越靠外分离越多（真实的色散就是这样）
                    let falloff = distance / (frame.width as f64 * 0.5).max(1.0);
                    let offset = (spread as f64 * falloff) as i64;
                    let src_r = roll_index(x as i64 + offset, frame.width as i64);
                    let src_b = roll_index(x as i64 - offset, frame.width as i64);
                    if let (Some(red), Some(blue), Some(center)) = (
                        frame.pixel(src_r as u32, y),
                        frame.pixel(src_b as u32, y),
                        frame.pixel(x, y),
                    ) {
                        // BGR：0=B、1=G、2=R
                        out.set_pixel(x, y, [blue[0], center[1], red[2]]);
                    }
                }
            }
            out
        }

        "色调分离" => {
            // 把每个通道压到 N 级台阶上，形成海报效果。级数越少越抽象。
            let steps = params.param("steps", 6.0).round().clamp(2.0, 32.0);
            // 强度控制「往台阶上靠多少」：100% 完全量化，0% 保持原样
            let blend = intensity_scale.clamp(0.0, 1.0);
            let mut out = frame.clone();
            for pixel in out.data.chunks_exact_mut(3) {
                for channel in pixel.iter_mut() {
                    let original = *channel as f64;
                    let quantized =
                        (original / 255.0 * (steps - 1.0)).round() / (steps - 1.0) * 255.0;
                    let mixed = original + (quantized - original) * blend;
                    *channel = mixed.clamp(0.0, 255.0).round() as u8;
                }
            }
            out
        }

        "半调网点" => {
            // 把亮度转成不同大小的圆点，模拟印刷网点。
            // 网点边长可调：越小点越密、越像真印刷。
            let cell = params.param("cell", 4.0).round().clamp(2.0, 24.0) as i64;
            let mut out = frame.clone();
            for y in 0..frame.height {
                for x in 0..frame.width {
                    // 所在网点的左上角
                    let cell_x = (x as i64 / cell) * cell;
                    let cell_y = (y as i64 / cell) * cell;
                    // 用网点中心的亮度决定这个点多大
                    let center_x = (cell_x + cell / 2).clamp(0, frame.width as i64 - 1) as u32;
                    let center_y = (cell_y + cell / 2).clamp(0, frame.height as i64 - 1) as u32;
                    let center = frame.pixel(center_x, center_y).unwrap_or([0, 0, 0]);
                    let luma = 0.114 * center[0] as f64
                        + 0.587 * center[1] as f64
                        + 0.299 * center[2] as f64;
                    // 亮度越高点越大；半径上限是半个网格
                    let radius = (luma / 255.0).sqrt() * (cell as f64) * 0.5;
                    // 当前像素到网点中心的距离
                    let dx = (x as i64 - (cell_x + cell / 2)) as f64;
                    let dy = (y as i64 - (cell_y + cell / 2)) as f64;
                    let distance = (dx * dx + dy * dy).sqrt();
                    // 点在圈内画白、圈外画黑 —— 这是印刷网点的经典形态
                    let value = if distance <= radius { 255u8 } else { 0 };
                    out.set_pixel(x, y, [value, value, value]);
                }
            }
            out
        }

        "镜像扫光" => {
            // 与「呼吸变焦扫光」共用扫光逻辑，只是不带缩放、位置按 progress 推进
            sweep_light(
                frame,
                progress,
                0.08 + 0.04 * intensity_scale,
                0.22 + 0.18 * intensity_scale,
            )
        }

        "呼吸模糊" => {
            let blur_wave = 0.5 - 0.5 * (2.0 * PI * 1.3 * speed * time_sec).cos();
            let blur_strength = ((1.0 + 8.0 * intensity_scale) * blur_wave) as i64;
            let ksize = 1i64.max(blur_strength * 2 + 1) as u32;
            let blurred = gaussian_blur(frame, ksize);
            super::pixels::blend_weighted(frame, &blurred, 0.35 + 0.45 * blur_wave)
        }

        "径向拉伸" => {
            // 近似 zoom blur：多次缩放回贴后叠加
            let layers = 5;
            let mut acc = vec![0.0f64; frame.data.len()];
            for (index, byte) in frame.data.iter().enumerate() {
                acc[index] = *byte as f64 * 0.35;
            }
            for i in 1..=layers {
                let t = i as f64 / layers as f64;
                let s = 1.0
                    + (0.02 + 0.08 * intensity_scale)
                        * t
                        * (0.5 - 0.5 * (2.0 * PI * speed * time_sec).cos());
                let resized = scaled(frame, s);
                let cropped = center_crop(&resized, frame.width, frame.height);
                let weight = 0.65 / layers as f64;
                for (index, byte) in cropped.data.iter().enumerate() {
                    acc[index] += *byte as f64 * weight;
                }
            }
            let mut out = frame.clone();
            for (index, value) in acc.iter().enumerate() {
                out.data[index] = value.clamp(0.0, 255.0) as u8;
            }
            out
        }

        "边缘闪烁" => {
            let gray = to_gray(frame);
            let edges = canny(&gray, frame.width, frame.height, 60.0, 140.0);
            let blurred = gaussian_blur_gray(&edges, frame.width, frame.height, 3);
            let pulse = 0.15
                + (0.45 * intensity_scale)
                    * (0.5 - 0.5 * (2.0 * PI * 3.2 * speed * time_sec).cos());
            let mut out = frame.clone();
            // ⚠️ `blurred` 是「每像素 1 字节」，`out.data` 是「每像素 3 字节」——
            // 用字节下标去取灰度高会越界（第一版就这样崩了）。
            for (pixel, glow) in blurred.iter().enumerate() {
                let glow = *glow as f64;
                for channel in 0..3 {
                    let index = pixel * 3 + channel;
                    out.data[index] =
                        (frame.data[index] as f64 + glow * pulse).clamp(0.0, 255.0) as u8;
                }
            }
            out
        }

        "透视俯仰" => {
            let tilt = (0.02 + 0.06 * intensity_scale) * (2.0 * PI * 0.8 * speed * time_sec).sin();
            perspective_tilt(frame, width * tilt)
        }

        "滚动快门" => {
            // 专属参数：滚动条数（默认 4.0，与改造前一致）
            let bands = params.param("bands", 4.0).clamp(0.5, 40.0);
            let mut out = frame.clone();
            for y in 0..frame.height {
                let phase =
                    2.0 * PI * ((y as f64 / 1.0f64.max(height)) * bands + speed * time_sec * 2.0);
                let shift = ((3.0 + 10.0 * intensity_scale) * phase.sin()) as i64;
                for x in 0..frame.width {
                    let src = roll_index(x as i64 - shift, frame.width as i64);
                    if let Some(value) = frame.pixel(src as u32, y) {
                        out.set_pixel(x, y, value);
                    }
                }
            }
            out
        }

        "灵魂出窍" => {
            let intensity_clamped = (params.intensity / 100.0).clamp(0.0, 2.0);
            let speed_clamped = speed.max(0.1);
            let index = ((time_sec * speed_clamped * SOUL_OUT_CURVE_FPS).floor() as i64)
                .rem_euclid(16) as usize;
            let scale = 1.0 + (SOUL_OUT_SCALE_CURVE[index] - 1.0) * intensity_clamped;
            let mixture = (SOUL_OUT_MIX_CURVE[index] * intensity_clamped).clamp(0.0, 1.0);
            // 注意中心点是 ((w-1)*0.5, (h-1)*0.5)，且边界是 REPLICATE（与其它特效不同）
            let matrix = rotation_matrix((width - 1.0) * 0.5, (height - 1.0) * 0.5, 0.0, scale);
            let zoomed = warp_affine(frame, matrix, BorderMode::Replicate);
            super::pixels::blend_weighted(frame, &zoomed, mixture)
        }

        _ => frame.clone(),
    }
}

/// 缩放后中心裁剪（多数特效的通用收尾）。
fn scaled(frame: &BgrFrame, scale: f64) -> BgrFrame {
    super::pixels::resize(
        frame,
        ((frame.width as f64 * scale) as i64).max(1) as u32,
        ((frame.height as f64 * scale) as i64).max(1) as u32,
        super::pixels::ResizeFilter::Bilinear,
    )
}

fn scaled_then_crop(frame: &BgrFrame, scale: f64) -> BgrFrame {
    let resized = scaled(frame, scale);
    center_crop(&resized, frame.width, frame.height)
}

/// `np.roll` 的索引（环形）。
fn roll_index(value: i64, size: i64) -> i64 {
    if size <= 0 {
        return 0;
    }
    value.rem_euclid(size)
}

/// 高斯核半径：`max(1, k)*2+1` 的奇数化，返回核尺寸。
fn kernel_size(value: f64) -> u32 {
    // Python: ksize = max(1, int(...) * 2 + 1)
    let base = value.max(1.0) as u32;
    base * 2 + 1
}

/// `cv2.GaussianBlur(src, (k, k), sigmaX=0)` 的可分离实现。
///
/// sigma=0 时 OpenCV 按 `0.3*((k-1)*0.5 - 1) + 0.8` 推算 sigma。
pub(crate) fn gaussian_blur_ksize_pub(frame: &BgrFrame, ksize: u32) -> BgrFrame {
    gaussian_blur(frame, ksize)
}

fn gaussian_blur(frame: &BgrFrame, ksize: u32) -> BgrFrame {
    if ksize <= 1 {
        return frame.clone();
    }
    let ksize = if ksize.is_multiple_of(2) {
        ksize + 1
    } else {
        ksize
    };
    let sigma = 0.3 * (((ksize - 1) as f64) * 0.5 - 1.0) + 0.8;
    let radius = (ksize / 2) as i64;
    let mut kernel: Vec<f64> = Vec::with_capacity(ksize as usize);
    let mut total = 0.0;
    for offset in -radius..=radius {
        let weight = (-(offset as f64).powi(2) / (2.0 * sigma * sigma)).exp();
        kernel.push(weight);
        total += weight;
    }
    for weight in kernel.iter_mut() {
        *weight /= total;
    }

    // 横向
    let mut horizontal = frame.clone();
    for y in 0..frame.height {
        for x in 0..frame.width {
            let mut sum = [0.0f64; 3];
            for (index, weight) in kernel.iter().enumerate() {
                let sx = roll_index(x as i64 + index as i64 - radius, frame.width as i64) as u32;
                if let Some(pixel) = frame.pixel(sx, y) {
                    for channel in 0..3 {
                        sum[channel] += pixel[channel] as f64 * weight;
                    }
                }
            }
            horizontal.set_pixel(
                x,
                y,
                [
                    sum[0].round().clamp(0.0, 255.0) as u8,
                    sum[1].round().clamp(0.0, 255.0) as u8,
                    sum[2].round().clamp(0.0, 255.0) as u8,
                ],
            );
        }
    }
    // 纵向
    let mut vertical = frame.clone();
    for y in 0..frame.height {
        for x in 0..frame.width {
            let mut sum = [0.0f64; 3];
            for (index, weight) in kernel.iter().enumerate() {
                let sy = roll_index(y as i64 + index as i64 - radius, frame.height as i64) as u32;
                if let Some(pixel) = horizontal.pixel(x, sy) {
                    for channel in 0..3 {
                        sum[channel] += pixel[channel] as f64 * weight;
                    }
                }
            }
            vertical.set_pixel(
                x,
                y,
                [
                    sum[0].round().clamp(0.0, 255.0) as u8,
                    sum[1].round().clamp(0.0, 255.0) as u8,
                    sum[2].round().clamp(0.0, 255.0) as u8,
                ],
            );
        }
    }
    vertical
}

/// 单通道灰度图的高斯模糊（`边缘闪烁` 用）。
fn gaussian_blur_gray(source: &[u8], width: u32, height: u32, ksize: u32) -> Vec<u8> {
    if ksize <= 1 {
        return source.to_vec();
    }
    let sigma = 0.3 * (((ksize - 1) as f64) * 0.5 - 1.0) + 0.8;
    let radius = (ksize / 2) as i64;
    let mut kernel: Vec<f64> = Vec::with_capacity(ksize as usize);
    let mut total = 0.0;
    for offset in -radius..=radius {
        let weight = (-(offset as f64).powi(2) / (2.0 * sigma * sigma)).exp();
        kernel.push(weight);
        total += weight;
    }
    for weight in kernel.iter_mut() {
        *weight /= total;
    }
    // 横向
    let mut horizontal = vec![0f64; source.len()];
    for y in 0..height {
        for x in 0..width {
            let mut sum = 0.0;
            for (index, weight) in kernel.iter().enumerate() {
                let sx = roll_index(x as i64 + index as i64 - radius, width as i64) as u32;
                sum += source[(y * width + sx) as usize] as f64 * weight;
            }
            horizontal[(y * width + x) as usize] = sum;
        }
    }
    // 纵向
    let mut out = vec![0u8; source.len()];
    for y in 0..height {
        for x in 0..width {
            let mut sum = 0.0;
            for (index, weight) in kernel.iter().enumerate() {
                let sy = roll_index(y as i64 + index as i64 - radius, height as i64) as u32;
                sum += horizontal[(sy * width + x) as usize] * weight;
            }
            out[(y * width + x) as usize] = sum.round().clamp(0.0, 255.0) as u8;
        }
    }
    out
}

/// BGR → 灰度（`cv2.cvtColor(..., COLOR_BGR2GRAY)` 的整数权重）。
fn to_gray(frame: &BgrFrame) -> Vec<u8> {
    let mut out = vec![0u8; (frame.width * frame.height) as usize];
    for (index, slot) in out.iter_mut().enumerate() {
        let b = frame.data[index * 3] as f64;
        let g = frame.data[index * 3 + 1] as f64;
        let r = frame.data[index * 3 + 2] as f64;
        *slot = (0.114 * b + 0.587 * g + 0.299 * r)
            .round()
            .clamp(0.0, 255.0) as u8;
    }
    out
}

/// Canny 边缘检测（Sobel + 非极大值抑制 + 双阈值）。
///
/// `cv2.Canny` 的完整实现很重，这里用的是同结构近似：
/// 3x3 Sobel 梯度 → 方向量化后的非极大值抑制 → 双阈值滞后连接。
/// 与 OpenCV 的边界处理细节会有差异，属 B 路线可接受的近似。
fn canny(gray: &[u8], width: u32, height: u32, low: f64, high: f64) -> Vec<u8> {
    let w = width as i64;
    let h = height as i64;
    let mut magnitude = vec![0.0f64; gray.len()];
    let mut direction = vec![0u8; gray.len()];

    let at = |x: i64, y: i64| -> f64 {
        let px = x.clamp(0, w - 1);
        let py = y.clamp(0, h - 1);
        gray[(py * w + px) as usize] as f64
    };

    for y in 0..h {
        for x in 0..w {
            let gx = -at(x - 1, y - 1) - 2.0 * at(x - 1, y) - at(x - 1, y + 1)
                + at(x + 1, y - 1)
                + 2.0 * at(x + 1, y)
                + at(x + 1, y + 1);
            let gy = -at(x - 1, y - 1) - 2.0 * at(x, y - 1) - at(x + 1, y - 1)
                + at(x - 1, y + 1)
                + 2.0 * at(x, y + 1)
                + at(x + 1, y + 1);
            let index = (y * w + x) as usize;
            magnitude[index] = (gx * gx + gy * gy).sqrt();
            // 方向量化到 0/45/90/135 度四档
            let angle = gy.atan2(gx).to_degrees().rem_euclid(180.0);
            direction[index] = if !(22.5..157.5).contains(&angle) {
                0
            } else if angle < 67.5 {
                1
            } else if angle < 112.5 {
                2
            } else {
                3
            };
        }
    }

    // 非极大值抑制
    let mut thin = vec![0.0f64; gray.len()];
    for y in 0..h {
        for x in 0..w {
            let index = (y * w + x) as usize;
            let (dx, dy) = match direction[index] {
                0 => (1i64, 0i64),
                1 => (1, 1),
                2 => (0, 1),
                _ => (-1, 1),
            };
            let current = magnitude[index];
            let prev =
                magnitude[((y + dy).clamp(0, h - 1) * w + (x + dx).clamp(0, w - 1)) as usize];
            let next =
                magnitude[((y - dy).clamp(0, h - 1) * w + (x - dx).clamp(0, w - 1)) as usize];
            if current >= prev && current >= next {
                thin[index] = current;
            }
        }
    }

    // 双阈值 + 滞后
    let mut out = vec![0u8; gray.len()];
    for index in 0..out.len() {
        if thin[index] >= high {
            out[index] = 255;
        }
    }
    // 简单的一轮传播（OpenCV 用迭代连通，这里做 8 邻域两轮）
    for _ in 0..2 {
        let snapshot = out.clone();
        for y in 0..h {
            for x in 0..w {
                let index = (y * w + x) as usize;
                if snapshot[index] != 0 || thin[index] < low {
                    continue;
                }
                let mut linked = false;
                for dy in -1i64..=1 {
                    for dx in -1i64..=1 {
                        let nx = x + dx;
                        let ny = y + dy;
                        if nx < 0 || ny < 0 || nx >= w || ny >= h {
                            continue;
                        }
                        if snapshot[(ny * w + nx) as usize] == 255 {
                            linked = true;
                            break;
                        }
                    }
                    if linked {
                        break;
                    }
                }
                if linked {
                    out[index] = 255;
                }
            }
        }
    }
    out
}

/// 逐点重映射（`cv2.remap` + 双线性 + BORDER_REFLECT）。
fn remap(source: &BgrFrame, map_x: &[f32], map_y: &[f32], border: BorderMode) -> BgrFrame {
    let mut out = source.clone();
    for y in 0..source.height {
        for x in 0..source.width {
            let index = (y * source.width + x) as usize;
            let value = sample_bilinear(source, map_x[index] as f64, map_y[index] as f64, border);
            out.set_pixel(x, y, value);
        }
    }
    out
}

/// 横向扫光：以 `center_ratio ∈ [0,1]` 为中心叠加一条白色光带。
fn sweep_light(frame: &BgrFrame, center_ratio: f64, width_ratio: f64, strength: f64) -> BgrFrame {
    let width = frame.width;
    let band_center = center_ratio * width as f64;
    let band_width = (10.0f64).max(width as f64 * width_ratio);
    let mut out = frame.clone();
    for y in 0..frame.height {
        for x in 0..width {
            let alpha =
                (1.0 - (x as f64 - band_center).abs() / band_width).clamp(0.0, 1.0) * strength;
            if alpha <= 0.0 {
                continue;
            }
            if let Some(pixel) = frame.pixel(x, y) {
                let mixed = [
                    (pixel[0] as f64 * (1.0 - alpha) + 255.0 * alpha).clamp(0.0, 255.0) as u8,
                    (pixel[1] as f64 * (1.0 - alpha) + 255.0 * alpha).clamp(0.0, 255.0) as u8,
                    (pixel[2] as f64 * (1.0 - alpha) + 255.0 * alpha).clamp(0.0, 255.0) as u8,
                ];
                out.set_pixel(x, y, mixed);
            }
        }
    }
    out
}

/// 整体乘一个系数并截断（`np.clip(frame * (1+glow), 0, 255)`）。
fn multiply_and_clip(frame: &BgrFrame, factor: f64) -> BgrFrame {
    let mut out = frame.clone();
    for byte in out.data.iter_mut() {
        *byte = (*byte as f64 * factor).clamp(0.0, 255.0) as u8;
    }
    out
}

/// 四角水平错位的透视变换（`透视呼吸摆动` / `透视俯仰`）。
///
/// 与 Python 一致：`src = [[0,0],[w-1,0],[0,h-1],[w-1,h-1]]`、
/// `dst = [[dx,0],[w-1-dx,0],[-dx,h-1],[w-1+dx,h-1]]`，
/// `getPerspectiveTransform` 求 3x3 矩阵后用 `warpPerspective` 反向采样。
///
/// ⚠️ 第一版我用「按行水平平移」近似，垂直方向完全没变形 ——
/// 22% 的像素超阈值，肉眼能看出是两回事。必须解真的 8 参数透视矩阵。
fn perspective_tilt(frame: &BgrFrame, dx: f64) -> BgrFrame {
    let w = frame.width as f64;
    let h = frame.height as f64;
    let src = [
        (0.0, 0.0),
        (w - 1.0, 0.0),
        (0.0, h - 1.0),
        (w - 1.0, h - 1.0),
    ];
    let dst = [
        (dx, 0.0),
        (w - 1.0 - dx, 0.0),
        (-dx, h - 1.0),
        (w - 1.0 + dx, h - 1.0),
    ];
    let Some(matrix) = perspective_transform(&src, &dst) else {
        return frame.clone();
    };
    warp_perspective(frame, matrix, BorderMode::Reflect)
}

/// 解 `cv2.getPerspectiveTransform`：求 3x3 矩阵 `M` 使 `dst = M · src`（齐次坐标）。
///
/// 8 个未知数（第 9 个固定为 1），每对点给 2 个方程，用高斯消元解线性系统。
fn perspective_transform(src: &[(f64, f64); 4], dst: &[(f64, f64); 4]) -> Option<[[f64; 3]; 3]> {
    let mut a = [[0.0f64; 9]; 8];
    for index in 0..4 {
        let (x, y) = src[index];
        let (u, v) = dst[index];
        a[index * 2] = [x, y, 1.0, 0.0, 0.0, 0.0, -x * u, -y * u, u];
        a[index * 2 + 1] = [0.0, 0.0, 0.0, x, y, 1.0, -x * v, -y * v, v];
    }

    // 高斯消元（列主元）
    for column in 0..8 {
        let mut pivot = column;
        for row in column + 1..8 {
            if a[row][column].abs() > a[pivot][column].abs() {
                pivot = row;
            }
        }
        if a[pivot][column].abs() < 1e-12 {
            return None;
        }
        a.swap(column, pivot);
        let divisor = a[column][column];
        for value in a[column][column..9].iter_mut() {
            *value /= divisor;
        }
        for row in 0..8 {
            if row == column {
                continue;
            }
            let factor = a[row][column];
            if factor == 0.0 {
                continue;
            }
            // 复制主元行再按列相减：`a[row]` 与 `a[column]` 是同一数组的两行，
            // 直接双下标会让借用检查器拒绝，而这里只是 9 个 f64。
            let pivot_row = a[column];
            for (cell, value) in a[row].iter_mut().enumerate().skip(column) {
                *value -= factor * pivot_row[cell];
            }
        }
    }
    let solution: Vec<f64> = (0..8).map(|row| a[row][8]).collect();
    Some([
        [solution[0], solution[1], solution[2]],
        [solution[3], solution[4], solution[5]],
        [solution[6], solution[7], 1.0],
    ])
}

/// `cv2.warpPerspective`：对每个目标像素用**逆矩阵**求源坐标再双线性采样。
fn warp_perspective(frame: &BgrFrame, matrix: [[f64; 3]; 3], border: BorderMode) -> BgrFrame {
    let inverse = match invert3(matrix) {
        Some(value) => value,
        None => return frame.clone(),
    };
    let mut out = frame.clone();
    for y in 0..frame.height {
        for x in 0..frame.width {
            let fx = x as f64;
            let fy = y as f64;
            let denominator = inverse[2][0] * fx + inverse[2][1] * fy + inverse[2][2];
            if denominator.abs() < 1e-12 {
                continue;
            }
            let sx = (inverse[0][0] * fx + inverse[0][1] * fy + inverse[0][2]) / denominator;
            let sy = (inverse[1][0] * fx + inverse[1][1] * fy + inverse[1][2]) / denominator;
            let value = sample_bilinear(frame, sx, sy, border);
            out.set_pixel(x, y, value);
        }
    }
    out
}

/// 3x3 矩阵求逆（伴随矩阵法）。
fn invert3(matrix: [[f64; 3]; 3]) -> Option<[[f64; 3]; 3]> {
    let a = matrix[0][0];
    let b = matrix[0][1];
    let c = matrix[0][2];
    let d = matrix[1][0];
    let e = matrix[1][1];
    let f = matrix[1][2];
    let g = matrix[2][0];
    let h = matrix[2][1];
    let i = matrix[2][2];
    let determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
    if determinant.abs() < 1e-12 {
        return None;
    }
    let inverse_det = 1.0 / determinant;
    Some([
        [
            (e * i - f * h) * inverse_det,
            (c * h - b * i) * inverse_det,
            (b * f - c * e) * inverse_det,
        ],
        [
            (f * g - d * i) * inverse_det,
            (a * i - c * g) * inverse_det,
            (c * d - a * f) * inverse_det,
        ],
        [
            (d * h - e * g) * inverse_det,
            (b * g - a * h) * inverse_det,
            (a * e - b * d) * inverse_det,
        ],
    ])
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
/// 供转场模块复用：双线性 + BORDER_REFLECT 采样（`cv2.remap` 的默认边界）。
pub(crate) fn sample_bilinear_reflect(source: &BgrFrame, x: f64, y: f64) -> [u8; 3] {
    sample_bilinear(source, x, y, BorderMode::Reflect)
}

/// 供转场模块复用：指定核大小与 sigma 的高斯模糊。
pub(crate) fn gaussian_blur_sigma_pub(frame: &BgrFrame, ksize: u32, sigma: f64) -> BgrFrame {
    if ksize <= 1 {
        return frame.clone();
    }
    let ksize = if ksize.is_multiple_of(2) {
        ksize + 1
    } else {
        ksize
    };
    let radius = (ksize / 2) as i64;
    let mut kernel: Vec<f64> = Vec::with_capacity(ksize as usize);
    let mut total = 0.0;
    for offset in -radius..=radius {
        let weight = (-(offset as f64).powi(2) / (2.0 * sigma * sigma)).exp();
        kernel.push(weight);
        total += weight;
    }
    for weight in kernel.iter_mut() {
        *weight /= total;
    }
    let mut horizontal = frame.clone();
    for y in 0..frame.height {
        for x in 0..frame.width {
            let mut sum = [0.0f64; 3];
            for (index, weight) in kernel.iter().enumerate() {
                let sx = (x as i64 + index as i64 - radius).rem_euclid(frame.width as i64) as u32;
                if let Some(pixel) = frame.pixel(sx, y) {
                    for channel in 0..3 {
                        sum[channel] += pixel[channel] as f64 * weight;
                    }
                }
            }
            horizontal.set_pixel(
                x,
                y,
                [
                    sum[0].round().clamp(0.0, 255.0) as u8,
                    sum[1].round().clamp(0.0, 255.0) as u8,
                    sum[2].round().clamp(0.0, 255.0) as u8,
                ],
            );
        }
    }
    let mut vertical = frame.clone();
    for y in 0..frame.height {
        for x in 0..frame.width {
            let mut sum = [0.0f64; 3];
            for (index, weight) in kernel.iter().enumerate() {
                let sy = (y as i64 + index as i64 - radius).rem_euclid(frame.height as i64) as u32;
                if let Some(pixel) = horizontal.pixel(x, sy) {
                    for channel in 0..3 {
                        sum[channel] += pixel[channel] as f64 * weight;
                    }
                }
            }
            vertical.set_pixel(
                x,
                y,
                [
                    sum[0].round().clamp(0.0, 255.0) as u8,
                    sum[1].round().clamp(0.0, 255.0) as u8,
                    sum[2].round().clamp(0.0, 255.0) as u8,
                ],
            );
        }
    }
    vertical
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
        EffectParams::new(effect, time_sec, 3.0, 100.0, 1.0)
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
        assert_eq!(
            reflect_index(-1, 8),
            0,
            "BORDER_REFLECT 的 -1 映射到 0（不是 1）"
        );
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
        let result = warp_affine(
            &frame,
            rotation_matrix(3.0, 2.5, 0.0, 1.0),
            BorderMode::Reflect,
        );
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
        let matrix = Affine {
            m00: 1.0,
            m01: 0.0,
            m02: -100.0,
            m10: 0.0,
            m11: 1.0,
            m12: 0.0,
        };
        let result = warp_affine(&frame, matrix, BorderMode::Constant);
        assert_eq!(result.pixel(0, 0), Some([0, 0, 0]));
    }

    #[test]
    fn replicate_border_repeats_edge() {
        let frame = solid(4, 4, [123, 45, 67]);
        let matrix = Affine {
            m00: 1.0,
            m01: 0.0,
            m02: -100.0,
            m10: 0.0,
            m11: 1.0,
            m12: 0.0,
        };
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
        let matrix = Affine {
            m00: 1.0,
            m01: 0.0,
            m02: 1.0,
            m10: 0.0,
            m11: 1.0,
            m12: 0.0,
        };
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
                assert_eq!(chunk, [200, 100, 50], "{effect} 第 {index} 个像素被污染");
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
