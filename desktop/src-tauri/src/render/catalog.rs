//! 特效与转场的**声明式目录**：参数、分组、顺序、别名，全部集中在这一处。
//!
//! ## 为什么要有这个文件
//!
//! 之前这些信息分散在三处而且互不相通：
//! - 特效名在 `constants.ts:VIDEO_EFFECTS`（前端下拉）
//! - 又一份在 `src/engine/config.py:DEFAULT_VIDEO_EFFECTS`（后端默认值）
//! - 实现分支在 `effects.rs` 的 `match`（没有参数元信息）
//!
//! 结果是：想给某个特效单独加一个参数（比如「故障抖动」想要一个色彩偏移量的滑杆），
//! 得同时改三处，还要记住改契约测试的解析规则。而界面上永远只有
//! 「强度」和「速度」两个通用滑杆 —— 因为后端根本没有地方声明「这个特效有哪些参数」。
//!
//! 这个文件补上那块缺失的信息：**每个特效/转场自己声明它需要什么参数**。
//! 界面读它自动生成控件，测试读它自动生成断言，文档读它自动生成表格。
//!
//! ## 与渲染代码的关系
//!
//! 目录是**纯描述**，不参与像素运算。`effects.rs` / `transitions.rs` 仍然是
//! 唯一的实现处。两边靠 `id` 对齐，`catalog_parity` 测试保证不出错漏。
//!
//! ## 加一个新特效要做的事
//!
//! 1. 在 `EFFECTS` 里加一条（id、中文名、分组、参数）—— 界面下拉会自动出现
//! 2. 在 `effects.rs` 的 `match` 里加实现分支
//! 3. 在 `effects_baseline_test.rs` 的 `PROBE_EFFECTS` 加一行（基线自动覆盖）
//! 4. 跑测试：`catalog_parity` 会告诉你哪一步漏了

/// 参数类型。决定界面用什么控件，以及测试怎么取值。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ParamKind {
    /// 百分比滑杆（界面显示 0–100，实现里除 100）。绝大多数「强度」类参数用它。
    Percent,
    /// 倍数滑杆（1.0 = 原速）。
    Factor,
    /// 整数枚举（界面显示下拉，实现里拿到的是下标）。
    Choice,
    /// 布尔开关。
    Toggle,
}

/// 一个参数的定义。
#[derive(Debug, Clone, Copy)]
pub struct ParamSpec {
    /// 内部键名，实现代码按这个名字取参数。
    pub key: &'static str,
    /// 界面显示的标签。
    pub label: &'static str,
    pub kind: ParamKind,
    pub min: f64,
    pub max: f64,
    pub default: f64,
    /// `Choice` 类型的可选项；其它类型为空。
    pub choices: &'static [&'static str],
}

impl ParamSpec {
    pub const fn percent(
        key: &'static str,
        label: &'static str,
        default: f64,
    ) -> Self {
        ParamSpec {
            key,
            label,
            kind: ParamKind::Percent,
            min: 0.0,
            max: 200.0,
            default,
            choices: &[],
        }
    }

    pub const fn factor(key: &'static str, label: &'static str, default: f64) -> Self {
        ParamSpec {
            key,
            label,
            kind: ParamKind::Factor,
            min: 0.1,
            max: 5.0,
            default,
            choices: &[],
        }
    }

    pub const fn choice(
        key: &'static str,
        label: &'static str,
        choices: &'static [&'static str],
        default: f64,
    ) -> Self {
        ParamSpec {
            key,
            label,
            kind: ParamKind::Choice,
            min: 0.0,
            max: (choices.len() - 1) as f64,
            default,
            choices,
        }
    }
}

/// 一个特效或转场的完整声明。
#[derive(Debug, Clone, Copy)]
pub struct ItemSpec {
    /// 与实现的 `match` 分支、前端下拉的字符串**逐字一致**的 ID。
    pub id: &'static str,
    /// 分组，决定界面上的折叠块。
    pub group: &'static str,
    /// 一句话说明，用于悬浮提示。
    pub summary: &'static str,
    /// 该特效独有的参数。通用的「强度/速度」不在里面 —— 它们由 `EffectParams` 统一提供。
    pub params: &'static [ParamSpec],
    /// 同义名（用户旧配置里可能存的写法），一律映射到 `id`。
    pub aliases: &'static [&'static str],
}

