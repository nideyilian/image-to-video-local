//! 转场渲染，对齐 `src/core/transition_engine.py` 的 `TurboTransitionEngine`。
//!
//! 三个必须原样复刻的细节（错一个画面就不一样）：
//!
//! 1. **`np.linspace(0, 1, n)` 含两端**：n 个点，步长 `1/(n-1)`，第 i 个是 `i*step`。
//!    n==1 时是 `[0.0]`。不是 `i/n`。
//! 2. **`generate_transition_frames` 会多生成 2 帧再掐头去尾**：
//!    `generate_count = num_frames + 2`，算完取 `frames[1:-1]`。
//!    所以真正用于计算的 linspace 是 `n+2` 个点，取中间 `n` 个。
//! 3. **`.astype(np.uint8)` 是截断**（向下取整），而 `cv2.addWeighted` 是四舍五入。
//!    淡入淡出用的是前者，`blend_weighted` 用的是后者，两者不能混用。

use std::f64::consts::PI;

use super::pixels::BgrFrame;

/// 生成 n 个中间帧所需的 alpha 序列（`np.linspace(0, 1, n)`）。
pub fn linspace01(n: usize) -> Vec<f64> {
    if n == 0 {
        return Vec::new();
    }
    if n == 1 {
        return vec![0.0];
    }
    let step = 1.0 / (n as f64 - 1.0);
    (0..n).map(|index| index as f64 * step).collect()
}

/// 生成 n 个 0..limit 的整数切分点（`np.linspace(0, limit, n, dtype=int)`）。
///
/// ⚠️ numpy 的 `linspace(..., dtype=int)` 是**截断**转换，不是四舍五入。
pub fn linspace_int(n: usize, limit: i64) -> Vec<i64> {
    linspace01(n)
        .into_iter()
        .map(|value| (value * limit as f64).trunc() as i64)
        .collect()
}

/// `(a * (1 - alpha) + b * alpha).astype(np.uint8)`：**截断**而非四舍五入。
fn blend_truncate(first: &BgrFrame, second: &BgrFrame, alpha: f64) -> BgrFrame {
    let width = first.width.min(second.width);
    let height = first.height.min(second.height);
    let mut result = BgrFrame::new(width, height);
    let inverse = 1.0 - alpha;
    for index in 0..(width as usize * height as usize) {
        let offset = index * 3;
        for channel in 0..3 {
            let value = first.data[offset + channel] as f64 * inverse
                + second.data[offset + channel] as f64 * alpha;
            // astype(uint8) 对越界值的行为未定义，但 linspace 在 [0,1] 内不会越界
            result.data[offset + channel] = value.clamp(0.0, 255.0).trunc() as u8;
        }
    }
    result
}

/// 转场类型（与 `GUI_TRANSITIONS` 的文案一一对应）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Transition {
    Fade,
    SlideLeft,
    SlideUp,
    CircleExpand,
    Zoom,
    Blinds,
    Pixelate,
    // ---- 第二批 ----
    Rotate,
    Checkerboard,
    Wave,
    ColorMix,
    Block,
    ZoomInImpact,
    ZoomOutExplode,
    RotateZoom,
    ElasticZoom,
    Flip3d,
    PushIn,
    DiagonalWipe,
    DoorOpen,
    Flash,
    Shatter,
    GlowSpread,
    RadialSweep,
    VortexDistort,
    DiamondReveal,
    FocusBlur,
    CurtainVertical,
    CurtainHorizontal,
    LiquidBlend,
    LightStreak,
    ClockWipe,
    /// 未识别或有「无转场」时按淡入淡出处理（与 Python 的默认分支一致）
    Fallback,
}

/// 文案 → 转场类型。未识别的返回 `Fallback`（淡入淡出）。
pub fn parse(name: &str) -> Transition {
    match name {
        "淡入淡出" => Transition::Fade,
        "交叉溶解" => Transition::Fade,
        "左右滑动" => Transition::SlideLeft,
        "上下滑动" => Transition::SlideUp,
        "圆形扩展" => Transition::CircleExpand,
        "缩放过渡" => Transition::Zoom,
        "百叶窗" => Transition::Blinds,
        "像素化" => Transition::Pixelate,
        "旋转变换" => Transition::Rotate,
        "棋盘格" => Transition::Checkerboard,
        "波浪" => Transition::Wave,
        // ⚠️ 曾经这里写成 `Transition::Fade`，导致「颜色混合」实际走的是淡入淡出。
        // 同一个字符串在 match 里出现两次时，**后面那条永远不生效**，
        // Rust 只报 unreachable pattern 警告，跑起来完全看不出问题。
        "颜色混合" => Transition::ColorMix,
        "方块过渡" => Transition::Block,
        "放大冲击" => Transition::ZoomInImpact,
        "缩小爆炸" => Transition::ZoomOutExplode,
        "旋转放大" => Transition::RotateZoom,
        "弹性缩放" => Transition::ElasticZoom,
        "3D翻转" => Transition::Flip3d,
        "推入效果" => Transition::PushIn,
        "对角擦除" => Transition::DiagonalWipe,
        "门式打开" => Transition::DoorOpen,
        "闪光过渡" => Transition::Flash,
        "碎片飞散" => Transition::Shatter,
        "光晕扩散" => Transition::GlowSpread,
        "径向旋切" => Transition::RadialSweep,
        "漩涡扭曲" => Transition::VortexDistort,
        "菱形开幕" => Transition::DiamondReveal,
        "镜头虚焦" => Transition::FocusBlur,
        "纵向拉幕" => Transition::CurtainVertical,
        "横向拉幕" => Transition::CurtainHorizontal,
        "液态融合" => Transition::LiquidBlend,
        "流光擦拭" => Transition::LightStreak,
        "时钟扫描" => Transition::ClockWipe,
        _ => Transition::Fallback,
    }
}

/// 生成转场中间帧。返回的帧数**恰好是 `num_frames`**（已掐头去尾）。
pub fn generate_frames(
    first: &BgrFrame,
    second: &BgrFrame,
    transition: Transition,
    num_frames: usize,
    extra: &serde_json::Map<String, serde_json::Value>,
) -> Vec<BgrFrame> {
    if num_frames == 0 {
        return Vec::new();
    }
    // 多生成 2 帧再掐头去尾，避免首尾帧与静态帧重复。
    //
    // ⚠️ `num_frames == 1` 时**也要** +2：Python 的 `generate_transition_frames`
    // 无条件生成 `num_frames + 2` 帧再 `[1:-1]`，所以 1 帧请求得到的是 alpha=0.5
    // 的中帧。我第一版对 1 帧走了"不加 2"的分支，结果这一帧退化成 alpha=0
    // （等于原图），导出视频里每个转场都"跳"一下 —— 10 帧的视频只有第 4 帧不一致，
    // 因为是那唯一一个转场帧。
    let generate_count = num_frames + 2;
    let mut frames = generate_raw(first, second, transition, generate_count, extra);
    if frames.len() >= num_frames + 2 {
        frames = frames[1..frames.len() - 1].to_vec();
    } else if frames.len() > num_frames {
        frames.truncate(num_frames);
    }
    frames
}

