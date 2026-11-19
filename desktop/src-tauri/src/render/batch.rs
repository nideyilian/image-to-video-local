//! 批量导出编排（对齐 `src/render/job.py` 的 `run_batch`）。
//!
//! 这是「让 worker 不再需要 Python」的最后一块：选图 → 逐个视频调用
//! `compositor::create_video` → 进度事件。
//!
//! 三种选图模式的行为差异很大，抄错会静默出不同的视频：
//! - `随机选择`：**首图不重复**（用过的首图不再参与），剩余图随机补齐
//! - `按名称排序`：第 i 个视频取 `[i*n, (i+1)*n)`，不足则少取
//! - `按子文件夹抽取`：每个子文件夹各抽 1 张组成一轮，用 `plan_combinations`
//!   跨视频统一去重（超出组合总数时才重复，且次数摊平）

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use serde_json::{json, Map, Value};

use super::compositor;
use super::transitions;
use crate::engine::config;
use crate::engine::paths;
use crate::engine::scan;
use crate::engine::preview_random;

/// 随机源（SplitMix64，保证同一配置多次导出结果稳定）。
struct Rng(u64);

impl Rng {
    fn new(seed: u64) -> Self {
        Rng(seed)
    }

    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    /// `[0, bound)`
    fn below(&mut self, bound: usize) -> usize {
        if bound == 0 {
            0
        } else {
            (self.next() % bound as u64) as usize
        }
    }

    fn shuffle<T>(&mut self, values: &mut [T]) {
        for index in (1..values.len()).rev() {
            let swap = self.below(index + 1);
            values.swap(index, swap);
        }
    }
}

fn text(config: &Map<String, Value>, key: &str, default: &str) -> String {
    config
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or(default)
        .to_string()
}

fn number(config: &Map<String, Value>, key: &str, default: f64) -> f64 {
    match config.get(key) {
        Some(Value::Number(value)) => value.as_f64().unwrap_or(default),
        Some(Value::String(value)) => value.trim().parse().unwrap_or(default),
        _ => default,
    }
}

fn integer(config: &Map<String, Value>, key: &str, default: i64) -> i64 {
    number(config, key, default as f64) as i64
}

fn flag(config: &Map<String, Value>, key: &str, default: bool) -> bool {
    match config.get(key) {
        Some(Value::Bool(value)) => *value,
        Some(Value::Number(value)) => value.as_f64().unwrap_or(0.0) != 0.0,
        Some(Value::String(value)) => !value.is_empty() && value != "0",
        _ => default,
    }
}

/// `compose_output_filename`：日期前缀 / 首图名 / 自定义前缀 / 序号。
fn compose_output_filename(
    use_date_prefix: bool,
    use_first_image_name: bool,
    first_image_name: &str,
    custom_prefix: &str,
    index: i64,
    video_format: &str,
) -> String {
    let mut parts: Vec<String> = Vec::new();
    if use_date_prefix {
        parts.push(today_stamp());
    }
    // ⚠️ 是 `elif` 不是两个 if：勾了「用首图名」就不再追加自定义前缀，
    // 否则会生成 `img1-测试-1.mp4`（Python 是 `img1-1.mp4`）。
    if use_first_image_name && !first_image_name.trim().is_empty() {
        parts.push(first_image_name.trim().to_string());
    } else if !custom_prefix.trim().is_empty() {
        parts.push(custom_prefix.trim().to_string());
    }
    parts.push(index.to_string());
    format!(
        "{}.{}",
        parts.join("-"),
        video_format.trim_start_matches('.').to_lowercase()
    )
}

/// 今天日期 `YYYYMMDD`（本地时区）。
fn today_stamp() -> String {
    // 与 write_ops 的实现保持一致：用系统本地时间
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_secs() as i64)
        .unwrap_or(0);
    // 简化：直接借用项目的本地时间格式化
    crate::engine::snapshot::now_iso()
        .split(' ')
        .next()
        .unwrap_or("1970-01-01")
        .replace('-', "")
        .to_string()
        + &{
            let _ = now;
            String::new()
        }
}

/// `cycle_images_to_duration`：按总时长把图片循环/截断成整数个时间槽。
fn cycle_images_to_duration(images: &[String], image_duration: f64, total_duration: f64) -> Vec<String> {
    if images.is_empty() {
        return Vec::new();
    }
    let Ok(Some(slots)) = crate::engine::config::timeline_slot_count(image_duration, total_duration)
    else {
        return images.to_vec();
    };
    (0..slots as usize)
        .map(|index| images[index % images.len()].clone())
        .collect()
}

