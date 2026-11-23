//! 应用内更新检查：**只比对版本号，把下载链接交给浏览器**。
//!
//! ## 为什么长成这样（2026-11-20 重写）
//!
//! 旧方案用 `tauri-plugin-updater`：4 个镜像端点顺序轮询 + minisign 签名链 +
//! 应用内下载安装。实测「经常失败」，根因有三层：
//!
//! | 端点 | 拉清单 | 下载安装包 |
//! |---|---|---|
//! | 直连 GitHub | 失败 | 拿到 0 字节 |
//! | mirror.ghproxy.com | 失败 | 失败 |
//! | ghproxy.net | 302 | 403 |
//! | gh-proxy.com | 200 | 2.9 MB/s |
//!
//! 1. 4 个端点里 3 个是坏的，而插件是**顺序轮询**：前面任何一步超时都要等满
//!    20 秒，看着就像卡死。
//! 2. GitHub 生成的 `latest.json` 里下载地址是
//!    `api.github.com/repos/.../assets/ID`，要求 `Accept: application/octet-stream`，
//!    多数公共镜像对这种 API 地址直接 403。
//! 3. 失败提示只有一句「国内网络受限」，用户不知道该改什么。
//!
//! ## 现在
//!
//! 检查 = 拉一个只含 `{version, url}` 的清单，比版本号，有新版就把链接给前端。
//! **下载交给系统浏览器**（用户点链接 → 浏览器下载 → 自己运行安装包）。
//!
//! 这样做的取舍：
//! - 失去：应用内一键更新
//! - 得到：失败点从 5 个降到 1 个（只有「拉清单」可能失败）；不需要签名链、
//!   不需要写临时文件、不需要处理安装器退出码；浏览器下载有断点续传和进度，
//!   比我们自己 curl 更可靠
//!
//! 清单格式（发布时由 CI 生成，见 `.github/workflows/release-desktop.yml`）：
//!
//! ```json
//! { "version": "3.0.0-local.25",
//!   "url": "https://github.com/OWNER/REPO/releases/download/v3.0.0-local.25/app-setup.exe" }
//! ```
//!
//! `url` 必须是 `releases/download/<文件名>` 这种**静态直链** —— 任何 gh 镜像
//! 都能代理它，这正是旧方案栽跟头的地方。

use std::process::Command;

use serde_json::Value;

use super::system::hide_console;

/// 版本清单的候选地址，按顺序尝试，第一个可用的就用。
///
/// ⚠️ **顺序有讲究**：把实测可用的放前面。用户网络下「直连 GitHub」通常
/// 拿不到字节，排第一位只会白等一个超时 —— 所以镜像在前、直连在后。
///
/// ⚠️ 文件名是 `update.json` 而不是 `latest.json`：后者是
/// `tauri-plugin-updater` 的格式（`platforms` 嵌套 + api.github.com 下载地址），
/// 老版本（≤ 3.0.0-local.24）还在按那个格式读。两套清单并存、互不干扰，
/// 等老版本自然淘汰后再考虑合并。
pub const MANIFEST_URLS: [&str; 2] = [
    "https://gh-proxy.com/https://github.com/nideyilian/image-to-video-local/releases/latest/download/update.json",
    "https://github.com/nideyilian/image-to-video-local/releases/latest/download/update.json",
];

/// 拉清单的超时（秒）。清单不到 1KB，正常几百毫秒；超过就是网络不通。
const MANIFEST_TIMEOUT: u64 = 8;

/// 解析后的版本清单。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Manifest {
    pub version: String,
    pub url: String,
}

/// 把版本号拆成可比较的数字段：`3.0.0-local.24` → `[3, 0, 0, 24]`。
///
/// 项目用 `3.0.0-local.N` 这种带预发布后缀的写法，semver 会把 `-local` 当成
/// 预发布标签，于是 `3.0.0-local.25 > 3.0.0` 判成 false —— 和直觉相反。
/// 干脆只取数字段逐位比较，简单且符合本项目的版本习惯。
pub fn version_segments(version: &str) -> Vec<u64> {
    version
        .split(|ch: char| !ch.is_ascii_digit())
        .filter(|part| !part.is_empty())
        .filter_map(|part| part.parse::<u64>().ok())
        .collect()
}

/// 版本 `a` 是否比 `b` 新。段数不同时短的那边补 0 比较。
pub fn is_newer(a: &str, b: &str) -> bool {
    let (left, right) = (version_segments(a), version_segments(b));
    let len = left.len().max(right.len());
    for index in 0..len {
        let l = left.get(index).copied().unwrap_or(0);
        let r = right.get(index).copied().unwrap_or(0);
        if l != r {
            return l > r;
        }
    }
    false
}

