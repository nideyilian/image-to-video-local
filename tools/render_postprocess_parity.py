# -*- coding: utf-8 -*-
"""后处理命令对照：用同一批用例分别由 Rust 与 Python 拼命令，逐字符比对。

Python 侧不能直接调 `build_cmd()`（它内部会读图片、选曲、探测元数据，
结果随真实素材变化），所以这里按 `src/render/postprocess.py` 的同一套规则
重写一遍拼装逻辑，只比较**拼装结果**。

用法：
    python tools/render_postprocess_parity.py <cases.json> <rust.json>
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 与 src/render/postprocess.py 保持一致的映射
ACODEC_BY_EXT = {".avi": "mp3"}
MUXER_BY_EXT = {".mp4": "mp4", ".m4v": "mp4", ".mov": "mov", ".avi": "avi", ".mkv": "matroska"}
BLEND_MODE_MAP = {
    "滤色": "screen",
    "叠加": "overlay",
    "正片叠底": "multiply",
    "变亮": "lighten",
    "变暗": "darken",
    "相加": "addition",
}


def output_extension(path: str) -> str:
    ext = os.path.splitext(str(path))[1].lower()
    return ext if ext else ".mp4"


def build_temp_output_path(path: str, suffix: str) -> str:
    base, _ = os.path.splitext(path)
    return f"{base}.{suffix}{output_extension(path)}"


def build_command(case: dict, main_meta: tuple[int, int, float]) -> dict:
    """与 `build_command()` 同构的实现（只拼参数，不执行）。"""
    main_w, main_h, main_duration = main_meta
    output_path = case.get("output", "C:/out/v.mp4")
    vcodec = case.get("codec", "libx264")
    watermark = case.get("watermark")
    fixed_layers = case.get("fixed_layers") or []
    bgm = case.get("bgm")

    base_cmd = ["-y", "-i", output_path]
    filter_parts = []
    current_label = "[0:v]"
    input_idx = 1
    audio_label = None

    if watermark:
        looped = watermark.get("looped", True)
        if looped:
            base_cmd += ["-stream_loop", "-1"]
        base_cmd += ["-i", watermark["path"]]

        wm_label = f"wmv_{input_idx}"
        ratio = watermark.get("stretch_ratio")
        if ratio is not None:
            wm_chain = f"[{input_idx}:v]setpts={ratio:.6f}*PTS,scale={watermark['target_w']}:{watermark['target_h']}"
        else:
            wm_chain = f"[{input_idx}:v]setpts=PTS-STARTPTS,scale={watermark['target_w']}:{watermark['target_h']}"
        blend_mode = watermark.get("blend_mode", "正常")
        alpha = float(watermark.get("alpha", 0.5))
        if blend_mode == "正常":
            wm_chain += f",format=rgba,colorchannelmixer=aa={alpha:.3f}"
        filter_parts.append(f"{wm_chain}[{wm_label}]")

        next_label = f"v_wm_{input_idx}"
        if blend_mode == "正常":
            overlay_mode = "shortest=1" if looped else "eof_action=pass"
            filter_parts.append(
                f"{current_label}[{wm_label}]overlay=x={watermark['x']}:y={watermark['y']}:{overlay_mode}[{next_label}]"
            )
            current_label = f"[{next_label}]"
        else:
            ffmpeg_blend_mode = BLEND_MODE_MAP.get(blend_mode)
            x_clip = max(0, min(watermark["x"], max(0, main_w - watermark["target_w"])))
            y_clip = max(0, min(watermark["y"], max(0, main_h - watermark["target_h"])))
            roi_base_label = f"roi_base_{input_idx}"
            wm_blend_src_label = f"wm_src_{input_idx}"
            roi_blend_label = f"roi_blend_{input_idx}"
            blend_sync_opts = "shortest=1" if looped else "eof_action=pass:repeatlast=0"
            filter_parts.append(
                f"{current_label}crop={watermark['target_w']}:{watermark['target_h']}:{x_clip}:{y_clip},format=gbrp[{roi_base_label}]"
            )
            filter_parts.append(f"[{wm_label}]format=gbrp[{wm_blend_src_label}]")
            filter_parts.append(
                f"[{roi_base_label}][{wm_blend_src_label}]blend=all_mode={ffmpeg_blend_mode}:all_opacity={alpha:.3f}:{blend_sync_opts}[{roi_blend_label}]"
            )
            overlay_mode = "shortest=1" if looped else "eof_action=pass"
            filter_parts.append(
                f"{current_label}[{roi_blend_label}]overlay=x={x_clip}:y={y_clip}:{overlay_mode}[{next_label}]"
            )
            current_label = f"[{next_label}]"
        input_idx += 1

    for idx, spec in enumerate(fixed_layers):
        base_cmd += ["-loop", "1", "-i", spec["path"]]
        fix_label = f"fix_{idx}"
        filter_parts.append(
            f"[{input_idx}:v]format=rgba,colorchannelmixer=aa={spec['opacity']:.3f},"
            f"scale={spec['target_w']}:{spec['target_h']}[{fix_label}]"
        )
        next_label = f"v_fix_{idx}"
        filter_parts.append(
            f"{current_label}[{fix_label}]overlay=x={spec['x']}:y={spec['y']}:shortest=1[{next_label}]"
        )
        current_label = f"[{next_label}]"
        input_idx += 1

    bgm_loop = True
    if bgm:
        bgm_loop = bool(bgm.get("looped", True))
        if bgm_loop:
            base_cmd += ["-stream_loop", "-1"]
        base_cmd += ["-i", bgm["path"]]
        audio_label = "bgm_a"
        volume = float(bgm.get("volume", 0.5))
        filter_parts.append(f"[{input_idx}:a]volume={volume:.2f}[{audio_label}]")
        input_idx += 1

    temp_output = build_temp_output_path(output_path, "pipeline_temp")
    cmd = list(base_cmd)
    if filter_parts:
        cmd += ["-filter_complex", ";".join(filter_parts)]
    video_map = current_label if current_label != "[0:v]" else "0:v"
    cmd += ["-map", video_map]
    if audio_label:
        a_codec = ACODEC_BY_EXT.get(output_extension(output_path), "aac")
        cmd += ["-map", f"[{audio_label}]", "-c:a", a_codec, "-b:a", "192k"]
        if bgm_loop:
            cmd += ["-shortest"]
        elif main_duration > 0:
            cmd += ["-t", f"{main_duration:.3f}"]
        else:
            cmd += ["-shortest"]
    else:
        cmd += ["-map", "0:a?", "-c:a", "copy"]
    cmd += ["-c:v", vcodec]
    if vcodec == "libx264":
        cmd += ["-preset", "medium"]
    cmd += ["-filter_threads", "0", "-threads", "0"]
    muxer = MUXER_BY_EXT.get(output_extension(output_path))
    cmd += ["-pix_fmt", "yuv420p"]
    if muxer:
        cmd += ["-f", muxer]
    cmd += [temp_output]
    return {"args": cmd, "temp_output": temp_output}


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cases = json.load(open(sys.argv[1], encoding="utf-8"))
    rust = json.load(open(sys.argv[2], encoding="utf-8"))

    main_meta = (1920, 1080, 5.0)
    diffs = []
    for case in cases:
        case_id = case["id"]
        expected = build_command(case, main_meta)
        actual = rust.get(case_id)
        if actual is None:
            diffs.append((case_id, "缺失", "有"))
            continue
        if actual.get("temp_output") != expected["temp_output"]:
            diffs.append((case_id + "·temp", actual.get("temp_output"), expected["temp_output"]))
        if actual.get("args") != expected["args"]:
            # 找出第一个不同的位置，便于定位
            left = actual.get("args") or []
            right = expected["args"]
            spot = next(
                (i for i, (a, b) in enumerate(zip(left, right)) if a != b),
                min(len(left), len(right)),
            )
            diffs.append(
                (
                    case_id + "·args",
                    left[spot : spot + 3],
                    right[spot : spot + 3],
                )
            )

    print(f"用例数: {len(cases)}")
    if diffs:
        print(f"不一致 {len(diffs)} 项：")
        for key, rust_value, py_value in diffs[:8]:
            print(f"  {key}\n    rust={rust_value!r}\n    py  ={py_value!r}")
        return 1
    print("RESULT: IDENTICAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())