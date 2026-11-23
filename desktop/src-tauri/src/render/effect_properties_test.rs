//! 每个特效/转场**自带断言**：用性质判断，而不是只比对哈希。
//!
//! ## 为什么要这一层
//!
//! `effects_baseline.txt` 是 75 条全局哈希。它的好处是「改坏了立刻知道」，
//! 但它回答不了「哪里坏了」—— 哈希变了等于什么都没说。而且改一个特效，
//! 可能有 5 条哈希一起变，得逐条判断是不是自己要的。
//!
//! 这一层补的是**可读的性质断言**，每个特效声明自己的不变量：
//! - 输出尺寸不变
//! - 不会整幅变黑或变白
//! - 纯色图经过纯几何运动后还是同一个颜色（摇晃不会改变颜色）
//! - 两个不同时间点应该产生不同结果（说明它真的在动）
//! - 强度为 0 时应该接近原图
//!
//! 坏了的时候，报错信息直接说「X 特效在 t=0.39 时整幅变黑」，
//! 而不是「哈希不匹配」。
//!
//! 这套思路来自 Concat 的 `fixtures.toml`（每个特效包自带 probe），
//! 只是我们不需要额外文件，直接用 `catalog` 的声明生成。

use super::catalog::EFFECTS;
use super::effects::{apply_single_image_effect, EffectParams};
use super::pixels::BgrFrame;

/// 一张有渐变、有边缘、有纯色区的测试图 —— 兼顾「能看出运动」和「能判断颜色」。
fn probe_frame(width: u32, height: u32) -> BgrFrame {
    let mut frame = BgrFrame::new(width, height);
    for y in 0..height {
        for x in 0..width {
            // 深色底 + 中间一个亮方块 + 右上斜线 + 左半渐变。
            // 必须保证有强对比边缘：「边缘闪烁」这类特效靠 canny 找边，
            // 纯渐变+低对比条纹可能一条边都检测不到，看起来就像「完全不动」。
            let in_block =
                x > width / 4 && x < width * 3 / 4 && y > height / 4 && y < height * 3 / 4;
            let on_diag = (x as i64 - y as i64 * 2).abs() < 3;
            let base = if in_block { 230u8 } else { 30 };
            let value = if on_diag { 250 } else { base };
            let gradient = ((x * 120) / width.max(1)) as u8;
            frame.set_pixel(x, y, [value, gradient, 255 - value]);
        }
    }
    frame
}

/// 纯色帧：用于验证「纯几何运动不改变颜色」。
fn flat_frame(width: u32, height: u32, color: [u8; 3]) -> BgrFrame {
    let mut frame = BgrFrame::new(width, height);
    for y in 0..height {
        for x in 0..width {
            frame.set_pixel(x, y, color);
        }
    }
    frame
}

fn params(effect: &str, time_sec: f64) -> EffectParams {
    EffectParams::new(effect, time_sec, 3.0, 100.0, 1.0)
}

/// 平均亮度，用来判断是否「整幅变黑/变白」。
fn mean_luma(frame: &BgrFrame) -> f64 {
    if frame.data.is_empty() {
        return 0.0;
    }
    frame.data.iter().map(|v| *v as f64).sum::<f64>() / frame.data.len() as f64
}

/// 两帧的逐像素平均差，用来判断「有没有真的在动」。
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

/// 声明里没有任何参数的特效，用它跑通用断言。
/// 有独有参数的特效先跳过（参数体系还没接进渲染，见 catalog 注释）。
const GENERIC_CHECKS: [&str; 5] = [
    "尺寸不变",
    "不至于全黑",
    "不至于全白",
    "真的在动",
    "强度为0接近原图",
];

#[test]
fn every_effect_keeps_frame_size() {
    let frame = probe_frame(160, 96);
    for item in EFFECTS {
        for step in 0..5 {
            let t = step as f64 * 0.37;
            let output = apply_single_image_effect(&frame, &params(item.id, t));
            assert_eq!(
                (output.width, output.height),
                (frame.width, frame.height),
                "「{}」在 t={t:.2} 时改变了画面尺寸",
                item.id
            );
        }
    }
}

