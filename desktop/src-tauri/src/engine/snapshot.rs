//! 素材库索引与快照，对齐 `src/engine/library.py` 的 `_scan_tree` / `snapshot`。
//!
//! 每个目录一个 `.library_index.json`，按 `mtime_ns + size` 判断是否需要重算；
//! 重算时补 SHA-256、时长、BGM 指纹，并把 `added_at` 记成首次入库时间。
//!
//! 两个容易踩的点：
//! 1. `fs::rename` 在 Windows 上不能覆盖已存在文件，写索引要「失败再删再写」；
//! 2. 素材库的图片扩展名比「选图」多一个 `.gif`，音频多 `.wma/.aiff` —— 两套别混用。

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use serde_json::{json, Map, Value};

use super::fingerprint;
use super::hash;
use super::library;
use super::paths;
use super::system;

pub(crate) const INDEX_FILE_NAME: &str = ".library_index.json";

pub const AUDIO_EXTENSIONS: [&str; 8] = [
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma", ".aiff",
];
pub const IMAGE_EXTENSIONS: [&str; 7] = [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"];
pub const VIDEO_EXTENSIONS: [&str; 14] = [
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm", ".m4v", ".ts", ".mpg", ".mpeg", ".3gp",
    ".rmvb", ".f4v",
];

fn cached_ffmpeg() -> Option<&'static Path> {
    static CACHE: OnceLock<Option<PathBuf>> = OnceLock::new();
    CACHE.get_or_init(|| system::resolve_ffmpeg(None)).as_deref()
}

fn cached_ffprobe() -> Option<&'static Path> {
    static CACHE: OnceLock<Option<PathBuf>> = OnceLock::new();
    CACHE
        .get_or_init(|| {
            let ffmpeg = cached_ffmpeg().map(Path::to_path_buf);
            system::resolve_ffprobe(None, ffmpeg.as_deref())
        })
        .as_deref()
}

pub(crate) fn has_extension(path: &Path, extensions: &[&str]) -> bool {
    match path.extension().and_then(|ext| ext.to_str()) {
        Some(ext) => {
            let lowered = format!(".{}", ext.to_lowercase());
            extensions.contains(&lowered.as_str())
        }
        None => false,
    }
}

fn is_audio(path: &Path) -> bool {
    has_extension(path, &AUDIO_EXTENSIONS)
}

fn is_video(path: &Path) -> bool {
    has_extension(path, &VIDEO_EXTENSIONS)
}

fn file_name(path: &Path) -> String {
    path.file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default()
}

/// 与 Python `time.strftime("%Y-%m-%d %H:%M:%S")` 等价的本地时间。
#[cfg(windows)]
pub(crate) fn now_iso() -> String {
    #[repr(C)]
    #[derive(Default)]
    struct LocalFileTime {
        year: u16,
        month: u16,
        day_of_week: u16,
        day: u16,
        hour: u16,
        minute: u16,
        second: u16,
        milliseconds: u16,
    }
    extern "system" {
        fn GetLocalTime(time: *mut LocalFileTime);
    }
    let mut time = LocalFileTime::default();
    unsafe { GetLocalTime(&mut time) };
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
        time.year, time.month, time.day, time.hour, time.minute, time.second
    )
}

#[cfg(not(windows))]
pub(crate) fn now_iso() -> String {
    // 非 Windows 只做兜底（项目仅发 Windows 安装包），格式仍保持 YYYY-MM-DD HH:MM:SS。
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_secs())
        .unwrap_or(0);
    format!("{seconds}")
}

pub(crate) fn modified_ns(metadata: &fs::Metadata) -> i64 {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        // FILETIME：1601-01-01 起的 100ns 计数；Python 的 st_mtime_ns 是 Unix 纳秒。
        const EPOCH_DIFFERENCE: i64 = 116_444_736_000_000_000;
        let file_time = metadata.last_write_time() as i64;
        (file_time - EPOCH_DIFFERENCE) * 100
    }
    #[cfg(not(windows))]
    {
        metadata
            .modified()
            .ok()
            .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|duration| duration.as_nanos() as i64)
            .unwrap_or(0)
    }
}

