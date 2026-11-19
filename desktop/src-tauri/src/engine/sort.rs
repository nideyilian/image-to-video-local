//! 自然排序：与 Python 版 `config.natural_sort_key` 对齐。
//!
//! 旧引擎的排序规则是 `re.split(r"(\d+)", name)` 后逐段比较：
//! 数字段按整数值比（`2` 排在 `10` 前面），其余段转小写按字符比。
//! 这里用同样的分段方式，避免 Rust 版与 Python 版扫出不同顺序 —— 顺序一变，
//! 「按名称排序」生成的视频内容和预览就全错位了。

use std::cmp::Ordering;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Segment {
    Num(u128),
    Text(String),
}

impl Ord for Segment {
    fn cmp(&self, other: &Self) -> Ordering {
        match (self, other) {
            (Segment::Num(left), Segment::Num(right)) => left.cmp(right),
            (Segment::Text(left), Segment::Text(right)) => left.cmp(right),
            // Python 侧数字段与文本段不会在同一位置相遇（分段模式一致），
            // 这里给一个稳定且确定的先后，避免比较时 panic。
            (Segment::Num(_), Segment::Text(_)) => Ordering::Less,
            (Segment::Text(_), Segment::Num(_)) => Ordering::Greater,
        }
    }
}

impl PartialOrd for Segment {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

/// 生成排序键。注意：只有 ASCII 数字按数值处理（旧引擎的 `\d` 还包含全角等
/// Unicode 数字，文件名里极少见，已在迁移说明中标注为已知差异）。
pub fn natural_sort_key(value: &str) -> Vec<Segment> {
    let mut segments: Vec<Segment> = Vec::new();
    let mut text = String::new();
    let mut digits = String::new();

    for ch in value.chars() {
        if ch.is_ascii_digit() {
            if !text.is_empty() {
                segments.push(Segment::Text(text.to_lowercase()));
                text.clear();
            }
            digits.push(ch);
        } else {
            if !digits.is_empty() {
                segments.push(Segment::Num(digits.parse::<u128>().unwrap_or(u128::MAX)));
                digits.clear();
            }
            text.push(ch);
        }
    }
    if !digits.is_empty() {
        segments.push(Segment::Num(digits.parse::<u128>().unwrap_or(u128::MAX)));
    }
    if !text.is_empty() {
        segments.push(Segment::Text(text.to_lowercase()));
    }
    segments
}

/// 按自然顺序比较两个名字。
pub fn compare_names(left: &str, right: &str) -> Ordering {
    natural_sort_key(left).cmp(&natural_sort_key(right))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sorted(names: &[&str]) -> Vec<String> {
        let mut items: Vec<String> = names.iter().map(|name| name.to_string()).collect();
        items.sort_by(|a, b| compare_names(a, b));
        items
    }

    #[test]
    fn numbers_sort_numerically_not_lexically() {
        assert_eq!(
            sorted(&["10.jpg", "2.jpg", "1.jpg", "20.jpg", "3.jpg"]),
            vec!["1.jpg", "2.jpg", "3.jpg", "10.jpg", "20.jpg"]
        );
    }

    #[test]
    fn case_insensitive_and_stable_for_chinese() {
        assert_eq!(sorted(&["B.jpg", "a.jpg"]), vec!["a.jpg", "B.jpg"]);
        // 中文按 Unicode 码点（与 Python 一致：「一」<「三」）
        assert_eq!(sorted(&["三.jpg", "一.jpg"]), vec!["一.jpg", "三.jpg"]);
    }

    #[test]
    fn mixed_text_and_digits() {
        assert_eq!(
            sorted(&["视频9-片段.mp4", "视频10-片段.mp4", "视频1-片段.mp4"]),
            vec!["视频1-片段.mp4", "视频9-片段.mp4", "视频10-片段.mp4"]
        );
    }
}