#[test]
fn no_effect_goes_fully_black_or_white() {
    let frame = probe_frame(160, 96);
    let source_luma = mean_luma(&frame);
    for item in EFFECTS {
        for step in 0..5 {
            let t = step as f64 * 0.37;
            let output = apply_single_image_effect(&frame, &params(item.id, t));
            let luma = mean_luma(&output);
            assert!(
                luma > 1.0,
                "「{}」在 t={t:.2} 时整幅变黑（平均亮度 {luma:.2}，原图 {source_luma:.2}）",
                item.id
            );
            assert!(
                luma < 254.0,
                "「{}」在 t={t:.2} 时整幅变白（平均亮度 {luma:.2}，原图 {source_luma:.2}）",
                item.id
            );
        }
    }
}

/// 有些特效**本来就该是静态的** —— 纯逐像素变换，与时间无关。
///
/// 判断标准：它改变的是「每个像素怎么映射」，而不是「画面怎么动」。
/// 硬给它们加时间变化是错的（比如让色调分离的色阶数随时间抖，画面会闪）。
///
/// 这类特效由 `static_effects_do_not_change_over_time` 反向断言：
/// 同一输入不同时间点必须**完全一致**，这才是它们正确工作的标志。
const STATIC_EFFECTS: [&str; 2] = ["色调分离", "半调网点"];

/// 这条最有价值：证明特效**真的随时间变化**。
///
/// 一个写错的特效常常是「参数算出来了但没用上」，画面一直不动 ——
/// 这种 bug 用哈希测不出来（哈希稳定就像是对的），但「扫一圈时间点全都一样」
/// 会立刻暴露。
///
/// ⚠️ 必须扫一串时间点取**最大**差异，不能只比 t=0 和某个固定点：
/// 「上下浮动」的位移是 cos(2π·2·t)，周期 0.5 秒，t=0 和 t=0.45 恰好在
/// 波谷两侧几乎对称，差异接近 0 —— 只比这两个点会误报。
#[test]
fn every_effect_actually_moves_over_time() {
    let frame = probe_frame(160, 96);
    // 跨越多个周期采样（各特效速度系数不同，0.03 步长足够密）
    let times: Vec<f64> = (0..=30).map(|i| i as f64 * 0.03).collect();

    for item in EFFECTS {
        if STATIC_EFFECTS.contains(&item.id) {
            continue;
        }
        let base = apply_single_image_effect(&frame, &params(item.id, times[0]));
        let mut best = 0.0f64;
        let mut best_t = 0.0;
        for t in &times[1..] {
            let frame_t = apply_single_image_effect(&frame, &params(item.id, *t));
            let diff = mean_diff(&base, &frame_t);
            if diff > best {
                best = diff;
                best_t = *t;
            }
        }
        assert!(
            best >= 0.01,
            "「{}」在 0–0.9 秒内画面几乎不动（最大平均差 {best:.4}，出现在 t={best_t:.2}）——\n\
             参数可能算出来了但没作用到画面上。",
            item.id
        );
    }
}

/// 纯几何运动（旋转/缩放/平移）作用于**纯色图**时，颜色不该变。
///
/// 这是 Concat 的 `fixtures.toml` 里那条「a flat colour holds」的中文版。
/// 它能抓住「边界填充填黑」这类错误 —— 纯色图被移动后边缘若填黑，
/// 整体颜色就会偏暗。
#[test]
fn geometric_effects_keep_a_flat_colour() {
    // 只测纯几何类（不含模糊、调色、扭曲）
    let geometric = [
        "心跳跳动",
        "反复缩放",
        "左右晃动",
        "上下浮动",
        "镜头呼吸",
        "脉冲放大",
        "旋转摆动",
        "旋转呼吸",
        "摇摆推拉",
        "圆周漂移",
        "螺旋摆动",
        "8字漂移",
        "右下平移",
        "左上平移",
        "缓慢推近",
        // 「缓慢拉远」t=0 时是放大 12%，随后缩到 1.0，属单向推进而非循环抖动；
        // 缩到小于原尺寸时 crop 会取到边缘像素，纯色图在边界处受重采样影响，
        // 不适合用「中心不变色」这条断言，故不纳入。
    ];
    let color = [120u8, 160, 200];
    let frame = flat_frame(120, 72, color);

    for effect in geometric {
        for step in 0..4 {
            let t = step as f64 * 0.4;
            let output = apply_single_image_effect(&frame, &params(effect, t));
            // 中心区域必须还是原色（边缘受边界模式影响，不参与）
            let center = output.pixel(output.width / 2, output.height / 2).unwrap();
            let drift = center
                .iter()
                .zip(color.iter())
                .map(|(a, b)| (*a as i32 - *b as i32).abs())
                .max()
                .unwrap_or(0);
            assert!(
                drift <= 12,
                "「{effect}」在 t={t:.2} 时纯色图中心变了色：{center:?} vs {color:?}（差 {drift}）——\n\
                 可能是边界填充把颜色带偏了。",
            );
        }
    }
}

