//! 转场基线：33 个转场 × 5 个进度点的哈希。
//!
//! ## 为什么先补这个
//!
//! 特效有 75 条哈希基线守着，**转场一个都没有**。这意味着改转场代码时
//! 没有任何机制能告诉我「画面变了」—— 全靠肉眼对比导出视频，而那
//! 通常是几天后才被发现。
//!
//! 补上这一层之后，任何转场改动（加参数、换算法、修 bug）都会被立刻拦住，
//! 由人判断「这个变化是不是我要的」。
//!
//! 与特效基线的差异：转场是**两帧之间的过渡**，所以输入是两张图，
//! 检查的是「进度 0 → 1 全程」的中间帧。除了哈希，还断言三条性质
//! （见文件末尾），因为哈希只回答「变了没」，答不出「变得对不对」。
//!
//! ## 怎么重新生成基线
//!
//! 确认改动是有意的之后：
//!
//! ```sh
//! ITV_TRANSITION_BASELINE_WRITE=1 cargo test --release --offline \
//!     --lib transitions_baseline_is_stable -- --nocapture
//! ```
//!
//! 输出粘到 `transitions_baseline.txt` 即可（与特效基线同一套做法）。

use super::pixels::BgrFrame;
use super::transitions::{self};

/// 参与基线的转场。与 `catalog::TRANSITIONS` 必须一一对应 ——
/// 有 `baseline_covers_every_declared_transition` 守着。
const PROBE_TRANSITIONS: [&str; 33] = [
    "淡入淡出",
    "交叉溶解",
    "左右滑动",
    "上下滑动",
    "圆形扩展",
    "缩放过渡",
    "百叶窗",
    "像素化",
    "旋转变换",
    "棋盘格",
    "波浪",
    "颜色混合",
    "方块过渡",
    "放大冲击",
    "缩小爆炸",
    "旋转放大",
    "弹性缩放",
    "3D翻转",
    "推入效果",
    "对角擦除",
    "门式打开",
    "闪光过渡",
    "碎片飞散",
    "光晕扩散",
    "径向旋切",
    "漩涡扭曲",
    "菱形开幕",
    "镜头虚焦",
    "纵向拉幕",
    "横向拉幕",
    "液态融合",
    "流光擦拭",
    "时钟扫描",
];

/// 两张一眼能分开的测试图：左图偏红且左亮，右图偏蓝且右亮。
///
/// 必须「一眼能分开」，否则淡入淡出一类的中间帧会几乎和原图一样，
/// 哈希测不出转场有没有真的发生。
fn frame_a(width: u32, height: u32) -> BgrFrame {
    let mut frame = BgrFrame::new(width, height);
    for y in 0..height {
        for x in 0..width {
            let bright = if x < width / 2 { 200 } else { 40 };
            frame.set_pixel(x, y, [bright, bright / 3, 20]);
        }
    }
    frame
}

fn frame_b(width: u32, height: u32) -> BgrFrame {
    let mut frame = BgrFrame::new(width, height);
    for y in 0..height {
        for x in 0..width {
            let bright = if x < width / 2 { 40 } else { 200 };
            frame.set_pixel(x, y, [20, bright / 3, bright]);
        }
    }
    frame
}

