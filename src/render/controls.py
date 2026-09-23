"""渲染过程的控制原语：暂停 / 取消应答与内存清理（与界面无关）。

从 ``src/gui/main_window.py`` 的 ``ImageToVideoTab`` 抽出。注意：
**进度显示非内核职责**，相关方法留在界面层，
内核只通过 ``RenderContext`` 的回调上报。本模块不导入任何 GUI 库。
"""

from __future__ import annotations

import time

from .context import RenderContext, should_cancel


def wait_for_processing_control(sleep_sec=0.03, ctx=None):
    """处理暂停/取消控制，返回False表示应立即中断。"""
    ctx = ctx or RenderContext()
    if should_cancel(ctx):
        return False

    pause_event = ctx.pause_event
    if pause_event is None:
        return True

    while not pause_event.is_set():
        if should_cancel(ctx):
            return False
        time.sleep(max(0.01, float(sleep_sec)))

    return not should_cancel(ctx)


def maybe_realtime_cleanup(turbo_accelerator=None, transition_engine=None,
                           last_cleanup=0.0, interval=2.0, force: bool = False,
                           ctx=None):
    """处理过程中实时清理缓存，避免堆积"""
    now = time.time()
    if not force and (now - last_cleanup) < interval:
        return last_cleanup
    last_cleanup = now
    if turbo_accelerator and turbo_accelerator.enabled:
        turbo_accelerator.realtime_cleanup(force=force)
    if transition_engine and hasattr(transition_engine, "realtime_cleanup"):
        transition_engine.realtime_cleanup(force=force)

    return last_cleanup