// ---------------------------------------------------------------------------
// 特效分组
// ---------------------------------------------------------------------------

/// 分组的显示顺序。新增分组时加在这里，否则界面会把它排到最后。
pub const EFFECT_GROUPS: &[&str] = &[
    "基础缩放",
    "平移漂移",
    "旋转摆动",
    "复合运动",
    "变形扭曲",
    "风格化",
    "特殊",
];

/// 全部特效声明，顺序即界面下拉的顺序。
///
/// ⚠️ 顺序会影响「第一个选项」的默认值，改顺序前先看 `constants.ts:VIDEO_EFFECTS`
/// 与契约测试 `test_video_effect_enum_matches_frontend`。
pub const EFFECTS: &[ItemSpec] = &[
    // ---- 基础缩放：只有一个缩放动作，靠强度/速度调快慢 ----
    ItemSpec {
        id: "心跳跳动",
        group: "基础缩放",
        summary: "有节奏地放大缩小，像心跳",
        params: &[],
        aliases: &["心跳跃动"],
    },
    ItemSpec {
        id: "反复缩放",
        group: "基础缩放",
        summary: "匀速来回放大缩小",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "轻微摇摆",
        group: "基础缩放",
        summary: "小幅度的左右摆动",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "镜头呼吸",
        group: "基础缩放",
        summary: "缓慢推进再退回，源自轻微放大",
        params: &[],
        aliases: &["轻微放大"],
    },
    ItemSpec {
        id: "脉冲放大",
        group: "基础缩放",
        summary: "快速脉冲式放大，源自轻微缩小",
        params: &[],
        aliases: &["轻微缩小"],
    },
    // ---- 平移漂移：整幅画面位移 ----
    ItemSpec {
        id: "左右晃动",
        group: "平移漂移",
        summary: "横向来回平移，源自左右平移",
        params: &[],
        aliases: &["左右平移"],
    },
    ItemSpec {
        id: "上下浮动",
        group: "平移漂移",
        summary: "纵向上下浮动，源自上下平移",
        params: &[],
        aliases: &["上下平移"],
    },
    ItemSpec {
        id: "圆周漂移",
        group: "平移漂移",
        summary: "沿圆周轨迹缓慢移动",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "8字漂移",
        group: "平移漂移",
        summary: "走一个横 8 字",
        params: &[],
        aliases: &[],
    },
    // ---- 旋转摆动 ----
    ItemSpec {
        id: "旋转摆动",
        group: "旋转摆动",
        summary: "绕画面中心来回旋转，源自旋转缩放",
        params: &[],
        aliases: &["旋转缩放"],
    },
    ItemSpec {
        id: "旋转呼吸",
        group: "旋转摆动",
        summary: "旋转叠加呼吸缩放",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "摇摆推拉",
        group: "旋转摆动",
        summary: "一边摇一边推近",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "心跳摇摆",
        group: "旋转摆动",
        summary: "心跳节奏叠加轻微摇摆",
        params: &[],
        aliases: &[],
    },
    // ---- 复合运动：多个轴同时动 ----
    ItemSpec {
        id: "螺旋摆动",
        group: "复合运动",
        summary: "边转边缩边平移，走螺旋",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "双轴呼吸",
        group: "复合运动",
        summary: "横纵两个方向独立缩放，会轻微变形",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "波浪平移",
        group: "复合运动",
        summary: "横纵相位不同的波浪式位移",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "径向脉冲旋转",
        group: "复合运动",
        summary: "径向脉冲与旋转叠加",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "镜头抖动呼吸",
        group: "复合运动",
        summary: "手持抖动叠加缓慢呼吸",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "反向双旋",
        group: "复合运动",
        summary: "内外反向旋转，形成对扭",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "呼吸变焦扫光",
        group: "复合运动",
        summary: "呼吸缩放叠加一条扫过的光带",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "旋摆模糊脉冲",
        group: "复合运动",
        summary: "旋转摆动叠加周期性的模糊脉冲",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "透视呼吸摆动",
        group: "复合运动",
        summary: "带透视倾斜的呼吸摆动",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "涡旋推拉",
        group: "复合运动",
        summary: "涡旋感叠加推拉",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "变焦摇移",
        group: "复合运动",
        summary: "变焦同时横向摇移",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "旋转漂移闪动",
        group: "复合运动",
        summary: "旋转漂移叠加亮度闪动",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "双频摆动",
        group: "复合运动",
        summary: "两个不同频率的摆动叠加",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "环形巡航",
        group: "复合运动",
        summary: "沿环形轨迹巡航",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "呼吸鱼眼旋摆",
        group: "复合运动",
        summary: "鱼眼变形叠加呼吸旋摆",
        params: &[],
        aliases: &[],
    },
    // ---- 变形扭曲 ----
    ItemSpec {
        id: "水波扭曲",
        group: "变形扭曲",
        summary: "像水面涟漪一样扭曲画面",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "漩涡旋转",
        group: "变形扭曲",
        summary: "绕中心扭转，越靠外扭得越厉害",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "鱼眼镜头",
        group: "变形扭曲",
        summary: "广角鱼眼的桶形畸变",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "径向拉伸",
        group: "变形扭曲",
        summary: "沿径向往外拉伸",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "透视俯仰",
        group: "变形扭曲",
        summary: "模拟上下俯仰的透视变化",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "滚动快门",
        group: "变形扭曲",
        summary: "逐行位移，模拟果冻效应",
        // 滚动条数原来硬编码为 4.0，改小会变成横向渐变、改大会变成细密条纹。
        params: &[ParamSpec::factor("bands", "滚动条数", 4.0)],
        aliases: &[],
    },
    // ---- 风格化 ----
    ItemSpec {
        id: "故障抖动",
        group: "风格化",
        summary: "数码故障感的错位与抖动",
        // 这两个参数直击原实现的硬编码：位移幅度原来写死为
        // `3.0 + 7.0 * intensity`，抖动频率写死为 3.0 Hz。
        params: &[
            ParamSpec::percent("shift", "错位幅度", 100.0),
            ParamSpec::factor("freq", "抖动频率", 3.0),
        ],
        aliases: &[],
    },
    ItemSpec {
        id: "镜像扫光",
        group: "风格化",
        summary: "镜像反射叠加扫过的光",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "呼吸模糊",
        group: "风格化",
        summary: "模糊程度随呼吸周期变化",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "边缘闪烁",
        group: "风格化",
        summary: "画面边缘周期性亮灭",
        params: &[],
        aliases: &[],
    },
    // ---- 特殊 ----
    ItemSpec {
        id: "灵魂出窍",
        group: "特殊",
        summary: "剪映同款：放大并叠加，16 帧循环曲线",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "缓慢拉远",
        group: "特殊",
        summary: "持续缓慢缩小",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "右下平移",
        group: "平移漂移",
        summary: "从左上往右下平移",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "左上平移",
        group: "平移漂移",
        summary: "从右下往左上平移",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "缓慢推近",
        group: "特殊",
        // ⚠️ 这条是 catalog_parity 测试抓出来的：effects.rs 早就实现了它，
        // 但从来没有出现在界面的下拉里，用户一直选不到。
        summary: "持续缓慢放大",
        params: &[],
        aliases: &[],
    },
];

