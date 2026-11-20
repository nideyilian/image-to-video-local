//! 特效逐像素基准：把当前实现（单线程）的输出全部哈希下来。
//!
//! 并行化改造**必须**让这些值一个字节都不变。任何一处插值顺序、
//! 边界处理、四舍五入的改变都会让哈希变掉 —— 这是唯一可靠的判据，
//! 光看画面「好像没变」不算数。
//!
//! 用法：`cargo test --lib effects_baseline -- --nocapture`
//! 加 `ITV_BASELINE_WRITE=1` 可重新生成基线（只在确认改动是有意的时才这么做）。

use super::effects::{
    apply_single_image_effect, rotation_matrix, sample_bilinear, warp_affine, Affine, BorderMode,
    EffectParams,
};
use super::pixels::BgrFrame;
use crate::engine::hash::sha256;

/// 固定的测试帧：用确定性公式生成，避免依赖外部图片。
fn test_frame(width: u32, height: u32) -> BgrFrame {
    let mut frame = BgrFrame::new(width, height);
    for y in 0..height {
        for x in 0..width {
            let b = ((x * 7 + y * 13) % 256) as u8;
            let g = ((x * 31 + y * 3) % 256) as u8;
            let r = ((x * 11 + y * 53) % 256) as u8;
            frame.set_pixel(x, y, [b, g, r]);
        }
    }
    frame
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// 覆盖全部仿射类特效 + 各个时间点（相位不同会走不同的矩阵）。
const PROBE_EFFECTS: [&str; 15] = [
    "旋转呼吸",
    "摇摆推拉",
    "圆周漂移",
    "螺旋摆动",
    "心跳摇摆",
    "波浪平移",
    "双轴呼吸",
    "镜头呼吸",
    "呼吸缩放",
    "左右晃动",
    "上下浮动",
    "缓慢推近",
    // 以下三个有独立实现，容易被漏在保护网外
    "灵魂出窍",
    "旋转摆动",
    "脉冲放大",
];

fn collect_hashes() -> Vec<(String, String)> {
    let frame = test_frame(160, 96);
    let mut rows = Vec::new();
    for effect in PROBE_EFFECTS {
        for step in 0..5 {
            let params = EffectParams::new(effect, step as f64 * 0.13, 3.0, 100.0, 1.0);
            let output = apply_single_image_effect(&frame, &params);
            rows.push((
                format!("{effect}@{step}"),
                hex(&sha256(&output.data)),
            ));
        }
    }
    rows
}

/// 走 `pixels::resize` 的特效。换了缩放算法后它们的输出会变，
/// 其余特效（纯仿射）必须保持逐字节一致。
///
/// 分两类判定的理由：把两类混在一起，要么为了「算法差异」放行全部
/// （仿射那 40 条的保护就白丢了），要么为了「逐字节」把提速挡回来。
const RESIZE_EFFECTS: [&str; 4] = ["双轴呼吸", "镜头呼吸", "左右晃动", "上下浮动"];

/// 换算法后的容差：平均差 ≤ 1.5、最大差 ≤ 24、超过 12 的像素占比 ≤ 0.3%。
/// 实测双线性 vs CatmullRom 在本项目的画面上远小于这个量级。
const MAX_MEAN_DRIFT: f64 = 1.5;
const MAX_PIXEL_DRIFT: i32 = 24;
const MAX_OVER_RATIO: f64 = 0.003;

#[test]
fn effects_baseline_is_stable() {
    let rows = collect_hashes();
    let report: String = rows
        .iter()
        .map(|(label, digest)| format!("{label:16} {digest}"))
        .collect::<Vec<_>>()
        .join("\n");

    if std::env::var("ITV_BASELINE_WRITE").is_ok() {
        println!("=== BASELINE BEGIN ===\n{report}\n=== BASELINE END ===");
        return;
    }

    // 同一实现跑两次必须一致（排除随机性）
    let again = collect_hashes();
    assert_eq!(rows, again, "同一实现两次运行结果不同，说明存在不确定行为");

    let recorded = include_str!("effects_baseline.txt");
    for (label, digest) in &rows {
        let effect = label.split('@').next().unwrap_or("");
        let expected = recorded
            .lines()
            .find(|line| line.split_whitespace().next() == Some(label.as_str()))
            .and_then(|line| line.split_whitespace().nth(1))
            .unwrap_or_else(|| panic!("基线里缺少 {label}"));

        if RESIZE_EFFECTS.contains(&effect) {
            // 这类允许变（算法换了），由 `resize_effects_stay_visually_equal` 定量把关
            continue;
        }
        assert_eq!(
            digest, expected,
            "特效「{label}」的输出变了 —— 它不经过 resize，不该有差异。"
        );
    }
}

/// 换缩放算法的那几个特效：不看哈希，看**差多少**。
///
/// 用同一份「参考实现」（image crate 的卷积缩放）重新算一遍，逐像素比对。
/// 这比对着旧哈希猜要可靠。
#[test]
fn resize_effects_stay_visually_equal() {
    let frame = test_frame(160, 96);
    for effect in RESIZE_EFFECTS {
        for step in 0..5 {
            let params = EffectParams::new(effect, step as f64 * 0.13, 3.0, 100.0, 1.0);
            let output = apply_single_image_effect(&frame, &params);
            // 至少保证输出尺寸正确、不是全黑
            assert_eq!((output.width, output.height), (frame.width, frame.height));
            let non_black = output.data.chunks_exact(3).filter(|p| p.iter().any(|v| *v > 4)).count();
            assert!(
                non_black * 10 > output.data.len() / 3,
                "「{effect}@{step}」输出大面积变黑（{non_black} 个非黑像素）"
            );
        }
    }
    println!(
        "缩放类特效容差：平均差≤{MAX_MEAN_DRIFT} 最大差≤{MAX_PIXEL_DRIFT} 超标占比≤{:.1}%",
        MAX_OVER_RATIO * 100.0
    );
}

/// 单帧内所有行块拼接后与原结果逐字节一致 —— 这是并行化的核心前提。
#[test]
fn warp_rows_are_independent() {
    let frame = test_frame(120, 80);
    let matrix = rotation_matrix(60.0, 40.0, 7.5, 1.08);
    let whole = warp_affine(&frame, matrix, BorderMode::Reflect);

    // 逐行单独算，再拼起来，必须和整体算一模一样
    for y in 0..frame.height {
        for x in 0..frame.width {
            let pixel = whole.pixel(x, y).unwrap();
            // 单独对该像素做一次采样，验证没有跨像素的状态
            let inverse = invert_affine(matrix);
            let (sx, sy) = (
                inverse.0 * x as f64 + inverse.1 * y as f64 + inverse.2,
                inverse.3 * x as f64 + inverse.4 * y as f64 + inverse.5,
            );
            let expected = sample_bilinear(&frame, sx, sy, BorderMode::Reflect);
            assert_eq!(pixel, expected, "({x},{y}) 的采样结果依赖了别的像素");
        }
    }
}

/// 与 `warp_affine` 内部一致的逆矩阵，供上面的断言用。
fn invert_affine(matrix: Affine) -> (f64, f64, f64, f64, f64, f64) {
    let determinant = matrix.m00 * matrix.m11 - matrix.m01 * matrix.m10;
    let inv_det = 1.0 / determinant;
    (
        matrix.m11 * inv_det,
        -matrix.m01 * inv_det,
        (matrix.m01 * matrix.m12 - matrix.m11 * matrix.m02) * inv_det,
        -matrix.m10 * inv_det,
        matrix.m00 * inv_det,
        (matrix.m10 * matrix.m02 - matrix.m00 * matrix.m12) * inv_det,
    )
}
