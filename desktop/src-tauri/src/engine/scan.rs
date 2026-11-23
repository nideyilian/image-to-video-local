//! 图片扫描：与 Python 版 `config.scan_images` / `config.scan_subfolders` 对齐。
//!
//! 两个容易出错的细节，都按旧引擎的行为复刻：
//! 1. 递归扫描**不跟随目录符号链接**（`Path.rglob("*")` 的默认行为）；
//! 2. 排序键是**完整路径**（`images.sort(key=natural_sort_key)`），不是文件名 ——
//!    跨子目录时父目录名也参与比较，改成只比文件名会得到不同顺序。

use std::fs;
use std::path::{Path, PathBuf};

use super::paths;
use super::sort::compare_names;

pub const IMAGE_EXTENSIONS: [&str; 6] = [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"];

pub fn is_image(path: &Path) -> bool {
    match path.extension().and_then(|ext| ext.to_str()) {
        Some(ext) => {
            let lowered = format!(".{}", ext.to_lowercase());
            IMAGE_EXTENSIONS.contains(&lowered.as_str())
        }
        None => false,
    }
}

fn collect_recursive(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let Ok(file_type) = entry.file_type() else {
            continue;
        };
        if file_type.is_dir() {
            collect_recursive(&path, out);
        } else if is_image(&path) && path.is_file() {
            // `path.is_file()` 会跟随符号链接，与 Python 的 `path.is_file()` 一致。
            out.push(path);
        }
    }
}

/// 递归收集图片，按完整路径自然排序后返回绝对路径。
pub fn scan_images(input_dir: &str) -> Vec<String> {
    let root = Path::new(input_dir.trim());
    if !root.is_dir() {
        return Vec::new();
    }
    let mut found: Vec<PathBuf> = Vec::new();
    collect_recursive(root, &mut found);
    let mut images: Vec<String> = found
        .iter()
        .map(|path| paths::to_string(&paths::absolute(path)))
        .collect();
    images.sort_by(|left, right| compare_names(left, right));
    images
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Group {
    pub name: String,
    pub images: Vec<String>,
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct SubfolderScan {
    pub groups: Vec<Group>,
    pub skipped: Vec<String>,
}

/// 按直接子目录分组收集图片（只扫一层，跳过 `.` 开头的隐藏目录）。
pub fn scan_subfolders(input_dir: &str) -> SubfolderScan {
    let mut scan = SubfolderScan::default();
    let root = Path::new(input_dir.trim());
    if !root.is_dir() {
        return scan;
    }
    let Ok(entries) = fs::read_dir(root) else {
        return scan;
    };
    let mut children: Vec<PathBuf> = entries.flatten().map(|entry| entry.path()).collect();
    children.sort_by(|left, right| {
        compare_names(
            &paths::file_name(&paths::to_string(left)),
            &paths::file_name(&paths::to_string(right)),
        )
    });

    for child in children {
        let name = child
            .file_name()
            .map(|value| value.to_string_lossy().into_owned())
            .unwrap_or_default();
        if !child.is_dir() || name.starts_with('.') {
            continue;
        }
        let mut images: Vec<String> = Vec::new();
        if let Ok(items) = fs::read_dir(&child) {
            for item in items.flatten() {
                let path = item.path();
                if is_image(&path) && path.is_file() {
                    images.push(paths::to_string(&paths::absolute(&path)));
                }
            }
        }
        if images.is_empty() {
            scan.skipped.push(name);
            continue;
        }
        images.sort_by(|left, right| compare_names(left, right));
        scan.groups.push(Group { name, images });
    }
    scan
}

/// 组合总数 = 各子文件夹图片数之积（任一为空则为 0）。
pub fn combination_total(groups: &[Group]) -> u128 {
    if groups.is_empty() {
        return 0;
    }
    groups.iter().fold(1u128, |acc, group| {
        acc.saturating_mul(group.images.len() as u128)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::File;

    struct TempTree {
        root: PathBuf,
    }

    impl TempTree {
        fn new(tag: &str) -> Self {
            let root = std::env::temp_dir().join(format!(
                "itv-engine-{}-{}-{}",
                tag,
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|value| value.as_nanos())
                    .unwrap_or(0)
            ));
            fs::create_dir_all(&root).expect("创建临时目录");
            Self { root }
        }

        fn touch(&self, relative: &str) -> PathBuf {
            let path = self.root.join(relative);
            fs::create_dir_all(path.parent().expect("父目录")).expect("创建子目录");
            File::create(&path).expect("创建文件");
            path
        }

        fn mkdir(&self, relative: &str) -> PathBuf {
            let path = self.root.join(relative);
            fs::create_dir_all(&path).expect("创建目录");
            path
        }
    }

    impl Drop for TempTree {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    #[test]
    fn scan_images_is_recursive_and_naturally_sorted() {
        let tree = TempTree::new("scan");
        tree.touch("a/10.jpg");
        tree.touch("a/2.jpg");
        tree.touch("a/1.JPG");
        tree.touch("a/notes.txt");
        tree.touch("b/3.png");

        let images = scan_images(&tree.root.to_string_lossy());
        let names: Vec<String> = images.iter().map(|path| paths::file_name(path)).collect();

        assert_eq!(names, vec!["1.JPG", "2.jpg", "10.jpg", "3.png"]);
        assert!(images.iter().all(|path| Path::new(path).is_absolute()));
    }

    #[test]
    fn scan_images_ignores_non_images_and_missing_dir() {
        let tree = TempTree::new("scan-empty");
        tree.touch("a/cover.txt");
        assert!(scan_images(&tree.root.to_string_lossy()).is_empty());
        assert!(scan_images("").is_empty());
        assert!(scan_images(&tree.root.join("不存在").to_string_lossy()).is_empty());
    }

    #[test]
    fn scan_subfolders_groups_sorts_and_reports_skipped() {
        let tree = TempTree::new("subfolder");
        tree.touch("2/b.jpg");
        tree.touch("10/a.jpg");
        tree.touch("10/c.jpg");
        tree.mkdir("空文件夹");
        tree.mkdir(".hidden");
        tree.touch(".hidden/x.jpg");
        tree.touch("loose.jpg");

        let scan = scan_subfolders(&tree.root.to_string_lossy());

        assert_eq!(
            scan.groups
                .iter()
                .map(|group| group.name.as_str())
                .collect::<Vec<_>>(),
            vec!["2", "10"]
        );
        assert_eq!(scan.groups[0].images.len(), 1);
        assert_eq!(scan.groups[1].images.len(), 2);
        assert_eq!(scan.skipped, vec!["空文件夹"]);
        assert_eq!(combination_total(&scan.groups), 2);
    }

    #[test]
    fn missing_input_dir_returns_empty_scan() {
        let scan = scan_subfolders("");
        assert!(scan.groups.is_empty());
        assert!(scan.skipped.is_empty());
        assert_eq!(combination_total(&scan.groups), 0);
    }
}