// ---------------------------------------------------------------------------
// 转场
// ---------------------------------------------------------------------------

/// 转场分组显示顺序。
pub const TRANSITION_GROUPS: &[&str] = &["基础", "滑动推移", "几何展开", "缩放冲击", "擦除", "视觉特效"];

/// 全部转场声明，顺序即界面下拉顺序。
pub const TRANSITIONS: &[ItemSpec] = &[
    ItemSpec {
        id: "淡入淡出",
        group: "基础",
        summary: "最常用的交叉淡化",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "交叉溶解",
        group: "基础",
        summary: "与淡入淡出同实现",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "左右滑动",
        group: "滑动推移",
        summary: "新画面从右侧滑入",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "上下滑动",
        group: "滑动推移",
        summary: "新画面从上方滑入",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "推入效果",
        group: "滑动推移",
        summary: "旧画面被顶出去",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "纵向拉幕",
        group: "滑动推移",
        summary: "像幕布一样纵向拉开",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "横向拉幕",
        group: "滑动推移",
        summary: "像幕布一样横向拉开",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "圆形扩展",
        group: "几何展开",
        summary: "圆形从中心扩散",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "菱形开幕",
        group: "几何展开",
        summary: "菱形从中心张开",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "门式打开",
        group: "几何展开",
        summary: "两扇门向两侧打开",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "百叶窗",
        group: "几何展开",
        summary: "条形百叶窗逐条翻开",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "棋盘格",
        group: "几何展开",
        summary: "方格逐个切换",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "方块过渡",
        group: "几何展开",
        summary: "大块拼接切换",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "缩放过渡",
        group: "缩放冲击",
        summary: "整体缩放切换",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "放大冲击",
        group: "缩放冲击",
        summary: "猛地放大切走",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "缩小爆炸",
        group: "缩放冲击",
        summary: "缩到消失再爆开",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "旋转放大",
        group: "缩放冲击",
        summary: "边转边放大",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "弹性缩放",
        group: "缩放冲击",
        summary: "带回弹的缩放",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "对角擦除",
        group: "擦除",
        summary: "沿对角线擦除",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "径向旋切",
        group: "擦除",
        summary: "绕中心旋转着切",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "时钟扫描",
        group: "擦除",
        summary: "像钟表指针扫过",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "流光擦拭",
        group: "擦除",
        summary: "带光带的擦除",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "旋转变换",
        group: "视觉特效",
        summary: "整体旋转切换",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "波浪",
        group: "视觉特效",
        summary: "波浪状推进",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "颜色混合",
        group: "视觉特效",
        summary: "颜色通道先过渡再换图",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "像素化",
        group: "视觉特效",
        summary: "像素块逐渐变大再还原",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "3D翻转",
        group: "视觉特效",
        summary: "模拟翻牌",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "闪光过渡",
        group: "视觉特效",
        summary: "中间闪一下白",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "碎片飞散",
        group: "视觉特效",
        summary: "碎成小块飞走",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "光晕扩散",
        group: "视觉特效",
        summary: "光晕向外扩散",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "漩涡扭曲",
        group: "视觉特效",
        summary: "画面被卷进漩涡",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "镜头虚焦",
        group: "视觉特效",
        summary: "先虚化再对焦",
        params: &[],
        aliases: &[],
    },
    ItemSpec {
        id: "液态融合",
        group: "视觉特效",
        summary: "像液体一样交融",
        params: &[],
        aliases: &[],
    },
];

