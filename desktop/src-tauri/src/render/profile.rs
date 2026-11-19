//! 特效各阶段耗时探针。仅在设置 `ITV_PROFILE=1` 时输出，正常渲染零开销。
//!
//! 存在的意义：不要凭猜测优化。上一轮我猜 `warp_affine` 是热点，
//! 并行化之后**一秒都没快** —— 真正的热点是 `resize` 里的三次整幅遍历。
//!
//! 用法：`ITV_PROFILE=1 cargo test --release --lib parity_run_batch -- --nocapture`

use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;

static RESIZE_NS: AtomicU64 = AtomicU64::new(0);
static WARP_NS: AtomicU64 = AtomicU64::new(0);
static BLUR_NS: AtomicU64 = AtomicU64::new(0);
static RESIZE_CALLS: AtomicU64 = AtomicU64::new(0);
static WARP_CALLS: AtomicU64 = AtomicU64::new(0);

pub fn enabled() -> bool {
    std::env::var("ITV_PROFILE").is_ok()
}

/// 给一段计算计时，并累加到对应的计数器上。
pub fn measure<T>(slot: &str, run: impl FnOnce() -> T) -> T {
    if !enabled() {
        return run();
    }
    let start = Instant::now();
    let value = run();
    let elapsed = start.elapsed().as_nanos() as u64;
    let counter = match slot {
        "resize" => &RESIZE_NS,
        "warp" => &WARP_NS,
        _ => &BLUR_NS,
    };
    counter.fetch_add(elapsed, Ordering::Relaxed);
    match slot {
        "resize" => RESIZE_CALLS.fetch_add(1, Ordering::Relaxed),
        "warp" => WARP_CALLS.fetch_add(1, Ordering::Relaxed),
        _ => 0,
    };
    value
}

pub fn report() -> String {
    if !enabled() {
        return String::new();
    }
    let resize = RESIZE_NS.load(Ordering::Relaxed) as f64 / 1e9;
    let warp = WARP_NS.load(Ordering::Relaxed) as f64 / 1e9;
    let blur = BLUR_NS.load(Ordering::Relaxed) as f64 / 1e9;
    format!(
        "[PROFILE] resize={resize:.2}s ({} 次)  warp={warp:.2}s ({} 次)  blur={blur:.2}s",
        RESIZE_CALLS.load(Ordering::Relaxed),
        WARP_CALLS.load(Ordering::Relaxed),
    )
}

pub fn reset() {
    RESIZE_NS.store(0, Ordering::Relaxed);
    WARP_NS.store(0, Ordering::Relaxed);
    BLUR_NS.store(0, Ordering::Relaxed);
    RESIZE_CALLS.store(0, Ordering::Relaxed);
    WARP_CALLS.store(0, Ordering::Relaxed);
}
