//! 缩放路径的成本分解（仅测试用，不进生产代码）。
//!
//! 目的：把 `resize` 那 87ms/次拆开看，到底贵在哪一步 ——
//! BGR→RGB、卷积本身、RGB→BGR，还是别的。
//! 不做这一步就只能瞎改。

use std::time::Instant;

use super::pixels::{BgrFrame, ResizeFilter};

fn frame(width: u32, height: u32) -> BgrFrame {
    let mut frame = BgrFrame::new(width, height);
    for y in 0..height {
        for x in 0..width {
            frame.set_pixel(x, y, [(x % 256) as u8, (y % 256) as u8, ((x + y) % 256) as u8]);
        }
    }
    frame
}

fn bench(label: &str, rounds: u32, mut run: impl FnMut()) {
    // 先热身，排除首次的内存分配与页错误
    run();
    let start = Instant::now();
    for _ in 0..rounds {
        run();
    }
    let total = start.elapsed();
    println!(
        "{label:28} {:>8.2} ms/次  ({} 次 {:.2}s)",
        total.as_secs_f64() * 1000.0 / rounds as f64,
        rounds,
        total.as_secs_f64()
    );
}

#[test]
fn resize_cost_breakdown() {
    // 典型场景：1080p 帧缩放 1.07 倍（「镜头呼吸」的最大缩放）
    let source = frame(1920, 1080);
    let (tw, th) = (2054u32, 1156u32);

    bench("BGR->RGB (1080p)", 20, || {
        std::hint::black_box(source.to_rgb());
    });

    let rgb = source.to_rgb();
    bench("imageops::resize Triangle", 20, || {
        std::hint::black_box(image::imageops::resize(&rgb, tw, th, image::imageops::FilterType::Triangle));
    });
    bench("imageops::resize CatmullRom", 20, || {
        std::hint::black_box(image::imageops::resize(&rgb, tw, th, image::imageops::FilterType::CatmullRom));
    });
    bench("imageops::resize Nearest", 20, || {
        std::hint::black_box(image::imageops::resize(&rgb, tw, th, image::imageops::FilterType::Nearest));
    });

    let resized = image::imageops::resize(&rgb, tw, th, image::imageops::FilterType::Triangle);
    bench("RGB->BGR (放大后)", 20, || {
        std::hint::black_box(BgrFrame::from_rgb(&resized));
    });

    // 校准：纯遍历写一遍，看这台机器的基础速度
    bench("基准·逐像素写(2.37M)", 20, || {
        let mut out = vec![0u8; tw as usize * th as usize * 3];
        for (index, slot) in out.chunks_exact_mut(3).enumerate() {
            let value = (index % 256) as u8;
            slot.copy_from_slice(&[value, value, value]);
        }
        std::hint::black_box(out);
    });
    bench("基准·memcpy 6MB", 20, || {
        let src = vec![7u8; 1920 * 1080 * 3];
        let mut dst = vec![0u8; 1920 * 1080 * 3];
        dst.copy_from_slice(&src);
        std::hint::black_box(dst);
    });
    println!("可用线程数: {}", std::thread::available_parallelism().map(|v| v.get()).unwrap_or(0));

    // 新实现
    bench("新·resize_bgr Bilinear", 20, || {
        std::hint::black_box(super::resize_fast::resize_bgr(&source, tw, th, super::resize_fast::Kernel::Bilinear));
    });
    bench("新·resize_bgr Nearest", 20, || {
        std::hint::black_box(super::resize_fast::resize_bgr(&source, tw, th, super::resize_fast::Kernel::Nearest));
    });

    // 画质对比：新旧实现逐像素最大差值
    let old = super::pixels::resize(&source, tw, th, ResizeFilter::Bilinear);
    let new = super::resize_fast::resize_bgr(&source, tw, th, super::resize_fast::Kernel::Bilinear);
    let mut max_diff = 0i32;
    let mut sum_diff = 0i64;
    let mut over = 0usize;
    for (a, b) in old.data.iter().zip(new.data.iter()) {
        let d = (*a as i32 - *b as i32).abs();
        max_diff = max_diff.max(d);
        sum_diff += d as i64;
        if d > 8 { over += 1; }
    }
    let total = old.data.len();
    println!(
        "画质对比: max差={max_diff} 平均差={:.3} 超8的像素占比={:.4}%",
        sum_diff as f64 / total as f64,
        over as f64 * 100.0 / total as f64
    );

    // 完整的当前实现（Area → CatmullRom）
    bench("resize(Area=CatmullRom)", 10, || {
        std::hint::black_box(super::pixels::resize(&source, tw, th, ResizeFilter::Area));
    });
    bench("resize(Bilinear=Triangle)", 10, || {
        std::hint::black_box(super::pixels::resize(&source, tw, th, ResizeFilter::Bilinear));
    });
}

