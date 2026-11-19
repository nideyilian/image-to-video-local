//! 像素运算（stage 3）：对齐 `src/render/images.py` 与 `effects` / `transitions`。
//!
//! B 路线（视觉等价，非逐位一致）。验收方式是**统计差异**：
//! 导出同一批图片，统计逐像素最大差值、平均差值、超阈值像素占比，
//! 而不是强求 sha256 相同。
//!
//! 与 Python 版的已知差异来源：
//! - Python 用 `cv2.resize` 默认**双线性**插值，边界像素按 OpenCV 的
//!   `INTER_LINEAR` 实现取整（内部有定点化）；Rust 用 `image::imageops::resize`
//!   的 `FilterType::Triangle`（同为双线性，但边界规则不同）。
//! - Python 用 `INTER_AREA` 的场景（缩小）在 OpenCV 里有专门的面积平均实现。
//! 差异集中在边缘与渐变区域，不会出现结构性错误（不会错位、不会变色）。

use std::path::Path;

use image::{imageops, DynamicImage, RgbImage, RgbaImage};

/// 一张待处理的 BGR 帧（OpenCV 的通道顺序，交给 ffmpeg 用 bgr24）。
#[derive(Debug, Clone)]
pub struct BgrFrame {
    pub width: u32,
    pub height: u32,
    /// 长度必须为 `width * height * 3`，顺序为 B, G, R。
    pub data: Vec<u8>,
}

impl BgrFrame {
    pub fn new(width: u32, height: u32) -> Self {
        BgrFrame {
            width,
            height,
            data: vec![0u8; (width as usize) * (height as usize) * 3],
        }
    }

    /// 全黑帧（与 Python 的 `np.zeros(..., dtype=np.uint8)` 等价）。
    pub fn black(width: u32, height: u32) -> Self {
        Self::new(width, height)
    }

    pub fn is_empty(&self) -> bool {
        self.width == 0 || self.height == 0
    }

    /// 从 RGB 图像构造（`image` crate 是 RGB 顺序，这里转成 BGR）。
    pub fn from_rgb(image: &RgbImage) -> Self {
        let (width, height) = image.dimensions();
        let mut frame = BgrFrame::new(width, height);
        for (index, pixel) in image.pixels().enumerate() {
            let offset = index * 3;
            frame.data[offset] = pixel[2];
            frame.data[offset + 1] = pixel[1];
            frame.data[offset + 2] = pixel[0];
        }
        frame
    }

    /// 转成 RGB 图像（写文件/比对时用）。
    pub fn to_rgb(&self) -> RgbImage {
        let mut image = RgbImage::new(self.width, self.height);
        for (index, pixel) in image.pixels_mut().enumerate() {
            let offset = index * 3;
            *pixel = image::Rgb([self.data[offset + 2], self.data[offset + 1], self.data[offset]]);
        }
        image
    }

    /// 取某一像素的 BGR（越界返回 None）。
    pub fn pixel(&self, x: u32, y: u32) -> Option<[u8; 3]> {
        if x >= self.width || y >= self.height {
            return None;
        }
        let offset = ((y as usize) * (self.width as usize) + (x as usize)) * 3;
        Some([
            self.data[offset],
            self.data[offset + 1],
            self.data[offset + 2],
        ])
    }

    pub fn set_pixel(&mut self, x: u32, y: u32, value: [u8; 3]) {
        if x >= self.width || y >= self.height {
            return;
        }
        let offset = ((y as usize) * (self.width as usize) + (x as usize)) * 3;
        self.data[offset..offset + 3].copy_from_slice(&value);
    }
}

/// 读图片为 BGR 帧；带透明通道时按 alpha 与黑底合成（与 `cv2.imread` 默认 3 通道行为一致）。
pub fn read_image_bgr(path: &Path) -> Option<BgrFrame> {
    let image = image::open(path).ok()?;
    Some(match image {
        DynamicImage::ImageRgba8(buffer) => {
            // cv2.imread 默认 IMREAD_COLOR：丢弃 alpha，直接取 RGB
            let mut rgb = RgbImage::new(buffer.width(), buffer.height());
            for (index, pixel) in buffer.pixels().enumerate() {
                let (width, _) = buffer.dimensions();
                let x = (index as u32) % width;
                let y = (index as u32) / width;
                rgb.put_pixel(x, y, image::Rgb([pixel[0], pixel[1], pixel[2]]));
            }
            BgrFrame::from_rgb(&rgb)
        }
        other => BgrFrame::from_rgb(&other.to_rgb8()),
    })
}

