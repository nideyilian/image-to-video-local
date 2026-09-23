#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""无界面渲染 worker：读配置与控制文件，调渲染内核，按 NDJSON 输出进度。

与 ``src/gui_qt/tk_bridge_runner.py`` 的对外协议**完全一致**，因此调用方无需改动：

    {"type": "status",   "message": str}
    {"type": "progress", "percent": int, "overall": int, "speed": str|None,
     "phase": str, "elapsed_sec": float}
    {"type": "done",     "success": bool}

区别在于：这里**不创建 Tk 窗口**，配置直接从 JSON 读取，进度由内核回调驱动。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from typing import Any

from . import job
from .context import RenderContext


def _configure_utf8_stdio() -> None:
    """保证非 ASCII 路径/文案在 stdout 上无损输出。"""
    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="无界面渲染 worker")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--control", default="", help="控制文件路径（暂停/取消）")
    args = parser.parse_args(argv)

    config_file = os.path.abspath(args.config)
    control_file = os.path.abspath(args.control) if args.control else ""

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        cfg = raw if isinstance(raw, dict) else {}
    except Exception as exc:
        _emit({"type": "status", "message": f"配置文件读取失败: {exc}"})
        _emit({"type": "done", "success": False})
        return 2

    # ---- 暂停 / 取消：与 tk_bridge_runner 一样轮询控制文件 ----
    stop = threading.Event()
    control_state = {"cancel": False, "paused": False}
    pause_event = threading.Event()
    pause_event.set()

    def control_loop() -> None:
        while not stop.is_set():
            try:
                if control_file and os.path.exists(control_file):
                    with open(control_file, "r", encoding="utf-8") as f:
                        ctrl = json.load(f)
                    paused = bool(ctrl.get("paused", False))
                    cancel = bool(ctrl.get("cancel", False))
                    if paused != control_state["paused"]:
                        control_state["paused"] = paused
                        if paused:
                            pause_event.clear()
                            _emit({"type": "status", "message": "已暂停"})
                        else:
                            pause_event.set()
                            _emit({"type": "status", "message": "继续处理"})
                    if cancel:
                        control_state["cancel"] = True
                        pause_event.set()
                        _emit({"type": "status", "message": "已请求取消"})
                        return
            except Exception:
                pass
            time.sleep(0.05)

    worker = threading.Thread(target=control_loop, daemon=True)
    worker.start()

    # ---- 界面侧上下文：配置即状态，内核通过 read/set_value 存取 ----
    state: dict[str, Any] = dict(cfg)
    start_ts = time.time()

    def read_value(name, default=None):
        return state.get(name, default)

    def set_value(name, value):
        state[name] = value

    def overall_percent() -> int:
        total = int(state.get("overall_total_videos", 0) or 0)
        if total <= 0:
            return 0
        idx = min(int(state.get("current_video_index", 0) or 0), total - 1)
        pct = float(state.get("_abs_percent", 0) or 0)
        return max(0, min(100, int(((idx + pct / 100.0) / total) * 100)))

    def on_absolute_progress(percent, info_text=None, force=False) -> None:
        try:
            state["_abs_percent"] = max(0, min(100, int(percent)))
        except Exception:
            return
        _emit({
            "type": "progress",
            "percent": state["_abs_percent"],
            "overall": overall_percent(),
            "speed": state.get("speed_info"),
            "phase": str(state.get("_progress_phase_label", "") or ""),
            "elapsed_sec": round(max(0.0, time.time() - start_ts), 1),
        })

    def on_progress(value) -> None:
        # 帧数上报阶段不一定已换算成百分比，沿用最近的绝对值
        _emit({
            "type": "progress",
            "percent": int(state.get("_abs_percent", 0) or 0),
            "overall": overall_percent(),
            "speed": state.get("speed_info"),
            "phase": str(state.get("_progress_phase_label", "") or ""),
            "elapsed_sec": round(max(0.0, time.time() - start_ts), 1),
        })

    ctx = RenderContext(
        read=read_value,
        set_value=set_value,
        # 编码器取自配置（界面侧对应的字段是 codec / codec_var）
        codec_provider=lambda: state.get("codec", "XVID"),
        notify=lambda message: _emit({"type": "status", "message": str(message)}),
        progress=on_progress,
        reset_progress=lambda *a, **k: state.__setitem__("_abs_percent", 0),
        reset_overall_progress=lambda n: state.__setitem__("overall_total_videos", int(n or 0)),
        set_absolute_progress=on_absolute_progress,
        cancel_provider=lambda: control_state["cancel"],
        pause_event=pause_event,
        ffmpeg_available=True,
        startupinfo=None,
        fps_provider=lambda: float(state.get("fps", 30) or 30),
        turbo_accelerator=None,
        transition_engine=None,
    )

    _emit({"type": "status", "message": "已加载配置，开始处理..."})
    try:
        success = bool(job.run_batch(ctx))
    except Exception as exc:
        _emit({"type": "status", "message": f"渲染内核异常: {exc}"})
        success = False
    finally:
        stop.set()

    _emit({"type": "done", "success": success})
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
