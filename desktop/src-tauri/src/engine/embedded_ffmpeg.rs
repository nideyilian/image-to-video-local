//! 内嵌 FFmpeg：让免安装版成为**单个 exe**，双击即可用。
//!
//! ## 为什么需要这个
//!
//! 之前免安装版是「exe + resources/ffmpeg.exe」两个文件（合计 102MB）。
//! exe 只有 18MB，单独拷出去会因为找不到 ffmpeg 而无法导出 ——
//! 用户拿到手里还得整个文件夹一起搬，或者我们打 zip 让他解压。
//!
//! 现在把 ffmpeg 编进 exe（约 105MB 单文件），运行时按需释放到缓存目录。
//!
//! ## 为什么不每次解压
//!
//! 87MB 解压约 0.5-1 秒。用「大小 + 修改时间」做标记，只在首次或版本变化时
//! 释放一次，之后直接命中缓存 —— 后续启动零开销。
//!
//! ## 缓存位置
//!
//! `%LOCALAPPDATA%\image-to-video\ffmpeg-<大小>-<哈希前缀>.exe`
//!
//! 文件名带版本标识，升级软件后旧文件不会被误用（也不会被覆盖到一半）；
//! 旧版本残留由 [`cleanup_stale`] 在启动时清掉。
//!
//! ## 为什么不用 temp 目录
//!
//! Windows 的 `%TEMP%` 会被「磁盘清理」和其他程序动。ffmpeg 是我们渲染的
//! 核心依赖，丢了就得重新解压 87MB —— 放在 `%LOCALAPPDATA%` 更稳。

use std::path::PathBuf;

/// 编进二进制的 ffmpeg。
///
/// `include_bytes!` 要求编译期文件存在，所以 `build.rs` 里有一道检查
/// （`resources/ffmpeg.exe` 缺失会直接编译失败，而不是运行时才发现）。
static EMBEDDED_FFMPEG: &[u8] = include_bytes!("../../resources/ffmpeg.exe");

/// 缓存目录名（在 `%LOCALAPPDATA%` 下）。
const CACHE_DIR: &str = "image-to-video";

/// 缓存目录；拿不到 `%LOCALAPPDATA%` 时退回系统临时目录。
fn cache_dir() -> PathBuf {
    let base = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    base.join(CACHE_DIR)
}