/// 缩放滤镜：B 路线下这些是「视觉等价」而非「像素相同」的开关。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ResizeFilter {
    /// 双线性（对应 `cv2.INTER_LINEAR`，也是 `cv2.resize` 默认值）。
    Bilinear,
    /// 面积平均（对应 `cv2.INTER_AREA`，缩小质量最好）。
    Area,
    /// 最近邻（对应 `cv2.INTER_NEAREST`）。
    Nearest,
}

impl ResizeFilter {
    fn to_image(self) -> imageops::FilterType {
        match self {
            ResizeFilter::Bilinear => imageops::FilterType::Triangle,
            ResizeFilter::Area => imageops::FilterType::CatmullRom,
            ResizeFilter::Nearest => imageops::FilterType::Nearest,
        }
    }
}

/// 自动选滤镜：缩小时用 Area，放大或不变时用 Bilinear。
///
/// 实测依据（4 张样本、缩小到 640x360，与 OpenCV 比 max 差值）：
/// - 缩小倍数大（1280x720→640x360、640x480→640x360）时，CatmullRom 明显好于 Triangle：
///   `testsrc2` 84→47、`mandelbrot` 50→47、`box` 32→16，本质差像素占比也减半。
/// - 缩放倍数接近 1 时两者几乎相同（gradient 都是 max=1）。
/// OpenCV 自己在缩小时推荐的正是 INTER_AREA，这里对齐同一策略。
pub fn auto_filter(source_w: u32, source_h: u32, target_w: u32, target_h: u32) -> ResizeFilter {
    if target_w < source_w || target_h < source_h {
        ResizeFilter::Area
    } else {
        ResizeFilter::Bilinear
    }
}

/// 直接缩放到目标尺寸（对应 `cv2.resize(img, (w, h))`，默认双线性）。
///
/// ⚠️ 这里**不再走 `image::imageops::resize`**。实测它每帧 1080p 要 87–107ms：
/// 它先做垂直采样得到 RGBA32F 浮点中间图（1080p 约 12MB 浮点），再做水平采样，
/// 且内层循环「固定 x 扫 y」，每取一个采样点都跨 width*3 字节跳内存，缓存全废
/// （连只读一个像素的最近邻也要 81ms）。
///
/// 现在走 `resize_fast::resize_bgr`：行优先、无浮点中间图、按行多线程。
/// 实测同样场景 **3ms**（快约 30 倍），与旧实现逐像素 max 差值 2、平均 0.66。
pub fn resize(frame: &BgrFrame, target_w: u32, target_h: u32, filter: ResizeFilter) -> BgrFrame {
    if frame.is_empty() || target_w == 0 || target_h == 0 {
        return BgrFrame::new(target_w.max(1), target_h.max(1));
    }
    if target_w == frame.width && target_h == frame.height {
        return frame.clone();
    }
    // 核的选择与旧实现保持一致：
    // - 缩小 → Bicubic（CatmullRom）。旧实现缩小时用 CatmullRom；
    //   若这里用双线性，1080→360 会明显变糊（实测平均差 13.7、23% 像素差超 12）。
    // - 放大 → Bilinear，与旧实现一致。
    let shrinking = target_w < frame.width || target_h < frame.height;
    let kernel = match filter {
        ResizeFilter::Nearest => super::resize_fast::Kernel::Nearest,
        ResizeFilter::Area => super::resize_fast::Kernel::Bicubic,
        ResizeFilter::Bilinear => {
            if shrinking {
                super::resize_fast::Kernel::Bicubic
            } else {
                super::resize_fast::Kernel::Bilinear
            }
        }
    };
    super::profile::measure("resize", || {
        super::resize_fast::resize_bgr(frame, target_w, target_h, kernel)
    })
}