fn generate_raw(
    first: &BgrFrame,
    second: &BgrFrame,
    transition: Transition,
    count: usize,
    extra: &serde_json::Map<String, serde_json::Value>,
) -> Vec<BgrFrame> {
    if count == 0 {
        return Vec::new();
    }
    // 参数由各个转场函数自己取（每个函数只关心自己那几个键），
    // 这里只负责把 extra 透传下去。
    match transition {
        Transition::Fade | Transition::Fallback => linspace01(count)
            .into_iter()
            .map(|alpha| blend_truncate(first, second, alpha))
            .collect(),
        Transition::SlideLeft => slide(first, second, count, true),
        Transition::SlideUp => slide(first, second, count, false),
        Transition::CircleExpand => circle_expand(first, second, count),
        Transition::Zoom => zoom(first, second, count),
        Transition::Blinds => blinds(first, second, count, extra),
        Transition::Pixelate => pixelate(first, second, count),
        Transition::Rotate => rotate(first, second, count),
        Transition::Checkerboard => checkerboard(first, second, count, extra),
        Transition::Wave => wave(first, second, count, extra),
        Transition::ColorMix => color_mix(first, second, count),
        Transition::Block => block(first, second, count, extra),
        Transition::ZoomInImpact => zoom_in_impact(first, second, count),
        Transition::ZoomOutExplode => zoom_out_explode(first, second, count),
        Transition::RotateZoom => rotate_zoom(first, second, count),
        Transition::ElasticZoom => elastic_zoom(first, second, count),
        Transition::Flip3d => flip_3d(first, second, count),
        Transition::PushIn => push_in(first, second, count),
        Transition::DiagonalWipe => diagonal_wipe(first, second, count),
        Transition::DoorOpen => door_open(first, second, count),
        Transition::Flash => flash(first, second, count),
        Transition::Shatter => shatter(first, second, count, extra),
        Transition::GlowSpread => glow_spread(first, second, count),
        Transition::RadialSweep => radial_sweep(first, second, count),
        Transition::VortexDistort => vortex_distort(first, second, count),
        Transition::DiamondReveal => diamond_reveal(first, second, count),
        Transition::FocusBlur => focus_blur(first, second, count),
        Transition::CurtainVertical => curtain(first, second, count, true),
        Transition::CurtainHorizontal => curtain(first, second, count, false),
        Transition::LiquidBlend => liquid_blend(first, second, count),
        Transition::LightStreak => light_streak(first, second, count),
        Transition::ClockWipe => clock_wipe(first, second, count),
    }
}

fn slide(first: &BgrFrame, second: &BgrFrame, count: usize, horizontal: bool) -> Vec<BgrFrame> {
    let limit = if horizontal {
        first.width as i64
    } else {
        first.height as i64
    };
    linspace_int(count, limit)
        .into_iter()
        .map(|split| {
            let mut frame = BgrFrame::black(first.width, first.height);
            if horizontal {
                // 左侧用 second，右侧用 first
                for y in 0..first.height {
                    for x in 0..first.width {
                        let source = if (x as i64) < split { second } else { first };
                        if let Some(value) = source.pixel(x, y) {
                            frame.set_pixel(x, y, value);
                        }
                    }
                }
            } else {
                for y in 0..first.height {
                    let source = if (y as i64) < split { second } else { first };
                    for x in 0..first.width {
                        if let Some(value) = source.pixel(x, y) {
                            frame.set_pixel(x, y, value);
                        }
                    }
                }
            }
            frame
        })
        .collect()
}

fn circle_expand(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    // ⚠️ 半径是**浮点**，不取整：`np.linspace(0, max_radius, n)` 直接比较 `d² <= r²`。
    // 若先把半径截断成整数，边界那一圈像素会差一个（表现为 max=191 的零星差异）。
    let center_x = (first.width / 2) as f64;
    let center_y = (first.height / 2) as f64;
    let max_radius = ((center_x * center_x + center_y * center_y).sqrt()) as i64;
    linspace01(count)
        .into_iter()
        .map(|ratio| {
            let radius = ratio * max_radius as f64;
            let mut frame = first.clone();
            for y in 0..first.height {
                for x in 0..first.width {
                    let dx = x as f64 - center_x;
                    let dy = y as f64 - center_y;
                    if dx * dx + dy * dy <= radius * radius {
                        if let Some(value) = second.pixel(x, y) {
                            frame.set_pixel(x, y, value);
                        }
                    }
                }
            }
            frame
        })
        .collect()
}

fn zoom(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    // ⚠️ 这里是**两层**效果，不是简单的缩放：
    // 1. img2 从 0.5 放大到 1.0，居中贴在黑底上；
    // 2. img1 从 1.0 缩小到 0.5，居中后与上一步结果做 addWeighted(1-progress, progress)。
    // 第一版我漏了第 2 步，对照测试当场发现 88.87% 的像素不一致。
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let mut frame = BgrFrame::black(first.width, first.height);

            // --- img2 放大 ---
            let scale2 = 0.5 + progress * 0.5;
            let new_w2 = (first.width as f64 * scale2).trunc() as u32;
            let new_h2 = (first.height as f64 * scale2).trunc() as u32;
            if new_w2 > 0 && new_h2 > 0 {
                let scaled = super::pixels::resize(
                    second,
                    new_w2,
                    new_h2,
                    super::pixels::ResizeFilter::Bilinear,
                );
                let x2 = (first.width.saturating_sub(new_w2) / 2) as i64;
                let y2 = (first.height.saturating_sub(new_h2) / 2) as i64;
                super::pixels::blit(&mut frame, &scaled, x2, y2);
            }

            // --- img1 缩小并与上面结果混合 ---
            let scale1 = 1.0 - progress * 0.5;
            let new_w1 = (first.width as f64 * scale1).trunc() as u32;
            let new_h1 = (first.height as f64 * scale1).trunc() as u32;
            if new_w1 > 0 && new_h1 > 0 {
                let scaled = super::pixels::resize(
                    first,
                    new_w1,
                    new_h1,
                    super::pixels::ResizeFilter::Bilinear,
                );
                let x1 = (first.width.saturating_sub(new_w1) / 2) as i64;
                let y1 = (first.height.saturating_sub(new_h1) / 2) as i64;
                // 取出目标区域，与缩小后的 img1 做 addWeighted（四舍五入语义）
                let region = super::pixels::crop(&frame, x1, y1, new_w1, new_h1);
                let alpha = 1.0 - progress;
                let blended = super::pixels::blend_weighted(&region, &scaled, alpha);
                super::pixels::blit(&mut frame, &blended, x1, y1);
            }

            frame
        })
        .collect()
}

fn blinds(
    first: &BgrFrame,
    second: &BgrFrame,
    count: usize,
    extra: &serde_json::Map<String, serde_json::Value>,
) -> Vec<BgrFrame> {
    // 专属参数取值，缺省用原硬编码值 —— 保证不传参数时画面逐字节不变
    let param = |key: &str, fallback: f64| -> f64 {
        extra
            .get(key)
            .and_then(|value| value.as_f64())
            .filter(|value| value.is_finite())
            .unwrap_or(fallback)
    };
    // ⚠️ 是「每条百叶窗从中心向上下同时展开」，不是「一条一条轮流显示」。
    // 第一版按后者实现，对照测试发现 20% 的像素不一致。
    // 条数可调：默认 10 与改造前一致。太少会变成大块翻板，太多会失去百叶窗的形。
    let num_blinds = param("blinds", 10.0).round().clamp(2.0, 60.0) as i64;
    let height = first.height as i64;
    let blind_height = height / num_blinds.max(1);
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let mut frame = first.clone();
            let open_height = (blind_height as f64 * progress).trunc() as i64;
            if open_height > 0 {
                for index in 0..num_blinds {
                    let y_start = index * blind_height;
                    let y_end = ((index + 1) * blind_height).min(height);
                    let center = (y_start + y_end) / 2;
                    let open_start = y_start.max(center - open_height / 2);
                    let open_end = y_end.min(center + open_height / 2);
                    for y in open_start..open_end {
                        if y < 0 || y >= height {
                            continue;
                        }
                        for x in 0..first.width {
                            if let Some(value) = second.pixel(x, y as u32) {
                                frame.set_pixel(x, y as u32, value);
                            }
                        }
                    }
                }
            }
            frame
        })
        .collect()
}