/// `combination_total`：各分组大小之积。
fn combination_total(sizes: &[i64]) -> i64 {
    if sizes.is_empty() || sizes.iter().any(|size| *size <= 0) {
        return 0;
    }
    sizes.iter().product()
}

/// `plan_combinations`：规划互不重复的下标组合。
fn plan_combinations(sizes: &[i64], count: i64, rng: &mut Rng) -> Vec<Vec<usize>> {
    const ENUMERATION_LIMIT: i64 = 50_000;
    let total = combination_total(sizes);
    if total == 0 || count <= 0 {
        return Vec::new();
    }
    if total <= ENUMERATION_LIMIT {
        // 穷举全部组合后整池洗牌，每轮取一段（重复只会跨轮发生，次数摊平）
        let mut pool: Vec<Vec<usize>> = vec![Vec::new()];
        for size in sizes {
            let mut next = Vec::new();
            for prefix in &pool {
                for index in 0..*size as usize {
                    let mut combination = prefix.clone();
                    combination.push(index);
                    next.push(combination);
                }
            }
            pool = next;
        }
        let mut picks: Vec<Vec<usize>> = Vec::new();
        while (picks.len() as i64) < count {
            rng.shuffle(&mut pool);
            let need = (count - picks.len() as i64) as usize;
            picks.extend(pool.iter().take(need).cloned());
        }
        return picks;
    }
    // 池子太大：随机抽取 + 去重
    let mut seen: BTreeSet<Vec<usize>> = BTreeSet::new();
    let mut picks: Vec<Vec<usize>> = Vec::new();
    let mut wasted = 0i64;
    let wasted_limit = count * 64 + 1024;
    while (picks.len() as i64) < count && wasted < wasted_limit {
        let pick: Vec<usize> = sizes.iter().map(|size| rng.below(*size as usize)).collect();
        if !seen.insert(pick.clone()) {
            wasted += 1;
            continue;
        }
        picks.push(pick);
    }
    while (picks.len() as i64) < count {
        picks.push(sizes.iter().map(|size| rng.below(*size as usize)).collect());
    }
    picks
}

/// 一次导出的结果摘要。
pub struct BatchOutcome {
    pub success: usize,
    pub total: i64,
    pub outputs: Vec<String>,
}