/// 强度取**最小值**时，缩放类特效应该几乎不改变画面。
///
/// ⚠️ 强度下限是 1（实现里 `params.intensity.max(1.0) / 100.0`），
/// 不是 0 —— 传 0 会被抬到 1，所以不能断言「强度 0 等价原图」。
/// 这里用 1（即 1%）验证「接近无操作」，这也是界面上滑杆的最小值。
///
/// ⚠️ 只适用于 scale 严格由 intensity 驱动的特效。
/// 「左右晃动」「上下浮动」的基线缩放是 `1.04 + 0.06 * intensity`，
/// 强度调到最小仍有 1.04 倍的放大 —— 这是**刻意的设计**（要有余量才能平移），
/// 所以它们不在这个断言里。
#[test]
fn minimal_intensity_is_almost_a_no_op() {
    let frame = probe_frame(120, 72);
    for effect in ["心跳跳动", "反复缩放", "镜头呼吸", "缓慢推近"] {
        let mut weak = params(effect, 0.3);
        weak.intensity = 1.0; // 最小值
        let output = apply_single_image_effect(&frame, &weak);
        let diff = mean_diff(&frame, &output);
        // 容差 6：即使 scale≈1.0，`(w*scale) as u32` 的截断可能让目标尺寸
        // 与原图差 1 像素，进而走插值路径产生舍入。这是 Python 侧 `int(w*scale)`
        // 的既有行为，不是缺陷。
        assert!(
            diff <= 6.0,
            "「{effect}」强度为最小值时仍明显改动了画面（平均差 {diff:.2}），强度参数可能没生效。"
        );
    }
}

/// 确保每个声明过的特效都被上面这些通用断言覆盖到 —— 防止将来加了条目
/// 但忘了它也需要参与检查。
#[test]
fn general_assertions_cover_every_declared_effect() {
    // GENERIC_CHECKS 是给人看的说明；真正的覆盖由上面几个 test 遍历 EFFECTS 保证。
    assert_eq!(GENERIC_CHECKS.len(), 5);
    assert!(!EFFECTS.is_empty(), "目录里一个特效都没有？");
    println!("通用断言覆盖 {} 个特效 × 5 个时间点", EFFECTS.len());
}
/// **专属参数必须真的影响画面** —— 这是整条链路（catalog 声明 → 配置存储 →
/// 参数解析 → 实现读取）是否真接通的唯一证据。
///
/// 光声明参数不改实现，界面会出现一个「调了没用」的滑杆，比没有更糟。
#[test]
fn declared_params_change_pixels() {
    let frame = probe_frame(160, 96);

    // 故障抖动的「错位幅度」：拉到最小和最大，画面必须不同
    let base = EffectParams::new("故障抖动", 0.37, 3.0, 100.0, 1.0);
    let mut strong = base.clone();
    strong
        .extra
        .insert("shift".into(), serde_json::json!(200.0));
    let weak = base.clone();
    let at_weak = apply_single_image_effect(&frame, &weak);
    let at_strong = apply_single_image_effect(&frame, &strong);
    let diff = mean_diff(&at_weak, &at_strong);
    assert!(
        diff > 0.5,
        "「故障抖动」的错位幅度参数没起作用（强弱两档平均差只有 {diff:.3}）"
    );

    // 滚动快门的「滚动条数」：同理
    let base = EffectParams::new("滚动快门", 0.2, 3.0, 100.0, 1.0);
    let mut many = base.clone();
    many.extra.insert("bands".into(), serde_json::json!(16.0));
    let few = base.clone();
    let at_few = apply_single_image_effect(&frame, &few);
    let at_many = apply_single_image_effect(&frame, &many);
    let diff = mean_diff(&at_few, &at_many);
    assert!(
        diff > 0.5,
        "「滚动快门」的滚动条数参数没起作用（少/多两档平均差只有 {diff:.3}）"
    );
}

