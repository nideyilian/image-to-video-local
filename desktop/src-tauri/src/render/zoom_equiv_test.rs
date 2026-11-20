//! 纯缩放（角度=0）时，`warp_affine` 与 `resize_bgr` 是否等价？
//!
//! 灵魂出窍只做缩放不做旋转，如果能用更快的那条路径替代，
//! 就能省掉 `warp_affine` 里每像素的边界计算。
//! 但必须先用数据证明两者一致，不能想当然。

use super::effects::{rotation_matrix, warp_affine, BorderMode};
use super::pixels::BgrFrame;
use super::resize_fast::{resize_bgr, Kernel};

fn frame(width: u32, height: u32) -> BgrFrame {
    let mut frame = BgrFrame::new(width, height);
    for y in 0..height {
        for x in 0..width {
            frame.set_pixel(
                x,
                y,
                [
                    ((x * 7 + y * 13) % 256) as u8,
                    ((x * 31 + y * 3) % 256) as u8,
                    ((x * 11 + y * 53) % 256) as u8,
                ],
            );
        }
    }
    frame
}

/// 两者都是「以像素中心对齐的双线性重采样」，但边界处理不同：
/// warp_affine 在缩放 >1 时目标全在图内，不会触发边界。
#[test]
fn zoom_only_matches_resize() {
    let source = frame(200, 120);
    for scale in [1.05f64, 1.2, 1.6268295, 2.0, 3.453861] {
        let (width, height) = (source.width as f64, source.height as f64);
        // warp_affine 版（灵魂出窍现在用的）
        let matrix = rotation_matrix((width - 1.0) * 0.5, (height - 1.0) * 0.5, 0.0, scale);
        let warped = warp_affine(&source, matrix, BorderMode::Replicate);
        // resize 放大 + 中心裁剪版
        let tw = ((width * scale) as i64).max(1) as u32;
        let th = ((height * scale) as i64).max(1) as u32;
        let zoomed = resize_bgr(&source, tw, th, Kernel::Bilinear);
        let crop_x = ((tw.saturating_sub(source.width)) / 2) as i64;
        let crop_y = ((th.saturating_sub(source.height)) / 2) as i64;
        let cropped = super::pixels::crop(&zoomed, crop_x, crop_y, source.width, source.height);

        let mut max_diff = 0i32;
        let mut sum = 0i64;
        for (a, b) in warped.data.iter().zip(cropped.data.iter()) {
            let d = (*a as i32 - *b as i32).abs();
            max_diff = max_diff.max(d);
            sum += d as i64;
        }
        println!(
            "scale={scale:.4}  max差={max_diff:<3} 平均差={:.3}",
            sum as f64 / warped.data.len() as f64
        );
    }
}
