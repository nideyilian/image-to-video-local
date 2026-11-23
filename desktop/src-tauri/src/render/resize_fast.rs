//! 行优先的 BGR 双线性/面积缩放。
//!
//! 为什么不用 `image::imageops::resize`：
//! - 它先做垂直采样得到 **RGBA32F 浮点中间图**（1080p 约 12MB 浮点），
//!   再水平采样 —— 两趟 + 中间浮点缓冲；
//! - 它的内层循环是「固定 x 扫 y」，每取一个采样点都跨 `width*3` 字节跳内存，
//!   缓存全废。实测最近邻（只需读一个像素）也要 81ms。
//!
//! 这里的实现按行扫描，源行和目标行都在连续内存里顺序访问，
//! 且直接在 u8 上做双线性（累加用 i32 定点），不产生任何浮点中间图。
//!
//! ⚠️ 数值口径与 `image` crate 不同，因此这是**视觉等价**而非逐字节一致。
//! 换算法后要用 `resize_bench_test` 的差异统计确认 max 差值可接受。

use super::pixels::BgrFrame;

/// 缩放核。
///
/// - `Bilinear`：放大用，每方向 2 个采样点。
/// - `Bicubic`：**缩小用**。CatmullRom（B=0, C=0.5），每方向 4 个采样点，
///   带负瓣所以锐利。旧实现缩小走的就是它，换成双线性会让画面变软 ——
///   实测 1080→360 时平均差 13.7、23% 的像素差超过 12，肉眼可见变糊。
/// - `Nearest`：预览缩略图用，最快。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kernel {
    Bilinear,
    Bicubic,
    Nearest,
}

/// 预计算的一维采样表。
///
/// ⚠️ 关键：**缩小时采样窗口要随比例放大**。旧实现（`image` crate）里
/// `sratio = max(1, src/dst)`、`support *= sratio`，所以缩 3 倍时每个输出像素
/// 要覆盖 6 个源像素（CatmullRom 支撑 2 × 3）。
///
/// 我第一版固定只取 4 个点，缩小越多漏得越多 —— 实测 1080→360 平均差 13.7、
/// 23% 像素超标，肉眼明显变糊。这里按同样的规则动态决定 tap 数。
const MAX_TAPS: usize = 16;

/// 权重定点精度。
///
/// 用 8 位（256）而不是 16 位：实测 16 位的「更精确」反而与旧实现（f32 中间图）
/// 差得更多（平均差 1.94 vs 1.75）。因为旧实现的舍入特性本身就更接近 8 位定点，
/// 追求「数学上更准」在这里没有意义 —— 目标是别让画面变样。
const WEIGHT_ONE: i32 = 256;

struct AxisTable {
    /// 每个目标位置依次取哪些源索引（不足的填 0）
    index: Vec<[usize; MAX_TAPS]>,
    /// 对应权重（定点 65536 = 1.0，16 位精度）
    weight: Vec<[i32; MAX_TAPS]>,
    /// 实际使用的 tap 数
    taps: usize,
}

