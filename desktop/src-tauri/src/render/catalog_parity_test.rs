//! 目录与实现的一致性：读源码，核对三个地方不能脱节。
//!
//! 读过 Concat 的做法后加这层保护：它用 `effect.toml` 声明 + `fixtures.toml` 断言，
//! 加特效时漏写一处会立刻失败。我们改成从源码里提取，不需要额外文件，
//! 但同样能在**加特效时漏步骤**的当下就报错。
//!
//! 检查三件事：
//! 1. `catalog::EFFECTS` 里声明的每个 ID，`effects.rs` 的 `match` 里必须真有分支
//! 2. 反过来，`match` 里有分支的，目录里必须声明（否则界面上看不到它）
//! 3. 转场同理

use super::catalog::{EFFECTS, TRANSITIONS};

/// 从源码文本里抽出 `match` 臂的字符串字面量。
///
/// 用缩进判界：从起点行开始，遇到缩进回到起始层级的那一行 `}` 就结束。
/// 这样不依赖具体写法，match 里嵌套多深都不会误判。
fn arms(source: &str, start_marker: &str) -> Vec<String> {
    let start = source.find(start_marker).expect("找不到 match 起点");
    let body = &source[start..];

    // 起点行的缩进量
    let line_start = source[..start].rfind('\n').map_or(0, |at| at + 1);
    let indent = source[line_start..start]
        .chars()
        .take_while(|c| *c == ' ')
        .count();

    let mut found = Vec::new();
    for line in body.lines().skip(1) {
        let trimmed = line.trim_start();
        let this_indent = line.len() - trimmed.len();
        // 回到起点缩进的 `}`：match 结束
        if this_indent <= indent && trimmed.starts_with('}') {
            break;
        }
        // 只认 `"名字" =>` 这种臂
        if !trimmed.starts_with('"') {
            continue;
        }
        if let Some(close) = trimmed[1..].find('"') {
            let name = &trimmed[1..1 + close];
            let after = trimmed[1 + close + 1..].trim_start();
            if after.starts_with("=>") {
                found.push(name.to_string());
            }
        }
    }
    found
}

#[test]
fn every_declared_effect_has_an_implementation() {
    let source = include_str!("effects.rs");
    let implemented = arms(source, "match effect.as_str() {");

    for item in EFFECTS {
        assert!(
            implemented.iter().any(|arm| arm == item.id),
            "目录里声明了「{}」，但 effects.rs 的 match 里没有对应分支。\n\
             要么补实现，要么从 catalog::EFFECTS 删掉这条。",
            item.id
        );
    }
}

#[test]
fn every_implemented_effect_is_declared() {
    let source = include_str!("effects.rs");
    let implemented = arms(source, "match effect.as_str() {");

    for arm in &implemented {
        assert!(
            EFFECTS.iter().any(|item| item.id == arm),
            "effects.rs 实现了「{arm}」，但它不在 catalog::EFFECTS 里。\n\
             这样界面下拉里看不到它，用户选不到。",
        );
    }
}

#[test]
fn every_declared_transition_has_an_implementation() {
    let source = include_str!("transitions.rs");
    // 转场用 `parse()` 把字符串映射到枚举
    let implemented = arms(source, "match name {");

    for item in TRANSITIONS {
        assert!(
            implemented.iter().any(|arm| arm == item.id),
            "目录里声明了转场「{}」，但 transitions.rs 的 parse() 里没有对应分支。",
            item.id
        );
    }
}

#[test]
fn every_implemented_transition_is_declared() {
    let source = include_str!("transitions.rs");
    let implemented = arms(source, "match name {");

    for arm in &implemented {
        assert!(
            TRANSITIONS.iter().any(|item| item.id == arm),
            "transitions.rs 解析了「{arm}」，但它不在 catalog::TRANSITIONS 里。",
        );
    }
}

/// 目录里声明的别名，必须是 `normalize_effect` 也认识的，
/// 否则用户存了别名进来，目录能纠正、实现却对不上。
#[test]
fn aliases_agree_with_normalizer() {
    let source = include_str!("effects.rs");
    let start = source
        .find("pub fn normalize_effect")
        .expect("找不到 normalize_effect");
    let body = &source[start..];
    // 函数到下一个顶格 `}` 结束
    let end = body.find("\n}\n").unwrap_or(body.len());
    let normalizer = &body[..end];

    for item in EFFECTS {
        for alias in item.aliases {
            assert!(
                normalizer.contains(&format!("\"{alias}\"")),
                "目录声明了别名「{alias}」（属于 {}），但 normalize_effect 里没有它。",
                item.id
            );
            // 别名必须映射到主名，否则纠正完还是错的
            let pattern = format!("\"{alias}\"");
            if let Some(at) = normalizer.find(&pattern) {
                let tail = &normalizer[at..];
                let line_end = tail.find('\n').unwrap_or(tail.len());
                let line = &tail[..line_end];
                assert!(
                    line.contains(&format!("\"{}\"", item.id)),
                    "normalize_effect 里「{alias}」没有映射到「{}」，实际是：{line}",
                    item.id
                );
            }
        }
    }
}