fn pixelate(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    // ⚠️ 三处与直觉不同（第一版全错，对照测试暴露）：
    // 1. 像素化的对象是 **img1**，不是 img2；
    // 2. pixel_size 从 `min(h,w)//4` 线性降到 1（是尺寸，不是块数）；
    // 3. alpha 由 pixel_size 反推：`1 - (pixel_size-1)/(pixel_sizes[0]-1)`。
    // 且 `pixel_size <= 1` 时直接输出整张 img2。
    let small_side = first.width.min(first.height) as i64;
    let start_size = small_side / 4;
    let pixel_sizes: Vec<i64> = linspace01(count)
        .into_iter()
        .map(|ratio| {
            let value = start_size as f64 + (1.0 - start_size as f64) * ratio;
            value.trunc() as i64
        })
        .collect();
    let first_size = pixel_sizes.first().copied().unwrap_or(1);

    pixel_sizes
        .into_iter()
        .map(|pixel_size| {
            if pixel_size <= 1 {
                return second.clone();
            }
            let small_w = (first.width as i64 / pixel_size).max(0) as u32;
            let small_h = (first.height as i64 / pixel_size).max(0) as u32;
            if small_w == 0 || small_h == 0 {
                return second.clone();
            }
            let down = super::pixels::resize(
                first,
                small_w,
                small_h,
                super::pixels::ResizeFilter::Nearest,
            );
            let up = super::pixels::resize(
                &down,
                first.width,
                first.height,
                super::pixels::ResizeFilter::Nearest,
            );
            let denominator = (first_size - 1) as f64;
            let alpha = if denominator == 0.0 {
                1.0
            } else {
                1.0 - (pixel_size - 1) as f64 / denominator
            };
            super::pixels::blend_weighted(&up, second, alpha)
        })
        .collect()
}


// ---------- 第二批：24 种转场 ----------

/// 复制一块矩形区域（目标坐标可能越界，自动裁剪）。
fn copy_rect(dst: &mut BgrFrame, src: &BgrFrame, x0: i64, y0: i64, x1: i64, y1: i64) {
    let x_start = x0.max(0);
    let y_start = y0.max(0);
    let x_end = x1.min(dst.width as i64);
    let y_end = y1.min(dst.height as i64);
    for y in y_start..y_end {
        for x in x_start..x_end {
            if let Some(value) = src.pixel(x as u32, y as u32) {
                dst.set_pixel(x as u32, y as u32, value);
            }
        }
    }
}

/// 极简确定性伪随机（SplitMix64）：用于「本身就是随机」的转场。
///
/// 这几个转场（棋盘格 / 方块 / 缩小爆炸 / 碎片飞散）在 Python 里用 `np.random`，
/// **每次运行结果都不同**，不存在「逐帧对齐」的可能。这里用固定种子生成
/// 视觉等价的效果，保证同一配置多次渲染结果稳定（比 Python 更可复现）。
struct SplitMix64(u64);

impl SplitMix64 {
    fn new(seed: u64) -> Self {
        SplitMix64(seed)
    }

    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    /// [0, 1)
    fn unit(&mut self) -> f64 {
        (self.next() >> 11) as f64 / (1u64 << 53) as f64
    }

    /// 近似标准正态（Box-Muller），对应 `np.random.randn()` 的用法
    fn normal(&mut self) -> f64 {
        let u1 = self.unit().max(1e-12);
        let u2 = self.unit();
        (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
    }
}

/// `旋转变换`：img1 旋转 0→360°，角度越大越淡化到 img2。
///
/// ⚠️ Python 的 `cv2.warpAffine` 这里**没传 borderMode**，默认是 `BORDER_CONSTANT`（补黑），
/// 不是其它特效用的 REFLECT。用错会在四角出现镜像而不是黑边。
fn rotate(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let center_x = (first.width / 2) as f64;
    let center_y = (first.height / 2) as f64;
    // np.linspace(0, 360, n) 含两端
    let angles: Vec<f64> = if count <= 1 {
        vec![0.0]
    } else {
        (0..count)
            .map(|index| 360.0 * index as f64 / (count - 1) as f64)
            .collect()
    };
    angles
        .into_iter()
        .map(|angle| {
            let matrix = super::effects::rotation_matrix(center_x, center_y, angle, 1.0);
            let rotated =
                super::effects::warp_affine(first, matrix, super::effects::BorderMode::Constant);
            // alpha = angle / 360；addWeighted(rotated, 1-a, second, a, 0)
            super::pixels::blend_weighted(&rotated, second, angle / 360.0)
        })
        .collect()
}

/// `棋盘格`：逐格随机切换（格数随进度增加）
fn checkerboard(
    first: &BgrFrame,
    second: &BgrFrame,
    count: usize,
    extra: &serde_json::Map<String, serde_json::Value>,
) -> Vec<BgrFrame> {
    // 专属参数取值，缺省用原硬编码值 —— 保证不传参数时画面逐字节不变
    let param = |key: &str, fallback: f64| -> f64 {
        extra
            .get(key)
            .and_then(|value| value.as_f64())
            .filter(|value| value.is_finite())
            .unwrap_or(fallback)
    };
    // 格子边长可调：默认 20px 与改造前一致。数值越小格子越密。
    let grid = param("grid", 20.0).round().clamp(4.0, 200.0) as i64;
    let rows = (first.height as i64 / grid).max(1);
    let cols = (first.width as i64 / grid).max(1);
    let mut rng = SplitMix64::new(0xC0FFEE);
    // 预生成格子顺序（避免每帧重新随机导致画面闪烁）
    let total = (rows * cols).max(1) as usize;
    let mut order: Vec<(i64, i64)> = Vec::with_capacity(total);
    for row in 0..rows {
        for col in 0..cols {
            order.push((row, col));
        }
    }
    for index in (1..order.len()).rev() {
        let swap = (rng.next() as usize) % (index + 1);
        order.swap(index, swap);
    }

    linspace01(count)
        .into_iter()
        .map(|progress| {
            let mut frame = first.clone();
            let switches = (progress * total as f64) as usize;
            for &(row, col) in order.iter().take(switches.min(order.len())) {
                let y0 = row * grid;
                let x0 = col * grid;
                copy_rect(
                    &mut frame,
                    second,
                    x0,
                    y0,
                    (x0 + grid).min(first.width as i64),
                    (y0 + grid).min(first.height as i64),
                );
            }
            frame
        })
        .collect()
}

/// `波浪`：按行正弦错位推进
fn wave(
    first: &BgrFrame,
    second: &BgrFrame,
    count: usize,
    extra: &serde_json::Map<String, serde_json::Value>,
) -> Vec<BgrFrame> {
    // 专属参数取值，缺省用原硬编码值 —— 保证不传参数时画面逐字节不变
    let param = |key: &str, fallback: f64| -> f64 {
        extra
            .get(key)
            .and_then(|value| value.as_f64())
            .filter(|value| value.is_finite())
            .unwrap_or(fallback)
    };
    // 振幅与波长可调：默认 20.0 / 0.02 与改造前一致。
    // frequency 是「每像素的相位增量」，越大波越密。
    let amplitude = param("amplitude", 20.0).clamp(1.0, 200.0);
    let frequency = param("frequency", 0.02).clamp(0.001, 0.2);
    let width = first.width as f64;
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let mut frame = first.clone();
            for y in 0..first.height {
                let wave_offset =
                    (amplitude * (frequency * y as f64 + progress * 2.0 * PI).sin()) as i64;
                let wave_progress = (progress + wave_offset as f64 / width) % 1.0;
                let split_x = (width * wave_progress) as i64;
                if split_x > 0 {
                    copy_rect(&mut frame, second, 0, y as i64, split_x, y as i64 + 1);
                }
            }
            frame
        })
        .collect()
}

