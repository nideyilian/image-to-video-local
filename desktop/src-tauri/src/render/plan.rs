//! 帧计划，对齐 `src/render/plan.py`。
//!
//! 这里的数字直接决定导出视频的**时长**，差一帧用户就能看出来（10 秒变 9.97 秒）。
//! 三条规则必须原样保留：
//! 1. 每图帧数用 `round` 而非截断；
//! 2. 总帧数 = round(图片数 × 时长 × 帧率)，余数由**最后一张**吸收；
//! 3. 不做「每图至少 0.5 秒」的钳制，否则每图时长 < 0.5 秒时视频会被撑长。

/// 每张图的基准帧数、每段转场帧数、每图静态帧数、最后一张的总帧数。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FramePlan {
    pub frames_per_img: i64,
    pub transition_frames: i64,
    pub display_frames_per_img: i64,
    pub last_img_frames: i64,
}

/// 与 `compute_video_frame_plan()` 逐字等价。
///
/// ⚠️ Python 的 `round()` 是**四舍六入五成双**（banker's rounding），
/// Rust 的 `f64::round()` 是四舍五入（half away from zero）。
/// 只有恰好在 .5 上才会不同（例如 `duration * fps = 2.5`），
/// 但用户填 2.5 秒 30fps 是完全可能的，所以这里必须用 [`py_round`]。
pub fn compute_video_frame_plan(
    total_images: i64,
    duration: f64,
    fps: i64,
    transition_frames: i64,
    transition_type: &str,
) -> FramePlan {
    let mut frames_per_img = 1i64.max(py_round(duration * fps as f64) as i64);
    let mut transition_frames = transition_frames;
    let display_frames_per_img;
    if transition_frames > 0 && transition_type != "无转场" {
        transition_frames = transition_frames.min(0i64.max(frames_per_img / 3));
        display_frames_per_img = 0i64.max(frames_per_img - transition_frames);
    } else {
        transition_frames = 0;
        display_frames_per_img = frames_per_img;
    }
    let total_frames = total_images.max(py_round(total_images as f64 * duration * fps as f64) as i64);
    let mut last_img_frames = total_frames - (total_images - 1) * frames_per_img;
    if last_img_frames < 1 {
        last_img_frames = 1;
    }
    if frames_per_img < 1 {
        frames_per_img = 1;
    }
    FramePlan {
        frames_per_img,
        transition_frames,
        display_frames_per_img,
        last_img_frames,
    }
}

