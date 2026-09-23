"""渲染内核所需的界面侧上下文。

内核只通过这些回调“上报”与“读取”，不关心界面如何展示。
继承 ``CodecContext`` 以复用编码相关字段。本模块不导入任何 GUI 库。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .codec import CodecContext


@dataclass
class RenderContext(CodecContext):
    """渲染内核的界面侧上下文。全部可选，内核独立使用时留空。"""

    # 读取 / 写回界面侧配置、状态（按名取值）
    read: Callable[..., Any] | None = None
    set_value: Callable[..., None] | None = None
    # 进度上报：内核只告诉界面“多少了”，具体怎么显示由界面决定
    progress: Callable[[Any], None] | None = None
    reset_progress: Callable[..., None] | None = None
    reset_overall_progress: Callable[[int], None] | None = None
    set_absolute_progress: Callable[..., None] | None = None
    # 暂停 / 取消
    cancel_provider: Callable[[], bool] | None = None
    pause_event: Any = None
    # 内存管理
    turbo_accelerator: Any = None
    transition_engine: Any = None


def read_value(ctx, name, default=None):
    """从界面侧按名取值；未注入时返回 default。"""
    if ctx is None or ctx.read is None:
        return default
    return ctx.read(name, default)


def emit_progress(ctx, value) -> None:
    if ctx is not None and ctx.progress is not None:
        ctx.progress(value)


def emit_reset_progress(ctx, total_frames, render_weight=1.0) -> None:
    if ctx is not None and ctx.reset_progress is not None:
        ctx.reset_progress(total_frames, render_weight)


def emit_reset_overall_progress(ctx, total_videos) -> None:
    if ctx is not None and ctx.reset_overall_progress is not None:
        ctx.reset_overall_progress(total_videos)


def emit_set_absolute_progress(ctx, *args, **kwargs) -> None:
    """\u540e\u5904\u7406\u9636\u6bb5\u7684\u7edd\u5bf9\u8fdb\u5ea6\uff08\u5e26\u6587\u6848 / force\uff09\u3002"""
    if ctx is not None and ctx.set_absolute_progress is not None:
        ctx.set_absolute_progress(*args, **kwargs)


def notify(ctx, message) -> None:
    """向界面上报一条状态消息；未注入时静默。"""
    if ctx is not None and ctx.notify is not None:
        ctx.notify(message)


def should_cancel(ctx) -> bool:
    if ctx is None or ctx.cancel_provider is None:
        return False
    return bool(ctx.cancel_provider())


def set_value(ctx, name, value) -> None:
    """写回界面侧状态（例如内核需要告知界面当前处于哪个阶段）。"""
    if ctx is not None and ctx.set_value is not None:
        ctx.set_value(name, value)