/// BGR → HSV（H∈[0,180)、S/V∈[0,255]，对齐 OpenCV 的 8U 整数实现）。
///
/// ⚠️ 三个容易出错的细节（第一版全踩了）：
/// 1. **H 不要再多除 2**：`*30` 已经隐含了「0-360 → 0-180」的那次除以二；
///    多除一次色相会整体差一倍。
/// 2. 除法用 **floor**（`div_euclid`）而不是 Rust 的截断除法，
///    否则负角度会差 1（实测 2000 个随机色里约一半）。
/// 3. S 是 `(diff*255 + v/2) / v`，带半个 v 的补偿。
///
/// 仍与 OpenCV 存在 ±1 的差异（它内部还有 SIMD 的定点运算），
/// 这在「颜色混合」这种逐通道插值的场景会累积成轻微色偏，属 B 路线可接受范围。
fn bgr_to_hsv(pixel: [u8; 3]) -> [u8; 3] {
    let b = pixel[0] as i64;
    let g = pixel[1] as i64;
    let r = pixel[2] as i64;
    let v = r.max(g).max(b);
    if v == 0 {
        return [0, 0, 0];
    }
    let min = r.min(g).min(b);
    let diff = v - min;
    let s = (diff * 255 + v / 2) / v;
    if diff == 0 {
        return [0, s as u8, v as u8];
    }
    let raw = if v == r {
        (g - b) * 30
    } else if v == g {
        60 * diff + (b - r) * 30
    } else {
        120 * diff + (r - g) * 30
    };
    let mut h = raw.div_euclid(diff);
    if h < 0 {
        h += 180;
    }
    [h.clamp(0, 179) as u8, s.clamp(0, 255) as u8, v as u8]
}

/// HSV → BGR（对齐 OpenCV 的 8U 整数实现）。
fn hsv_to_bgr(pixel: [u8; 3]) -> [u8; 3] {
    let h = pixel[0] as i64;
    let s = pixel[1] as i64;
    let v = pixel[2] as i64;
    if s == 0 {
        return [v as u8, v as u8, v as u8];
    }
    let region = h / 30;
    let remainder = (h - region * 30) * 255 / 30;
    let p = (v * (255 - s) + 127) / 255;
    let q = (v * (255 - s * remainder / 255) + 127) / 255;
    let t = (v * (255 - s * (255 - remainder) / 255) + 127) / 255;
    let (r, g, b) = match region % 6 {
        0 => (v, t, p),
        1 => (q, v, p),
        2 => (p, v, t),
        3 => (p, q, v),
        4 => (t, p, v),
        _ => (v, p, q),
    };
    [
        b.clamp(0, 255) as u8,
        g.clamp(0, 255) as u8,
        r.clamp(0, 255) as u8,
    ]
}

/// `颜色混合`：HSV 空间插值（不是 BGR 淡入淡出）
fn color_mix(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let first_hsv: Vec<[u8; 3]> = (0..first.data.len() / 3)
        .map(|index| {
            bgr_to_hsv([
                first.data[index * 3],
                first.data[index * 3 + 1],
                first.data[index * 3 + 2],
            ])
        })
        .collect();
    let second_hsv: Vec<[u8; 3]> = (0..second.data.len() / 3)
        .map(|index| {
            bgr_to_hsv([
                second.data[index * 3],
                second.data[index * 3 + 1],
                second.data[index * 3 + 2],
            ])
        })
        .collect();

    linspace01(count)
        .into_iter()
        .map(|progress| {
            let mut frame = first.clone();
            for index in 0..first_hsv.len() {
                let mut mixed = [0u8; 3];
                for channel in 0..3 {
                    let a = first_hsv[index][channel] as f64;
                    let b = second_hsv[index][channel] as f64;
                    mixed[channel] = (a * (1.0 - progress) + b * progress)
                        .round()
                        .clamp(0.0, 255.0) as u8;
                }
                // clip 后转回 BGR（Python 同样先 clip 到 0..255 再 cvtColor）
                let bgr = hsv_to_bgr(mixed);
                frame.data[index * 3] = bgr[0];
                frame.data[index * 3 + 1] = bgr[1];
                frame.data[index * 3 + 2] = bgr[2];
            }
            frame
        })
        .collect()
}

/// `方块过渡`：40px 方块随机顺序出现
fn block(
    first: &BgrFrame,
    second: &BgrFrame,
    count: usize,
    extra: &serde_json::Map<String, serde_json::Value>,
) -> Vec<BgrFrame> {
    // 专属参数取值，缺省用原硬编码值 —— 保证不传参数时画面逐字节不变
    let param = |key: &str, fallback: f64| -> f64 {
        extra
            .get(key)
            .and_then(|value| value.as_f64())
            .filter(|value| value.is_finite())
            .unwrap_or(fallback)
    };
    // 方块边长可调：默认 40px 与改造前一致。
    let block_size = param("block", 40.0).round().clamp(8.0, 300.0) as i64;
    let rows = (first.height as i64 + block_size - 1) / block_size;
    let cols = (first.width as i64 + block_size - 1) / block_size;
    let total = (rows * cols).max(1) as usize;
    let mut rng = SplitMix64::new(0xB10C);
    let mut order: Vec<usize> = (0..total).collect();
    for index in (1..order.len()).rev() {
        let swap = (rng.next() as usize) % (index + 1);
        order.swap(index, swap);
    }

    linspace01(count)
        .into_iter()
        .map(|progress| {
            let mut frame = first.clone();
            let blocks = (total as f64 * progress) as usize;
            for &block_index in order.iter().take(blocks.min(order.len())) {
                let row = block_index as i64 / cols;
                let col = block_index as i64 % cols;
                let y0 = row * block_size;
                let x0 = col * block_size;
                copy_rect(
                    &mut frame,
                    second,
                    x0,
                    y0,
                    (x0 + block_size).min(first.width as i64),
                    (y0 + block_size).min(first.height as i64),
                );
            }
            frame
        })
        .collect()
}

/// `放大冲击`：img2 从 0.1 放大到 1.0，非线性进度
fn zoom_in_impact(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let height = first.height as f64;
    let width = first.width as f64;
    linspace01(count)
        .into_iter()
        .map(|raw| {
            let progress = raw.sqrt();
            let mut frame = first.clone();
            let scale = 0.1 + progress * 0.9;
            let new_h = (height * scale) as i64;
            let new_w = (width * scale) as i64;
            if new_h > 0 && new_w > 0 {
                let scaled = super::pixels::resize(
                    second,
                    new_w as u32,
                    new_h as u32,
                    super::pixels::ResizeFilter::Bilinear,
                );
                let alpha = progress.sqrt();
                if new_h <= first.height as i64 && new_w <= first.width as i64 {
                    let y_offset = (first.height as i64 - new_h) / 2;
                    let x_offset = (first.width as i64 - new_w) / 2;
                    for y in 0..new_h {
                        for x in 0..new_w {
                            let dy = (y_offset + y) as u32;
                            let dx = (x_offset + x) as u32;
                            if let (Some(base), Some(top)) = (frame.pixel(dx, dy), scaled.pixel(x as u32, y as u32)) {
                                let mut mixed = [0u8; 3];
                                for channel in 0..3 {
                                    mixed[channel] = (base[channel] as f64 * (1.0 - alpha)
                                        + top[channel] as f64 * alpha)
                                        .round()
                                        .clamp(0.0, 255.0)
                                        as u8;
                                }
                                frame.set_pixel(dx, dy, mixed);
                            }
                        }
                    }
                } else {
                    frame = super::pixels::blend_weighted(&frame, second, alpha);
                }
            }
            frame
        })
        .collect()
}