/// 内嵌 ffmpeg 的指纹：大小 + 前 64KB 的 FNV 哈希。
///
/// 只哈希开头是为了启动快（全量哈希 87MB 要几百毫秒），
/// 而 ffmpeg 二进制的头部包含版本与编译信息，换个版本必然不同。
fn fingerprint() -> String {
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in EMBEDDED_FFMPEG.iter().take(64 * 1024) {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("{:016x}", hash)
}

/// 缓存文件名，带大小与指纹 —— 版本变了文件名就变，不会误用旧文件。
fn cached_name() -> String {
    format!("ffmpeg-{}-{}.exe", EMBEDDED_FFMPEG.len(), fingerprint())
}

/// 取出可用的 ffmpeg 路径；必要时把内嵌的那份释放到缓存目录。
///
/// 返回 `None` 只在磁盘写入失败时发生（权限问题 / 磁盘满），
/// 调用方仍可回退到「用户自己装的 ffmpeg」。
pub fn materialize() -> Option<PathBuf> {
    let directory = cache_dir();
    let target = directory.join(cached_name());

    // 已经释放过且大小对得上 —— 直接用，不解压
    if let Ok(metadata) = std::fs::metadata(&target) {
        if metadata.len() as usize == EMBEDDED_FFMPEG.len() {
            return Some(target);
        }
    }

    std::fs::create_dir_all(&directory).ok()?;

    // 先写临时名再改名：避免「写了一半被中断」留下一个残缺的 ffmpeg，
    // 下次启动看到文件存在就直接用了，结果渲染全失败。
    // 改成原子 rename 之后，残缺文件只会以 .tmp 形式存在，不影响判断。
    let staging = directory.join(format!("{}.tmp", cached_name()));
    std::fs::write(&staging, EMBEDDED_FFMPEG).ok()?;
    if std::fs::rename(&staging, &target).is_err() {
        // rename 失败（比如杀软占用）就退回直接写
        std::fs::write(&target, EMBEDDED_FFMPEG).ok()?;
        let _ = std::fs::remove_file(&staging);
    }

    Some(target)
}

/// 清掉本软件写过、但版本已经不同的旧 ffmpeg。
///
/// 只在启动时调一次。不删别的程序的东西 —— 只认
/// `ffmpeg-<数字>-<16位十六进制>.exe` 这个我们自己定的名字。
pub fn cleanup_stale() {
    let directory = cache_dir();
    let Ok(entries) = std::fs::read_dir(&directory) else {
        return;
    };
    let keep = cached_name();
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().to_string();
        if !name.starts_with("ffmpeg-") || !name.ends_with(".exe") {
            continue;
        }
        if name == keep {
            continue;
        }
        // 只删符合我们命名规则的
        let stem = &name[7..name.len() - 4];
        let mut parts = stem.split('-');
        let (Some(size), Some(hash)) = (parts.next(), parts.next()) else {
            continue;
        };
        if size.parse::<usize>().is_err() || hash.len() != 16 {
            continue;
        }
        if !hash.chars().all(|c| c.is_ascii_hexdigit()) {
            continue;
        }
        let _ = std::fs::remove_file(entry.path());
    }
    // 顺手清掉可能的半成品
    if let Ok(entries) = std::fs::read_dir(&directory) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with("ffmpeg-") && name.ends_with(".exe.tmp") {
                let _ = std::fs::remove_file(entry.path());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 内嵌的二进制必须是完整的 exe（至少能看出 PE 头）。
    ///
    /// 这条能抓到「resources/ffmpeg.exe 被 gitignore 清掉后编了个空文件」——
    /// 那种情况编译能过，运行时才发现所有导出失败。
    #[test]
    fn embedded_binary_looks_like_an_exe() {
        assert!(EMBEDDED_FFMPEG.len() > 10 * 1024 * 1024, "内嵌的 ffmpeg 太小，可能不是真文件");
        assert_eq!(&EMBEDDED_FFMPEG[..2], b"MZ", "不是 PE 可执行文件");
    }

    /// 缓存名必须随内容变化 —— 否则升级后会用旧 ffmpeg。
    #[test]
    fn cache_name_includes_size_and_hash() {
        let name = cached_name();
        assert!(name.starts_with("ffmpeg-"));
        assert!(name.ends_with(".exe"));
        let stem = &name[7..name.len() - 4];
        let parts: Vec<&str> = stem.split('-').collect();
        assert_eq!(parts.len(), 2, "名字格式应为 ffmpeg-<大小>-<哈希>");
        assert_eq!(parts[0].parse::<usize>().unwrap(), EMBEDDED_FFMPEG.len());
        assert_eq!(parts[1].len(), 16);
    }

    /// 指纹要稳定：同一份二进制两次算出来必须一样。
    #[test]
    fn fingerprint_is_stable() {
        assert_eq!(fingerprint(), fingerprint());
    }

    /// 释放出来的文件必须与内嵌内容逐字节一致。
    ///
    /// 这条是核心保证：如果释放过程截断/损坏了，导出的视频会随机出错，
    /// 而错误信息通常只是「ffmpeg 退出码非 0」，极难排查。
    #[test]
    fn materialize_writes_identical_bytes() {
        let Some(path) = materialize() else {
            // 无写权限的 CI 环境跳过
            return;
        };
        let written = std::fs::read(&path).expect("应该能读回");
        assert_eq!(written.len(), EMBEDDED_FFMPEG.len(), "大小不一致");
        assert_eq!(written, EMBEDDED_FFMPEG, "内容不一致");
    }

    /// 第二次调用必须命中缓存（不再重写）。用修改时间判断。
    #[test]
    fn second_call_reuses_cache() {
        let Some(first) = materialize() else {
            return;
        };
        let before = std::fs::metadata(&first).and_then(|m| m.modified()).ok();
        std::thread::sleep(std::time::Duration::from_millis(20));
        let Some(second) = materialize() else {
            return;
        };
        assert_eq!(first, second);
        let after = std::fs::metadata(&second).and_then(|m| m.modified()).ok();
        assert_eq!(before, after, "第二次调用不该重写文件");
    }

    /// 清理只动我们自己命名的文件，别人的东西不碰。
    #[test]
    fn cleanup_only_touches_our_own_files() {
        let directory = cache_dir();
        if std::fs::create_dir_all(&directory).is_err() {
            return;
        }
        let foreign = directory.join("keep-me-please.txt");
        let _ = std::fs::write(&foreign, b"x");
        let stale = directory.join("ffmpeg-123-0123456789abcdef.exe");
        let _ = std::fs::write(&stale, b"old");
        cleanup_stale();
        assert!(foreign.exists(), "不该删除非本软件的文件");
        assert!(!stale.exists(), "旧版本 ffmpeg 应被清掉");
        let _ = std::fs::remove_file(&foreign);
    }
}