/// 与 `effects_baseline_test.rs` 一致的十六进制摘要（不引第三方哈希库）。
fn hex(data: &[u8]) -> String {
    // FNV-1a 64 位：足够稳定，且无依赖
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in data {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("{hash:016x}")
}

fn iterations() -> [usize; 4] {
    [1, 2, 5, 10]
}

#[test]
fn transitions_baseline_is_stable() {
    let width = 96u32;
    let height = 64u32;
    let first = frame_a(width, height);
    let second = frame_b(width, height);
    let writing = std::env::var("ITV_TRANSITION_BASELINE_WRITE").is_ok();

    let mut rows: Vec<(String, String)> = Vec::new();
    for name in PROBE_TRANSITIONS {
        let parsed = transitions::parse(name);
        for count in iterations() {
            let frames =
                transitions::generate_frames(&first, &second, parsed, count, &Default::default());
            assert_eq!(
                frames.len(),
                count,
                "「{name}」在 count={count} 时产出的帧数不对"
            );
            // 取整段的摘要，而不是逐帧 —— 中间帧怎么排也是形状的一部分
            let mut digest_input = Vec::with_capacity(frames.len() * 3);
            for frame in &frames {
                digest_input.extend_from_slice(&frame.data);
            }
            rows.push((format!("{name}@{count}"), hex(&digest_input)));
        }
    }

    if writing {
        println!("TRANSITION_BASELINE BEGIN");
        for (name, digest) in &rows {
            println!("{name}\t{digest}");
        }
        println!("TRANSITION_BASELINE END");
        return;
    }

    let baseline = include_str!("transitions_baseline.txt");
    let mut mismatches = Vec::new();
    for (name, digest) in &rows {
        let expected = baseline
            .lines()
            .find_map(|line| line.strip_prefix(&format!("{name}\t")));
        match expected {
            Some(expected) if expected.trim() == digest => {}
            Some(expected) => mismatches.push(format!(
                "「{name}」输出变了：基线 {} 现在 {}",
                expected.trim(),
                digest
            )),
            None => mismatches.push(format!("「{name}」在基线里找不到")),
        }
    }
    assert!(
        mismatches.is_empty(),
        "转场基线不匹配（{} 项）：\n{}\n\n如果这次改动是**有意的**，重新生成基线：\n\
         ITV_TRANSITION_BASELINE_WRITE=1 cargo test --release --offline \
         --lib transitions_baseline_is_stable -- --nocapture",
        mismatches.len(),
        mismatches.join("\n")
    );
}

/// 基线必须覆盖目录里声明的每一个转场 —— 加了新转场忘了进基线，
/// 它就回到了「没人管」的状态。
#[test]
fn baseline_covers_every_declared_transition() {
    use super::catalog::TRANSITIONS;
    for item in TRANSITIONS {
        assert!(
            PROBE_TRANSITIONS.contains(&item.id),
            "转场「{}」没进 PROBE_TRANSITIONS，它的画质无人把关",
            item.id
        );
    }
    assert_eq!(
        PROBE_TRANSITIONS.len(),
        TRANSITIONS.len(),
        "基线转场数与目录声明数不一致"
    );
}

/// 转场必须**真的从 A 变到 B**：整段过程中应该能看出「越来越接近第二张」。
///
/// ⚠️ 不能断言「首帧 == 第一张图」：有些转场首帧就带着效果了 ——
/// 「缩小爆炸」首帧是第一张图缩到 90% 再抖动，「闪光过渡」首帧带白闪。
/// 所以这里断言的是**趋势**：最后几帧必须比最开始几帧更像第二张。
#[test]
fn every_transition_moves_from_first_to_second() {
    let width = 96u32;
    let height = 64u32;
    let first = frame_a(width, height);
    let second = frame_b(width, height);

    for name in PROBE_TRANSITIONS {
        let parsed = transitions::parse(name);
        let frames = transitions::generate_frames(&first, &second, parsed, 10, &Default::default());
        assert_eq!(frames.len(), 10);

        // 前 3 帧平均离第二张多远 vs 后 3 帧
        let early: f64 = (0..3).map(|i| mean_diff(&frames[i], &second)).sum::<f64>() / 3.0;
        let late: f64 = (7..10).map(|i| mean_diff(&frames[i], &second)).sum::<f64>() / 3.0;

        assert!(
            late <= early,
            "「{name}」后段离第二张图（{late:.1}）比前段（{early:.1}）还远 —— 方向可能反了"
        );

        // 至少要有一次真的动过，不能全程都是同一张
        let moved = (1..10).any(|i| mean_diff(&frames[0], &frames[i]) > 1.0);
        assert!(moved, "「{name}」全程画面没变化 —— 转场可能根本没发生");
    }
}

/// 「闪光过渡」这类会在中途插入一帧极端亮/暗的转场，不该把整段都搞成全黑。
#[test]
fn no_transition_goes_fully_black() {
    let width = 96u32;
    let height = 64u32;
    let first = frame_a(width, height);
    let second = frame_b(width, height);

    for name in PROBE_TRANSITIONS {
        let parsed = transitions::parse(name);
        for frame in transitions::generate_frames(&first, &second, parsed, 6, &Default::default()) {
            let luma = mean_luma(&frame);
            assert!(
                luma > 0.5,
                "「{name}」中途整幅变黑（平均亮度 {luma:.2}）—— 可能是遮罩写反了"
            );
        }
    }
}

fn mean_luma(frame: &BgrFrame) -> f64 {
    if frame.data.is_empty() {
        return 0.0;
    }
    frame.data.iter().map(|v| *v as f64).sum::<f64>() / frame.data.len() as f64
}

fn mean_diff(a: &BgrFrame, b: &BgrFrame) -> f64 {
    if a.data.len() != b.data.len() || a.data.is_empty() {
        return 0.0;
    }
    let sum: i64 = a
        .data
        .iter()
        .zip(b.data.iter())
        .map(|(x, y)| (*x as i64 - *y as i64).abs())
        .sum();
    sum as f64 / a.data.len() as f64
}
/// **转场专属参数必须真的影响画面。**
///
/// 这条是上一轮漏掉的教训：当时界面给转场渲染了控件，但参数根本没传进
/// `generate_frames`，拖了没有任何效果。光声明不改管道，等于做了个假控件。
#[test]
fn transition_params_change_pixels() {
    let first = frame_a(96, 64);
    let second = frame_b(96, 64);

    // 每个转场：一个参数 + 两档取值
    let cases: &[(&str, &str, f64, f64)] = &[
        ("百叶窗", "blinds", 4.0, 30.0),
        ("棋盘格", "grid", 8.0, 60.0),
        ("方块过渡", "block", 12.0, 120.0),
        ("碎片飞散", "shard", 12.0, 120.0),
        ("波浪", "amplitude", 5.0, 80.0),
    ];

    for (name, key, low, high) in cases {
        let parse = transitions::parse(name);
        let build = |value: f64| {
            let mut extra = serde_json::Map::new();
            extra.insert((*key).to_string(), serde_json::json!(value));
            transitions::generate_frames(&first, &second, parse, 6, &extra)
        };
        let at_low = build(*low);
        let at_high = build(*high);

        let diff: f64 = at_low
            .iter()
            .zip(at_high.iter())
            .map(|(a, b)| mean_diff(a, b))
            .sum::<f64>()
            / at_low.len() as f64;
        assert!(
            diff > 0.5,
            "「{name}」的参数「{key}」没起作用（{low} vs {high} 平均差只有 {diff:.3}）——\n\
             界面上会是个调了没用的控件。"
        );
    }
}

/// 不传转场参数时，结果与显式传默认值完全一致 —— 老配置不能变样。
#[test]
fn missing_transition_params_match_explicit_defaults() {
    let first = frame_a(96, 64);
    let second = frame_b(96, 64);

    let defaults: &[(&str, &str, f64)] = &[
        ("百叶窗", "blinds", 10.0),
        ("棋盘格", "grid", 20.0),
        ("方块过渡", "block", 40.0),
        ("碎片飞散", "shard", 40.0),
        ("波浪", "amplitude", 20.0),
    ];

    for (name, key, default) in defaults {
        let parse = transitions::parse(name);
        let bare = transitions::generate_frames(&first, &second, parse, 5, &Default::default());

        let mut extra = serde_json::Map::new();
        extra.insert((*key).to_string(), serde_json::json!(default));
        let explicit = transitions::generate_frames(&first, &second, parse, 5, &extra);

        for (index, (a, b)) in bare.iter().zip(explicit.iter()).enumerate() {
            assert_eq!(
                a.data, b.data,
                "「{name}」第 {index} 帧：缺省参数与显式默认值 {default} 不一致"
            );
        }
    }
}