/// 跑一批导出。`hooks` 提供日志与取消/暂停回调。
pub fn run_batch(
    raw_config: &Value,
    ffmpeg: &Path,
    hooks: &mut dyn compositor::ComposeHooks,
) -> Result<BatchOutcome, String> {
    let normalized = config::normalize_config(Some(raw_config));
    let config = normalized.as_object().cloned().unwrap_or_default();

    let input_dir = text(&config, "input_dir", "");
    let output_dir = text(&config, "output_dir", "");
    if input_dir.is_empty() {
        return Err("请选择输入目录".to_string());
    }
    if !Path::new(&input_dir).exists() {
        return Err("输入目录不存在".to_string());
    }
    if output_dir.is_empty() {
        return Err("请选择输出目录".to_string());
    }
    std::fs::create_dir_all(&output_dir).map_err(|error| error.to_string())?;

    let num_images = integer(&config, "num_images", 1);
    let video_count = integer(&config, "video_count", 1);
    let selection_mode = text(&config, "image_selection_mode", "随机选择");
    let duration = number(&config, "duration", 3.0);
    let total_duration = number(&config, "total_duration", 0.0);

    // ---- 收集图片 ----
    let mut subfolder_groups: Vec<crate::engine::scan::Group> = Vec::new();
    let all_images: Vec<String> = if selection_mode == "按子文件夹抽取" {
        let scanned = scan::scan_subfolders(&input_dir);
        if !scanned.skipped.is_empty() {
            hooks.log(&format!(
                "以下子文件夹没有可用图片，已跳过：{}",
                scanned.skipped.join("、")
            ));
        }
        subfolder_groups = scanned.groups;
        subfolder_groups
            .iter()
            .flat_map(|group| group.images.clone())
            .collect()
    } else if selection_mode == "按名称排序" {
        scan::scan_images(&input_dir)
    } else {
        // 「随机选择」：先洗牌，后续再按「首图不重复」规则抽
        let mut rng = Rng::new(0xBEEF);
        let mut images = scan::scan_images(&input_dir);
        rng.shuffle(&mut images);
        images
    };

    if all_images.is_empty() {
        return Err(if selection_mode == "按子文件夹抽取" {
            "输入目录里没有包含图片的子文件夹，请放入形如 1、2、3 的子文件夹".to_string()
        } else {
            "目录中没有找到图片文件".to_string()
        });
    }

    // ---- 数量校验（与 Python 的文案一致）----
    if selection_mode == "按子文件夹抽取" {
        let sizes: Vec<i64> = subfolder_groups
            .iter()
            .map(|group| group.images.len() as i64)
            .collect();
        let pool = combination_total(&sizes);
        hooks.log(&format!(
            "{} 个子文件夹共可组成 {} 种组合，将生成 {} 个视频",
            subfolder_groups.len(),
            pool,
            video_count
        ));
        if subfolder_groups.len() < 2 && !subfolder_groups.is_empty() {
            hooks.log(&format!(
                "提示：只找到 1 个子文件夹（{}），一轮只有 1 张图，循环后是静止画面",
                subfolder_groups[0].name
            ));
        }
        if video_count > pool {
            hooks.log(&format!(
                "组合数量不足：只有 {pool} 种组合，需要 {video_count} 个视频；超出部分会复用组合，且各组合出现次数最多相差 1 次"
            ));
        }
    } else if selection_mode == "按名称排序" {
        let required = video_count * num_images;
        if (all_images.len() as i64) < required {
            return Err(format!(
                "图片数量不足，共有{}张，生成{}个视频需要{}张（每个{}张）",
                all_images.len(),
                video_count,
                required,
                num_images
            ));
        }
    } else {
        if (all_images.len() as i64) < num_images {
            return Err(format!(
                "图片数量不足，只有{}张，需要{}张",
                all_images.len(),
                num_images
            ));
        }
        if (all_images.len() as i64) < video_count {
            return Err(format!(
                "图片数量不足以保证首图不重复：共有{}张，计划生成{}个视频",
                all_images.len(),
                video_count
            ));
        }
    }
    hooks.log(&format!(
        "找到{}张图片，将生成{}个视频",
        all_images.len(),
        video_count
    ));

    // ---- 组合 / 转场计划 ----
    let combinations = if selection_mode == "按子文件夹抽取" {
        let sizes: Vec<i64> = subfolder_groups
            .iter()
            .map(|group| group.images.len() as i64)
            .collect();
        let mut rng = Rng::new(0x5EED);
        plan_combinations(&sizes, video_count, &mut rng)
    } else {
        Vec::new()
    };

    let use_transition = flag(&config, "use_transition", true);
    let random_transition = flag(&config, "random_transition", false);
    let transition_plan: Vec<String> = if use_transition && random_transition {
        let enabled = config
            .get("enabled_transitions")
            .and_then(Value::as_array)
            .map(|values| {
                values
                    .iter()
                    .filter_map(|value| value.as_str().map(str::to_string))
                    .filter(|name| transitions::parse(name) != transitions::Transition::Fallback
                        || matches!(name.as_str(), "淡入淡出" | "交叉溶解"))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        if enabled.is_empty() {
            Vec::new()
        } else {
            let mut rng = Rng::new(0x7A11);
            (0..video_count)
                .map(|_| enabled[rng.below(enabled.len())].clone())
                .collect()
        }
    } else {
        Vec::new()
    };
    if !transition_plan.is_empty() {
        hooks.log(&format!(
            "[RANDOM] 已生成转场计划: {}",
            transition_plan.join(" | ")
        ));
    }

    // ---- 逐个视频 ----
    let mut used_first: BTreeSet<String> = BTreeSet::new();
    let mut rng = Rng::new(0x1234_5678);
    let mut success = 0usize;
    let mut outputs: Vec<String> = Vec::new();

    for video_index in 0..video_count {
        if hooks.cancelled() {
            hooks.log("已取消处理");
            return Err("已取消处理".to_string());
        }
        hooks.log(&format!("正在生成第{}个视频...", video_index + 1));

        let selected: Vec<String> = match selection_mode.as_str() {
            "按子文件夹抽取" => {
                let combination = combinations
                    .get(video_index as usize)
                    .cloned()
                    .unwrap_or_else(|| vec![0; subfolder_groups.len()]);
                let picked: Vec<String> = subfolder_groups
                    .iter()
                    .enumerate()
                    .map(|(position, group)| {
                        let index = *combination.get(position).unwrap_or(&0);
                        group
                            .images
                            .get(index % group.images.len().max(1))
                            .cloned()
                            .unwrap_or_default()
                    })
                    .filter(|image| !image.is_empty())
                    .collect();
                let names: Vec<String> = subfolder_groups
                    .iter()
                    .zip(picked.iter())
                    .map(|(group, image)| {
                        format!(
                            "{}:{}",
                            group.name,
                            Path::new(image)
                                .file_name()
                                .map(|value| value.to_string_lossy().into_owned())
                                .unwrap_or_default()
                        )
                    })
                    .collect();
                hooks.log(&format!(
                    "第{}个视频按子文件夹顺序抽取: {}",
                    video_index + 1,
                    names.join(" / ")
                ));
                picked
            }
            "按名称排序" => {
                let start = (video_index * num_images) as usize;
                let picked: Vec<String> = (0..num_images as usize)
                    .filter_map(|offset| all_images.get(start + offset).cloned())
                    .collect();
                hooks.log(&format!(
                    "第{}个视频使用图片 {}-{}: {:?}",
                    video_index + 1,
                    start + 1,
                    start + picked.len(),
                    picked
                        .iter()
                        .map(|image| Path::new(image)
                            .file_name()
                            .map(|value| value.to_string_lossy().into_owned())
                            .unwrap_or_default())
                        .collect::<Vec<_>>()
                ));
                picked
            }
            // 随机选择：首图不重复
            _ => {
                let candidates: Vec<String> = all_images
                    .iter()
                    .filter(|image| !used_first.contains(*image))
                    .cloned()
                    .collect();
                if candidates.is_empty() {
                    return Err("随机首图池已耗尽，无法继续保证首图不重复".to_string());
                }
                let first = candidates[rng.below(candidates.len())].clone();
                used_first.insert(first.clone());

                let target = (num_images as usize).min(all_images.len());
                let need = target.saturating_sub(1);
                let mut pool: Vec<String> = all_images
                    .iter()
                    .filter(|image| **image != first)
                    .cloned()
                    .collect();
                rng.shuffle(&mut pool);
                let mut picked = vec![first];
                picked.extend(pool.into_iter().take(need));
                hooks.log(&format!(
                    "第{}个视频随机选择图片: {:?}",
                    video_index + 1,
                    picked
                        .iter()
                        .map(|image| Path::new(image)
                            .file_name()
                            .map(|value| value.to_string_lossy().into_owned())
                            .unwrap_or_default())
                        .collect::<Vec<_>>()
                ));
                picked
            }
        };

        let source_count = selected.len();
        let selected = cycle_images_to_duration(&selected, duration, total_duration);
        if selected.len() != source_count {
            hooks.log(&format!(
                "第{}个视频按总时长循环为 {} 个图片片段",
                video_index + 1,
                selected.len()
            ));
        }
        if selected.is_empty() {
            hooks.log(&format!("第{}个视频没有可用图片，跳过", video_index + 1));
            continue;
        }

        // 输出文件名
        let first_image_name = Path::new(&selected[0])
            .file_stem()
            .map(|value| value.to_string_lossy().into_owned())
            .unwrap_or_default();
        let filename = compose_output_filename(
            flag(&config, "use_date_prefix", false),
            flag(&config, "use_first_image_name", false),
            &first_image_name,
            &text(&config, "custom_prefix", ""),
            video_index + 1,
            &text(&config, "video_format", "mp4"),
        );
        let output_path = Path::new(&output_dir).join(&filename);

        // 转场类型
        let transition_type = if !use_transition {
            "无转场".to_string()
        } else if random_transition {
            transition_plan
                .get(video_index as usize)
                .cloned()
                .unwrap_or_else(|| "淡入淡出".to_string())
        } else {
            text(&config, "transition_type", "淡入淡出")
        };
        // 随机特效（每个视频抽一次）
        let mut effect_type = text(&config, "video_effect_type", "无特效");
        if flag(&config, "use_video_effect", false) && flag(&config, "random_video_effect", false) {
            let enabled: Vec<String> = config
                .get("enabled_video_effects")
                .and_then(Value::as_array)
                .map(|values| {
                    values
                        .iter()
                        .filter_map(|value| value.as_str().map(str::to_string))
                        .collect()
                })
                .unwrap_or_default();
            if !enabled.is_empty() {
                effect_type = enabled[rng.below(enabled.len())].clone();
            }
        }
        let transition_frames = if use_transition { 15 } else { 0 };
        hooks.log(&format!(
            "第{}个视频 - 转场: {}, 特效: {}, 帧数: {}",
            video_index + 1,
            transition_type,
            effect_type,
            transition_frames
        ));

        let options = compositor::ComposeOptions {
            images: selected,
            output_path: output_path.to_string_lossy().into_owned(),
            duration,
            fps: integer(&config, "fps", 30),
            width: integer(&config, "width", 1920).max(2) as u32,
            height: integer(&config, "height", 1080).max(2) as u32,
            resize_mode: "适应".to_string(),
            transition_frames,
            transition_type,
            target_bitrate: integer(&config, "bitrate", 2000),
            selected_codec: text(&config, "codec", "H264"),
            effect_override: Some(effect_type),
        };

        let start = std::time::Instant::now();
        let mut per_video_config = config.clone();
        per_video_config.insert(
            "_current_video_index".to_string(),
            json!(video_index),
        );
        match compositor::create_video(
            &options,
            &crate::render::audio::JsonConfig::new(&Value::Object(per_video_config)),
            &ffmpeg.to_string_lossy(),
            hooks,
            None,
        ) {
            Ok(result) => {
                success += 1;
                outputs.push(paths::display(&paths::absolute(&output_path)));
                hooks.log(&format!(
                    "成功生成第{}个视频: {}，耗时 {:.1} 秒（{} 帧 {}x{}）",
                    video_index + 1,
                    filename,
                    start.elapsed().as_secs_f64(),
                    result.frames_written,
                    result.width,
                    result.height
                ));
            }
            Err(error) => {
                hooks.log(&format!(
                    "生成第{}个视频失败（耗时 {:.1} 秒）：{error}",
                    video_index + 1,
                    start.elapsed().as_secs_f64()
                ));
            }
        }
    }

    if success == 0 {
        return Err("所有视频生成都失败！".to_string());
    }
    hooks.log(&format!(
        "处理完成！成功生成{success}个视频（共{video_count}个）"
    ));
    Ok(BatchOutcome {
        success,
        total: video_count,
        outputs,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn filename_rules_match_python() {
        // 日期 + 前缀 + 序号
        assert_eq!(
            compose_output_filename(true, false, "", "video", 1, "mp4")
                .split('-')
                .last()
                .unwrap(),
            "1.mp4"
        );
        // 仅前缀
        assert_eq!(
            compose_output_filename(false, false, "", "video", 7, "mp4"),
            "video-7.mp4"
        );
        // 全空
        assert_eq!(
            compose_output_filename(false, false, "", "", 3, "MP4"),
            "3.mp4"
        );
        // 首图名（此时忽略自定义前缀 —— Python 是 elif）
        assert_eq!(
            compose_output_filename(false, true, "风景", "测试", 2, "mp4"),
            "风景-2.mp4"
        );
        // 未开首图名时才用自定义前缀
        assert_eq!(
            compose_output_filename(false, false, "风景", "测试", 2, "mp4"),
            "测试-2.mp4"
        );
    }

    #[test]
    fn combination_total_is_product() {
        assert_eq!(combination_total(&[3, 4]), 12);
        assert_eq!(combination_total(&[3, 0]), 0);
        assert_eq!(combination_total(&[]), 0);
    }

    #[test]
    fn plan_combinations_are_unique_until_exhausted() {
        let mut rng = Rng::new(42);
        let picks = plan_combinations(&[3, 4], 12, &mut rng);
        assert_eq!(picks.len(), 12);
        let unique: BTreeSet<Vec<usize>> = picks.iter().cloned().collect();
        assert_eq!(unique.len(), 12, "12 个组合应互不重复");
        // 每个下标都在范围内
        for pick in &picks {
            assert!(pick[0] < 3 && pick[1] < 4, "{pick:?}");
        }
    }

    #[test]
    fn plan_combinations_allows_repeats_beyond_total() {
        let mut rng = Rng::new(7);
        let picks = plan_combinations(&[2, 2], 6, &mut rng);
        assert_eq!(picks.len(), 6);
        // 出现次数最多相差 1：6 次分给 4 个组合 → 2,2,1,1
        let mut counts = std::collections::BTreeMap::new();
        for pick in &picks {
            *counts.entry(pick.clone()).or_insert(0) += 1;
        }
        let min = counts.values().min().copied().unwrap_or(0);
        let max = counts.values().max().copied().unwrap_or(0);
        assert!(max - min <= 1, "次数应摊平：{counts:?}");
    }

    #[test]
    fn cycle_to_duration_repeats_images() {
        let images = vec!["a".to_string(), "b".to_string()];
        // 单图 1 秒、总时长 3 秒 → 3 个槽
        let cycled = cycle_images_to_duration(&images, 1.0, 3.0);
        assert_eq!(cycled, vec!["a", "b", "a"]);
        // 总时长 0 表示不限制 → 原样返回
        assert_eq!(cycle_images_to_duration(&images, 1.0, 0.0), images);
    }
}
