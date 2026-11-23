//! 帧脚本：把「整段视频会产出哪些帧」提前算成一份**纯数据清单**，再交给执行器去画。
//!
//! ## 为什么要拆这一层
//!
//! 原来 `compositor::create_video` 一个函数里同时做了四件事：
//! 1. 算帧计划（每图几帧、转场几帧）
//! 2. 遍历图片、决定「第 N 帧该用第几张图的第几个时间点」
//! 3. 真的做像素运算（缩放、特效、转场）
//! 4. 往 ffmpeg 管道里写
//!
//! 前两件是**纯计算**，不碰像素也不做 IO。混在一起导致：
//! - 想验证「帧序对不对」（比如转场是不是接在正确位置）必须真的跑一遍渲染
//! - 想改帧策略（比如加淡入淡出）得在像素代码中间改
//! - 帧数算错时（10 秒变 9.97 秒）很难定位是哪一步错
//!
//! 拆出来之后，`plan::frame_script` 只回答「有哪些帧、每帧用哪张图、什么参数」，
//! 可以单独测试，而且**改它不影响像素代码，改像素代码也不影响它**。
//!
//! ## 这个设计来自 Concat
//!
//! Concat 的 `concat-render` 把渲染分成 `plan`（算什么）和 `compositor`（怎么画），
//! 它的文档说得很清楚：`plan_frame` 不碰像素、不做 IO，所以「快、可精确测试、
//! 对 CPU 和 GPU 后端输出完全一致」。我们只有 CPU 一个后端，但前两个好处照样成立。
//!
//! 差异：Concat 是**询问制**（给一个时刻，回答那一帧是什么），因为它的预览要
//! 随机跳转。我们是**批处理**（一次性产出整段），所以用「脚本清单」而不是
//! 「逐时刻询问」更合适 —— 这也说明抄设计要按自己的场景改。

use super::effects::EffectParams;

/// 这一帧从哪来。
#[derive(Debug, Clone, PartialEq)]
pub enum FrameSource {
    /// 第 `image_index` 张图的静态帧，第 `frame_in_image` 次输出同一幅画面（无特效时）。
    Still {
        image_index: usize,
        frame_in_image: i64,
    },
    /// 第 `image_index` 张图叠加特效，时间点是 `params.time_sec`。
    Effect {
        image_index: usize,
        frame_in_image: i64,
        params: EffectParams,
    },
    /// 第 `image_index` 到 `image_index + 1` 之间的转场，进度 `step / total`。
    Transition {
        image_index: usize,
        step: i64,
        total: i64,
    },
}

impl FrameSource {
    /// 这一帧需要解码哪张图（执行器据此决定是否复用上一帧的解码结果）。
    pub fn primary_image(&self) -> usize {
        match self {
            FrameSource::Still { image_index, .. }
            | FrameSource::Effect { image_index, .. }
            | FrameSource::Transition { image_index, .. } => *image_index,
        }
    }

    /// 转场还需要下一张图。
    pub fn needs_next_image(&self) -> bool {
        matches!(self, FrameSource::Transition { .. })
    }
}

/// 一帧的完整描述。
#[derive(Debug, Clone, PartialEq)]
pub struct FrameStep {
    /// 在整段视频里的序号，从 0 开始。
    pub index: i64,
    pub source: FrameSource,
}

/// 整段视频的帧脚本。
#[derive(Debug, Clone)]
pub struct FrameScript {
    pub steps: Vec<FrameStep>,
    /// 每张图在脚本里第一次出现的位置，执行器可据此预解码。
    pub image_frame_counts: Vec<i64>,
}

impl FrameScript {
    pub fn len(&self) -> usize {
        self.steps.len()
    }

    pub fn is_empty(&self) -> bool {
        self.steps.is_empty()
    }
}