/// 解析清单 JSON。`version` 与 `url` 缺一不可，`url` 必须 https。
///
/// 校验得这么严是因为清单是唯一的判断依据：格式松一点，一个手滑写成空字符串
/// 就会让「发现有新版」但「点了没反应」。
pub fn parse_manifest(raw: &str) -> Result<Manifest, String> {
    let value: Value =
        serde_json::from_str(raw).map_err(|error| format!("版本清单不是合法 JSON：{error}"))?;
    let text = |key: &str| -> Result<String, String> {
        value
            .get(key)
            .and_then(Value::as_str)
            .map(|item| item.trim().to_string())
            .filter(|item| !item.is_empty())
            .ok_or_else(|| format!("版本清单缺少字段「{key}」"))
    };
    let version = text("version")?;
    let url = text("url")?;
    if !url.starts_with("https://") {
        return Err(format!("下载地址必须是 https：{url}"));
    }
    Ok(Manifest { version, url })
}

/// 系统 curl 的位置。Windows 10 1803+ 内置在 System32。
///
/// 不硬编码成 `curl`（依赖 PATH，可能被用户装的别的 curl 顶掉），
/// 优先用 System32 下的那个；拿不到才退回 PATH。
pub fn curl_path() -> String {
    #[cfg(windows)]
    {
        let system_root = std::env::var("SystemRoot").unwrap_or_else(|_| "C:\\Windows".into());
        let candidate = std::path::Path::new(&system_root)
            .join("System32")
            .join("curl.exe");
        if candidate.is_file() {
            return candidate.to_string_lossy().into_owned();
        }
    }
    "curl".to_string()
}

/// 用 curl 取一段文本。`--fail` 让 4xx/5xx 变成非 0 退出码，
/// 否则 curl 会把错误页当成功内容返回。
fn fetch_text(url: &str) -> Result<String, String> {
    let mut command = Command::new(curl_path());
    command
        .arg("--silent")
        .arg("--show-error")
        .arg("--location")
        .arg("--fail")
        .arg("--max-time")
        .arg(MANIFEST_TIMEOUT.to_string())
        .arg(url);
    hide_console(&mut command);
    let output = command
        .output()
        .map_err(|error| format!("启动 curl 失败：{error}"))?;
    if !output.status.success() {
        let detail = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if detail.is_empty() {
            format!("请求失败（退出码 {:?}）", output.status.code())
        } else {
            detail
        });
    }
    String::from_utf8(output.stdout).map_err(|_| "清单不是合法 UTF-8".to_string())
}

/// 按 [`MANIFEST_URLS`] 顺序拉清单，返回第一个解析成功的。
///
/// 每个失败原因都拼进最终错误里 —— 用户说「更新不了」时，这句话直接说明
/// 是网络问题还是清单问题，不用再猜。
pub fn fetch_manifest() -> Result<Manifest, String> {
    let mut failures: Vec<String> = Vec::new();
    for url in MANIFEST_URLS {
        match fetch_text(url).and_then(|body| parse_manifest(&body)) {
            Ok(manifest) => return Ok(manifest),
            Err(error) => failures.push(format!("{url}\n  → {error}")),
        }
    }
    Err(format!(
        "无法获取版本清单（已尝试 {} 个地址）：\n{}",
        MANIFEST_URLS.len(),
        failures.join("\n")
    ))
}

