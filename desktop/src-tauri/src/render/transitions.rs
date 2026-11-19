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
    /// 未识别或有「无转场」时按淡入淡出处理（与 Python 的默认分支一致）
    Fallback,
}

/// 文案 → 转场类型。未识别的返回 `Fallback`（淡入淡出）。
pub fn parse(name: &str) -> Transition {
    match name {
        "淡入淡出" => Transition::Fade,
        "交叉溶解" => Transition::Fade,
        "颜色混合" => Transition::Fade,
        "左右滑动" => Transition::SlideLeft,
        "上下滑动" => Transition::SlideUp,
        "圆形扩展" => Transition::CircleExpand,
        "缩放过渡" => Transition::Zoom,
        "百叶窗" => Transition::Blinds,
        "像素化" => Transition::Pixelate,
        _ => Transition::Fallback,
    }
}

/// 生成转场中间帧。返回的帧数**恰好是 `num_frames`**（已掐头去尾）。
pub fn generate_frames(
    first: &BgrFrame,
    second: &BgrFrame,
    transition: Transition,
    num_frames: usize,
) -> Vec<BgrFrame> {
    if num_frames == 0 {
        return Vec::new();
    }
    // 多生成 2 帧再掐头去尾，避免首尾帧与静态帧重复
    let generate_count = if num_frames > 1 { num_frames + 2 } else { num_frames };
    let mut frames = generate_raw(first, second, transition, generate_count);
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
) -> Vec<BgrFrame> {
    if count == 0 {
        return Vec::new();
    }
    match transition {
        Transition::Fade | Transition::Fallback => linspace01(count)
            .into_iter()
            .map(|alpha| blend_truncate(first, second, alpha))
            .collect(),
        Transition::SlideLeft => slide(first, second, count, true),
        Transition::SlideUp => slide(first, second, count, false),
        Transition::CircleExpand => circle_expand(first, second, count),
        Transition::Zoom => zoom(first, second, count),
        Transition::Blinds => blinds(first, second, count),
        Transition::Pixelate => pixelate(first, second, count),
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

fn blinds(first: &BgrFrame, second: &BgrFrame, count: usize) -> Vec<BgrFrame> {
    // ⚠️ 是「每条百叶窗从中心向上下同时展开」，不是「一条一条轮流显示」。
    // 第一版按后者实现，对照测试发现 20% 的像素不一致。
    const NUM_BLINDS: i64 = 10;
    let height = first.height as i64;
    let blind_height = height / NUM_BLINDS;
    linspace01(count)
        .into_iter()
        .map(|progress| {
            let mut frame = first.clone();
            let open_height = (blind_height as f64 * progress).trunc() as i64;
            if open_height > 0 {
                for index in 0..NUM_BLINDS {
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
                let frames = generate_frames(&a, &b, transition, num_frames);
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
        let frames = generate_raw(&a, &b, Transition::Fade, 3);
        assert_eq!(frames[1].pixel(0, 0), Some([127, 127, 127]));
        assert_eq!(frames[0].pixel(0, 0), Some([0, 0, 0]));
        assert_eq!(frames[2].pixel(0, 0), Some([255, 255, 255]));
    }

    #[test]
    fn fade_first_and_last_are_dropped() {
        let a = solid(4, 4, [0, 0, 0]);
        let b = solid(4, 4, [100, 100, 100]);
        let frames = generate_frames(&a, &b, Transition::Fade, 3);
        // 生成 5 帧 [0, 25, 50, 75, 100]，掐头去尾 → [25, 50, 75]
        assert_eq!(frames.len(), 3);
        assert_eq!(frames[0].pixel(0, 0), Some([25, 25, 25]));
        assert_eq!(frames[2].pixel(0, 0), Some([75, 75, 75]));
    }

    #[test]
    fn horizontal_slide_splits_at_truncated_positions() {
        let a = solid(10, 4, [10, 10, 10]);
        let b = solid(10, 4, [200, 200, 200]);
        let frames = generate_raw(&a, &b, Transition::SlideLeft, 3);
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
        let frames = generate_raw(&a, &b, Transition::SlideUp, 3);
        assert_eq!(frames[1].pixel(0, 4), Some([200, 200, 200]));
        assert_eq!(frames[1].pixel(0, 5), Some([10, 10, 10]));
    }

    #[test]
    fn circle_expand_grows_from_center() {
        let a = solid(40, 40, [0, 0, 0]);
        let b = solid(40, 40, [255, 255, 255]);
        let frames = generate_raw(&a, &b, Transition::CircleExpand, 3);
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
        let frames = generate_raw(&a, &b, Transition::Zoom, 3);
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
        let frames = generate_raw(&a, &b, Transition::Blinds, 3);
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
        let frames = generate_raw(&a, &b, Transition::Pixelate, 3);
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
        assert!(generate_frames(&a, &b, Transition::Fade, 0).is_empty());
    }
}
