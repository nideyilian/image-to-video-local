//! 「灵魂出窍」等逐像素特效的成本分解。
//!
//! 只测不猜：先看清每一步占多少，再决定优化什么。

use std::time::Instant;

use super::effects::{
    apply_single_image_effect, rotation_matrix, warp_affine, BorderMode, EffectParams,
};
use super::pixels::{blend_weighted, BgrFrame};

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

fn bench(label: &str, rounds: u32, mut run: impl FnMut()) {
    run();
    let start = Instant::now();
    for _ in 0..rounds {
        run();
    }
    let total = start.elapsed();
    println!(
        "{label:32} {:>8.2} ms/次",
        total.as_secs_f64() * 1000.0 / rounds as f64
    );
}

#[test]
fn soul_out_cost_breakdown() {
    let source = frame(1920, 1080);
    let (w, h) = (source.width as f64, source.height as f64);

    let params = EffectParams::new("灵魂出窍", 0.5, 3.0, 100.0, 1.0);
    bench("完整 灵魂出窍", 10, || {
        std::hint::black_box(apply_single_image_effect(&source, &params));
    });

    // 拆解：默认最狠的一档（curve 第 12 帧以后 scale=3.453861）
    let scale = 3.453861;
    let matrix = rotation_matrix((w - 1.0) * 0.5, (h - 1.0) * 0.5, 0.0, scale);
    bench("warp_affine(scale=3.45,REPLICATE)", 10, || {
        std::hint::black_box(warp_affine(&source, matrix, BorderMode::Replicate));
    });
    // 对比：同样的缩放走 resize 路径
    bench("resize_bgr(scale=3.45,双线性)", 10, || {
        let tw = (source.width as f64 * scale) as u32;
        let th = (source.height as f64 * scale) as u32;
        std::hint::black_box(super::resize_fast::resize_bgr(
            &source,
            tw,
            th,
            super::resize_fast::Kernel::Bilinear,
        ));
    });

    let zoomed = warp_affine(&source, matrix, BorderMode::Replicate);
    bench("blend_weighted(mixture=0.5)", 10, || {
        std::hint::black_box(blend_weighted(&source, &zoomed, 0.5));
    });

    // 基准：纯拷贝
    bench("基准·clone", 10, || {
        std::hint::black_box(source.clone());
    });
}
