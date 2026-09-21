"""为多个视频规划互不重复的图片组合。

一个「组合」= 依次从每个子文件夹抽 1 张图拼成的完整一轮，长度等于子文件夹数。
组合总数 = 各子文件夹图片数之积：

- 请求数量不超过组合总数时，每个组合最多出现一次；
- 只有超出总数时才允许重复，且重复被摊平：任意两个组合的出现次数相差不超过 1。

本模块只依赖标准库，不读取磁盘，便于单独测试。
"""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")

ENUMERATION_LIMIT = 50_000
"""组合总数不超过该值时直接穷举后洗牌。

超过该值说明组合空间大得不可能被请求量填满（此时请求数远小于总数），
改用去重随机抽样，避免构造一张巨大的组合表。
"""


def combination_total(group_sizes: Sequence[int]) -> int:
    """返回组合总数（各子文件夹图片数之积）；任一子文件夹为空时返回 0。"""
    sizes = [int(size) for size in group_sizes]
    if not sizes or any(size <= 0 for size in sizes):
        return 0
    return math.prod(sizes)


def plan_combinations(
    groups: Sequence[Sequence[T]],
    count: int,
    rng: random.Random | None = None,
) -> list[list[T]]:
    """规划 ``count`` 个组合，每个组合按 ``groups`` 的顺序各取一个元素。

    Args:
        groups: 每个子文件夹的候选列表，列表顺序即组合顺序。
        count: 需要的组合数量，通常等于要生成的视频数。
        rng: 随机源；传入固定种子可复现同一批组合。

    Returns:
        长度为 ``count`` 的列表。组合互不重复，仅在组合总数不足时才重复。
        任一子文件夹为空或 ``count <= 0`` 时返回空列表。
    """
    sizes = [len(group) for group in groups]
    total = combination_total(sizes)
    if total == 0 or count <= 0:
        return []

    chosen = rng or random.Random()
    picks = _plan_indices(sizes, total, int(count), chosen)
    return [[groups[position][index] for position, index in enumerate(pick)] for pick in picks]


def _plan_indices(
    sizes: list[int],
    total: int,
    count: int,
    rng: random.Random,
) -> list[tuple[int, ...]]:
    """在索引空间里规划组合，避免直接构造图片路径的笛卡尔积。"""
    if total <= ENUMERATION_LIMIT:
        # 池子放得下：整池洗牌，每轮取走一段。
        # 轮次之间重新洗牌，所以重复只可能发生在跨轮处，
        # 每个组合的出现次数最多相差 1 次。
        pool = list(itertools.product(*(range(size) for size in sizes)))
        picks: list[tuple[int, ...]] = []
        while len(picks) < count:
            rng.shuffle(pool)
            picks.extend(pool[: count - len(picks)])
        return picks

    # 池子太大：随机抽取 + 已用集合去重。
    # 此时 count 远小于 total，碰撞概率极低；重试上限只是兜底，避免理论上的死循环。
    seen: set[tuple[int, ...]] = set()
    picks = []
    wasted = 0
    wasted_limit = count * 64 + 1024
    while len(picks) < count and wasted < wasted_limit:
        pick = tuple(rng.randrange(size) for size in sizes)
        if pick in seen:
            wasted += 1
            continue
        seen.add(pick)
        picks.append(pick)
    # 兜底：请求量逼近总数时允许重复，保证数量正确且不卡死。
    while len(picks) < count:
        picks.append(tuple(rng.randrange(size) for size in sizes))
    return picks