/// `缩小爆炸`：img1 缩小并随机偏移，淡出到 img2
fn zoom_out_explode(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let height = first.height as f64;
    let width = first.width as f64;
    let mut rng = SplitMix64::new(0xE8B0DE);
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let scale = 1.0 - progress * 0.9;
            let new_h = (height * scale) as i64;
            let new_w = (width * scale) as i64;
            if new_h <= 0 || new_w <= 0 || scale <= 0.1 {
                return second.clone();
            }
            let scaled = super::pixels::resize(
                first,
                new_w as u32,
                new_h as u32,
                super::pixels::ResizeFilter::Bilinear,
            );
            let explosion = progress * progress;
            let offset_x = (rng.normal() * 20.0 * explosion) as i64;
            let offset_y = (rng.normal() * 20.0 * explosion) as i64;
            let y_offset = (first.height as i64 - new_h) / 2 + offset_y;
            let x_offset = (first.width as i64 - new_w) / 2 + offset_x;
            let alpha = 1.0 - progress;

            let mut frame = second.clone();
            let y1 = y_offset.max(0);
            let y2 = (y_offset + new_h).min(first.height as i64);
            let x1 = x_offset.max(0);
            let x2 = (x_offset + new_w).min(first.width as i64);
            let src_y1 = (-y_offset).max(0);
            let src_x1 = (-x_offset).max(0);
            for y in 0..(y2 - y1).max(0) {
                for x in 0..(x2 - x1).max(0) {
                    let dst = ((y1 + y) as u32, (x1 + x) as u32);
                    let src = ((src_x1 + x) as u32, (src_y1 + y) as u32);
                    if let (Some(base), Some(top)) = (frame.pixel(dst.0, dst.1), scaled.pixel(src.0, src.1)) {
                        let mut mixed = [0u8; 3];
                        for channel in 0..3 {
                            mixed[channel] = (base[channel] as f64 * (1.0 - alpha)
                                + top[channel] as f64 * alpha)
                                .round()
                                .clamp(0.0, 255.0) as u8;
                        }
                        frame.set_pixel(dst.0, dst.1, mixed);
                    }
                }
            }
            frame
        })
        .collect()
}

/// `旋转放大`：img2 旋转 360° 同时从 0.3 放大到 1.0
fn rotate_zoom(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let center_x = (first.width / 2) as f64;
    let center_y = (first.height / 2) as f64;
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let angle = progress * 360.0;
            let scale = 0.3 + progress * 0.7;
            let matrix = super::effects::rotation_matrix(center_x, center_y, angle, scale);
            let warped = super::effects::warp_affine(second, matrix, super::effects::BorderMode::Constant);
            super::pixels::blend_weighted(first, &warped, progress)
        })
        .collect()
}

/// `弹性缩放`：前半段线性放大，后半段回弹
fn elastic_zoom(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let height = first.height as f64;
    let width = first.width as f64;
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let elastic = if progress >= 0.5 {
                1.0 + 0.2 * ((progress - 0.5) * 2.0 * PI * 2.0).sin()
            } else {
                progress * 2.0
            }
            .clamp(0.0, 1.2);
            let scale = 0.5 + elastic * 0.7;
            let new_h = (height * scale) as i64;
            let new_w = (width * scale) as i64;
            if new_h <= 0 || new_w <= 0 {
                return first.clone();
            }
            let scaled = super::pixels::resize(
                second,
                new_w as u32,
                new_h as u32,
                super::pixels::ResizeFilter::Bilinear,
            );
            let alpha = progress;
            if new_h <= first.height as i64 && new_w <= first.width as i64 {
                let mut frame = first.clone();
                let y_offset = (first.height as i64 - new_h) / 2;
                let x_offset = (first.width as i64 - new_w) / 2;
                for y in 0..new_h {
                    for x in 0..new_w {
                        let dy = (y_offset + y) as u32;
                        let dx = (x_offset + x) as u32;
                        if let (Some(base), Some(top)) = (frame.pixel(dx, dy), scaled.pixel(x as u32, y as u32)) {
                            let mut mixed = [0u8; 3];
                            for channel in 0..3 {
                                mixed[channel] = (base[channel] as f64 * (1.0 - alpha)
                                    + top[channel] as f64 * alpha)
                                    .round()
                                    .clamp(0.0, 255.0) as u8;
                            }
                            frame.set_pixel(dx, dy, mixed);
                        }
                    }
                }
                frame
            } else {
                let crop_y = (new_h - first.height as i64) / 2;
                let crop_x = (new_w - first.width as i64) / 2;
                let cropped = super::pixels::crop(
                    &scaled,
                    crop_x,
                    crop_y,
                    first.width,
                    first.height,
                );
                super::pixels::blend_weighted(first, &cropped, alpha)
            }
        })
        .collect()
}

/// `3D翻转`：水平压缩模拟翻转，前半段 img1、后半段 img2
fn flip_3d(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let width = first.width as f64;
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let angle = progress * 180.0;
            let scale_x = (angle * PI / 180.0).cos().abs();
            let current = if angle < 90.0 { first } else { second };
            let new_w = 1i64.max((width * scale_x) as i64) as u32;
            let scaled = super::pixels::resize(
                current,
                new_w,
                first.height,
                super::pixels::ResizeFilter::Bilinear,
            );
            let mut frame = BgrFrame::black(first.width, first.height);
            let x_offset = (first.width.saturating_sub(new_w)) / 2;
            super::pixels::blit(&mut frame, &scaled, x_offset as i64, 0);
            // 阴影：整体乘 (1 - 0.3*(1-scale_x))
            let factor = 1.0 - 0.3 * (1.0 - scale_x);
            for byte in frame.data.iter_mut() {
                *byte = (*byte as f64 * factor).clamp(0.0, 255.0) as u8;
            }
            frame
        })
        .collect()
}

/// `推入效果`：img1 左移、img2 从右侧推入
fn push_in(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let width = first.width as i64;
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let mut frame = BgrFrame::black(first.width, first.height);
            let push_pos = (width as f64 * progress) as i64;
            // img1 左移
            let img1_offset = -push_pos;
            copy_rect(
                &mut frame,
                first,
                img1_offset,
                0,
                img1_offset + width,
                first.height as i64,
            );
            // img2 从右侧进入
            let img2_offset = width - push_pos;
            if img2_offset < width {
                copy_rect(
                    &mut frame,
                    second,
                    img2_offset,
                    0,
                    width,
                    first.height as i64,
                );
            }
            frame
        })
        .collect()
}

/// `对角擦除`：x+y < threshold 的区域换成 img2
fn diagonal_wipe(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let total = first.width as f64 + first.height as f64;
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let threshold = progress * total;
            let mut frame = first.clone();
            for y in 0..first.height {
                for x in 0..first.width {
                    if (x + y) as f64 <= threshold {
                        if let Some(value) = second.pixel(x, y) {
                            frame.set_pixel(x, y, value);
                        }
                    }
                }
            }
            frame
        })
        .collect()
}

/// `门式打开`：从中心向两侧展开
fn door_open(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let center_x = first.width as i64 / 2;
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let mut frame = first.clone();
            let door_width = (center_x as f64 * progress) as i64;
            if door_width > 0 {
                copy_rect(
                    &mut frame,
                    second,
                    center_x - door_width,
                    0,
                    center_x + door_width,
                    first.height as i64,
                );
            }
            frame
        })
        .collect()
}

/// `闪光过渡`：中间最亮的白光
fn flash(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let flash_intensity = (1.0 - (2.0 * progress - 1.0).abs()).powi(2);
            let base = if progress < 0.5 { first } else { second };
            // addWeighted(base, 1-f, white, f, 0)
            let mut frame = base.clone();
            for byte in frame.data.iter_mut() {
                *byte = (*byte as f64 * (1.0 - flash_intensity) + 255.0 * flash_intensity)
                    .round()
                    .clamp(0.0, 255.0) as u8;
            }
            frame
        })
        .collect()
}