#[derive(Debug, Default)]
pub(crate) struct Index {
    pub version: i64,
    pub kind: Option<String>,
    pub entries: Map<String, Value>,
}

pub(crate) fn load_index(directory: &Path) -> Index {
    let data: Value = fs::read_to_string(directory.join(INDEX_FILE_NAME))
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or(Value::Null);
    let version = data.get("version").and_then(Value::as_i64).unwrap_or(1);
    Index {
        // Python: int(data.get("version", 1) or 1) —— 0 也当 1
        version: if version == 0 { 1 } else { version },
        kind: data
            .get("kind")
            .and_then(Value::as_str)
            .map(str::to_string),
        entries: data
            .get("entries")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default(),
    }
}

pub(crate) fn save_index(directory: &Path, index: &Index) -> std::io::Result<()> {
    let target = directory.join(INDEX_FILE_NAME);
    let temporary = directory.join(format!(".{INDEX_FILE_NAME}.{}.tmp", std::process::id()));
    let payload = json!({
        "version": index.version,
        "kind": index.kind,
        "entries": index.entries,
    });
    fs::write(&temporary, format!("{}\n", serde_json::to_string_pretty(&payload)?))?;
    // Windows 上 rename 不能覆盖已存在文件；失败时先删再写（索引可重建，非致命）。
    if fs::rename(&temporary, &target).is_err() {
        let _ = fs::remove_file(&target);
        fs::rename(&temporary, &target)?;
    }
    Ok(())
}

fn relative_folder(base: &Path, directory: &Path) -> String {
    directory
        .strip_prefix(base)
        .map(|value| value.to_string_lossy().replace('\\', "/"))
        .unwrap_or_default()
}

struct ScanState<'a> {
    base: &'a Path,
    kind: &'a str,
    items: Vec<Value>,
    direct_counts: BTreeMap<String, usize>,
    all_dirs: Vec<String>,
}

fn walk(state: &mut ScanState, directory: &Path) {
    let folder = relative_folder(state.base, directory);
    state.all_dirs.push(folder.clone());

    let Ok(read_dir) = fs::read_dir(directory) else {
        return;
    };
    let mut dirs: Vec<PathBuf> = Vec::new();
    let mut files: Vec<PathBuf> = Vec::new();
    for entry in read_dir.flatten() {
        let path = entry.path();
        if path.is_dir() {
            dirs.push(path);
        } else {
            files.push(path);
        }
    }
    // Python: dirnames.sort(key=str.lower) / sorted(filenames, key=str.lower)
    dirs.sort_by_key(|path| file_name(path).to_lowercase());
    files.sort_by_key(|path| file_name(path).to_lowercase());

    let mut index = load_index(directory);
    let mut changed = false;

    for path in files {
        let name = file_name(&path);
        if name.starts_with('.') {
            continue;
        }
        let supported = if state.kind == "bgm" {
            is_audio(&path)
        } else {
            has_extension(&path, &IMAGE_EXTENSIONS) || is_video(&path)
        };
        if !supported {
            continue;
        }
        let Ok(metadata) = fs::metadata(&path) else {
            continue;
        };
        let size = metadata.len();
        let mtime_ns = modified_ns(&metadata);

        let cached = index
            .entries
            .get(&name)
            .filter(|entry| {
                entry.get("mtime_ns").and_then(Value::as_i64) == Some(mtime_ns)
                    && entry.get("size").and_then(Value::as_u64) == Some(size)
            })
            .cloned();

        let entry = match cached {
            Some(entry) => entry,
            None => {
                let sha256 = hash::file_sha256(&path).unwrap_or_default();
                let mut duration: Option<f64> = None;
                let mut media_type = "image";
                let mut signature: Option<Vec<f64>> = None;
                if state.kind == "bgm" {
                    if let Some(result) = fingerprint::compute(cached_ffmpeg(), &path) {
                        duration = Some(result.duration);
                        signature = Some(result.signature);
                    }
                } else if is_video(&path) {
                    media_type = "video";
                    duration = system::probe_duration(cached_ffprobe(), &path);
                }
                let mut entry = json!({
                    "sha256": sha256,
                    "duration": duration,
                    "type": media_type,
                    "added_at": now_iso(),
                    "mtime_ns": mtime_ns,
                    "size": size,
                });
                if let Some(signature) = signature {
                    entry["signature"] = json!(signature);
                }
                index.entries.insert(name.clone(), entry.clone());
                changed = true;
                entry
            }
        };

        *state.direct_counts.entry(folder.clone()).or_insert(0) += 1;
        let default_type = if state.kind == "bgm" { "audio" } else { "image" };
        state.items.push(json!({
            "name": name,
            "path": paths::to_string(&paths::absolute(&path)),
            "folder": folder,
            "type": entry.get("type").and_then(Value::as_str).unwrap_or(default_type),
            "size_bytes": size,
            "duration": entry.get("duration").cloned().unwrap_or(Value::Null),
            "added_at": entry.get("added_at").cloned().unwrap_or(Value::Null),
            "duplicate_key": entry.get("sha256").and_then(Value::as_str).unwrap_or(""),
            "tags": match entry.get("tags") {
                Some(Value::Array(items)) => Value::Array(items.clone()),
                _ => json!([]),
            },
            "starred": entry.get("starred").and_then(Value::as_bool).unwrap_or(false),
            "note": entry.get("note").and_then(Value::as_str).unwrap_or(""),
        }));
    }

    if changed {
        let _ = save_index(directory, &index);
    }

    for child in dirs {
        walk(state, &child);
    }
}

