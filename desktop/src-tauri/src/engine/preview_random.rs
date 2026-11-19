//! 预览用的确定性洗牌，对齐 `src/engine/preview_random.py`。
//!
//! 「换一组看看」要求同一个序号永远抽出同一组图，所以这里必须**逐位复刻**
//! Python 的 `random.Random(seed).shuffle(items)` —— 不是「差不多随机」就行。
//!
//! 复刻三件事：
//! 1. **MT19937**（Mersenne Twister），与 CPython 的 `_randommodule.c` 同一实现；
//! 2. **`init_by_array` 播种**：seed 是 int 时，CPython 把它拆成 32 位小端分块再播种；
//! 3. **`shuffle` 的洗牌顺序**：从末尾往前，每步 `j = _randbelow(i+1)` 交换，
//!    而 `_randbelow(n)` 是「取 `n.bit_length()` 位随机数，拒绝采样到小于 n」。
//!
//! 任何一处不同，同一个序号抽出来的图就会变 —— 用户会觉得「换一组」的结果不对。

// 部分辅助函数（preview_sequence / is_audio 等）留给后续「渲染类预览接口」使用，
// 当前通过 dispatch 暴露的是子集，故先允许未使用。
#![allow(dead_code)]

const N: usize = 624;
const M: usize = 397;
const MATRIX_A: u32 = 0x9908_b0df;
const UPPER_MASK: u32 = 0x8000_0000;
const LOWER_MASK: u32 = 0x7fff_ffff;

/// MT19937 状态。
pub struct Mt19937 {
    state: [u32; N],
    index: usize,
}

impl Mt19937 {
    /// `init_genrand(s)`。
    fn init_genrand(seed: u32) -> Self {
        let mut state = [0u32; N];
        state[0] = seed;
        for i in 1..N {
            state[i] = 1812433253u32
                .wrapping_mul(state[i - 1] ^ (state[i - 1] >> 30))
                .wrapping_add(i as u32);
        }
        Mt19937 { state, index: N }
    }

    /// `init_by_array(key)` —— 与 CPython 处理 int seed 的方式一致。
    fn init_by_array(key: &[u32]) -> Self {
        let mut engine = Self::init_genrand(19650218);
        let key_length = key.len().max(1);
        let mut i = 1usize;
        let mut j = 0usize;
        let mut k = if N > key_length { N } else { key_length };
        while k > 0 {
            engine.state[i] = (engine.state[i]
                ^ (engine.state[i - 1] ^ (engine.state[i - 1] >> 30)).wrapping_mul(1_664_525))
            .wrapping_add(key[j])
            .wrapping_add(j as u32);
            i += 1;
            j += 1;
            if i >= N {
                engine.state[0] = engine.state[N - 1];
                i = 1;
            }
            if j >= key_length {
                j = 0;
            }
            k -= 1;
        }
        let mut k = N - 1;
        while k > 0 {
            engine.state[i] = (engine.state[i]
                ^ (engine.state[i - 1] ^ (engine.state[i - 1] >> 30)).wrapping_mul(1_566_083_941))
            .wrapping_sub(i as u32);
            i += 1;
            if i >= N {
                engine.state[0] = engine.state[N - 1];
                i = 1;
            }
            k -= 1;
        }
        engine.state[0] = 0x8000_0000;
        engine
    }

    /// 从 Python 的 int seed 播种（拆成 32 位小端分块）。
    pub fn from_u64_seed(seed: u64) -> Self {
        let key = if seed == 0 {
            vec![0u32]
        } else {
            let mut words = Vec::new();
            let mut value = seed;
            while value > 0 {
                words.push((value & 0xFFFF_FFFF) as u32);
                value >>= 32;
            }
            words
        };
        Self::init_by_array(&key)
    }

    /// `genrand_uint32()`。
    pub fn next_u32(&mut self) -> u32 {
        if self.index >= N {
            self.generate();
        }
        let mut value = self.state[self.index];
        self.index += 1;
        // tempering
        value ^= value >> 11;
        value ^= (value << 7) & 0x9d2c_5680;
        value ^= (value << 15) & 0xefc6_0000;
        value ^= value >> 18;
        value
    }