/// `碎片飞散`：img1 切成 40px 碎片旋转飞散，露出 img2
fn shatter(
    first: &BgrFrame,
    second: &BgrFrame,
    count: usize,
    extra: &serde_json::Map<String, serde_json::Value>,
) -> Vec<BgrFrame> {
    // 专属参数取值，缺省用原硬编码值 —— 保证不传参数时画面逐字节不变
    let param = |key: &str, fallback: f64| -> f64 {
        extra
            .get(key)
            .and_then(|value| value.as_f64())
            .filter(|value| value.is_finite())
            .unwrap_or(fallback)
    };
    // 碎片边长可调：默认 40px 与改造前一致。越小碎得越细。
    let shard = param("shard", 40.0).round().clamp(8.0, 300.0) as i64;
    let rows = (first.height as i64 + shard - 1) / shard;
    let cols = (first.width as i64 + shard - 1) / shard;
    // Python 用 `np.random.seed(42)` 固定种子，这里用固定种子的等价实现
    let mut rng = SplitMix64::new(42);
    let mut velocities: Vec<(f64, f64, f64)> = Vec::new();
    for _ in 0..(rows * cols) {
        let vel_x = rng.normal() * 50.0;
        let vel_y = rng.normal() * 50.0 - 30.0;
        let rotation = rng.normal() * 180.0;
        velocities.push((vel_x, vel_y, rotation));
    }

    linspace01(count)
        .into_iter()
        .map(|progress| {
            let mut frame = second.clone();
            let mut index = 0usize;
            for row in 0..rows {
                for col in 0..cols {
                    let y1 = row * shard;
                    let y2 = (y1 + shard).min(first.height as i64);
                    let x1 = col * shard;
                    let x2 = (x1 + shard).min(first.width as i64);
                    let shard = super::pixels::crop(first, x1, y1, (x2 - x1) as u32, (y2 - y1) as u32);
                    let (vel_x, vel_y, rotation) = velocities[index];
                    let alpha = (1.0 - progress * 1.2).max(0.0);
                    if alpha > 0.01 && progress < 0.9 && shard.width > 0 && shard.height > 0 {
                        let offset_x = (vel_x * progress.powf(1.5)) as i64;
                        let offset_y = (vel_y * progress.powf(1.5)) as i64;
                        let angle = rotation * progress;
                        let matrix = super::effects::rotation_matrix(
                            shard.width as f64 / 2.0,
                            shard.height as f64 / 2.0,
                            angle,
                            1.0,
                        );
                        let rotated = super::effects::warp_affine(
                            &shard,
                            matrix,
                            super::effects::BorderMode::Constant,
                        );
                        let new_x = x1 + offset_x;
                        let new_y = y1 + offset_y;
                        let dst_y1 = new_y.max(0);
                        let dst_y2 = (new_y + shard.height as i64).min(first.height as i64);
                        let dst_x1 = new_x.max(0);
                        let dst_x2 = (new_x + shard.width as i64).min(first.width as i64);
                        let src_y1 = (-new_y).max(0);
                        let src_x1 = (-new_x).max(0);
                        for y in 0..(dst_y2 - dst_y1).max(0) {
                            for x in 0..(dst_x2 - dst_x1).max(0) {
                                let dx = (dst_x1 + x) as u32;
                                let dy = (dst_y1 + y) as u32;
                                let sx = (src_x1 + x) as u32;
                                let sy = (src_y1 + y) as u32;
                                if let (Some(base), Some(top)) =
                                    (frame.pixel(dx, dy), rotated.pixel(sx, sy))
                                {
                                    let mut mixed = [0u8; 3];
                                    for channel in 0..3 {
                                        mixed[channel] = (base[channel] as f64 * (1.0 - alpha)
                                            + top[channel] as f64 * alpha)
                                            .round()
                                            .clamp(0.0, 255.0)
                                            as u8;
                                    }
                                    frame.set_pixel(dx, dy, mixed);
                                }
                            }
                        }
                    }
                    index += 1;
                }
            }
            frame
        })
        .collect()
}

/// `光晕扩散`：圆形遮罩从中心扩散，边缘高斯羽化
fn glow_spread(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let center_x = first.width as i64 / 2;
    let center_y = first.height as i64 / 2;
    let max_r = (((center_x * center_x + center_y * center_y) as f64).sqrt()) as i64;
    // img2 轻微发光版本：addWeighted(img2, 0.75, blur(img2, sigma=10), 0.25, 0)
    let glow = gaussian_blur_sigma(second, 10.0);
    let target = super::pixels::blend_weighted(second, &glow, 0.25);
    // 半径为 0 时 cv2.GaussianBlur((0,0), sigma=8) 的核大小 ≈ 2*ceil(3*8)+1
    let soft_mask = |radius: f64| -> (u32, u32, f64) { (0, 0, radius) };
    let _ = soft_mask;

    linspace01(count)
        .into_iter()
        .map(|progress| {
            let radius = (max_r as f64 * progress) as i64;
            let mask = circle_mask(first.width, first.height, center_x, center_y, radius.max(1));
            let feathered = gaussian_blur_gray_sigma(&mask, first.width, first.height, 8.0);
            let mut frame = first.clone();
            for y in 0..first.height {
                for x in 0..first.width {
                    let weight = feathered[(y * first.width + x) as usize] as f64 / 255.0;
                    if let (Some(base), Some(top)) = (first.pixel(x, y), target.pixel(x, y)) {
                        let mut mixed = [0u8; 3];
                        for channel in 0..3 {
                            mixed[channel] = (base[channel] as f64 * (1.0 - weight)
                                + top[channel] as f64 * weight)
                                .clamp(0.0, 255.0) as u8;
                        }
                        frame.set_pixel(x, y, mixed);
                    }
                }
            }
            frame
        })
        .collect()
}

/// 生成实心圆遮罩（对应 `cv2.circle(mask, ..., 255, -1)`）。
fn circle_mask(width: u32, height: u32, cx: i64, cy: i64, radius: i64) -> Vec<u8> {
    let mut mask = vec![0u8; (width * height) as usize];
    for y in 0..height as i64 {
        for x in 0..width as i64 {
            let dx = x - cx;
            let dy = y - cy;
            if dx * dx + dy * dy <= radius * radius {
                mask[(y * width as i64 + x) as usize] = 255;
            }
        }
    }
    mask
}

/// 指定 sigma 的高斯模糊（`cv2.GaussianBlur(src, (0,0), sigma)`）。
///
/// `ksize=(0,0)` 时 OpenCV 按 `2*ceil(3*sigma)+1` 自动定核大小。
fn gaussian_blur_sigma(frame: &BgrFrame, sigma: f64) -> BgrFrame {
    let radius = (3.0 * sigma).ceil() as i64;
    let radius = radius.max(1);
    let ksize = (radius * 2 + 1) as u32;
    // 复用 effects 里的实现（方差相同即可）
    super::effects::gaussian_blur_sigma_pub(frame, ksize, sigma)
}

/// 单通道灰度 + 指定 sigma 的高斯模糊。
fn gaussian_blur_gray_sigma(source: &[u8], width: u32, height: u32, sigma: f64) -> Vec<u8> {
    let radius = ((3.0 * sigma).ceil() as i64).max(1);
    let mut kernel: Vec<f64> = Vec::new();
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
                let sx = (x as i64 + index as i64 - radius).rem_euclid(width as i64) as u32;
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
                let sy = (y as i64 + index as i64 - radius).rem_euclid(height as i64) as u32;
                sum += horizontal[(sy * width + x) as usize] * weight;
            }
            out[(y * width + x) as usize] = sum.round().clamp(0.0, 255.0) as u8;
        }
    }
    out
}

/// `径向旋切`：按极角扫描
fn radial_sweep(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let center_x = first.width as f64 / 2.0;
    let center_y = first.height as f64 / 2.0;
    // 预计算每个像素的角度
    let mut angles = vec![0.0f64; (first.width * first.height) as usize];
    for y in 0..first.height {
        for x in 0..first.width {
            let angle = (y as f64 - center_y).atan2(x as f64 - center_x).to_degrees();
            angles[(y * first.width + x) as usize] = (angle + 360.0) % 360.0;
        }
    }
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let threshold = progress * 360.0;
            let mut frame = first.clone();
            for y in 0..first.height {
                for x in 0..first.width {
                    if angles[(y * first.width + x) as usize] <= threshold {
                        if let Some(value) = second.pixel(x, y) {
                            frame.set_pixel(x, y, value);
                        }
                    }
                }
            }
            frame
        })
        .collect()
}