/// 用真实图片（而非纯色合成图）验证新旧缩放的画质差。
#[test]
fn real_image_quality() {
    let dir = std::path::Path::new("C:/Users/tt/AppData/Local/Temp/itv-smoke/detail");
    let mut checked = 0;
    for entry in std::fs::read_dir(dir).into_iter().flatten().flatten() {
        let path = entry.path();
        if !path.is_file() { continue; }
        let Some(source) = super::pixels::read_image_bgr(&path) else { continue; };

        for (tw, th) in [(960u32, 540u32), (640, 360), (480, 270), (1280, 720)] {
            let old = super::pixels::resize_old_for_compare(&source, tw, th);
            let new = super::resize_fast::resize_bgr(&source, tw, th, super::resize_fast::Kernel::Bilinear);
            let mut max_diff = 0i32;
            let mut sum = 0i64;
            let mut over12 = 0usize;
            for (a, b) in old.data.iter().zip(new.data.iter()) {
                let d = (*a as i32 - *b as i32).abs();
                max_diff = max_diff.max(d);
                sum += d as i64;
                if d > 12 { over12 += 1; }
            }
            let total = old.data.len();
            println!(
                "{:24?} {:>5}x{:<5} max={:<3} 平均={:.3} 超12占比={:.4}%",
                path.file_name().unwrap_or_default(),
                tw, th, max_diff,
                sum as f64 / total as f64,
                over12 as f64 * 100.0 / total as f64
            );
            // 判定口径（实测得出的上界，留一倍余量）：
            // 平均差是主指标（决定整体观感），最大差只在少数锐利边缘出现，放宽看。
            assert!(
                sum as f64 / total as f64 <= 3.0,
                "{:?} {tw}x{th} 平均差 {:.2} 超过 3.0 —— 画面会明显变样",
                path.file_name().unwrap_or_default(),
                sum as f64 / total as f64
            );
            assert!(
                (over12 as f64) * 100.0 / total as f64 <= 6.0,
                "{:?} {tw}x{th} 超阈值像素占比 {:.2}% 超过 6%",
                path.file_name().unwrap_or_default(),
                over12 as f64 * 100.0 / total as f64
            );
        }
        checked += 1;
    }
    println!("共检查 {checked} 张真实图片");
    assert!(checked > 0, "没找到测试图片");
}


/// 把新旧缩放结果各存一张 PNG，供肉眼比对。
#[test]
fn dump_resize_comparison() {
    let source = super::pixels::read_image_bgr(std::path::Path::new(
        "C:/Users/tt/AppData/Local/Temp/itv-smoke/detail/mandel.png",
    ))
    .expect("找不到测试图");

    for (tw, th, tag) in [(1280u32, 720u32, "half"), (640, 360, "third")] {
        let old = super::pixels::resize_old_for_compare(&source, tw, th);
        let new = super::resize_fast::resize_bgr(&source, tw, th, super::resize_fast::Kernel::Bicubic);
        old.to_rgb().save(format!("C:/Users/tt/AppData/Local/Temp/cmp_old_{tag}.png")).unwrap();
        new.to_rgb().save(format!("C:/Users/tt/AppData/Local/Temp/cmp_new_{tag}.png")).unwrap();
        println!("已保存 {tag}: old / new");
    }
}