fn folders_of(state: &ScanState) -> Vec<Value> {
    let mut dirs = state.all_dirs.clone();
    // Python: sorted(all_dirs) —— 默认字符串排序（区分大小写、按码点）
    dirs.sort();
    dirs.into_iter()
        .filter(|folder| !folder.is_empty())
        .map(|folder| {
            let prefix = format!("{folder}/");
            let count: usize = state
                .direct_counts
                .iter()
                .filter(|(key, _)| *key == &folder || key.starts_with(&prefix))
                .map(|(_, value)| *value)
                .sum();
            let name = folder.rsplit('/').next().unwrap_or(&folder).to_string();
            json!({
                "relative": folder,
                "name": name,
                "path": paths::to_string(&paths::absolute(&state.base.join(&folder))),
                "count": count,
            })
        })
        .collect()
}

fn scan_tree(base: &Path, kind: &str) -> (Vec<Value>, Vec<Value>) {
    let mut state = ScanState {
        base,
        kind,
        items: Vec::new(),
        direct_counts: BTreeMap::new(),
        all_dirs: Vec::new(),
    };
    walk(&mut state, base);
    let folders = folders_of(&state);
    (state.items, folders)
}

pub(crate) fn resolve_dir(params: &Map<String, Value>, key: &str, fallback: &Path) -> PathBuf {
    match params.get(key).and_then(Value::as_str).map(str::trim) {
        Some(value) if !value.is_empty() => {
            // Python 会先 expanduser；这里只处理 "~" 开头的常见写法
            if let Some(rest) = value.strip_prefix("~/").or_else(|| value.strip_prefix("~\\")) {
                if let Some(home) = std::env::var_os("USERPROFILE").or_else(|| std::env::var_os("HOME")) {
                    return PathBuf::from(home).join(rest);
                }
            }
            PathBuf::from(value)
        }
        _ => fallback.to_path_buf(),
    }
}