    fn generate(&mut self) {
        for i in 0..N {
            let y = (self.state[i] & UPPER_MASK) | (self.state[(i + 1) % N] & LOWER_MASK);
            let mut next = self.state[(i + M) % N] ^ (y >> 1);
            if y & 1 != 0 {
                next ^= MATRIX_A;
            }
            self.state[i] = next;
        }
        self.index = 0;
    }

    /// `getrandbits(k)`：k <= 32 时取 `next_u32() >> (32 - k)`；
    /// k > 32 时按 CPython 的方式拼多个 32 位字（最后一个右移补高位）。
    pub fn getrandbits(&mut self, k: u32) -> u64 {
        if k == 0 {
            return 0;
        }
        if k <= 32 {
            return (self.next_u32() >> (32 - k)) as u64;
        }
        let words = ((k - 1) / 32 + 1) as usize;
        let mut result: u64 = 0;
        let mut remaining = k;
        for _ in 0..words {
            let r = self.next_u32();
            let value = if remaining < 32 {
                (r >> (32 - remaining)) as u64
            } else {
                r as u64
            };
            result = (result << 32) | value;
            remaining = remaining.saturating_sub(32);
        }
        result
    }

    /// `_randbelow(n)`：拒绝采样，保证均匀。
    pub fn randbelow(&mut self, n: u64) -> u64 {
        if n == 0 {
            return 0;
        }
        let bits = 64 - n.leading_zeros();
        loop {
            let value = self.getrandbits(bits);
            if value < n {
                return value;
            }
        }
    }

    /// `random.Random.shuffle(x)`：从末尾往前，每步与 `[0, i]` 内随机位置交换。
    pub fn shuffle<T>(&mut self, items: &mut [T]) {
        if items.len() < 2 {
            return;
        }
        for i in (1..items.len()).rev() {
            let j = self.randbelow(i as u64 + 1) as usize;
            items.swap(i, j);
        }
    }
}

/// 与 `_shuffled()` 等价的种子：`sha256(f"{domain}\0{signature}")` 的前 8 字节（大端）。
pub fn shuffle_seed(domain: &str, items: &[String]) -> u64 {
    let signature = items.join("\0");
    let payload = format!("{domain}\0{signature}");
    let digest = crate::engine::hash::sha256(payload.as_bytes());
    let mut bytes = [0u8; 8];
    bytes.copy_from_slice(&digest[..8]);
    u64::from_be_bytes(bytes)
}

/// 与 `_shuffled()` 等价。
pub fn shuffled(items: &[String], domain: &str) -> Vec<String> {
    let mut values = items.to_vec();
    let seed = shuffle_seed(domain, items);
    let mut engine = Mt19937::from_u64_seed(seed);
    engine.shuffle(&mut values);
    values
}

/// 与 `preview_choice()` 等价。
pub fn preview_choice(items: &[String], sequence: i64, domain: &str) -> Option<String> {
    let values = shuffled(items, domain);
    if values.is_empty() {
        return None;
    }
    let offset = (sequence.max(1) - 1).max(0) as usize;
    Some(values[offset % values.len()].clone())
}

/// 与 `preview_sample()` 等价：先洗牌，再从 `offset` 开始循环取 `count` 个。
pub fn preview_sample(
    items: &[String],
    count: i64,
    sequence: i64,
    domain: &str,
) -> Vec<String> {
    let values = shuffled(items, domain);
    if values.is_empty() {
        return Vec::new();
    }
    let wanted = values.len().min(count.max(0) as usize);
    let offset = ((sequence.max(1) - 1).max(0) as usize) % values.len();
    let mut rotated = values[offset..].to_vec();
    rotated.extend_from_slice(&values[..offset]);
    rotated.truncate(wanted);
    rotated
}

#[cfg(test)]
mod tests {
    use super::*;

    fn items(names: &[&str]) -> Vec<String> {
        names.iter().map(|name| name.to_string()).collect()
    }

    #[test]
    fn mt19937_matches_reference_sequence() {
        // MT19937 用 seed=5489 的标准首三个输出（参考实现文档里的值）
        let mut engine = Mt19937::init_genrand(5489);
        assert_eq!(engine.next_u32(), 3_499_211_612);
        assert_eq!(engine.next_u32(), 581_869_302);
        assert_eq!(engine.next_u32(), 3_890_346_734);
    }