// ---------------------------------------------------------------------------
// 查询辅助
// ---------------------------------------------------------------------------

/// 按 ID 或别名查特效声明。
pub fn find_effect(name: &str) -> Option<&'static ItemSpec> {
    EFFECTS.iter().find(|item| {
        item.id == name || item.aliases.contains(&name)
    })
}

/// 按 ID 或别名查转场声明。
pub fn find_transition(name: &str) -> Option<&'static ItemSpec> {
    TRANSITIONS.iter().find(|item| {
        item.id == name || item.aliases.contains(&name)
    })
}

/// 特效的规范 ID（别名会被纠正回主名）。查不到时原样返回。
pub fn canonical_effect(name: &str) -> &str {
    find_effect(name).map_or(name, |item| item.id)
}

/// 转场的规范 ID。
pub fn canonical_transition(name: &str) -> &str {
    find_transition(name).map_or(name, |item| item.id)
}

/// 按分组聚合，供界面渲染折叠块。返回 `(组名, 该组的项)`，组内顺序与声明一致。
pub fn group_effects() -> Vec<(&'static str, Vec<&'static ItemSpec>)> {
    group_by(EFFECT_GROUPS, EFFECTS)
}

pub fn group_transitions() -> Vec<(&'static str, Vec<&'static ItemSpec>)> {
    group_by(TRANSITION_GROUPS, TRANSITIONS)
}

