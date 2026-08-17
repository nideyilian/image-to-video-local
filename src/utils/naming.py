"""输出文件名组合规则。

约定：
- 所有连接符统一为 "-"（含日期前缀内部的时间分隔）；
- 末尾自动序号不补零（1、2、…、10、100）；
- 只使用用户配置的字段（日期前缀 / 自定义前缀 / 首图名称），
  前缀为空时不注入任何默认文案。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def compose_output_filename(
    *,
    use_date_prefix: bool,
    use_first_image_name: bool,
    first_image_name: str = "",
    custom_prefix: str = "",
    index: int,
    video_format: str = "mp4",
    now: Any | None = None,
) -> str:
    """按规则组合输出文件名，例如：

    - 日期 + 自定义前缀 + 序号：20260816-153000-video-1.mp4
    - 仅自定义前缀 + 序号：video-1.mp4
    - 仅日期 + 序号：20260816-153000-1.mp4（前缀为空时不注入 "video"）
    - 首图名称模式：20260816-153000-风景-3.mp4
    - 全部为空：1.mp4
    """
    parts: list[str] = []
    if use_date_prefix:
        stamp = now.strftime("%Y%m%d-%H%M%S") if now is not None else datetime.now().strftime("%Y%m%d-%H%M%S")
        parts.append(stamp)
    if use_first_image_name:
        if first_image_name.strip():
            parts.append(first_image_name.strip())
    elif custom_prefix.strip():
        parts.append(custom_prefix.strip())
    parts.append(str(int(index)))
    return f"{'-'.join(parts)}.{video_format or 'mp4'}"
