"""Helpers for building a fixed-duration image timeline."""

from __future__ import annotations

import math
from typing import Sequence, TypeVar


T = TypeVar("T")


def timeline_slot_count(image_duration: float, total_duration: float) -> int | None:
    """Return the number of equal image slots, or ``None`` for automatic duration."""
    image_seconds = float(image_duration)
    total_seconds = float(total_duration)
    if image_seconds <= 0:
        raise ValueError("每图时长必须大于 0")
    if total_seconds < 0:
        raise ValueError("总时长不能小于 0")
    if total_seconds == 0:
        return None

    raw_slots = total_seconds / image_seconds
    slot_count = round(raw_slots)
    if slot_count < 1 or not math.isclose(raw_slots, slot_count, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("总时长必须是每图时长的整数倍（例如每图 1 秒、总时长 8 秒）")
    return int(slot_count)


def cycle_images_to_duration(
    images: Sequence[T], image_duration: float, total_duration: float
) -> list[T]:
    """Repeat or trim images to fill a fixed-duration equal-slot timeline."""
    source = list(images)
    if not source:
        return []
    slot_count = timeline_slot_count(image_duration, total_duration)
    if slot_count is None:
        return source
    return [source[index % len(source)] for index in range(slot_count)]