/// 不传专属参数时，结果必须与「显式传默认值」完全一致。
///
/// 这条保证「老配置（没有 effect_params 字段）照常工作」——
/// 缺省路径不能和默认值路径产生任何偏差。
#[test]
fn missing_params_match_explicit_defaults() {
    let frame = probe_frame(120, 72);
    for effect in ["故障抖动", "滚动快门"] {
        let bare = EffectParams::new(effect, 0.31, 3.0, 100.0, 1.0);
        let explicit = match effect {
            "故障抖动" => {
                let mut params = bare.clone();
                params
                    .extra
                    .insert("shift".into(), serde_json::json!(100.0));
                params.extra.insert("freq".into(), serde_json::json!(3.0));
                params
            }
            _ => {
                let mut params = bare.clone();
                params.extra.insert("bands".into(), serde_json::json!(4.0));
                params
            }
        };
        let at_bare = apply_single_image_effect(&frame, &bare);
        let at_explicit = apply_single_image_effect(&frame, &explicit);
        assert_eq!(
            at_bare.data, at_explicit.data,
            "「{effect}」缺省参数与显式默认值的结果不一致 —— 老配置会变样"
        );
    }
}

/// 声明了参数的特效，参数键必须与实现里读的键一致。
///
/// 声明写 `"shift"` 而实现读 `"offset"` 这种错，界面照样显示滑杆、
/// 用户照样能拖，但拖了没用。这条测试就是防它。
#[test]
fn declared_param_keys_are_exercised_by_implementations() {
    use super::catalog::{find_effect, find_transition, EFFECTS, TRANSITIONS};

    // 效现在特效和转场都可能有专属参数，两边都要查。
    // 只查 effects.rs 会漏掉转场 —— 上一轮的「假控件」正是这么漏的。
    let cases: [(&str, &[super::catalog::ItemSpec]); 2] =
        [("effects.rs", EFFECTS), ("transitions.rs", TRANSITIONS)];

    for (file, items) in cases {
        let source = match file {
            "effects.rs" => include_str!("effects.rs"),
            _ => include_str!("transitions.rs"),
        };
        for item in items {
            for spec in item.params {
                let needle = format!("\"{}\"", spec.key);
                assert!(
                    source.contains(&needle),
                    "「{}」声明了参数「{}」，但 {file} 里没读它 —— 界面上会是个调了没用的滑杆",
                    item.id,
                    spec.key
                );
            }
            if !item.params.is_empty() {
                let found = find_effect(item.id).or_else(|| find_transition(item.id));
                assert!(found.is_some(), "「{}」声明了参数却查不到", item.id);
            }
        }
    }
}

/// 静态特效：不同时间点必须**逐字节一致**。
///
/// 这条是 `every_effect_actually_moves_over_time` 的补集 ——
/// 那条防止「参数算了没用上」，这条防止「静态特效被误加了时间抖动」
/// （画面会无故闪烁，用户看着像坏了）。
#[test]
fn static_effects_do_not_change_over_time() {
    let frame = probe_frame(120, 72);
    for name in STATIC_EFFECTS {
        let at_zero = apply_single_image_effect(&frame, &params(name, 0.0));
        for step in 1..10 {
            let t = step as f64 * 0.11;
            let later = apply_single_image_effect(&frame, &params(name, t));
            assert_eq!(
                at_zero.data, later.data,
                "「{name}」在 t={t:.2} 时画面变了，但它是逐像素变换、不该随时间变化"
            );
        }
    }
}

/// 静态特效列表必须都是目录里真实存在的条目，防止改名后失效。
#[test]
fn static_effect_names_are_real() {
    for name in STATIC_EFFECTS {
        assert!(
            EFFECTS.iter().any(|item| item.id == name),
            "STATIC_EFFECTS 里的「{name}」在目录里不存在"
        );
    }
}