/// `漩涡扭曲`：中心强、边缘弱的扭转到淡入 img2
fn vortex_distort(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let center_x = first.width as f64 / 2.0;
    let center_y = first.height as f64 / 2.0;
    let mut radius = vec![0.0f64; (first.width * first.height) as usize];
    let mut base_angle = vec![0.0f64; (first.width * first.height) as usize];
    let mut max_r = 1.0f64;
    for y in 0..first.height {
        for x in 0..first.width {
            let dx = x as f64 - center_x;
            let dy = y as f64 - center_y;
            let r = (dx * dx + dy * dy).sqrt();
            let index = (y * first.width + x) as usize;
            radius[index] = r;
            base_angle[index] = dy.atan2(dx);
            if r > max_r {
                max_r = r;
            }
        }
    }
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let mut map_x = vec![0.0f32; (first.width * first.height) as usize];
            let mut map_y = vec![0.0f32; (first.width * first.height) as usize];
            for y in 0..first.height {
                for x in 0..first.width {
                    let index = (y * first.width + x) as usize;
                    let twist = (1.0 - radius[index] / max_r) * (1.0 - progress) * 2.2;
                    let theta = base_angle[index] + twist;
                    map_x[index] = (center_x + radius[index] * theta.cos()) as f32;
                    map_y[index] = (center_y + radius[index] * theta.sin()) as f32;
                }
            }
            let warped = remap_reflect(first, &map_x, &map_y);
            super::pixels::blend_weighted(&warped, second, progress)
        })
        .collect()
}

/// 双线性 + BORDER_REFLECT 的逐点重映射（转场里用）。
fn remap_reflect(source: &BgrFrame, map_x: &[f32], map_y: &[f32]) -> BgrFrame {
    let mut out = source.clone();
    for y in 0..source.height {
        for x in 0..source.width {
            let index = (y * source.width + x) as usize;
            let value = super::effects::sample_bilinear_reflect(
                source,
                map_x[index] as f64,
                map_y[index] as f64,
            );
            out.set_pixel(x, y, value);
        }
    }
    out
}

/// `菱形开幕`：|x-cx| + |y-cy| 曼哈顿距离扩散
fn diamond_reveal(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let center_x = first.width as i64 / 2;
    let center_y = first.height as i64 / 2;
    let mut max_d = 1i64;
    let mut dist = vec![0i64; (first.width * first.height) as usize];
    for y in 0..first.height as i64 {
        for x in 0..first.width as i64 {
            let d = (x - center_x).abs() + (y - center_y).abs();
            dist[(y * first.width as i64 + x) as usize] = d;
            if d > max_d {
                max_d = d;
            }
        }
    }
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let threshold = (max_d as f64 * progress) as i64;
            let mut frame = first.clone();
            for y in 0..first.height {
                for x in 0..first.width {
                    if dist[(y * first.width + x) as usize] <= threshold {
                        if let Some(value) = second.pixel(x, y) {
                            frame.set_pixel(x, y, value);
                        }
                    }
                }
            }
            frame
        })
        .collect()
}

/// `镜头虚焦`：两边同时模糊后交叉淡化
fn focus_blur(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let blur_strength = (1.0 + (1.0 - (progress - 0.5).abs() * 2.0) * 16.0) as i64;
            let strength = blur_strength.max(1);
            let k = if strength % 2 == 1 { strength } else { strength + 1 };
            let b1 = super::effects::gaussian_blur_ksize_pub(first, k as u32);
            let b2 = super::effects::gaussian_blur_ksize_pub(second, k as u32);
            super::pixels::blend_weighted(&b1, &b2, progress)
        })
        .collect()
}

/// `纵向/横向拉幕`：从中心向两侧（或上下）拉开
fn curtain(first: &BgrFrame, second: &BgrFrame, count: usize, vertical: bool) -> Vec<BgrFrame> {
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let mut frame = first.clone();
            if vertical {
                let half = ((first.width as i64 / 2) as f64 * progress) as i64;
                if half > 0 {
                    let center = first.width as i64 / 2;
                    copy_rect(
                        &mut frame,
                        second,
                        center - half,
                        0,
                        center + half,
                        first.height as i64,
                    );
                }
            } else {
                let half = ((first.height as i64 / 2) as f64 * progress) as i64;
                if half > 0 {
                    let center = first.height as i64 / 2;
                    copy_rect(
                        &mut frame,
                        second,
                        0,
                        center - half,
                        first.width as i64,
                        center + half,
                    );
                }
            }
            frame
        })
        .collect()
}

/// `液态融合`：水平正弦扭曲后淡化
fn liquid_blend(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let mut map_x = vec![0.0f32; (first.width * first.height) as usize];
            let mut map_y = vec![0.0f32; (first.width * first.height) as usize];
            for y in 0..first.height {
                for x in 0..first.width {
                    let wave =
                        ((x as f64 / 30.0) + progress * PI * 3.5).sin() * (1.0 - progress) * 12.0;
                    let index = (y * first.width + x) as usize;
                    // np.clip(xx + wave, 0, w-1)
                    map_x[index] = (x as f64 + wave).clamp(0.0, first.width as f64 - 1.0) as f32;
                    map_y[index] = y as f32;
                }
            }
            let warped = remap_reflect(first, &map_x, &map_y);
            super::pixels::blend_weighted(&warped, second, progress)
        })
        .collect()
}

/// `流光擦拭`：擦除边界带一条白色光带
fn light_streak(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let width = first.width as i64;
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let split = (width as f64 * progress) as i64;
            let mut frame = first.clone();
            if split > 0 {
                copy_rect(&mut frame, second, 0, 0, split, first.height as i64);
            }
            let center = split;
            if center > 0 && center < width {
                let band = (width / 40).max(6);
                let x1 = (center - band).max(0);
                let x2 = (center + band).min(width);
                if x2 > x1 {
                    // addWeighted(frame, 0.45, white, 0.55, 0)
                    for y in 0..first.height {
                        for x in x1..x2 {
                            if let Some(base) = frame.pixel(x as u32, y) {
                                let mut mixed = [0u8; 3];
                                for channel in 0..3 {
                                    mixed[channel] =
                                        (base[channel] as f64 * 0.45 + 255.0 * 0.55)
                                            .round()
                                            .clamp(0.0, 255.0)
                                            as u8;
                                }
                                frame.set_pixel(x as u32, y, mixed);
                            }
                        }
                    }
                }
            }
            frame
        })
        .collect()
}