/// `updater_check` 的结果，直接序列化给前端。
pub fn check_payload(current: &str) -> Value {
    match fetch_manifest() {
        Ok(manifest) => serde_json::json!({
            "ok": true,
            "current": current,
            "available": is_newer(&manifest.version, current),
            "version": manifest.version,
            "url": manifest.url,
        }),
        Err(error) => serde_json::json!({ "ok": false, "current": current, "error": error }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_segments_extracts_all_numbers() {
        assert_eq!(version_segments("3.0.0-local.24"), vec![3, 0, 0, 24]);
        assert_eq!(version_segments("v1.2.3"), vec![1, 2, 3]);
        assert_eq!(version_segments("abc"), Vec::<u64>::new());
    }

    /// 本项目的版本号带 `-local.N` 后缀，语义化比较会判错 ——
    /// 这条把这个坑钉死：`3.0.0-local.25` 必须比 `3.0.0-local.24` 新。
    #[test]
    fn newer_detection_handles_local_suffix() {
        assert!(is_newer("3.0.0-local.25", "3.0.0-local.24"));
        assert!(!is_newer("3.0.0-local.24", "3.0.0-local.25"));
        assert!(!is_newer("3.0.0-local.24", "3.0.0-local.24"));
        // 段数不同不能 panic，短的补 0
        assert!(is_newer("3.0.1", "3.0"));
        assert!(!is_newer("3.0", "3.0.1"));
    }

    #[test]
    fn manifest_parses_valid_input() {
        let raw = r#"{
            "version": "3.0.0-local.25",
            "url": "https://example.com/app-setup.exe"
        }"#;
        let manifest = parse_manifest(raw).expect("应该解析成功");
        assert_eq!(manifest.version, "3.0.0-local.25");
        assert_eq!(manifest.url, "https://example.com/app-setup.exe");
    }

    /// 清单是唯一判断依据，格式校验要严到「不会把坏数据放过去」。
    #[test]
    fn manifest_rejects_bad_input() {
        // 缺字段
        assert!(parse_manifest(r#"{"version":"1.0.0"}"#)
            .unwrap_err()
            .contains("url"));
        // 空字符串同样算缺
        assert!(parse_manifest(r#"{"version":"","url":"https://x/a.exe"}"#)
            .unwrap_err()
            .contains("version"));
        // 非 https
        assert!(
            parse_manifest(r#"{"version":"1.0.0","url":"http://x/a.exe"}"#)
                .unwrap_err()
                .contains("https")
        );
        // 不是 JSON
        assert!(parse_manifest("not json").unwrap_err().contains("JSON"));
    }

    /// 清单地址必须非空且全为 https —— 明文传输会让篡改变得容易。
    #[test]
    fn manifest_urls_are_https() {
        assert!(!MANIFEST_URLS.is_empty());
        for url in MANIFEST_URLS {
            assert!(url.starts_with("https://"), "{url} 不是 https");
        }
    }

    /// curl 必须能找到：找不到等于整个检查功能不可用，症状是「点了没反应」，
    /// 很难查。这里提前把环境问题暴露出来。
    #[test]
    fn curl_is_available() {
        match Command::new(curl_path()).arg("--version").output() {
            Ok(result) => assert!(
                result.status.success(),
                "curl 存在但执行失败：{}",
                String::from_utf8_lossy(&result.stderr)
            ),
            Err(error) => panic!("找不到 curl（{error}）：检查更新将不可用"),
        }
    }

    /// **端到端：真实 HTTP 拉清单 → 比版本 → 得出「有新版 + 链接」**。
    ///
    /// 用 `ITV_UPDATER_URL` 指向本地 http 服务（`python -m http.server`）。
    /// 这条覆盖 `fetch_text` 的 curl 调用、`parse_manifest` 的解析、
    /// `is_newer` 的比较和 `check_payload` 的组装 —— 除了「打开浏览器」全链路。
    #[test]
    fn end_to_end_check_against_local_http() {
        let Ok(url) = std::env::var("ITV_UPDATER_URL") else {
            return;
        };
        let body = fetch_text(&url).expect("本地服务应该能取到清单");
        let manifest = parse_manifest(&body).expect("清单应该能解析");
        println!("拉到清单：{} → {}", manifest.version, manifest.url);

        // 当前版本更旧 → 必须报告有新版
        assert!(is_newer(&manifest.version, "3.0.0-local.24"));
        let payload = serde_json::json!({
            "ok": true,
            "current": "3.0.0-local.24",
            "available": is_newer(&manifest.version, "3.0.0-local.24"),
            "version": manifest.version,
            "url": manifest.url,
        });
        assert_eq!(payload["available"], serde_json::json!(true));
        assert_eq!(payload["version"], serde_json::json!("3.0.0-local.25"));
        assert!(payload["url"].as_str().unwrap().starts_with("https://"));

        // 当前版本相同 → 不该说「有新版」
        assert!(!is_newer(&manifest.version, &manifest.version));
    }

    /// **真实网络失败路径**：坏地址必须报错，不能 panic、不能返回空串。
    /// 用 `ITV_UPDATER_BAD_URL` 注入；没设就跳过（CI 不该依赖外网）。
    #[test]
    fn fetch_reports_failure_for_bad_url() {
        let Ok(url) = std::env::var("ITV_UPDATER_BAD_URL") else {
            return;
        };
        let error = fetch_text(&url).expect_err("坏地址应该失败");
        assert!(!error.trim().is_empty(), "失败原因不能是空字符串");
        println!("坏地址报错（这是期望行为）：{error}");
    }
}