fn group_by(
    groups: &'static [&'static str],
    items: &'static [ItemSpec],
) -> Vec<(&'static str, Vec<&'static ItemSpec>)> {
    let mut result: Vec<(&'static str, Vec<&'static ItemSpec>)> = groups
        .iter()
        .map(|group| (*group, Vec::new()))
        .collect();
    for item in items {
        match result.iter_mut().find(|(group, _)| *group == item.group) {
            Some((_, bucket)) => bucket.push(item),
            None => {
                // 声明里写了未注册的分组：挂到最后一组，并由测试报错
                if let Some((_, bucket)) = result.last_mut() {
                    bucket.push(item);
                }
            }
        }
    }
    result.retain(|(_, bucket)| !bucket.is_empty());
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 每个声明的 ID 必须唯一 —— 重复会让界面出现两个一模一样的选项。
    #[test]
    fn ids_are_unique() {
        let mut seen = std::collections::HashSet::new();
        for item in EFFECTS.iter().chain(TRANSITIONS.iter()) {
            assert!(seen.insert(item.id), "ID 重复：{}", item.id);
        }
    }

    /// 别名不能撞上别人的主名，否则查找会走错分支。
    #[test]
    fn aliases_do_not_collide_with_ids() {
        let ids: std::collections::HashSet<&str> =
            EFFECTS.iter().chain(TRANSITIONS.iter()).map(|i| i.id).collect();
        for item in EFFECTS.iter().chain(TRANSITIONS.iter()) {
            for alias in item.aliases {
                assert!(
                    !ids.contains(alias),
                    "别名「{alias}」与某个主 ID 撞了（声明在 {}）",
                    item.id
                );
            }
        }
    }

    /// 每个声明的分组都必须在分组表里注册，否则界面会把它塞到最后一块。
    #[test]
    fn groups_are_registered() {
        for item in EFFECTS {
            assert!(
                EFFECT_GROUPS.contains(&item.group),
                "特效「{}」的分组「{}」没在 EFFECT_GROUPS 注册",
                item.id,
                item.group
            );
        }
        for item in TRANSITIONS {
            assert!(
                TRANSITION_GROUPS.contains(&item.group),
                "转场「{}」的分组「{}」没在 TRANSITION_GROUPS 注册",
                item.id,
                item.group
            );
        }
    }

    /// 参数默认值必须落在 [min, max] 内，否则界面一打开就是非法值。
    #[test]
    fn param_defaults_are_in_range() {
        for item in EFFECTS.iter().chain(TRANSITIONS.iter()) {
            for param in item.params {
                assert!(
                    param.default >= param.min && param.default <= param.max,
                    "{}.{} 的默认值 {} 不在 [{}, {}] 内",
                    item.id,
                    param.key,
                    param.default,
                    param.min,
                    param.max
                );
            }
        }
    }

    /// 分组聚合不能丢项，也不能重复。
    #[test]
    fn grouping_keeps_every_item_once() {
        for (all, grouped) in [
            (EFFECTS, group_effects()),
            (TRANSITIONS, group_transitions()),
        ] {
            let collected: Vec<&str> = grouped
                .iter()
                .flat_map(|(_, bucket)| bucket.iter().map(|item| item.id))
                .collect();
            assert_eq!(collected.len(), all.len(), "分组后有项丢失或重复");
            for item in all {
                assert!(
                    collected.contains(&item.id),
                    "「{}」没出现在任何分组里",
                    item.id
                );
            }
        }
    }

    /// 别名必须能被查回主名。
    #[test]
    fn aliases_resolve_to_canonical_id() {
        assert_eq!(canonical_effect("心跳跃动"), "心跳跳动");
        assert_eq!(canonical_effect("轻微放大"), "镜头呼吸");
        assert_eq!(canonical_effect("左右平移"), "左右晃动");
        assert_eq!(canonical_transition("淡入淡出"), "淡入淡出");
        // 未知名字原样返回，不 panic
        assert_eq!(canonical_effect("不存在的特效"), "不存在的特效");
    }
}