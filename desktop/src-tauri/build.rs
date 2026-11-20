//! 构建脚本。
//!
//! ## 一个必须显式声明的依赖（踩过坑）
//!
//! `tauri_build::build()` 会在编译期把 `frontendDist`（`../dist`）里的前端资源
//! **快照**成 Rust 代码（`tauri-codegen-assets/`）。之后即使 `npm run build`
//! 重新生成了 dist，Cargo 也**不知道这些文件变了** —— 它只看 Rust 源码和
//! `rerun-if-changed` 声明的路径。
//!
//! 后果很隐蔽：Rust 代码全对、命令行能跑通，但打进 exe 的前端还是旧版 ——
//! 用户看到的是「新功能没生效」，而所有后端测试都是绿的。
//!
//! 所以这里显式声明：dist 下任何文件变化都要重跑本脚本，
//! 从而触发资源重新快照。
//!
//! ⚠️ 与 `tauri.conf.json` 的 `beforeBuildCommand` 配合：
//! 它是「先 build 前端、再 build Rust」，顺序本身是对的；
//! 这里补的是 Cargo 层面的失效检测。

use std::path::Path;

fn main() {
    // 前端资源目录：任何文件变动都让本脚本重跑，进而重新嵌入资源。
    let dist = Path::new("../dist");
    println!("cargo:rerun-if-changed={}", dist.display());
    println!("cargo:rerun-if-changed=../dist/index.html");

    // 逐个文件声明一遍 —— 某些文件系统上「只改文件不改目录 mtime」
    // 会让目录级监听漏检，而前端每次构建都会改文件名（内容哈希），
    // 所以这里必须逐个列出来。
    if let Ok(entries) = std::fs::read_dir(dist.join("assets")) {
        for entry in entries.flatten() {
            println!("cargo:rerun-if-changed={}", entry.path().display());
        }
    }

    // 内嵌的 ffmpeg 换了也要重编（否则 exe 里还是旧 ffmpeg）
    println!("cargo:rerun-if-changed=resources/ffmpeg.exe");

    // tauri.conf.json 改了（比如 bundle.resources）也要重跑
    println!("cargo:rerun-if-changed=tauri.conf.json");

    tauri_build::build()
}
