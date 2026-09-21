#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""「按子文件夹抽取」轮播：分组扫描 + 组合去重规划。

覆盖两条不变量：
1. 分组按子文件夹名自然排序，空目录/隐藏目录/根目录散图都不参与；
2. 视频数不超过组合总数时组合完全不重复，超出时每个组合都出现且出现次数最多相差 1。
"""

from __future__ import annotations

import itertools
import random
from collections import Counter
from pathlib import Path

from src.engine.config import SUBFOLDER_SELECTION_MODE, scan_subfolders, validate_config_detailed
from src.utils.combination import combination_total, plan_combinations


def make_group(root: Path, name: str, count: int) -> None:
    """在 root 下建一个名为 name 的子文件夹，塞 count 张假图片。"""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(1, count + 1):
        (folder / f"pic{index}.jpg").write_bytes(b"x")


def build_config(tmp_path: Path, **overrides: object) -> dict[str, object]:
    output_dir = tmp_path / "输出"
    output_dir.mkdir(exist_ok=True)
    config: dict[str, object] = {
        "input_dir": str(tmp_path),
        "output_dir": str(output_dir),
        "image_selection_mode": SUBFOLDER_SELECTION_MODE,
    }
    config.update(overrides)
    return config


def test_groups_are_naturally_sorted_and_empty_folder_is_skipped(tmp_path: Path) -> None:
    make_group(tmp_path, "1", 2)
    make_group(tmp_path, "2", 3)
    make_group(tmp_path, "10", 1)
    (tmp_path / "3").mkdir()  # 空文件夹
    make_group(tmp_path, ".cache", 1)  # 隐藏目录，即使有图也必须忽略
    (tmp_path / "散图.jpg").write_bytes(b"x")  # 根目录散图不参与分组
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")

    groups, skipped = scan_subfolders(str(tmp_path))

    # 关键断言：10 排在 2 后面，而不是字典序的 1、10、2
    assert [name for name, _images in groups] == ["1", "2", "10"]
    assert skipped == ["3"]


def test_images_inside_group_are_naturally_sorted(tmp_path: Path) -> None:
    folder = tmp_path / "1"
    folder.mkdir()
    for name in ("10.png", "2.png", "1.png"):
        (folder / name).write_bytes(b"x")

    groups, _skipped = scan_subfolders(str(tmp_path))

    assert [Path(path).name for path in groups[0][1]] == ["1.png", "2.png", "10.png"]


def test_non_image_files_do_not_make_a_group(tmp_path: Path) -> None:
    folder = tmp_path / "1"
    folder.mkdir()
    (folder / "note.txt").write_text("x", encoding="utf-8")
    (folder / "clip.mp4").write_bytes(b"x")

    groups, skipped = scan_subfolders(str(tmp_path))

    assert groups == []
    assert skipped == ["1"]


def test_nested_subfolders_are_not_scanned_recursively(tmp_path: Path) -> None:
    nested = tmp_path / "1" / "1-1"
    nested.mkdir(parents=True)
    (nested / "deep.jpg").write_bytes(b"x")

    groups, skipped = scan_subfolders(str(tmp_path))

    assert groups == []
    assert skipped == ["1"]


def test_chinese_group_names_fall_back_to_code_point_order(tmp_path: Path) -> None:
    """中文名没有可比较的数字片段，按 Unicode 码点排序。

    一(4E00) < 三(4E09) < 二(4E8C)，所以"第一组"排在"第三组"前面。
    这是已知限制：需要中文数字顺序时应自己给目录编号（1、2、3）。
    """
    for name in ("第一组", "第二组", "第三组"):
        make_group(tmp_path, name, 1)

    groups, _skipped = scan_subfolders(str(tmp_path))

    assert [name for name, _images in groups] == ["第一组", "第三组", "第二组"]


def test_missing_directory_returns_empty_result(tmp_path: Path) -> None:
    assert scan_subfolders(str(tmp_path / "不存在")) == ([], [])


def test_total_is_product_of_group_sizes() -> None:
    assert combination_total([3, 4, 5]) == 60
    assert combination_total([3, 0]) == 0
    assert combination_total([]) == 0


def test_combinations_are_unique_when_request_fits() -> None:
    groups = [["a1", "a2", "a3"], ["b1", "b2"], ["c1", "c2", "c3"]]
    total = combination_total([len(group) for group in groups])
    plans = plan_combinations(groups, total, random.Random(7))

    assert len(plans) == total == 18
    assert len({tuple(plan) for plan in plans}) == total
    for plan in plans:
        assert [item[0] for item in plan] == ["a", "b", "c"]


def test_partial_request_never_repeats() -> None:
    groups = [["a1", "a2", "a3"], ["b1", "b2"], ["c1", "c2", "c3"]]
    plans = plan_combinations(groups, 9, random.Random(5))

    assert len({tuple(plan) for plan in plans}) == 9


def test_repeats_are_spread_evenly_when_request_exceeds_total() -> None:
    groups = [["a1", "a2"], ["b1", "b2"]]  # 共 4 种组合
    total = combination_total([len(group) for group in groups])
    count = total * 2 + 1  # 9 个视频
    plans = plan_combinations(groups, count, random.Random(3))

    tally = Counter(tuple(plan) for plan in plans)

    assert len(plans) == count
    assert set(tally) == set(itertools.product(*groups))  # 每种组合都出现过
    assert max(tally.values()) - min(tally.values()) <= 1  # 重复被摊平


def test_each_combination_appears_once_per_full_round() -> None:
    groups = [["a1", "a2"], ["b1", "b2"], ["c1", "c2"]]
    total = combination_total([len(group) for group in groups])
    plans = plan_combinations(groups, total * 3, random.Random(1))

    tally = Counter(tuple(plan) for plan in plans)

    assert len(tally) == total
    assert set(tally.values()) == {3}


def test_large_combination_space_still_avoids_duplicates() -> None:
    # 20^6 = 6400 万种组合，远超穷举上限，只能靠抽样去重
    groups = [list(range(20)) for _ in range(6)]
    assert combination_total([len(group) for group in groups]) > 50_000

    plans = plan_combinations(groups, 200, random.Random(11))

    assert len(plans) == 200
    assert len({tuple(plan) for plan in plans}) == 200


def test_same_seed_reproduces_the_same_plan() -> None:
    groups = [["a1", "a2"], ["b1", "b2"], ["c1", "c2"]]

    assert plan_combinations(groups, 6, random.Random(2026)) == plan_combinations(
        groups, 6, random.Random(2026)
    )


def test_empty_group_or_non_positive_count_yields_nothing() -> None:
    assert plan_combinations([[], ["a"]], 5) == []
    assert plan_combinations([["a"], ["b"]], 0) == []
    assert plan_combinations([], 3) == []


def test_validation_accepts_repeating_beyond_combination_total(tmp_path: Path) -> None:
    make_group(tmp_path, "1", 2)
    make_group(tmp_path, "2", 2)
    # 只有 4 种组合却要 12 个视频：允许，重复由 plan_combinations 摊平
    config = build_config(tmp_path, video_count=12)

    assert validate_config_detailed(config) == []


def test_validation_ignores_num_images_in_subfolder_mode(tmp_path: Path) -> None:
    """新模式每视频图片数由子文件夹个数决定，num_images 不参与校验。"""
    make_group(tmp_path, "1", 1)
    make_group(tmp_path, "2", 1)

    assert validate_config_detailed(build_config(tmp_path, num_images=0)) == []


def test_num_images_still_required_in_other_modes(tmp_path: Path) -> None:
    """其它选图方式下「图片数」仍然是必填的正数。"""
    make_group(tmp_path, "1", 1)
    make_group(tmp_path, "2", 1)

    issues = validate_config_detailed(
        build_config(tmp_path, image_selection_mode="随机选择", num_images=0)
    )

    assert any(issue["field"] == "num_images" for issue in issues)


def test_validation_accepts_layout_with_loose_images_in_root(tmp_path: Path) -> None:
    make_group(tmp_path, "1", 1)
    make_group(tmp_path, "2", 1)
    (tmp_path / "散图.jpg").write_bytes(b"x")

    assert validate_config_detailed(build_config(tmp_path)) == []


def test_validation_rejects_directory_without_subfolders(tmp_path: Path) -> None:
    (tmp_path / "散图.jpg").write_bytes(b"x")

    issues = validate_config_detailed(build_config(tmp_path))

    assert issues, "根目录只有散图、没有子文件夹时必须报错"
    assert issues[0]["field"] == "input_dir"
    assert "子文件夹" in issues[0]["message"]


def test_validation_rejects_subfolders_without_images(tmp_path: Path) -> None:
    empty = tmp_path / "1"
    empty.mkdir()
    (empty / "note.txt").write_text("x", encoding="utf-8")

    issues = validate_config_detailed(build_config(tmp_path))

    assert issues, "子文件夹里没有图片时必须报错"
    assert issues[0]["field"] == "input_dir"