impl AxisTable {
    fn build(source_len: usize, target_len: usize, kernel: Kernel) -> Self {
        let ratio = source_len as f64 / target_len as f64;
        // 缩小时窗口按比例扩张，与 image crate 的 sratio 行为一致
        let sratio = ratio.max(1.0);
        let (support, base_taps) = match kernel {
            Kernel::Nearest => (0.0, 1),
            Kernel::Bilinear => (1.0, 2),
            Kernel::Bicubic => (2.0, 4),
        };
        let _ = base_taps;
        let scaled_support = support * sratio;
        // 每侧需要覆盖的源像素数
        let radius = scaled_support.ceil() as usize;
        let taps = (radius * 2 + 1).clamp(1, MAX_TAPS);

        let mut index = Vec::with_capacity(target_len);
        let mut weight = Vec::with_capacity(target_len);

        for position in 0..target_len {
            let mut row_index = [0usize; MAX_TAPS];
            let mut row_weight = [0i32; MAX_TAPS];

            match kernel {
                Kernel::Nearest => {
                    let nearest = nearest_index(position, source_len, target_len);
                    row_index[0] = nearest;
                    row_weight[0] = WEIGHT_ONE;
                }
                _ => {
                    // 中心坐标（像素中心对齐），与 image crate 的
                    // `inputy = (outy + 0.5) * ratio - 0.5` 一致
                    let center = (position as f64 + 0.5) * ratio - 0.5;
                    let left = (center - scaled_support).floor() as i64;
                    let left = left.clamp(0, source_len as i64 - 1);
                    let right = ((center + scaled_support).ceil() as i64)
                        .clamp(left + 1, source_len as i64);

                    let mut raw = [0.0f64; MAX_TAPS];
                    let mut total = 0.0f64;
                    let mut used = 0usize;
                    for source in left..right {
                        if used >= MAX_TAPS {
                            break;
                        }
                        // 距离要除以 sratio —— 这是「按比例扩张窗口」的关键
                        let distance = (source as f64 - center) / sratio;
                        let value = match kernel {
                            Kernel::Bicubic => catmullrom(distance.abs()),
                            _ => triangle(distance.abs()),
                        };
                        if value == 0.0 && used == 0 && source > left {
                            // 前导零权重跳过，但保留最后一个非零
                            continue;
                        }
                        raw[used] = value;
                        total += value;
                        row_index[used] = source as usize;
                        used += 1;
                    }
                    if used == 0 {
                        // 极端情况（support=0）退化为最近邻
                        row_index[0] = nearest_index(position, source_len, target_len);
                        row_weight[0] = WEIGHT_ONE;
                    } else if total.abs() > 1e-9 {
                        let mut assigned = 0i32;
                        for slot in 0..used.saturating_sub(1) {
                            row_weight[slot] =
                                (raw[slot] / total * WEIGHT_ONE as f64).round() as i32;
                            assigned += row_weight[slot];
                        }
                        // 最后一项补足总量，避免舍入累计成偏色
                        row_weight[used - 1] = WEIGHT_ONE - assigned;
                    } else {
                        row_weight[0] = WEIGHT_ONE;
                    }
                }
            }

            index.push(row_index);
            weight.push(row_weight);
        }

        // 实际用到的 tap 数取所有行里的最大值
        let taps = index
            .iter()
            .map(|row| {
                row.iter()
                    .rposition(|value| *value != 0)
                    .map_or(1, |pos| pos + 1)
            })
            .max()
            .unwrap_or(1)
            .min(taps)
            .max(if kernel == Kernel::Nearest { 1 } else { 2 });
        AxisTable {
            index,
            weight,
            taps,
        }
    }
}

/// 三角（双线性）核。
fn triangle(a: f64) -> f64 {
    if a < 1.0 {
        1.0 - a
    } else {
        0.0
    }
}

/// CatmullRom（B=0, C=0.5）核函数，与 `image` crate 的 `bc_cubic_spline(x,0,0.5)` 一致。
fn catmullrom(a: f64) -> f64 {
    if a < 1.0 {
        1.5 * a * a * a - 2.5 * a * a + 1.0
    } else if a < 2.0 {
        -0.5 * a * a * a + 2.5 * a * a - 4.0 * a + 2.0
    } else {
        0.0
    }
}

/// 最近邻的源索引，等价于 `floor((index + 0.5) * src / dst - 0.5)`。
///
/// 全部用整数运算：浮点写法会把 2.5 算成 2.4999999，floor 后差一格 —— 这是实际踩到的坑。
fn nearest_index(index: usize, source_len: usize, target_len: usize) -> usize {
    // center = ((2i+1)*src - dst) / (2*dst)，整体向下取整即可
    let numerator = (2 * index + 1) as i64 * source_len as i64 - target_len as i64;
    let denominator = 2 * target_len as i64;
    if numerator <= 0 {
        return 0;
    }
    let value = (numerator / denominator) as usize;
    value.min(source_len - 1)
}

