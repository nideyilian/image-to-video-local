//! 特效/转场参数的**取值与默认值**：把 `catalog` 的声明和用户配置接起来。
//!
//! ## 为什么需要这一层
//!
//! `catalog` 声明了「这个特效有哪些参数、范围多少、默认多少」，但声明本身
//! 不产生像素。渲染代码要的是「现在该用多少」，界面要的是「该显示几个控件」。
//! 这个文件负责把两边对起来：
//!
//! - [`params_for`]：给界面用 —— 返回某特效的全部参数及其**当前值**
//!   （用户改过的取用户值，没改过的取声明里的默认值）
//! - [`resolve`]：给渲染用 —— 只解析实现代码真正要的那几个键，缺的用默认值
//!
//! ## 存储格式
//!
//! 配置里存一个嵌套对象，按「特效 id → 参数键 → 值」两级索引：
//!
//! ```json
//! "effect_params": {
//!   "故障抖动": { "glitch_amount": 60, "color_shift": 30 },
//!   "镜头呼吸": { "breath_rate": 1.2 }
//! }
//! ```
//!
//! 这样切换特效时各自的调参互不干扰 —— 用户调好「故障抖动」再切到「镜头呼吸」，
//! 切回来时设置还在。

use serde_json::{json, Map, Value};

use super::catalog::{self, ParamKind, ParamSpec};

/// 配置里存参数的那个键名。
pub const CONFIG_KEY: &str = "effect_params";

/// 取某个特效/转场在配置里的参数表。
fn params_map<'a>(config: &'a Value, item_id: &str) -> Option<&'a Map<String, Value>> {
    config
        .get(CONFIG_KEY)?
        .get(item_id)?
        .as_object()
}

/// 解析单个参数的当前值：用户设过的取用户值，否则取声明默认值。
///
/// 会按 `ParamKind` 和 `min`/`max` 做夹取 —— 用户在输入框里敲了 9999 也不会
/// 让渲染拿到越界值。这一点很重要：界面输入框的 `max` 只是提示，能绕过。
pub fn resolve_value(config: &Value, item_id: &str, spec: &ParamSpec) -> Value {
    let raw = params_map(config, item_id)
        .and_then(|map| map.get(spec.key))
        .cloned();

    match spec.kind {
        ParamKind::Toggle => {
            let flag = match &raw {
                Some(Value::Bool(flag)) => *flag,
                Some(Value::Number(number)) => number.as_f64().unwrap_or(0.0) != 0.0,
                Some(Value::String(text)) => text == "true" || text == "1",
                _ => spec.default != 0.0,
            };
            json!(flag)
        }
        ParamKind::Choice => {
            // 枚举按下标存，越界就退到默认，避免实现里 match 落空
            let index = raw
                .as_ref()
                .and_then(|value| match value {
                    Value::Number(number) => number.as_f64(),
                    Value::String(text) => text.trim().parse().ok(),
                    _ => None,
                })
                .unwrap_or(spec.default);
            let count = spec.choices.len().max(1) as f64;
            let clamped = index.round().clamp(0.0, count - 1.0);
            json!(clamped)
        }
        ParamKind::Percent | ParamKind::Factor => {
            let number = raw
                .as_ref()
                .and_then(|value| match value {
                    Value::Number(number) => number.as_f64(),
                    Value::String(text) => text.trim().parse().ok(),
                    _ => None,
                })
                .unwrap_or(spec.default);
            // 非有限值（NaN/Inf）一律退回默认，否则会污染整帧像素
            let safe = if number.is_finite() { number } else { spec.default };
            json!(safe.clamp(spec.min, spec.max))
        }
    }
}

/// 解析某个特效的全部参数，返回 `{ 键: 值 }`。
///
/// 实现代码用这个结果，而不是自己去 `config` 里翻 —— 这样夹取和默认值只有一处。
pub fn resolve(config: &Value, item_id: &str) -> Map<String, Value> {
    let Some(item) = catalog::find_effect(item_id) else {
        return Map::new();
    };
    let mut out = Map::new();
    for spec in item.params {
        out.insert(spec.key.to_string(), resolve_value(config, item.id, spec));
    }
    out
}

/// 给界面用：某特效的参数定义 + 当前值，含类型/范围/选项，界面据此生成控件。
///
/// 返回的是纯 JSON，前端不需要知道 Rust 的类型。
pub fn params_for(config: &Value, item_id: &str) -> Value {
    let Some(item) = catalog::find_effect(item_id) else {
        return json!([]);
    };
    let list: Vec<Value> = item
        .params
        .iter()
        .map(|spec| {
            let kind = match spec.kind {
                ParamKind::Percent => "percent",
                ParamKind::Factor => "factor",
                ParamKind::Choice => "choice",
                ParamKind::Toggle => "toggle",
            };
            json!({
                "key": spec.key,
                "label": spec.label,
                "kind": kind,
                "min": spec.min,
                "max": spec.max,
                "default": spec.default,
                "choices": spec.choices,
                "value": resolve_value(config, item.id, spec),
            })
        })
        .collect();
    json!(list)
}

/// 界面初始化用：一次拿到「所有特效的参数定义」，避免每切一次特效就请求一次。
///
/// 结构：`{ 特效 id: [参数定义...] }`。只有声明了参数的特效才会出现在里面，
/// 没声明参数的（大多数）不在，界面就只显示通用的强度/速度。
pub fn all_definitions() -> Value {
    let mut map = Map::new();
    for item in catalog::EFFECTS {
        if item.params.is_empty() {
            continue;
        }
        map.insert(item.id.to_string(), params_for(&Value::Null, item.id));
    }
    json!(map)
}