/// 帧计划的输入参数（与 `plan::compute_video_frame_plan` 的入参一致）。
#[derive(Debug, Clone)]
pub struct ScriptOptions {
    pub total_images: usize,
    pub frames_per_img: i64,
    pub display_frames_per_img: i64,
    pub last_img_frames: i64,
    pub transition_frames: i64,
    pub fps: i64,
    /// 特效开关。关闭时静态帧不产生 `Effect`。
    pub effect_enabled: bool,
    pub effect_type: String,
    pub effect_intensity: f64,
    pub effect_speed: f64,
    /// 该特效的专属参数（来自配置，由 `effect_params::resolve` 算出）。
    /// 空表表示没设过，实现代码会用各自的默认值。
    pub effect_extra: serde_json::Map<String, serde_json::Value>,
    /// 是否有转场（除了 `transition_frames > 0`，还要看类型不是「无转场」）。
    pub transition_active: bool,
}

/// 算出整段视频的帧脚本。
///
/// **纯函数**：同样的输入永远得到同样的输出，不碰像素、不做 IO、不看时间。
/// 帧数合计必须等于 `(n-1) * frames_per_img + last_img_frames`，
/// 这个等式由 `script_frame_count_matches_plan` 测试守着。
pub fn build_script(options: &ScriptOptions) -> FrameScript {
    let mut steps = Vec::new();
    let mut image_frame_counts = vec![0i64; options.total_images];

    for (image_index, count) in image_frame_counts.iter_mut().enumerate() {
        if options.total_images == 0 {
            break;
        }
        let is_last = image_index == options.total_images - 1;
        let static_frames = if is_last {
            options.last_img_frames
        } else {
            options.display_frames_per_img
        };
        *count = static_frames;

        if static_frames > 0 {
            if options.effect_enabled {
                // 逐帧算特效：时间点从 0 开始，每帧推进 1/fps
                let effect_frames = static_frames.max(1);
                let duration_sec = (effect_frames as f64 / options.fps.max(1) as f64).max(0.001);
                for frame_in_image in 0..effect_frames {
                    let index = steps.len() as i64;
                    steps.push(FrameStep {
                        index,
                        source: FrameSource::Effect {
                            image_index,
                            frame_in_image,
                            params: EffectParams {
                                effect_type: options.effect_type.clone(),
                                time_sec: frame_in_image as f64 / options.fps.max(1) as f64,
                                duration_sec,
                                intensity: options.effect_intensity,
                                speed: options.effect_speed,
                                extra: options.effect_extra.clone(),
                            },
                        },
                    });
                }
            } else {
                for frame_in_image in 0..static_frames {
                    let index = steps.len() as i64;
                    steps.push(FrameStep {
                        index,
                        source: FrameSource::Still {
                            image_index,
                            frame_in_image,
                        },
                    });
                }
            }
        }

        // 转场（最后一张之后没有）
        if !is_last && options.transition_frames > 0 && options.transition_active {
            for step in 0..options.transition_frames {
                let index = steps.len() as i64;
                steps.push(FrameStep {
                    index,
                    source: FrameSource::Transition {
                        image_index,
                        step,
                        total: options.transition_frames,
                    },
                });
            }
        }
    }

    FrameScript {
        steps,
        image_frame_counts,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn base_options() -> ScriptOptions {
        ScriptOptions {
            total_images: 3,
            frames_per_img: 90,
            display_frames_per_img: 80,
            last_img_frames: 90,
            transition_frames: 10,
            fps: 30,
            effect_enabled: false,
            effect_type: "无特效".to_string(),
            effect_intensity: 100.0,
            effect_speed: 1.0,
            effect_extra: serde_json::Map::new(),
            transition_active: true,
        }
    }

    /// 帧总数必须等于 `(n-1) * frames_per_img + last_img_frames`。
    /// 这是「时长不跑偏」的根本保证（10 秒不能变 9.97 秒）。
    #[test]
    fn script_frame_count_matches_plan() {
        for (images, frames, display, last) in [
            (3usize, 90i64, 80i64, 90i64),
            (1, 150, 150, 150),
            (5, 60, 50, 60),
            (2, 30, 20, 30),
        ] {
            let options = ScriptOptions {
                total_images: images,
                frames_per_img: frames,
                display_frames_per_img: display,
                last_img_frames: last,
                transition_frames: frames - display,
                ..base_options()
            };
            let script = build_script(&options);
            let expected = (images as i64 - 1) * frames + last;
            assert_eq!(
                script.len() as i64,
                expected,
                "images={images} frames={frames} display={display} last={last} 时帧数不对"
            );
        }
    }

    /// 每张图的静态帧数要如实记录，执行器据此知道该图会产出多少帧。
    #[test]
    fn per_image_counts_are_recorded() {
        let script = build_script(&base_options());
        assert_eq!(script.image_frame_counts, vec![80, 80, 90]);
    }

    /// 每帧的 index 必须连续且从 0 开始。
    #[test]
    fn indices_are_sequential() {
        let script = build_script(&base_options());
        for (position, step) in script.steps.iter().enumerate() {
            assert_eq!(step.index, position as i64, "第 {position} 帧的 index 不对");
        }
    }

    /// 转场必须出现在「前一张图之后、下一张图之前」，且最后一张之后不能有。
    #[test]
    fn transitions_sit_between_images() {
        let script = build_script(&base_options());
        let mut seen = Vec::new();
        for step in &script.steps {
            if let FrameSource::Transition {
                image_index,
                step: step_in_transition,
                total,
            } = &step.source
            {
                assert!(*image_index < 2, "最后一张图之后不该有转场");
                assert_eq!(*total, 10);
                assert!(*step_in_transition < *total);
                seen.push((*image_index, *step_in_transition));
            }
        }
        assert_eq!(seen.len(), 20, "3 张图应该有 2 段转场 × 10 帧");
    }

    /// 开启特效时，静态帧变成 Effect，时间点按 1/fps 递增。
    #[test]
    fn effect_frames_carry_increasing_time() {
        let options = ScriptOptions {
            effect_enabled: true,
            effect_type: "镜头呼吸".to_string(),
            ..base_options()
        };
        let script = build_script(&options);
        let mut times = Vec::new();
        for step in &script.steps {
            if let FrameSource::Effect {
                frame_in_image,
                params,
                ..
            } = &step.source
            {
                if *frame_in_image < 3 {
                    times.push(params.time_sec);
                }
            }
        }
        assert!(times.len() >= 3);
        let expected = [0.0, 1.0 / 30.0, 2.0 / 30.0];
        for (actual, want) in times.iter().zip(expected.iter()) {
            assert!(
                (actual - want).abs() < 1e-9,
                "时间点不对：{actual} vs {want}"
            );
        }
    }

    /// 关闭特效时不产生 Effect 帧，全部是 Still。
    #[test]
    fn no_effect_means_all_stills() {
        let script = build_script(&base_options());
        assert!(script
            .steps
            .iter()
            .all(|step| !matches!(step.source, FrameSource::Effect { .. })));
    }

    /// 同样的输入必须得到逐字段相同的脚本 —— 纯函数的基本要求。
    ///
    /// 这条能挡住「脚本里混进了时间/随机/全局状态」这类问题。
    #[test]
    fn script_is_deterministic() {
        let options = ScriptOptions {
            effect_enabled: true,
            effect_type: "心跳跳动".to_string(),
            ..base_options()
        };
        let first = build_script(&options);
        let second = build_script(&options);
        assert_eq!(first.steps, second.steps, "两次构建的脚本不一致");
        assert_eq!(first.image_frame_counts, second.image_frame_counts);
    }

    /// 一张图时没有转场（前面后面都没有）。
    #[test]
    fn single_image_has_no_transition() {
        let options = ScriptOptions {
            total_images: 1,
            last_img_frames: 150,
            ..base_options()
        };
        let script = build_script(&options);
        assert_eq!(script.len(), 150);
        assert!(script
            .steps
            .iter()
            .all(|step| !step.source.needs_next_image()));
    }

    /// 无转场类型时，即使 transition_frames > 0 也不该产出转场帧。
    #[test]
    fn inactive_transition_produces_nothing() {
        let options = ScriptOptions {
            transition_active: false,
            ..base_options()
        };
        let script = build_script(&options);
        assert_eq!(script.len(), 80 + 80 + 90, "不该有转场帧");
    }
}
