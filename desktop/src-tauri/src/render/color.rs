//! 调色：亮度、对比度、饱和度、色温。
//!
//! ## 为什么单独一个文件
//!
//! 现有的 `effects.rs` 里 43 个特效**全是运动和变形**（缩放、平移、旋转、
//! 扭曲、鱼眼、水波）。整个项目之前没有「调整画面色调」这一层。
//!
//! 调色和特效是两件事：
//! - 特效随时间变化（第 N 帧的画面不同）
//! - 调色对整段一致（每一帧套同一套参数）
//!
//! 所以放在特效**之后**串一道，而不是混进 `effects.rs` 的 match 里。
//!
//! ## 与参考项目的关系
//!
//! Concat 的 100+ 「特效」里六成以上是调色预设（cyberpunk / bronze / autumn
//! 这类，一个风格一个包）。它走 GPU 着色器，我们是 CPU。
//!
//! 这里**没有照抄它的预设**（AGPL-3.0，而且预设是艺术选择不是技术），
//! 而是把它的底层算子拆出来：它那几十种 preset 本质上都是
//! 「亮度/对比度/饱和度/色温/曲线」的不同参数组合。
//! 我们做这 4 个基础算子，用户可以自己组合出风格 —— 比给 60 个固定
//! 预设更灵活，也不用替别人的审美背书。
//!
//! ## 实现要点
//!
//! - 全部在 **8 位 sRGB 空间**做（不做线性化）。原因：用户的预期是
//!   「拖滑杆立刻看到变化」，线性化会让 50% 亮度不等于视觉上的中灰。
//!   这也与 Concat 的 `space = "display"` 一致。
//! - 顺序固定：亮度 → 对比度 → 饱和度 → 色温。顺序会改变结果，
//!   所以写死在这里，不暴露给用户。
//! - 中灰是 128（8 位），对比度围绕 128 旋转。

use super::pixels::BgrFrame;

/// 调色参数。所有字段都是「0 = 不变」的偏移量。
///
/// 这样设计的好处：缺省值就是恒等变换，`Default` 可以直接跳过整道工序
/// （见 [`ColorGrade::is_identity`]），不改变任何既有输出。
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ColorGrade {
    /// 亮度偏移，范围 -100 ~ 100，映射到 ±64 个色阶。
    pub brightness: f64,
    /// 对比度，范围 -100 ~ 100。负值压平，正值拉大。
    pub contrast: f64,
    /// 饱和度，范围 -100 ~ 100。-100 是灰度，+100 是双倍饱和。
    pub saturation: f64,
    /// 色温，范围 -100 ~ 100。负值偏蓝，正值偏黄。
    pub temperature: f64,
}

impl Default for ColorGrade {
    fn default() -> Self {
        ColorGrade {
            brightness: 0.0,
            contrast: 0.0,
            saturation: 0.0,
            temperature: 0.0,
        }
    }
}

impl ColorGrade {
    /// 四个参数都是 0 时，这道工序可以整个跳过。
    ///
    /// 这个判断很重要：绝大多数用户不会调色，走这条路意味着**零开销**，
    /// 也就不可能改变既有导出的画面。
    pub fn is_identity(&self) -> bool {
        self.brightness == 0.0
            && self.contrast == 0.0
            && self.saturation == 0.0
            && self.temperature == 0.0
    }

    /// 从配置读四个参数，缺省全 0（即不调色）。
    pub fn from_config(config: &dyn super::audio::RenderConfig) -> Self {
        let read = |key: &str| config.f64_of(key, 0.0).clamp(-100.0, 100.0);
        ColorGrade {
            brightness: read("color_brightness"),
            contrast: read("color_contrast"),
            saturation: read("color_saturation"),
            temperature: read("color_temperature"),
        }
    }
}