/// `时钟扫描`：12 点方向开始顺时针扫描
fn clock_wipe(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    let center_x = first.width as f64 / 2.0;
    let center_y = first.height as f64 / 2.0;
    let mut angles = vec![0.0f64; (first.width * first.height) as usize];
    for y in 0..first.height {
        for x in 0..first.width {
            // 注意：与「径向旋切」的 atan2 参数顺序相反（这里是 (x-cx, cy-y)）
            let angle = (x as f64 - center_x).atan2(center_y - y as f64).to_degrees();
            angles[(y * first.width + x) as usize] = (angle + 360.0) % 360.0;
        }
    }
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let threshold = progress * 360.0;
            let mut frame = first.clone();
            for y in 0..first.height {
                for x in 0..first.width {
                    if angles[(y * first.width + x) as usize] <= threshold {
                        if let Some(value) = second.pixel(x, y) {
                            frame.set_pixel(x, y, value);
                        }
                    }
                }
            }
            frame
        })
        .collect()
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

    #[test]
    fn linspace_matches_numpy_including_endpoints() {
        assert_eq!(linspace01(1), vec![0.0]);
        assert_eq!(linspace01(2), vec![0.0, 1.0]);
        assert_eq!(linspace01(3), vec![0.0, 0.5, 1.0]);
        let five = linspace01(5);
        assert_eq!(five[0], 0.0);
        assert_eq!(five[4], 1.0);
        assert!((five[1] - 0.25).abs() < 1e-12);
        assert!((five[2] - 0.5).abs() < 1e-12);
        assert!(linspace01(0).is_empty());
    }

    #[test]
    fn linspace_int_truncates() {
        // linspace(0, 10, 4) = [0, 3.33, 6.67, 10] → int 截断 [0, 3, 6, 10]
        assert_eq!(linspace_int(4, 10), vec![0, 3, 6, 10]);
        assert_eq!(linspace_int(1, 10), vec![0]);
        assert_eq!(linspace_int(3, 9), vec![0, 4, 9]);
    }

    #[test]
    fn frame_count_is_exactly_requested() {
        let a = solid(40, 30, [0, 0, 0]);
        let b = solid(40, 30, [255, 255, 255]);
        for transition in [
            Transition::Fade,
            Transition::SlideLeft,
            Transition::SlideUp,
            Transition::CircleExpand,
            Transition::Zoom,
            Transition::Blinds,
            Transition::Pixelate,
        ] {
            for num_frames in [1usize, 2, 5, 8] {
                let frames = generate_frames(&a, &b, transition, num_frames, &Default::default());
                assert_eq!(
                    frames.len(),
                    num_frames,
                    "{transition:?} num_frames={num_frames} 生成了 {} 帧",
                    frames.len()
                );
            }
        }
    }

    #[test]
    fn fade_uses_truncation_not_rounding() {
        // 0*(1-a) + 255*a，a=0.5 → 127.5 → 截断 127（若四舍五入会是 128）
        let a = solid(2, 2, [0, 0, 0]);
        let b = solid(2, 2, [255, 255, 255]);
        let frames = generate_raw(&a, &b, Transition::Fade, 3, &Default::default());
        assert_eq!(frames[1].pixel(0, 0), Some([127, 127, 127]));
        assert_eq!(frames[0].pixel(0, 0), Some([0, 0, 0]));
        assert_eq!(frames[2].pixel(0, 0), Some([255, 255, 255]));
    }

    #[test]
    fn fade_first_and_last_are_dropped() {
        let a = solid(4, 4, [0, 0, 0]);
        let b = solid(4, 4, [100, 100, 100]);
        let frames = generate_frames(&a, &b, Transition::Fade, 3, &Default::default());
        // 生成 5 帧 [0, 25, 50, 75, 100]，掐头去尾 → [25, 50, 75]
        assert_eq!(frames.len(), 3);
        assert_eq!(frames[0].pixel(0, 0), Some([25, 25, 25]));
        assert_eq!(frames[2].pixel(0, 0), Some([75, 75, 75]));
    }

    #[test]
    fn horizontal_slide_splits_at_truncated_positions() {
        let a = solid(10, 4, [10, 10, 10]);
        let b = solid(10, 4, [200, 200, 200]);
        let frames = generate_raw(&a, &b, Transition::SlideLeft, 3, &Default::default());
        // 切分点 [0, 5, 10]
        assert_eq!(frames[0].pixel(0, 0), Some([10, 10, 10]), "切分 0：全是 a");
        assert_eq!(frames[1].pixel(4, 0), Some([200, 200, 200]), "切分 5：左侧 b");
        assert_eq!(frames[1].pixel(5, 0), Some([10, 10, 10]), "切分 5：右侧 a");
        assert_eq!(frames[2].pixel(9, 0), Some([200, 200, 200]), "切分 10：全是 b");
    }

    #[test]
    fn vertical_slide_splits_rows() {
        let a = solid(4, 10, [10, 10, 10]);
        let b = solid(4, 10, [200, 200, 200]);
        let frames = generate_raw(&a, &b, Transition::SlideUp, 3, &Default::default());
        assert_eq!(frames[1].pixel(0, 4), Some([200, 200, 200]));
        assert_eq!(frames[1].pixel(0, 5), Some([10, 10, 10]));
    }

    #[test]
    fn circle_expand_grows_from_center() {
        let a = solid(40, 40, [0, 0, 0]);
        let b = solid(40, 40, [255, 255, 255]);
        let frames = generate_raw(&a, &b, Transition::CircleExpand, 3, &Default::default());
        // radius 0 → 中心像素满足 dx²+dy² <= 0，应为 b
        assert_eq!(frames[0].pixel(20, 20), Some([255, 255, 255]));
        assert_eq!(frames[0].pixel(0, 0), Some([0, 0, 0]), "半径 0 时角落仍是 a");
        // max_radius = int(sqrt(20²+20²)) = int(28.28) = 28，角落距离 28.28 > 28，
        // 所以四角永远覆盖不到（Python 原行为，照抄不修）
        assert_eq!(frames[2].pixel(0, 0), Some([0, 0, 0]), "四角覆盖不到");
        // 右下角 (39,39) 距中心 sqrt(19²+19²)=26.87 <= 28，应被覆盖
        assert_eq!(frames[2].pixel(39, 39), Some([255, 255, 255]));
    }

    #[test]
    fn zoom_is_two_layer_zoom_and_blend() {
        let a = solid(40, 40, [0, 0, 0]);
        let b = solid(40, 40, [200, 200, 200]);
        let frames = generate_raw(&a, &b, Transition::Zoom, 3, &Default::default());
        // progress 0：img2 缩到 20x20 居中（200），img1 保持 40x40（0）与黑底混合
        // 中心区域：frame 是 200，img1 是 0，alpha=1 → 结果取 img1 的 0
        assert_eq!(frames[0].pixel(20, 20), Some([0, 0, 0]));
        // 四角无 img1 覆盖区域（img1 100% 铺满），所以是 0
        assert_eq!(frames[0].pixel(0, 0), Some([0, 0, 0]));
        // progress 1：img1 缩到 20x20（0）居中，alpha=0 → 全取上面那层（img2 铺满的 200）
        assert_eq!(frames[2].pixel(0, 0), Some([200, 200, 200]));
        assert_eq!(frames[2].pixel(20, 20), Some([200, 200, 200]));
    }

    #[test]
    fn blinds_open_from_each_stripe_center() {
        let a = solid(20, 100, [0, 0, 0]);
        let b = solid(20, 100, [255, 255, 255]);
        let frames = generate_raw(&a, &b, Transition::Blinds, 3, &Default::default());
        // blind_height = 10；progress 0 → open_height = 0，全不显示
        assert_eq!(frames[0].pixel(0, 0), Some([0, 0, 0]), "progress 0 全是 a");
        // progress 0.5 → open_height = 5，第一条从中心 5 向两侧展开 [3, 8)
        assert_eq!(frames[1].pixel(0, 5), Some([255, 255, 255]), "中心已打开");
        assert_eq!(frames[1].pixel(0, 0), Some([0, 0, 0]), "边缘未打开");
        // progress 1 → open_height = 10，整条覆盖
        assert_eq!(frames[2].pixel(0, 0), Some([255, 255, 255]));
        assert_eq!(frames[2].pixel(0, 9), Some([255, 255, 255]));
    }

    #[test]
    fn pixelate_pixelates_the_first_image() {
        // 40x40：start_size = 40/4 = 10 → pixel_sizes 从 10 降到 1
        let a = solid(40, 40, [0, 0, 0]);
        let b = solid(40, 40, [200, 200, 200]);
        let frames = generate_raw(&a, &b, Transition::Pixelate, 3, &Default::default());
        assert_eq!(frames.len(), 3);
        // 最后一帧 pixel_size = 1 → 直接返回整张 img2
        assert_eq!(frames[2].pixel(0, 0), Some([200, 200, 200]));
        // 第一帧 pixel_size = 10 → alpha = 1 - 9/9 = 0 → 全取像素化的 img1（黑）
        assert_eq!(frames[0].pixel(0, 0), Some([0, 0, 0]));
    }

    #[test]
    fn unknown_transition_falls_back_to_fade() {
        assert_eq!(parse("完全不存在的转场"), Transition::Fallback);
        assert_eq!(parse("淡入淡出"), Transition::Fade);
        assert_eq!(parse("交叉溶解"), Transition::Fade);
        assert_eq!(parse("左右滑动"), Transition::SlideLeft);
    }

    #[test]
    fn zero_frames_returns_empty() {
        let a = solid(4, 4, [0, 0, 0]);
        let b = solid(4, 4, [255, 255, 255]);
        assert!(generate_frames(&a, &b, Transition::Fade, 0, &Default::default()).is_empty());
    }
}