    #[test]
    fn getrandbits_zero_is_zero() {
        let mut engine = Mt19937::init_genrand(1);
        assert_eq!(engine.getrandbits(0), 0);
    }

    #[test]
    fn getrandbits_takes_high_bits() {
        let mut a = Mt19937::init_genrand(42);
        let mut b = Mt19937::init_genrand(42);
        let full = b.next_u32();
        // k=1 应取最高位
        assert_eq!(a.getrandbits(1), (full >> 31) as u64);
    }

    #[test]
    fn randbelow_stays_in_range() {
        let mut engine = Mt19937::init_genrand(7);
        for n in 1..50u64 {
            for _ in 0..20 {
                assert!(engine.randbelow(n) < n);
            }
        }
    }

    #[test]
    fn shuffle_is_deterministic_for_same_seed() {
        let mut first = Mt19937::init_genrand(123);
        let mut second = Mt19937::init_genrand(123);
        let mut a = items(&["a", "b", "c", "d", "e"]);
        let mut b = items(&["a", "b", "c", "d", "e"]);
        first.shuffle(&mut a);
        second.shuffle(&mut b);
        assert_eq!(a, b);
    }

    #[test]
    fn shuffle_keeps_all_elements() {
        let mut engine = Mt19937::init_genrand(99);
        let mut values = items(&["a", "b", "c", "d", "e", "f"]);
        engine.shuffle(&mut values);
        let mut sorted = values.clone();
        sorted.sort();
        assert_eq!(sorted, items(&["a", "b", "c", "d", "e", "f"]));
    }

    #[test]
    fn shuffled_is_stable_across_calls() {
        let values = items(&["x1.png", "x2.png", "x3.png", "x4.png"]);
        let first = shuffled(&values, "images");
        let second = shuffled(&values, "images");
        assert_eq!(first, second, "同一批输入必须永远抽出同一顺序");
    }

    #[test]
    fn different_domain_gives_different_order() {
        let values = items(&["a", "b", "c", "d", "e", "f", "g", "h"]);
        let images = shuffled(&values, "images");
        let bgm = shuffled(&values, "bgm");
        assert_ne!(images, bgm, "不同 domain 应洗出不同顺序");
    }

    #[test]
    fn preview_choice_wraps_around() {
        let values = items(&["a", "b", "c"]);
        let first = preview_choice(&values, 1, "images").unwrap();
        let fourth = preview_choice(&values, 4, "images").unwrap();
        assert_eq!(first, fourth, "序号 1 与 4 应落在同一位置（长度 3）");
    }

    #[test]
    fn preview_choice_treats_invalid_sequence_as_first() {
        let values = items(&["a", "b", "c"]);
        assert_eq!(
            preview_choice(&values, 0, "images"),
            preview_choice(&values, 1, "images")
        );
        assert_eq!(
            preview_choice(&values, -5, "images"),
            preview_choice(&values, 1, "images")
        );
    }

    #[test]
    fn preview_sample_rotates_from_offset() {
        let values = items(&["a", "b", "c", "d", "e"]);
        let all = preview_sample(&values, 5, 1, "images");
        let rotated = preview_sample(&values, 5, 2, "images");
        assert_eq!(all.len(), 5);
        // 第 2 组应是第 1 组左移一位
        let mut expected = all[1..].to_vec();
        expected.push(all[0].clone());
        assert_eq!(rotated, expected);
    }

    #[test]
    fn preview_sample_clamps_count() {
        let values = items(&["a", "b"]);
        assert_eq!(preview_sample(&values, 99, 1, "images").len(), 2);
        assert!(preview_sample(&values, 0, 1, "images").is_empty());
        assert!(preview_sample(&values, -3, 1, "images").is_empty());
    }

    #[test]
    fn empty_input_yields_empty_output() {
        assert!(shuffled(&[], "images").is_empty());
        assert!(preview_choice(&[], 1, "images").is_none());
        assert!(preview_sample(&[], 3, 1, "images").is_empty());
    }
}