/// 旧的缩放实现（`image` crate 卷积），**仅供测试做画质对比**，生产代码不走这条。
///
/// 留着它是因为：换算法这类改动，只有「新旧逐像素比对」才是可靠验收。
/// 删掉就再也证明不了画质没退化。
#[cfg(test)]
pub fn resize_old_for_compare(frame: &BgrFrame, target_w: u32, target_h: u32) -> BgrFrame {
    if frame.is_empty() || target_w == 0 || target_h == 0 {
        return BgrFrame::new(target_w.max(1), target_h.max(1));
    }
    if target_w == frame.width && target_h == frame.height {
        return frame.clone();
    }
    let filter = auto_filter(frame.width, frame.height, target_w, target_h);
    let rgb = frame.to_rgb();
    let resized = imageops::resize(&rgb, target_w, target_h, filter.to_image());
    BgrFrame::from_rgb(&resized)
}

/// 等比缩放 + 黑边居中（对应 `resize_with_aspect_ratio()`）。
///
/// ⚠️ `int()` 是向零截断：Python 用 `int(target_width / img_ratio)`，
/// 不能写成 `round`，否则 1080 → 607.5 会变成 608，差一个像素就会出现黑边。
pub fn resize_with_aspect_ratio(
    frame: &BgrFrame,
    target_width: u32,
    target_height: u32,
) -> BgrFrame {
    if frame.is_empty() {
        return BgrFrame::new(target_width, target_height);
    }
    let mut result = BgrFrame::black(target_width, target_height);
    if target_width == 0 || target_height == 0 {
        return result;
    }
    let img_ratio = frame.width as f64 / frame.height as f64;
    let target_ratio = target_width as f64 / target_height as f64;

    let (new_w, new_h, x_offset, y_offset) = if img_ratio > target_ratio {
        let new_w = target_width;
        let new_h = (target_width as f64 / img_ratio).trunc().max(1.0) as u32;
        let y_offset = (target_height.saturating_sub(new_h)) / 2;
        (new_w, new_h, 0u32, y_offset)
    } else {
        let new_h = target_height;
        let new_w = (target_height as f64 * img_ratio).trunc().max(1.0) as u32;
        let x_offset = (target_width.saturating_sub(new_w)) / 2;
        (new_w, new_h, x_offset, 0u32)
    };

    let filter = auto_filter(frame.width, frame.height, new_w, new_h);
    let resized = resize(frame, new_w, new_h, filter);
    blit(&mut result, &resized, x_offset as i64, y_offset as i64);
    result
}

/// 通用缩放（对应 `resize_image()`）：适应 / 拉伸 / 填充。
pub fn resize_image(
    frame: &BgrFrame,
    target_w: u32,
    target_h: u32,
    mode: &str,
) -> BgrFrame {
    if frame.is_empty() {
        return BgrFrame::new(target_w, target_h);
    }
    match mode {
        "拉伸" => {
            let filter = auto_filter(frame.width, frame.height, target_w, target_h);
            resize(frame, target_w, target_h, filter)
        }
        "填充" => {
            // 等比放大到覆盖目标，再居中裁剪
            let scale = f64::max(
                target_w as f64 / frame.width as f64,
                target_h as f64 / frame.height as f64,
            );
            let new_w = ((frame.width as f64 * scale).trunc() as u32).max(1);
            let new_h = ((frame.height as f64 * scale).trunc() as u32).max(1);
            let filter = auto_filter(frame.width, frame.height, new_w, new_h);
            let resized = resize(frame, new_w, new_h, filter);
            let x0 = (new_w.saturating_sub(target_w)) / 2;
            let y0 = (new_h.saturating_sub(target_h)) / 2;
            crop(&resized, x0 as i64, y0 as i64, target_w, target_h)
        }
        _ => resize_with_aspect_ratio(frame, target_w, target_h),
    }
}

/// 把 `src` 贴到 `dst` 的 (x, y)；超出边界的部分裁掉。alpha 为 None 表示直接覆盖。
pub fn blit(dst: &mut BgrFrame, src: &BgrFrame, x: i64, y: i64) {
    for sy in 0..src.height as i64 {
        let dy = y + sy;
        if dy < 0 || dy >= dst.height as i64 {
            continue;
        }
        for sx in 0..src.width as i64 {
            let dx = x + sx;
            if dx < 0 || dx >= dst.width as i64 {
                continue;
            }
            if let Some(value) = src.pixel(sx as u32, sy as u32) {
                dst.set_pixel(dx as u32, dy as u32, value);
            }
        }
    }
}

