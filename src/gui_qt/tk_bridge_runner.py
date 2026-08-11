#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Qt -> Tk 处理桥接器
读取配置文件，复用现有 Tk 处理管线，并用 JSON 行输出进度给 Qt。
"""

import argparse
import json
import os
import sys
import threading
import time
import tkinter as tk


def _emit(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--control", default="", help="控制文件路径（暂停/取消）")
    args = parser.parse_args()
    config_file = os.path.abspath(args.config)
    control_file = os.path.abspath(args.control) if args.control else ""

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        current_dir = getattr(sys, "_MEIPASS")
    else:
        current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src_dir = os.path.join(current_dir, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)

    try:
        from src.gui.main_window import ImageToVideoTab
    except Exception as exc:
        _emit({"type": "status", "message": f"桥接导入失败: {exc}"})
        return 2

    root = None
    stop_event = threading.Event()
    loaded_cfg = {}
    try:
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                raw_cfg = json.load(f)
                if isinstance(raw_cfg, dict):
                    loaded_cfg = raw_cfg
        except Exception:
            loaded_cfg = {}

        root = tk.Tk()
        root.withdraw()
        holder = tk.Frame(root)
        holder.pack_forget()

        tab = ImageToVideoTab(holder, config_file=config_file)
        if loaded_cfg and hasattr(tab, "apply_config_from_dict"):
            # 兜底注入完整配置，确保 watermark_mode 等字段在桥接模式下也生效。
            tab.apply_config_from_dict(loaded_cfg)
        tab.parent.update_idletasks()

        original_update_status = tab.update_status
        original_update_progress = tab.update_progress
        original_set_absolute_progress = getattr(tab, "_set_absolute_progress", None)
        last_status_state = {
            "message": "",
            "ts": 0.0,
        }

        def emit_progress_snapshot():
            percent = 0
            overall = 0
            speed = None
            phase = ""
            elapsed_sec = None
            try:
                if hasattr(tab, "progress_var"):
                    percent = int(tab.progress_var.get() or 0)
                if hasattr(tab, "overall_progress_var"):
                    overall = int(tab.overall_progress_var.get() or 0)
                phase = str(getattr(tab, "_progress_phase_label", "") or "")
                task_start_ts = getattr(tab, "_task_start_ts", None)
                if task_start_ts:
                    elapsed_sec = round(max(0.0, time.time() - float(task_start_ts)), 1)
                if hasattr(tab, "speed_info_var"):
                    speed_text = str(tab.speed_info_var.get())
                    if ":" in speed_text:
                        speed = speed_text.split(":", 1)[1].replace("张/秒", "").strip()
            except Exception:
                pass
            _emit({
                "type": "progress",
                "percent": percent,
                "overall": overall,
                "speed": speed,
                "phase": phase,
                "elapsed_sec": elapsed_sec,
            })

        def patched_update_status(message):
            msg = str(message)
            try:
                original_update_status(msg)
            except Exception:
                pass
            now = time.time()
            last_msg = str(last_status_state.get("message", ""))
            last_ts = float(last_status_state.get("ts", 0.0) or 0.0)
            elapsed = now - last_ts
            critical_keywords = ("完成", "失败", "错误", "异常", "取消", "暂停", "继续", "请求")
            is_critical = any(k in msg for k in critical_keywords)
            is_duplicate = (msg == last_msg)
            should_emit = is_critical or (not is_duplicate and elapsed >= 0.20) or (elapsed >= 1.0)
            if should_emit:
                last_status_state["message"] = msg
                last_status_state["ts"] = now
                _emit({"type": "status", "message": msg})

        def patched_update_progress(value):
            try:
                original_update_progress(value)
            except Exception:
                pass
            emit_progress_snapshot()

        def patched_set_absolute_progress(percent, info_text=None, force=False):
            if callable(original_set_absolute_progress):
                try:
                    original_set_absolute_progress(percent, info_text=info_text, force=force)
                except Exception:
                    pass
            emit_progress_snapshot()

        tab.update_status = patched_update_status
        tab.update_progress = patched_update_progress
        if callable(original_set_absolute_progress):
            tab._set_absolute_progress = patched_set_absolute_progress

        def control_loop():
            last_paused = False
            while not stop_event.is_set():
                try:
                    if control_file and os.path.exists(control_file):
                        with open(control_file, "r", encoding="utf-8") as f:
                            ctrl = json.load(f)
                        paused = bool(ctrl.get("paused", False))
                        cancel = bool(ctrl.get("cancel", False))
                        if paused != last_paused:
                            if paused:
                                tab.pause_event.clear()
                                tab.is_paused = True
                                _emit({"type": "status", "message": "已暂停"})
                            else:
                                tab.pause_event.set()
                                tab.is_paused = False
                                _emit({"type": "status", "message": "继续处理"})
                            last_paused = paused
                        if cancel:
                            tab.cancel_requested = True
                            tab.pause_event.set()
                            _emit({"type": "status", "message": "已请求取消"})
                            return
                except Exception:
                    pass
                # 提高控制文件轮询频率，缩短暂停/取消响应延迟
                time.sleep(0.05)

        t = threading.Thread(target=control_loop, daemon=True)
        t.start()

        _emit({"type": "status", "message": "已加载配置，开始处理..."})
        success = bool(tab.process_videos())
        _emit({"type": "done", "success": success})
        return 0 if success else 1
    except Exception as exc:
        _emit({"type": "status", "message": f"桥接处理异常: {exc}"})
        _emit({"type": "done", "success": False})
        return 1
    finally:
        stop_event.set()
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
