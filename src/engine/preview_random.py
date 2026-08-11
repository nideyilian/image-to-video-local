"""Preview-only selection helpers. These values never enter render configs."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from typing import TypeVar


T = TypeVar("T")


def _shuffled(values: Sequence[T], domain: str) -> list[T]:
    items = list(values)
    signature = "\0".join(str(item) for item in items)
    digest = hashlib.sha256(f"{domain}\0{signature}".encode("utf-8")).digest()
    random.Random(int.from_bytes(digest[:8], "big")).shuffle(items)
    return items


def preview_choice(values: Sequence[T], sequence: object, domain: str) -> T | None:
    items = _shuffled(values, domain)
    if not items:
        return None
    try:
        offset = max(1, int(sequence)) - 1
    except (TypeError, ValueError):
        offset = 0
    return items[offset % len(items)]


def preview_sample(values: Sequence[T], count: object, sequence: object, domain: str) -> list[T]:
    items = _shuffled(values, domain)
    if not items:
        return []
    try:
        wanted = min(len(items), max(0, int(count)))
    except (TypeError, ValueError):
        wanted = len(items)
    try:
        offset = max(1, int(sequence)) - 1
    except (TypeError, ValueError):
        offset = 0
    offset %= len(items)
    rotated = items[offset:] + items[:offset]
    return rotated[:wanted]
