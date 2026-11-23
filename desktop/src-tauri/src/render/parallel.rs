//! 按行分块的多线程辅助。
//!
//! 为什么不用 rayon：rayon 不在本机离线缓存里，而项目要求 `--offline` 构建。
//! `std::thread::scope` 是标准库自带的，零依赖、零体积增加。
//!
//! 安全性：调用方拿到的是**互不重叠的字节切片**，每个线程只写自己的那一段。
//! 由于 `chunks_mut` 保证区间不重叠，这里不需要任何锁或原子操作 ——
//! 这也是并行化不改变输出的前提。

/// 线程数上限。超过 8 个之后，1080p 一行的工作量已经小到被调度开销吃掉。
pub fn worker_count() -> usize {
    std::thread::available_parallelism()
        .map(|value| value.get())
        .unwrap_or(4)
        .clamp(1, 8)
}

/// 按行把帧切成若干块并行处理。
///
/// `handler` 收到 `(起始行, 该块的行数, 该块的字节切片)`。
/// 切片的长度必然是 `rows * width * 3`。
pub fn par_rows_mut<F>(frame: &mut super::pixels::BgrFrame, handler: F)
where
    F: Fn(usize, usize, &mut [u8]) + Sync,
{
    let width = frame.width as usize;
    let height = frame.height as usize;
    if width == 0 || height == 0 {
        return;
    }
    let row_bytes = width * 3;
    let workers = worker_count().min(height);
    if workers <= 1 {
        handler(0, height, &mut frame.data);
        return;
    }

    // 按行数均分，余数分摊到前几块，保证既不漏行也不重叠
    let rows_per_chunk = height.div_ceil(workers);
    let data = &mut frame.data;

    std::thread::scope(|scope| {
        for (index, chunk) in data.chunks_mut(rows_per_chunk * row_bytes).enumerate() {
            let start_row = index * rows_per_chunk;
            let rows = chunk.len() / row_bytes;
            let handler_ref = &handler;
            scope.spawn(move || handler_ref(start_row, rows, chunk));
        }
    });
}

/// 只读版本：把帧切成若干行区间并行读，结果写进互不重叠的输出块。
pub fn par_rows<F>(width: u32, height: u32, handler: F)
where
    F: Fn(usize, usize) + Sync,
{
    let height = height as usize;
    if width == 0 || height == 0 {
        return;
    }
    let workers = worker_count().min(height);
    if workers <= 1 {
        handler(0, height);
        return;
    }
    let rows_per_chunk = height.div_ceil(workers);
    std::thread::scope(|scope| {
        for index in 0..workers {
            let start_row = index * rows_per_chunk;
            if start_row >= height {
                break;
            }
            let rows = rows_per_chunk.min(height - start_row);
            let handler_ref = &handler;
            scope.spawn(move || handler_ref(start_row, rows));
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::render::pixels::BgrFrame;

    /// 分块必须完整覆盖所有行、且互不重叠 —— 少一行就是画面上的黑线。
    #[test]
    fn chunks_cover_every_row_exactly_once() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        for height in [1u32, 2, 3, 7, 8, 17, 96, 1080] {
            let mut frame = BgrFrame::new(4, height);
            // 每个 bit 代表一行，被处理两次就说明区间重叠
            let bitmask: Vec<AtomicUsize> =
                (0..height as usize).map(|_| AtomicUsize::new(0)).collect();
            par_rows_mut(&mut frame, |start, rows, chunk| {
                assert_eq!(chunk.len(), rows * 4 * 3, "切片长度与行数不符");
                for (row, counter) in bitmask.iter().enumerate().skip(start).take(rows) {
                    assert_eq!(
                        counter.fetch_add(1, Ordering::Relaxed),
                        0,
                        "第 {row} 行被处理了两次"
                    );
                }
            });
            for (row, counter) in bitmask.iter().enumerate() {
                assert_eq!(
                    counter.load(Ordering::Relaxed),
                    1,
                    "height={height} 时第 {row} 行漏掉了"
                );
            }
        }
    }

    /// 并行写完后，每个字节都应该被写过（初始值 0 会被覆盖成 0xFF）。
    #[test]
    fn every_byte_gets_written() {
        let mut frame = BgrFrame::new(5, 41);
        par_rows_mut(&mut frame, |_start, _rows, chunk| {
            chunk.fill(0xFF);
        });
        assert!(
            frame.data.iter().all(|byte| *byte == 0xFF),
            "存在没被写到的字节"
        );
    }

    /// 空帧不能 panic。
    #[test]
    fn empty_frame_is_safe() {
        let mut frame = BgrFrame::new(0, 0);
        par_rows_mut(&mut frame, |_start, _rows, _chunk| panic!("不应被调用"));
    }
}