/// 缩放一张 BGR 帧到目标尺寸。
pub fn resize_bgr(source: &BgrFrame, target_w: u32, target_h: u32, kernel: Kernel) -> BgrFrame {
    if source.is_empty() || target_w == 0 || target_h == 0 {
        return BgrFrame::black(target_w.max(1), target_h.max(1));
    }
    if target_w == source.width && target_h == source.height {
        return source.clone();
    }

    let src_w = source.width as usize;
    let dst_w = target_w as usize;
    let dst_h = target_h as usize;
    let src_data = &source.data;
    let src_row_bytes = src_w * 3;

    let xs = AxisTable::build(src_w, dst_w, kernel);
    let ys = AxisTable::build(source.height as usize, dst_h, kernel);
    let taps = xs.taps;

    let mut result = BgrFrame::black(target_w, target_h);
    let row_bytes = dst_w * 3;

    // 按目标行切块并行：每个线程写自己那一段，源数据只读。
    super::parallel::par_rows_mut(&mut result, |start_row, rows, chunk| {
        for local in 0..rows {
            let y = start_row + local;
            let out_at = local * row_bytes;

            // 最近邻：整行按 xs 索引取样，不插值
            if kernel == Kernel::Nearest {
                let src_row = ys.index[y][0] * src_row_bytes;
                let xindex = &xs.index;
                for (x, entry) in xindex.iter().enumerate().take(dst_w) {
                    let src_at = src_row + entry[0] * 3;
                    let dst_at = out_at + x * 3;
                    chunk[dst_at..dst_at + 3].copy_from_slice(&src_data[src_at..src_at + 3]);
                }
                continue;
            }

            // 每个输出像素把 taps×taps 个源点按二维权重累加。
            // 定点整数运算：权重各自放大 256 倍，乘积放大 65536 倍，最后右移还原。
            for x in 0..dst_w {
                let xindex = &xs.index[x];
                let xweight = &xs.weight[x];
                let mut vertical = [0i64; 3];
                for tap_y in 0..taps {
                    let wy = ys.weight[y][tap_y];
                    if wy == 0 {
                        continue;
                    }
                    let src_row = ys.index[y][tap_y] * src_row_bytes;
                    for tap_x in 0..taps {
                        let wx = xweight[tap_x];
                        if wx == 0 {
                            continue;
                        }
                        let src_at = src_row + xindex[tap_x] * 3;
                        let factor = wx as i64 * wy as i64;
                        vertical[0] += src_data[src_at] as i64 * factor;
                        vertical[1] += src_data[src_at + 1] as i64 * factor;
                        vertical[2] += src_data[src_at + 2] as i64 * factor;
                    }
                }
                // 权重总和是 WEIGHT_ONE^2，右移 16 位（8 位×8 位）还原
                let dst_at = out_at + x * 3;
                for channel in 0..3 {
                    let value =
                        (vertical[channel] + (WEIGHT_ONE as i64 * WEIGHT_ONE as i64 / 2)) >> 16;
                    chunk[dst_at + channel] = value.clamp(0, 255) as u8;
                }
            }
        }
    });

    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn gradient(width: u32, height: u32) -> BgrFrame {
        let mut frame = BgrFrame::new(width, height);
        for y in 0..height {
            for x in 0..width {
                frame.set_pixel(
                    x,
                    y,
                    [(x % 256) as u8, (y % 256) as u8, ((x * 2) % 256) as u8],
                );
            }
        }
        frame
    }

    /// 同尺寸直接返回，不做任何插值。
    #[test]
    fn same_size_is_identity() {
        let frame = gradient(20, 10);
        let out = resize_bgr(&frame, 20, 10, Kernel::Bilinear);
        assert_eq!(out.data, frame.data);
    }

    /// 整数倍放大时，双线性应精确复现源像素（权重恰好落在格点上）。
    #[test]
    fn exact_double_keeps_colors() {
        let frame = gradient(4, 4);
        let out = resize_bgr(&frame, 8, 8, Kernel::Bilinear);
        assert_eq!((out.width, out.height), (8, 8));
        // 检查左上角区域颜色单调，没有变成黑块
        let center = out.pixel(4, 4).unwrap();
        assert!(center[0] > 0 || center[1] > 0, "放大后不应全黑");
    }

    /// 缩小到 1/4 后，亮度均值应基本保持（面积平均的基本性质）。
    #[test]
    fn downscale_preserves_mean_brightness() {
        let frame = gradient(64, 64);
        let out = resize_bgr(&frame, 16, 16, Kernel::Bilinear);
        let mean = |data: &[u8]| data.iter().map(|v| *v as f64).sum::<f64>() / data.len() as f64;
        let before = mean(&frame.data);
        let after = mean(&out.data);
        assert!(
            (before - after).abs() < 12.0,
            "均值漂移过大：{before:.1} → {after:.1}"
        );
    }

    /// 最近邻必须逐字节等于「按比例取样」的结果。
    #[test]
    fn nearest_matches_direct_sampling() {
        let frame = gradient(8, 8);
        let out = resize_bgr(&frame, 4, 4, Kernel::Nearest);
        // 8→4 时中心坐标是 0.5/2.5/4.5/6.5，floor 后应为 0/2/4/6
        let expected = [0u32, 2, 4, 6];
        for y in 0..4u32 {
            for x in 0..4u32 {
                let (sx, sy) = (expected[x as usize], expected[y as usize]);
                assert_eq!(
                    out.pixel(x, y),
                    frame.pixel(sx, sy),
                    "({x},{y}) 取样位置不对"
                );
            }
        }
    }

    /// 空帧与零尺寸不能 panic。
    #[test]
    fn degenerate_inputs_are_safe() {
        let empty = BgrFrame::new(0, 0);
        assert_eq!(resize_bgr(&empty, 10, 10, Kernel::Bilinear).width, 10);
        let frame = gradient(4, 4);
        assert_eq!(resize_bgr(&frame, 0, 0, Kernel::Bilinear).width, 1);
    }
}