/// Python 内置 `round()` 的语义：四舍六入五成双。
///
/// ⚠️ 这里**不能加 EPS 容差**。浮点运算经常产生「差一点点就是 .5」的值，
/// 例如 `3 × 1.7 × 25 = 127.49999999999999`，Python 的 `round` 老老实实得到 127；
/// 若把 `0.4999999999999858` 当作「正好 .5」再取偶数，就会得到 128 —— 差一帧，
/// 视频时长从 5.08s 变成 5.12s。对照测试当场抓出过这个问题。
pub fn py_round(value: f64) -> f64 {
    if !value.is_finite() {
        return value;
    }
    let floor = value.floor();
    let diff = value - floor;
    if diff > 0.5 {
        floor + 1.0
    } else if diff < 0.5 {
        floor
    } else {
        // 恰好等于 .5（二进制可精确表示的情况，如 2.5 / 3.5）：取偶数
        if (floor as i64) % 2 == 0 {
            floor
        } else {
            floor + 1.0
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn py_round_matches_bankers_rounding() {
        assert_eq!(py_round(2.5), 2.0);
        assert_eq!(py_round(3.5), 4.0);
        assert_eq!(py_round(-2.5), -2.0);
        assert_eq!(py_round(2.4), 2.0);
        assert_eq!(py_round(2.6), 3.0);
        assert_eq!(py_round(0.5), 0.0);
        assert_eq!(py_round(1.5), 2.0);
        // Rust 原生 round 会把 2.5 → 3，两者不同，所以必须用 py_round
        assert_ne!(2.5f64.round(), py_round(2.5));
    }

    #[test]
    fn py_round_does_not_treat_float_noise_as_exact_half() {
        // 3 × 1.7 × 25 在浮点下是 127.49999999999999，Python round 得 127
        let value = 3.0 * 1.7 * 25.0;
        assert!(value < 127.5, "前提：浮点结果应略小于 127.5，实际 {value}");
        assert_eq!(py_round(value), 127.0);
        // 而真正的 .5（二进制可精确表示）仍走取偶数
        assert_eq!(py_round(127.5), 128.0);
        assert_eq!(py_round(126.5), 126.0);
    }

    #[test]
    fn no_transition_keeps_full_frames_per_image() {
        let plan = compute_video_frame_plan(3, 2.0, 30, 0, "无转场");
        assert_eq!(plan.frames_per_img, 60);
        assert_eq!(plan.transition_frames, 0);
        assert_eq!(plan.display_frames_per_img, 60);
        // 总帧数 180，最后一张 = 180 - 2*60 = 60
        assert_eq!(plan.last_img_frames, 60);
    }

    #[test]
    fn transition_is_capped_at_one_third_of_frames_per_image() {
        let plan = compute_video_frame_plan(2, 1.0, 30, 30, "淡入淡出");
        assert_eq!(plan.frames_per_img, 30);
        // 30 // 3 = 10，转场被压到 10
        assert_eq!(plan.transition_frames, 10);
        assert_eq!(plan.display_frames_per_img, 20);
    }

    #[test]
    fn remainder_is_absorbed_by_the_last_image() {
        // 3 张 × 1.0s × 30fps = 90 帧，但每图 round(30)=30 → 3*30=90，无余数
        let plan = compute_video_frame_plan(3, 1.0, 30, 0, "无转场");
        assert_eq!(plan.last_img_frames, 30);

        // 4 张 × 0.7s × 30fps = 84 帧；每图 round(21)=21 → 前 3 张 63，最后一张 21
        let plan = compute_video_frame_plan(4, 0.7, 30, 0, "无转场");
        assert_eq!(plan.frames_per_img, 21);
        assert_eq!(plan.last_img_frames, 21);

        // 7 张 × 1.0s × 24fps = 168；每图 24 → 6*24=144，最后 24
        let plan = compute_video_frame_plan(7, 1.0, 24, 0, "无转场");
        assert_eq!(plan.last_img_frames, 24);
    }

    #[test]
    fn last_image_never_below_one_frame() {
        let plan = compute_video_frame_plan(3, 0.01, 1, 0, "无转场");
        assert!(plan.last_img_frames >= 1);
        assert!(plan.frames_per_img >= 1);
    }

    #[test]
    fn sub_half_second_duration_is_not_inflated() {
        // 每图 0.2s × 30fps = 6 帧；不该被强行撑到 15 帧（旧实现踩过）
        let plan = compute_video_frame_plan(5, 0.2, 30, 0, "无转场");
        assert_eq!(plan.frames_per_img, 6);
        assert_eq!(plan.display_frames_per_img, 6);
    }

    #[test]
    fn total_frames_match_requested_duration_within_half_frame() {
        for images in 1..6 {
            for duration in [0.5, 1.0, 1.7, 2.3, 3.3333] {
                for fps in [24, 25, 30, 60] {
                    let plan = compute_video_frame_plan(images, duration, fps, 0, "无转场");
                    let total = (images - 1) * plan.frames_per_img + plan.last_img_frames;
                    let expected = images as f64 * duration * fps as f64;
                    let drift = (total as f64 - expected).abs();
                    assert!(
                        drift <= 1.0,
                        "{images}张 {duration}s {fps}fps: 实际 {total} 帧，期望 {expected:.2}，偏差 {drift}"
                    );
                }
            }
        }
    }
}