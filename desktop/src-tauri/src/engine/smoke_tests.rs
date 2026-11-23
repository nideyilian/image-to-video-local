//! 全接口冒烟检查：`cargo test --lib smoke_all_interfaces -- --nocapture`
//!
//! 目的不是替代单元测试，而是用**真实素材**把 45 个接口各打一遍，
//! 确认没有「能编译、能跑单测，但真实参数下报错/返回空」的情况。
//!
//! 素材目录由 `ITV_SMOKE_DIR` 指定（含 images/ 与 bgm1.wav）；
//! 素材库类接口全部指向临时目录，**不碰用户真实素材库**。

use serde_json::{json, Value};

use super::*;

#[derive(Default)]
struct Report {
    ok: usize,
    expected: Vec<String>,
    failed: Vec<String>,
}

#[test]
fn smoke_all_interfaces() {
    let Ok(base) = std::env::var("ITV_SMOKE_DIR") else {
        eprintln!("跳过：未设置 ITV_SMOKE_DIR");
        return;
    };
    let images_dir = format!("{base}/images");
    let bgm_file = format!("{base}/bgm1.wav");
    let lib = format!("{base}/library");
    let _ = std::fs::create_dir_all(format!("{lib}/BGM"));
    let _ = std::fs::create_dir_all(format!("{lib}/水印"));
    let lib_bgm = format!("{lib}/BGM");
    let lib_wm = format!("{lib}/水印");

    let mut report = Report::default();
    let check = |report: &mut Report, label: &str, method: &str, params: Value| {
        let response = dispatch(method, Some(params));
        if !response.handled {
            report
                .failed
                .push(format!("{label}: handled=false（未接管）"));
            return;
        }
        if let Some(error) = response.error {
            report.failed.push(format!("{label}: error={error}"));
            return;
        }
        match response.result {
            Some(value) => {
                report.ok += 1;
                let brief = serde_json::to_string(&value).unwrap_or_default();
                let snippet: String = brief.chars().take(110).collect();
                println!("OK  {label:38} {snippet}");
            }
            None => report.failed.push(format!("{label}: 无 result")),
        }
    };

    // 预期内的业务报错（参数不满足前置条件）。这类返回 `handled=true + error` 是
    // **正确行为**，必须与「本不该报错却报错」区分开，否则冒烟结果没法看。
    let check_rejects =
        |report: &mut Report, label: &str, method: &str, params: Value, expect: &str| {
            let response = dispatch(method, Some(params));
            if !response.handled {
                report
                    .failed
                    .push(format!("{label}: handled=false（未接管）"));
                return;
            }
            match response.error {
                Some(error) if error.contains(expect) => {
                    report
                        .expected
                        .push(format!("{label}: 已按预期拒绝（{error}）"));
                    println!("REJ {label:38} {error}");
                }
                Some(error) => report.failed.push(format!(
                    "{label}: 报错但信息不符，期望含「{expect}」，实际「{error}」"
                )),
                None => report
                    .failed
                    .push(format!("{label}: 期望被拒绝，却返回了成功")),
            }
        };

    // ---- 基础 / 配置 ----
    check(&mut report, "native_health", "native_health", json!({}));
    check(&mut report, "default_config", "default_config", json!({}));
    check(
        &mut report,
        "normalize_config",
        "normalize_config",
        json!({ "config": { "input_dir": images_dir, "output_dir": format!("{base}/out") } }),
    );
    check(
        &mut report,
        "validate_config",
        "validate_config",
        json!({ "config": { "input_dir": images_dir, "output_dir": format!("{base}/out") } }),
    );
    check(
        &mut report,
        "validate_config_detailed",
        "validate_config_detailed",
        json!({ "config": { "input_dir": images_dir, "output_dir": format!("{base}/out") } }),
    );

    // ---- 扫描 ----
    check(
        &mut report,
        "scan_images",
        "scan_images",
        json!({ "input_dir": images_dir }),
    );
    check(
        &mut report,
        "scan_images(limit)",
        "scan_images",
        json!({ "input_dir": images_dir, "limit": 3 }),
    );
    check(
        &mut report,
        "scan_images(seq)",
        "scan_images",
        json!({ "input_dir": images_dir, "limit": 3, "preview_sequence": 2 }),
    );
    check(
        &mut report,
        "scan_subfolders",
        "scan_subfolders",
        json!({ "input_dir": images_dir }),
    );
    check(
        &mut report,
        "scan_subfolder_groups",
        "scan_subfolder_groups",
        json!({ "input_dir": images_dir }),
    );
    check(
        &mut report,
        "scan_subfolder_groups(seq)",
        "scan_subfolder_groups",
        json!({ "input_dir": images_dir, "preview_sequence": 2 }),
    );
    check(
        &mut report,
        "scan_images(不存在目录)",
        "scan_images",
        json!({ "input_dir": format!("{base}/不存在") }),
    );

    // ---- 系统 ----
    check(
        &mut report,
        "system_snapshot",
        "system_snapshot",
        json!({ "output_dir": base }),
    );
    check(&mut report, "optimize_memory", "optimize_memory", json!({}));

    // ---- 素材库 只读 ----
    check(&mut report, "library_dirs", "library_dirs", json!({}));
    check(
        &mut report,
        "library_snapshot",
        "library_snapshot",
        json!({ "bgm_dir": lib_bgm, "watermark_dir": lib_wm }),
    );
    check(
        &mut report,
        "library_get_tags",
        "library_get_tags",
        json!({ "kind": "bgm", "bgm_dir": lib_bgm }),
    );
    check(
        &mut report,
        "library_smart_folders_list",
        "library_smart_folders_list",
        json!({ "bgm_dir": lib_bgm, "watermark_dir": lib_wm }),
    );
    // 查重需要真的有重复素材：等主素材导入后再补一份同内容、不同文件名的。
    // （顺序不能提前 —— 先导入重复件会让主素材被判重而拒绝入库，后面全部连锁失败。）
    check(
        &mut report,
        "library_scan_tainted",
        "library_scan_tainted",
        json!({ "kind": "bgm", "bgm_dir": lib_bgm }),
    );

    // ---- 素材库 写操作（全部落在临时目录）----
    check(
        &mut report,
        "library_create_folder",
        "library_create_folder",
        json!({ "kind": "bgm", "bgm_dir": lib_bgm, "folder": "测试夹" }),
    );
    check(
        &mut report,
        "library_import",
        "library_import",
        json!({ "kind": "bgm", "bgm_dir": lib_bgm, "paths": [bgm_file] }),
    );
    // 同内容、不同文件名的第二份：用于验证查重真能认出重复。
    check(
        &mut report,
        "library_import(重复素材)",
        "library_import",
        json!({ "kind": "bgm", "bgm_dir": lib_bgm, "paths": [format!("{base}/bgm_dup.wav")] }),
    );
    // 查重接口要有「重复组」才会走非空分支。`library_import` 会在入口拦下重复件，
    // 所以这里直接往库里塞一份同内容的副本，模拟「历史遗留的两条重复」。
    let _ = std::fs::copy(
        format!("{lib_bgm}/bgm1.wav"),
        format!("{lib_bgm}/bgm1-副本.wav"),
    );
    check(
        &mut report,
        "library_find_duplicates",
        "library_find_duplicates",
        json!({ "kind": "bgm", "bgm_dir": lib_bgm }),
    );
    let _ = std::fs::remove_file(format!("{lib_bgm}/bgm1-副本.wav"));
    check(
        &mut report,
        "library_snapshot(导入后)",
        "library_snapshot",
        json!({ "bgm_dir": lib_bgm, "watermark_dir": lib_wm }),
    );
    check(
        &mut report,
        "library_set_metadata",
        "library_set_metadata",
        json!({
            "kind": "bgm", "bgm_dir": lib_bgm,
            "path": format!("{lib_bgm}/bgm1.wav"),
            "tags": ["测试"], "starred": true, "note": "冒烟"
        }),
    );
    check(
        &mut report,
        "library_rename",
        "library_rename",
        json!({
            "kind": "bgm", "bgm_dir": lib_bgm,
            "path": format!("{lib_bgm}/bgm1.wav"), "new_name": "改名后.wav"
        }),
    );
    check(
        &mut report,
        "library_rename_batch",
        "library_rename_batch",
        json!({
            "kind": "bgm", "bgm_dir": lib_bgm,
            "paths": [format!("{lib_bgm}/改名后.wav")], "pattern": "重命名-{n}"
        }),
    );
    check(
        &mut report,
        "library_move",
        "library_move",
        json!({
            "kind": "bgm", "bgm_dir": lib_bgm,
            "paths": [format!("{lib_bgm}/重命名-1.wav")], "folder": "测试夹"
        }),
    );
    check(
        &mut report,
        "library_rename_folder",
        "library_rename_folder",
        json!({ "kind": "bgm", "bgm_dir": lib_bgm, "folder": "测试夹", "new_name": "改后夹" }),
    );
    check_rejects(
        &mut report,
        "library_clean_tainted(空选择)",
        "library_clean_tainted",
        json!({ "paths": [] }),
        "请先选择要清洗的文件",
    );
    check(
        &mut report,
        "library_remove_batch",
        "library_remove_batch",
        json!({
            "kind": "bgm", "bgm_dir": lib_bgm,
            "paths": [format!("{lib_bgm}/改后夹/重命名-1.wav")]
        }),
    );
    check(
        &mut report,
        "library_delete_folder",
        "library_delete_folder",
        json!({ "kind": "bgm", "bgm_dir": lib_bgm, "folder": "改后夹" }),
    );
    check_rejects(
        &mut report,
        "library_remove(库外文件)",
        "library_remove",
        json!({ "kind": "bgm", "bgm_dir": lib_bgm, "path": format!("{base}/bgm1.wav") }),
        "只能删除素材库内的文件",
    );

    // ---- 预览 ----
    check(
        &mut report,
        "preview_thumbnail",
        "preview_thumbnail",
        json!({ "path": format!("{images_dir}/p1.png") }),
    );
    check(
        &mut report,
        "preview_thumbnail(无参)",
        "preview_thumbnail",
        json!({ "input_dir": images_dir }),
    );
    check(
        &mut report,
        "library_audio_cover",
        "library_audio_cover",
        json!({ "path": bgm_file }),
    );
    check(
        &mut report,
        "library_preview_audio",
        "library_preview_audio",
        json!({ "path": bgm_file }),
    );
    // BGM 预览：`use_bgm` 才是开关（`bgm_enabled` 是界面字段名，引擎不认）。
    // 用未被「重命名 → 移动 → 删除」流程碰过的独立文件，否则路径早已不存在。
    let bgm_independent = format!("{base}/bgm_dup.wav");
    check(
        &mut report,
        "preview_bgm",
        "preview_bgm",
        json!({
            "config": json!({
                "input_dir": images_dir,
                "output_dir": format!("{base}/out"),
                "use_bgm": true,
                "watermark_audio": "使用BGM",
                "bgm_files": [bgm_independent],
                "duration": 4,
                "image_duration": 2,
            }),
            "preview_sequence": 1
        }),
    );

    // ---- 特效预览 ----
    check(
        &mut report,
        "effect_library_assets",
        "effect_library_assets",
        json!({}),
    );
    let eff_cfg = json!({
        "input_dir": images_dir,
        "output_dir": format!("{base}/out"),
        "video_effect_enabled": false,
        "use_transition": false,
    });
    check(
        &mut report,
        "preview_effect_frame",
        "preview_effect_frame",
        json!({
            "path": format!("{images_dir}/p1.png"),
            "config": eff_cfg,
            "time_sec": 0.2,
            "max_width": 480, "max_height": 270
        }),
    );
    check(
        &mut report,
        "effect_preview_animation",
        "effect_preview_animation",
        json!({ "name": "淡入淡出", "kind": "transition", "width": 240, "height": 135 }),
    );

    // ---- 任务队列 ----
    check(&mut report, "list_jobs", "list_jobs", json!({}));
    for method in ["pause_job", "resume_job", "cancel_job"] {
        check_rejects(
            &mut report,
            &format!("{method}(不存在)"),
            method,
            json!({ "job_id": "不存在的任务" }),
            "任务不存在",
        );
    }

    // ---- 拆 BGM（后台任务）----
    // 正常路径需要视频文件；这里用一个不存在的路径，确认它按预期拒绝而不是崩。
    check_rejects(
        &mut report,
        "library_extract_bgm(无视频)",
        "library_extract_bgm",
        json!({ "bgm_dir": lib_bgm, "paths": [format!("{base}/不存在.mp4")] }),
        "没有找到可处理的视频文件",
    );
    check_rejects(
        &mut report,
        "library_extract_cancel(无任务)",
        "library_extract_cancel",
        json!({ "task_id": "不存在的拆解任务" }),
        "拆 BGM 任务不存在",
    );

    println!(
        "\n===== 冒烟结果：通过 {} / 预期拒绝 {} / 异常 {} =====",
        report.ok,
        report.expected.len(),
        report.failed.len()
    );
    for item in &report.expected {
        println!("REJ  {item}");
    }
    for item in &report.failed {
        println!("FAIL {item}");
    }
    assert!(
        report.failed.is_empty(),
        "存在未通过的接口：{:#?}",
        report.failed
    );
}