/// 把调色应用到一帧。
///
/// 参数全是恒等时直接返回 `None`，让调用方跳过 —— 避免白做一次全图扫描。
pub fn apply(frame: &BgrFrame, grade: &ColorGrade) -> Option<BgrFrame> {
    if grade.is_identity() {
        return None;
    }

    // 预计算成乘加形式，避免每像素重复算
    let brightness_offset = grade.brightness / 100.0 * 64.0;

    // 对比度：以 128 为中心缩放。公式 (v-128)*k+128
    // k 从 1.0（不变）到 0.0（全灰）到 2.0（双倍对比）
    let contrast_k = 1.0 + grade.contrast / 100.0;

    // 饱和度：向灰度插值。0 = 灰度，1 = 原样，2 = 双倍
    let saturation_k = 1.0 + grade.saturation / 100.0;

    // 色温：正值加暖（R↑ B↓），负值加冷。幅度比亮度小，避免一拖就发黄
    let warm = grade.temperature / 100.0 * 40.0;

    let mut out = frame.clone();
    for pixel in out.data.chunks_exact_mut(3) {
        let mut r = pixel[2] as f64;
        let mut g = pixel[1] as f64;
        let mut b = pixel[0] as f64;

        // 1. 亮度
        r += brightness_offset;
        g += brightness_offset;
        b += brightness_offset;

        // 2. 对比度（围绕 128 缩放）
        r = (r - 128.0) * contrast_k + 128.0;
        g = (g - 128.0) * contrast_k + 128.0;
        b = (b - 128.0) * contrast_k + 128.0;

        // 3. 饱和度（向该像素自己的灰度靠拢或远离）
        //    用 Rec.601 权重，与 `to_gray` 一致，避免两处口径不同
        let luma = 0.299 * r + 0.587 * g + 0.114 * b;
        r = luma + (r - luma) * saturation_k;
        g = luma + (g - luma) * saturation_k;
        b = luma + (b - luma) * saturation_k;

        // 4. 色温（只动红蓝，绿保持 —— 绿通道主导亮度，动它容易整体偏色）
        r += warm;
        b -= warm;

        pixel[2] = r.clamp(0.0, 255.0).round() as u8;
        pixel[1] = g.clamp(0.0, 255.0).round() as u8;
        pixel[0] = b.clamp(0.0, 255.0).round() as u8;
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn solid(color: [u8; 3]) -> BgrFrame {
        let mut frame = BgrFrame::new(8, 8);
        for y in 0..8 {
            for x in 0..8 {
                frame.set_pixel(x, y, color);
            }
        }
        frame
    }

    /// 全 0 参数必须是恒等 —— 这样既能跳过工序，也保证老配置不变。
    #[test]
    fn identity_returns_none() {
        let frame = solid([100, 150, 200]);
        assert!(apply(&frame, &ColorGrade::default()).is_none());
    }

    #[test]
    fn identity_check_covers_every_field() {
        let cases = [
            ColorGrade {
                brightness: 1.0,
                ..Default::default()
            },
            ColorGrade {
                contrast: 1.0,
                ..Default::default()
            },
            ColorGrade {
                saturation: 1.0,
                ..Default::default()
            },
            ColorGrade {
                temperature: 1.0,
                ..Default::default()
            },
        ];
        for grade in cases {
            assert!(!grade.is_identity(), "漏判了某个参数：{grade:?}");
        }
    }

    /// 亮度只管明暗，不该改变色相比例。
    /// 用中灰测试：加亮后 RGB 三通道应等量增加。
    #[test]
    fn brightness_is_uniform_shift() {
        let frame = solid([100, 100, 100]);
        let grade = ColorGrade {
            brightness: 50.0,
            ..Default::default()
        };
        let out = apply(&frame, &grade).expect("应该处理");
        let pixel = out.pixel(0, 0).unwrap();
        // 50% → +32 色阶
        for channel in pixel {
            assert!(
                (channel as i32 - 132).abs() <= 1,
                "中灰加亮后应约为 132，实际 {pixel:?}"
            );
        }
    }

    /// 饱和度 -100 应该输出灰度：三通道相等。
    #[test]
    fn full_desaturation_makes_gray() {
        let frame = solid([200, 100, 50]);
        let grade = ColorGrade {
            saturation: -100.0,
            ..Default::default()
        };
        let out = apply(&frame, &grade).expect("应该处理");
        let [b, g, r] = out.pixel(0, 0).unwrap();
        let spread = (r as i32 - g as i32).abs().max((g as i32 - b as i32).abs());
        assert!(
            spread <= 1,
            "灰度图三通道应基本相等，实际 r={r} g={g} b={b}"
        );
    }

    /// 饱和度 +100 应该让颜色更鲜艳：通道间差异变大。
    #[test]
    fn oversaturation_spreads_channels() {
        let frame = solid([150, 100, 50]);
        let before = frame.pixel(0, 0).unwrap();
        let grade = ColorGrade {
            saturation: 100.0,
            ..Default::default()
        };
        let out = apply(&frame, &grade).expect("应该处理");
        let after = out.pixel(0, 0).unwrap();
        let spread = |p: [u8; 3]| {
            (p[2] as i32 - p[1] as i32)
                .abs()
                .max((p[1] as i32 - p[0] as i32).abs())
        };
        assert!(
            spread(after) > spread(before),
            "加饱和后通道差异应变大：{before:?} → {after:?}"
        );
    }

    /// 对比度 +100 让亮部更亮、暗部更暗。
    #[test]
    fn contrast_pushes_extremes() {
        let light = solid([180, 180, 180]);
        let dark = solid([80, 80, 80]);
        let grade = ColorGrade {
            contrast: 100.0,
            ..Default::default()
        };
        let light_out = apply(&light, &grade).unwrap().pixel(0, 0).unwrap()[0];
        let dark_out = apply(&dark, &grade).unwrap().pixel(0, 0).unwrap()[0];
        assert!(light_out > 180, "亮部应更亮，实际 {light_out}");
        assert!(dark_out < 80, "暗部应更暗，实际 {dark_out}");
    }

    /// 对比度 -100 把所有东西压向中灰。
    #[test]
    fn negative_contrast_flattens() {
        let frame = solid([250, 250, 250]);
        let grade = ColorGrade {
            contrast: -100.0,
            ..Default::default()
        };
        let out = apply(&frame, &grade).unwrap().pixel(0, 0).unwrap()[0];
        assert!((out as i32 - 128).abs() <= 2, "应压到中灰，实际 {out}");
    }

    /// 色温正值偏暖：R 升、B 降。
    #[test]
    fn warm_temperature_raises_red_lowers_blue() {
        let frame = solid([128, 128, 128]);
        let grade = ColorGrade {
            temperature: 100.0,
            ..Default::default()
        };
        let [b, _g, r] = apply(&frame, &grade).unwrap().pixel(0, 0).unwrap();
        assert!(r > 128, "暖色应提高红，实际 {r}");
        assert!(b < 128, "暖色应降低蓝，实际 {b}");
    }

    /// 冷色温是暖色的镜像。
    #[test]
    fn cool_temperature_is_opposite() {
        let frame = solid([128, 128, 128]);
        let grade = ColorGrade {
            temperature: -100.0,
            ..Default::default()
        };
        let [b, _g, r] = apply(&frame, &grade).unwrap().pixel(0, 0).unwrap();
        assert!(r < 128, "冷色应降低红，实际 {r}");
        assert!(b > 128, "冷色应提高蓝，实际 {b}");
    }

    /// 输出不能溢出（极端参数下夹取要生效）。
    #[test]
    fn extreme_values_stay_in_range() {
        let frame = solid([5, 250, 120]);
        let grade = ColorGrade {
            brightness: 100.0,
            contrast: 100.0,
            saturation: 100.0,
            temperature: 100.0,
        };
        let out = apply(&frame, &grade).expect("应该处理");
        // 只要不 panic、值都在 0..=255，就说明夹取生效（u8 天然保证）
        assert_eq!(out.data.len(), frame.data.len());
    }

    /// 尺寸必须保持不变 —— 调色不该改变画面几何。
    #[test]
    fn keeps_frame_size() {
        let frame = BgrFrame::new(37, 23);
        let grade = ColorGrade {
            brightness: 20.0,
            ..Default::default()
        };
        let out = apply(&frame, &grade).unwrap();
        assert_eq!((out.width, out.height), (37, 23));
    }
}