/// 裁剪；越界部分用黑色补齐（对应 numpy 切片会越界报错，但项目里不会越界）。
pub fn crop(frame: &BgrFrame, x: i64, y: i64, width: u32, height: u32) -> BgrFrame {
    let mut result = BgrFrame::black(width, height);
    if width == 0 || height == 0 || frame.is_empty() {
        return result;
    }
    let src_w = frame.width as i64;
    let src_h = frame.height as i64;
    // 逐行拷贝而不是逐像素 set_pixel：行内是连续内存，
    // 1080p 裁剪从「约 200 万次带边界检查的 set_pixel」降为「1080 次 memcpy」。
    let dst_row_bytes = width as usize * 3;
    for dy in 0..height as i64 {
        let sy = y + dy;
        if sy < 0 || sy >= src_h {
            continue;
        }
        // 计算源行内真正有交集的那一段，边界外留黑
        let start = x.max(0);
        let end = (x + width as i64).min(src_w);
        if end <= start {
            continue;
        }
        let copy_len = (end - start) as usize * 3;
        let src_at = (sy as usize * src_w as usize + start as usize) * 3;
        let dst_at = dy as usize * dst_row_bytes + (start - x) as usize * 3;
        result.data[dst_at..dst_at + copy_len]
            .copy_from_slice(&frame.data[src_at..src_at + copy_len]);
    }
    result
}

/// 确保宽高为偶数（对应 `ensure_even_frame()`）：右侧/下侧补黑边。
pub fn ensure_even_frame(frame: &BgrFrame) -> BgrFrame {
    if frame.width % 2 == 0 && frame.height % 2 == 0 {
        return frame.clone();
    }
    let width = frame.width + (frame.width % 2);
    let height = frame.height + (frame.height % 2);
    let mut result = BgrFrame::black(width, height);
    blit(&mut result, frame, 0, 0);
    result
}

/// 两张图按 alpha 线性混合（对应 `cv2.addWeighted(a, 1-alpha, b, alpha, 0)`）。
///
/// ⚠️ OpenCV 的 `addWeighted` 内部是 `saturate_cast<uchar>(a*(1-alpha) + b*alpha + 0)`，
/// 即**四舍五入**（`cvRound`），不是截断。这里必须同样四舍五入，
/// 否则整体画面会比旧版暗 0.5 个色阶。
pub fn blend_weighted(first: &BgrFrame, second: &BgrFrame, alpha: f64) -> BgrFrame {
    let width = first.width.max(second.width);
    let height = first.height.max(second.height);
    let mut result = BgrFrame::black(width, height);
    let inverse = 1.0 - alpha;
    for y in 0..height {
        for x in 0..width {
            let a = first.pixel(x, y).unwrap_or([0, 0, 0]);
            let b = second.pixel(x, y).unwrap_or([0, 0, 0]);
            let mut out = [0u8; 3];
            for channel in 0..3 {
                let value = a[channel] as f64 * inverse + b[channel] as f64 * alpha;
                out[channel] = value.round().clamp(0.0, 255.0) as u8;
            }
            result.set_pixel(x, y, out);
        }
    }
    result
}

/// 从 RGBA 图构造带透明度的叠加帧。
pub fn rgba_to_bgra(image: &RgbaImage) -> Vec<u8> {
    let mut data = Vec::with_capacity(image.len() * 4);
    for pixel in image.pixels() {
        data.extend_from_slice(&[pixel[2], pixel[1], pixel[0], pixel[3]]);
    }
    data
}

/// 图片差异统计（B 路线的验收指标）。
#[derive(Debug, Clone, PartialEq)]
pub struct PixelDiff {
    pub max_delta: u8,
    pub mean_delta: f64,
    /// 差值 > 阈值（默认 8）的像素占比
    pub outlier_ratio: f64,
    pub compared_pixels: usize,
}