/// 与 `LibraryManager.snapshot()` 等价。
pub fn snapshot(params: &Map<String, Value>) -> Value {
    let (root, default_bgm, default_watermark) = library::default_paths();
    let bgm_dir = resolve_dir(params, "bgm_dir", &default_bgm);
    let watermark_dir = resolve_dir(params, "watermark_dir", &default_watermark);

    // 首次打开素材库时自动建目录（与旧引擎一致）
    let _ = fs::create_dir_all(&bgm_dir);
    let _ = fs::create_dir_all(&watermark_dir);

    let (bgm_items, bgm_folders) = scan_tree(&bgm_dir, "bgm");
    let (watermark_items, watermark_folders) = scan_tree(&watermark_dir, "watermark");

    json!({
        "library_root": paths::display(&root),
        "bgm_dir": paths::display(&bgm_dir),
        "watermark_dir": paths::display(&watermark_dir),
        "bgm": bgm_items,
        "bgm_folders": bgm_folders,
        "watermark": watermark_items,
        "watermark_folders": watermark_folders,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    struct TempLibrary {
        root: PathBuf,
    }

    impl TempLibrary {
        fn new(tag: &str) -> Self {
            let root = std::env::temp_dir().join(format!(
                "itv-lib-{}-{}-{}",
                tag,
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|value| value.as_nanos())
                    .unwrap_or(0)
            ));
            fs::create_dir_all(root.join("BGM")).expect("创建 BGM 目录");
            fs::create_dir_all(root.join("水印")).expect("创建水印目录");
            Self { root }
        }

        fn write(&self, relative: &str, bytes: &[u8]) {
            let path = self.root.join(relative);
            fs::create_dir_all(path.parent().expect("父目录")).expect("创建父目录");
            let mut file = fs::File::create(&path).expect("创建文件");
            file.write_all(bytes).expect("写入");
        }
    }

    impl Drop for TempLibrary {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    #[test]
    fn snapshot_lists_items_folders_and_ignores_hidden() {
        let library = TempLibrary::new("snapshot");
        library.write("BGM/歌一.mp3", b"not-really-audio");
        library.write("BGM/歌二.wav", b"still-not-audio");
        library.write("BGM/.hidden.mp3", b"x");
        library.write("BGM/说明.txt", b"x");
        library.write("水印/图层/a.png", b"png");
        library.write("水印/图层/b.mov", b"mov");

        let result = snapshot(&json!({
            "bgm_dir": library.root.join("BGM").to_string_lossy(),
            "watermark_dir": library.root.join("水印").to_string_lossy(),
        }).as_object().expect("params").clone());

        let bgm = result["bgm"].as_array().expect("bgm");
        assert_eq!(bgm.len(), 2, "隐藏文件与非音频应被忽略：{bgm:?}");
        assert_eq!(bgm[0]["name"], "歌一.mp3");
        // 旧引擎给 BGM 素材的 type 就是 "image"（media_type 默认值没被改写），
        // 这里保持逐字段一致；前端靠所在的 tab/数组区分类型，不看这个字段。
        assert_eq!(bgm[0]["type"], "image");
        // 不是真音频，ffmpeg 解不出来 → 指纹为空、duration 为 null
        assert!(bgm[0]["duration"].is_null());

        // BGM 下没有子目录；「图层」在水印库里
        assert!(result["bgm_folders"].as_array().expect("bgm_folders").is_empty());
        let folders = result["watermark_folders"].as_array().expect("watermark_folders");
        assert_eq!(folders.len(), 1);
        assert_eq!(folders[0]["relative"], "图层");
        assert_eq!(folders[0]["count"], 2);

        let watermark = result["watermark"].as_array().expect("watermark");
        assert_eq!(watermark.len(), 2);
        let video = watermark
            .iter()
            .find(|item| item["name"] == "b.mov")
            .expect("b.mov");
        assert_eq!(video["type"], "video");
    }

    #[test]
    fn second_scan_reuses_index_without_rehashing() {
        let library = TempLibrary::new("index");
        library.write("BGM/a.mp3", b"payload");
        let params = json!({
            "bgm_dir": library.root.join("BGM").to_string_lossy(),
            "watermark_dir": library.root.join("水印").to_string_lossy(),
        })
        .as_object()
        .expect("params")
        .clone();

        let first = snapshot(&params);
        let added_first = first["bgm"][0]["added_at"].as_str().unwrap_or("").to_string();
        assert!(!added_first.is_empty());

        assert!(library.root.join("BGM").join(INDEX_FILE_NAME).is_file());
        let second = snapshot(&params);
        assert_eq!(second["bgm"][0]["duplicate_key"], first["bgm"][0]["duplicate_key"]);
        // 索引命中时复用 added_at，不会刷新时间
        assert_eq!(second["bgm"][0]["added_at"], first["bgm"][0]["added_at"]);
    }
}