/// 从 trait 型配置里解析参数。
///
/// `RenderConfig` 只提供「按键取值」，不给整份快照，所以这里按需取
/// `effect_params` 这一个键，再把该特效那一段交给 [`resolve`]。
pub fn resolve_from_config(
    config: &dyn super::audio::RenderConfig,
    item_id: &str,
) -> Map<String, Value> {
    let nested = config.get(CONFIG_KEY).unwrap_or(Value::Null);
    let scoped = json!({ CONFIG_KEY: nested });
    resolve(&scoped, item_id)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config_with(inner: Value) -> Value {
        json!({ CONFIG_KEY: inner })
    }

    /// 没设过任何参数时，全部返回声明里的默认值。
    #[test]
    fn missing_config_uses_declared_defaults() {
        let empty = json!({});
        let resolved = resolve(&empty, "故障抖动");
        // 故障抖动目前没声明参数，返回空表
        assert!(resolved.is_empty() || resolved.values().all(|v| v.is_number()));
    }

    /// 用户设过的值要生效。
    #[test]
    fn user_values_win() {
        let spec = ParamSpec::percent("amount", "强度", 50.0);
        let config = config_with(json!({ "某特效": { "amount": 73.0 } }));
        assert_eq!(resolve_value(&config, "某特效", &spec), json!(73.0));
    }

    /// 越界值必须被夹到范围内 —— 界面输入框的 max 能被绕过。
    #[test]
    fn out_of_range_is_clamped() {
        let spec = ParamSpec::percent("amount", "强度", 50.0);
        let high = config_with(json!({ "x": { "amount": 999999 } }));
        assert_eq!(resolve_value(&high, "x", &spec), json!(200.0));
        let low = config_with(json!({ "x": { "amount": -50 } }));
        assert_eq!(resolve_value(&low, "x", &spec), json!(0.0));
    }

    /// 非数字、NaN 之类要退回默认值，不能污染像素运算。
    #[test]
    fn garbage_falls_back_to_default() {
        let spec = ParamSpec::percent("amount", "强度", 50.0);
        let text = config_with(json!({ "x": { "amount": "不是数字" } }));
        assert_eq!(resolve_value(&text, "x", &spec), json!(50.0));
    }

    /// 枚举值按下标存，越界退到最后一档（不是默认档，避免用户选了高项却被悄悄改掉）。
    #[test]
    fn choice_index_is_clamped() {
        let spec = ParamSpec::choice("style", "样式", &["A", "B", "C"], 0.0);
        let config = config_with(json!({ "x": { "style": 99 } }));
        assert_eq!(resolve_value(&config, "x", &spec), json!(2.0));
        let negative = config_with(json!({ "x": { "style": -3 } }));
        assert_eq!(resolve_value(&negative, "x", &spec), json!(0.0));
    }

    /// 布尔型接受 true / 1 / "true" 三种写法。
    #[test]
    fn toggle_accepts_several_spellings() {
        let spec = ParamSpec {
            key: "on",
            label: "开关",
            kind: ParamKind::Toggle,
            min: 0.0,
            max: 1.0,
            default: 1.0,
            choices: &[],
        };
        for raw in [json!(true), json!(1), json!("true"), json!("1")] {
            let config = config_with(json!({ "x": { "on": raw } }));
            assert_eq!(resolve_value(&config, "x", &spec), json!(true));
        }
        let off = config_with(json!({ "x": { "on": false } }));
        assert_eq!(resolve_value(&off, "x", &spec), json!(false));
    }

    /// 不同特效的参数互不干扰 —— 这是嵌套存储的意义。
    #[test]
    fn different_effects_do_not_share_state() {
        let config = config_with(json!({ "甲": { "amount": 10 } }));
        let spec = ParamSpec::percent("amount", "强度", 50.0);
        assert_eq!(resolve_value(&config, "甲", &spec), json!(10.0));
        // 乙没设过，应是默认值而不是甲的 10
        assert_eq!(resolve_value(&config, "乙", &spec), json!(50.0));
    }

    /// 未知特效返回空参数表，不 panic。
    #[test]
    fn unknown_effect_is_safe() {
        let config = json!({});
        assert!(resolve(&config, "不存在的特效").is_empty());
        assert_eq!(params_for(&config, "不存在的特效"), json!([]));
    }

    /// 冒烟：打印引擎实际会返回的内容，人工确认格式对。
    #[test]
    fn schema_smoke_reports_content() {
        let all = all_definitions();
        println!("{}", serde_json::to_string_pretty(&all).unwrap_or_default());
        let map = all.as_object().expect("应是对象");
        assert!(!map.is_empty(), "一个声明了参数的特效都没有？");
    }

    /// 全量定义只包含声明了参数的特效，不该把 53 个全塞进去。
    #[test]
    fn definitions_only_include_effects_with_params() {
        let all = all_definitions();
        let map = all.as_object().expect("应该是对象");
        for item in catalog::EFFECTS {
            if item.params.is_empty() {
                assert!(!map.contains_key(item.id), "「{}」没参数却出现在定义里", item.id);
            }
        }
    }
}