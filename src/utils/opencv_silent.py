#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OpenCV 静默导入，避免本地库输出干扰控制台。
"""

from __future__ import annotations

import os
from typing import Any


def import_cv2_silent() -> Any:
    """静默导入 cv2，屏蔽底层库对 stderr 的输出。"""
    fd = os.dup(2)
    try:
        with open(os.devnull, "w") as devnull:
            os.dup2(devnull.fileno(), 2)
            import cv2  # type: ignore
        return cv2
    finally:
        os.dup2(fd, 2)
        os.close(fd)