/// 比较两张同尺寸图。尺寸不同直接返回 None（结构不一致，属于真错误）。
pub fn compare(first: &BgrFrame, second: &BgrFrame) -> Option<PixelDiff> {
    if first.width != second.width || first.height != second.height {
        return None;
    }
    let total = first.data.len();
    if total == 0 {
        return Some(PixelDiff {
            max_delta: 0,
            mean_delta: 0.0,
            outlier_ratio: 0.0,
            compared_pixels: 0,
        });
    }
    let mut max_delta = 0u8;
    let mut sum: u64 = 0;
    let mut outliers = 0usize;
    for (a, b) in first.data.iter().zip(second.data.iter()) {
        let delta = a.abs_diff(*b);
        if delta > max_delta {
            max_delta = delta;
        }
        sum += delta as u64;
        if delta > 8 {
            outliers += 1;
        }
    }
    let channels = total as f64;
    Some(PixelDiff {
        max_delta,
        mean_delta: sum as f64 / channels,
        outlier_ratio: outliers as f64 / channels,
        compared_pixels: total / 3,
    })
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
    fn solid_frame_roundtrip_through_rgb() {
        let frame = solid(4, 3, [10, 20, 30]);
        let rgb = frame.to_rgb();
        let back = BgrFrame::from_rgb(&rgb);
        assert_eq!(back.data, frame.data);
    }

    #[test]
    fn resize_keeps_solid_color_exactly() {
        let frame = solid(100, 50, [40, 80, 120]);
        let resized = resize(&frame, 33, 17, ResizeFilter::Bilinear);
        assert_eq!((resized.width, resized.height), (33, 17));
        // 纯色缩放后每像素仍应是同一颜色（插值不会引入新值）
        assert!(resized.data.chunks(3).all(|chunk| chunk == [40, 80, 120]));
    }

    #[test]
    fn aspect_ratio_letterboxes_with_black() {
        // 200x100 → 100x100：宽图，上下留黑边
        let frame = solid(200, 100, [255, 255, 255]);
        let result = resize_with_aspect_ratio(&frame, 100, 100);
        assert_eq!((result.width, result.height), (100, 100));
        assert_eq!(result.pixel(50, 0), Some([0, 0, 0]), "顶部应为黑边");
        assert_eq!(result.pixel(50, 99), Some([0, 0, 0]), "底部应为黑边");
        assert_eq!(result.pixel(50, 50), Some([255, 255, 255]), "中间应为白");
    }

    #[test]
    fn aspect_ratio_pillarboxes_for_tall_image() {
        // 100x200 → 100x100：高图，左右留黑边
        let frame = solid(100, 200, [1, 2, 3]);
        let result = resize_with_aspect_ratio(&frame, 100, 100);
        assert_eq!(result.pixel(0, 50), Some([0, 0, 0]), "左侧应为黑边");
        assert_eq!(result.pixel(50, 50), Some([1, 2, 3]), "中间应为原色");
    }

    #[test]
    fn aspect_ratio_truncates_like_python_int() {
        // 1920x1080 → 1080x1920：new_h = int(1080 / 1.7777...) = 607
        let frame = solid(1920, 1080, [9, 9, 9]);
        let result = resize_with_aspect_ratio(&frame, 1080, 1920);
        // y_offset = (1920 - 607) // 2 = 656
        assert_eq!(result.pixel(540, 655), Some([0, 0, 0]));
        assert_eq!(result.pixel(540, 656), Some([9, 9, 9]));
    }

    #[test]
    fn stretch_mode_fills_exactly() {
        let frame = solid(200, 100, [7, 8, 9]);
        let result = resize_image(&frame, 60, 60, "拉伸");
        assert_eq!((result.width, result.height), (60, 60));
        assert!(result.data.chunks(3).all(|chunk| chunk == [7, 8, 9]));
    }

    #[test]
    fn fill_mode_crops_center() {
        // 200x100 → 100x100：先按 max(0.5, 1.0) 放大到 200x100，再裁中间 100x100
        let frame = solid(200, 100, [5, 6, 7]);
        let result = resize_image(&frame, 100, 100, "填充");
        assert_eq!((result.width, result.height), (100, 100));
        assert!(result.data.chunks(3).all(|chunk| chunk == [5, 6, 7]));
    }

    #[test]
    fn unknown_mode_falls_back_to_aspect_ratio() {
        let frame = solid(200, 100, [3, 3, 3]);
        let result = resize_image(&frame, 100, 100, "未知模式");
        assert_eq!((result.width, result.height), (100, 100));
        assert_eq!(result.pixel(50, 0), Some([0, 0, 0]));
    }

    #[test]
    fn ensure_even_frame_pads_odd_sizes() {
        let frame = solid(101, 53, [1, 1, 1]);
        let padded = ensure_even_frame(&frame);
        assert_eq!((padded.width, padded.height), (102, 54));
        assert_eq!(padded.pixel(0, 0), Some([1, 1, 1]));
        assert_eq!(padded.pixel(101, 0), Some([0, 0, 0]), "右侧补黑");
        assert_eq!(padded.pixel(0, 53), Some([0, 0, 0]), "下侧补黑");

        let even = solid(100, 50, [1, 1, 1]);
        assert_eq!(ensure_even_frame(&even).data, even.data);
    }

    #[test]
    fn blend_weighted_rounds_like_opencv() {
        let a = solid(2, 1, [100, 0, 255]);
        let b = solid(2, 1, [200, 255, 0]);
        // alpha = 0.5 → [150, 127.5→128, 127.5→128]
        let blended = blend_weighted(&a, &b, 0.5);
        assert_eq!(blended.pixel(0, 0), Some([150, 128, 128]));

        // alpha = 0 → 全是 a
        assert_eq!(blend_weighted(&a, &b, 0.0).pixel(0, 0), Some([100, 0, 255]));
        // alpha = 1 → 全是 b
        assert_eq!(blend_weighted(&a, &b, 1.0).pixel(0, 0), Some([200, 255, 0]));
    }

    #[test]
    fn blit_clips_out_of_bounds() {
        let mut dst = solid(10, 10, [0, 0, 0]);
        let src = solid(4, 4, [9, 9, 9]);
        blit(&mut dst, &src, -2, -2);
        // 只有左上角 (0,0)-(1,1) 被覆盖
        assert_eq!(dst.pixel(0, 0), Some([9, 9, 9]));
        assert_eq!(dst.pixel(1, 1), Some([9, 9, 9]));
        assert_eq!(dst.pixel(2, 2), Some([0, 0, 0]));
    }

    #[test]
    fn crop_returns_requested_size() {
        let frame = solid(10, 10, [4, 5, 6]);
        let result = crop(&frame, 3, 3, 4, 4);
        assert_eq!((result.width, result.height), (4, 4));
        assert!(result.data.chunks(3).all(|chunk| chunk == [4, 5, 6]));
    }

    #[test]
    fn compare_reports_zero_for_identical_frames() {
        let frame = solid(8, 8, [1, 2, 3]);
        let diff = compare(&frame, &frame).unwrap();
        assert_eq!(diff.max_delta, 0);
        assert_eq!(diff.mean_delta, 0.0);
        assert_eq!(diff.outlier_ratio, 0.0);
        assert_eq!(diff.compared_pixels, 64);
    }

    #[test]
    fn compare_detects_difference_and_rejects_size_mismatch() {
        let a = solid(2, 2, [0, 0, 0]);
        let mut b = a.clone();
        b.set_pixel(1, 1, [20, 0, 0]);
        let diff = compare(&a, &b).unwrap();
        assert_eq!(diff.max_delta, 20);
        assert!(diff.outlier_ratio > 0.0);
        assert!(compare(&a, &solid(3, 3, [0, 0, 0])).is_none());
    }

    #[test]
    fn auto_filter_picks_area_for_downscale() {
        assert_eq!(auto_filter(1280, 720, 640, 360), ResizeFilter::Area);
        assert_eq!(auto_filter(100, 100, 50, 100), ResizeFilter::Area);
        assert_eq!(auto_filter(100, 100, 200, 200), ResizeFilter::Bilinear);
        assert_eq!(auto_filter(100, 100, 100, 100), ResizeFilter::Bilinear);
    }

    #[test]
    fn missing_file_returns_none() {
        assert!(read_image_bgr(Path::new("C:/definitely/missing.png")).is_none());
    }
}