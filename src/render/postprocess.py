"""后处理编排：BGM、固定水印图层、视频水印与重编码。

从 ``src/gui/main_window.py`` 的 ``ImageToVideoTab`` 抽出，函数体逐字保留。
本模块不导入任何 GUI 库。
"""

from __future__ import annotations

import os
import subprocess
import time

from ..utils.opencv_silent import import_cv2_silent
from .audio import add_audio_with_ffmpeg, resolve_bgm_candidates, select_bgm_file
from .codec import (build_temp_output_path, get_container_compatible_acodec,
                    get_ffmpeg_muxer_for_output, get_output_extension, get_selected_codec_name,
                    get_strict_ffmpeg_vcodec_for_output, log_output_probe,
                    reencode_video_to_selected_codec)
from .context import (RenderContext, emit_progress, emit_reset_overall_progress,
                      emit_reset_progress, emit_set_absolute_progress, notify, read_value,
                      set_value, should_cancel)
from .process import log_pipeline_stage, probe_video_meta, run_process_with_retry, safe_replace_file
from .watermark import (add_fixed_image_watermarks_to_video, add_video_watermark,
                        calc_overlay_geometry, collect_fixed_layer_specs_for_ffmpeg,
                        get_ffmpeg_blend_mode, get_image_files_in_dir, get_video_watermark_alpha,
                        get_video_watermark_blend_mode, get_watermark_files,
                        safe_read_image_with_alpha, select_video_watermark_file)

cv2 = import_cv2_silent()


def _stage(ctx, stage, message, log_func=None):
    log_pipeline_stage(stage, message, log_func, read_value(ctx, "_pipeline_log_file"))


def _run_proc(ctx, cmd, **kwargs):
    kwargs.setdefault("startupinfo", ctx.startupinfo)
    return run_process_with_retry(cmd, **kwargs)


def run_unified_postprocess_ffmpeg(ctx, output_path, fixed_layers, watermark_position, log_func=None):
    """阶段3：固定图层/视频水印/BGM 尽量一次FFmpeg完成。"""
    if not ctx.ffmpeg_available:
        return False
    if not os.path.isfile(output_path):
        return False

    main_meta = probe_video_meta(output_path, ctx.ffprobe_executable, ctx.ffmpeg_executable,
                          ctx.startupinfo, ctx.fps_provider)
    if not main_meta:
        return False

    watermark_video = select_video_watermark_file(ctx, log_func)
    bgm_file = select_bgm_file(ctx)
    fixed_specs = collect_fixed_layer_specs_for_ffmpeg(ctx) if fixed_layers else []
    blend_mode = get_video_watermark_blend_mode(ctx)

    if not (watermark_video or bgm_file or fixed_specs):
        return True

    ffmpeg_blend_mode = get_ffmpeg_blend_mode(ctx, blend_mode)
    wm_match_method = read_value(ctx, "watermark_match_method", "循环") if ctx is not None else "循环"
    # 高级混合模式只要 FFmpeg 支持，就走 FFmpeg 快速路径（含“单次”匹配）。
    # 单次模式通过 blend 的 eof_action=pass + repeatlast=0 实现“水印结束后透传原画面”。
    if watermark_video and blend_mode != "正常":
        if ffmpeg_blend_mode is None:
            _stage(ctx, 
                "POST-SKIP",
                f"视频水印混合模式={blend_mode} 暂不支持FFmpeg快速路径，回退OpenCV",
                log_func,
            )
            return False

    # 固定图片图层若使用高级混合模式，同样回退到OpenCV路径
    if any(spec.get("blend_mode", "正常") != "正常" for spec in fixed_specs):
        _stage(ctx, 
            "POST-SKIP",
            "检测到图片水印高级混合模式，回退OpenCV以保证混合模式生效",
            log_func,
        )
        return False

    _stage(ctx, 
        "POST-START",
        f"输入={output_path}, 帧数={main_meta['frames']}, 编排={{固定图层:{len(fixed_specs)}, 视频水印:{bool(watermark_video)}, BGM:{bool(bgm_file)}}}",
        log_func,
    )

    base_cmd = [ctx.ffmpeg_executable or "ffmpeg", "-y", "-i", output_path]
    filter_parts = []
    current_label = "[0:v]"
    input_idx = 1
    audio_label = None

    # 视频水印
    if watermark_video and os.path.isfile(watermark_video):
        match_method = read_value(ctx, "watermark_match_method", "循环")
        loop_wm = (match_method == "循环")
        if loop_wm:
            base_cmd += ["-stream_loop", "-1"]
        base_cmd += ["-i", watermark_video]

        wm_meta = probe_video_meta(watermark_video, ctx.ffprobe_executable, ctx.ffmpeg_executable,
                          ctx.startupinfo, ctx.fps_provider)
        if wm_meta:
            wm_w, wm_h = wm_meta["width"], wm_meta["height"]
            target_w, target_h, x_pos, y_pos = calc_overlay_geometry(ctx, 
                main_meta["width"],
                main_meta["height"],
                wm_w,
                wm_h,
                read_value(ctx, "watermark_size_mode", "自适应覆盖"),
                read_value(ctx, "watermark_scale", 20.0),
                watermark_position,
            )
            wm_label = f"wmv_{input_idx}"
            wm_chain = f"[{input_idx}:v]setpts=PTS-STARTPTS,scale={target_w}:{target_h}"
            if match_method == "拉伸" and wm_meta["duration"] > 0 and main_meta["duration"] > 0:
                stretch_ratio = main_meta["duration"] / wm_meta["duration"]
                wm_chain = f"[{input_idx}:v]setpts={stretch_ratio:.6f}*PTS,scale={target_w}:{target_h}"
            if blend_mode == "正常":
                blend_alpha = get_video_watermark_alpha(ctx, blend_mode)
                wm_chain += f",format=rgba,colorchannelmixer=aa={blend_alpha:.3f}"
            filter_parts.append(f"{wm_chain}[{wm_label}]")
            next_label = f"v_wm_{input_idx}"
            if blend_mode == "正常":
                overlay_mode = "shortest=1" if loop_wm else "eof_action=pass"
                filter_parts.append(
                    f"{current_label}[{wm_label}]overlay=x={x_pos}:y={y_pos}:{overlay_mode}[{next_label}]"
                )
                current_label = f"[{next_label}]"
            else:
                blend_alpha = get_video_watermark_alpha(ctx, blend_mode)
                # 仅在ROI区域做blend，避免对整帧颜色空间产生副作用（修复色偏问题）
                # 先将ROI与水印统一到 gbrp，再混合后贴回原视频。
                x_clip = max(0, min(x_pos, max(0, main_meta["width"] - target_w)))
                y_clip = max(0, min(y_pos, max(0, main_meta["height"] - target_h)))
                roi_base_label = f"roi_base_{input_idx}"
                wm_blend_src_label = f"wm_src_{input_idx}"
                roi_blend_label = f"roi_blend_{input_idx}"
                if loop_wm:
                    # 循环模式：水印流无限，按最短流结束（主视频）即可。
                    blend_sync_opts = "shortest=1"
                else:
                    # 单次/拉伸：水印流结束后透传主视频，不保留最后一帧。
                    blend_sync_opts = "eof_action=pass:repeatlast=0"
                filter_parts.append(
                    f"{current_label}crop={target_w}:{target_h}:{x_clip}:{y_clip},format=gbrp[{roi_base_label}]"
                )
                filter_parts.append(f"[{wm_label}]format=gbrp[{wm_blend_src_label}]")
                filter_parts.append(
                    f"[{roi_base_label}][{wm_blend_src_label}]blend=all_mode={ffmpeg_blend_mode}:all_opacity={blend_alpha:.3f}:{blend_sync_opts}[{roi_blend_label}]"
                )
                overlay_mode = "shortest=1" if loop_wm else "eof_action=pass"
                filter_parts.append(
                    f"{current_label}[{roi_blend_label}]overlay=x={x_clip}:y={y_clip}:{overlay_mode}[{next_label}]"
                )
                current_label = f"[{next_label}]"
        input_idx += 1

    # 固定图片图层
    for idx, spec in enumerate(fixed_specs):
        if not os.path.isfile(spec["path"]):
            continue
        base_cmd += ["-loop", "1", "-i", spec["path"]]
        wm_img = safe_read_image_with_alpha(ctx, spec["path"])
        if wm_img is None:
            input_idx += 1
            continue
        wm_h, wm_w = wm_img.shape[:2]
        target_w, target_h, x_pos, y_pos = calc_overlay_geometry(ctx, 
            main_meta["width"],
            main_meta["height"],
            wm_w,
            wm_h,
            spec["size_mode"],
            spec["scale"],
            spec["position"],
        )
        fix_label = f"fix_{idx}"
        filter_parts.append(
            f"[{input_idx}:v]format=rgba,colorchannelmixer=aa={spec['opacity']:.3f},scale={target_w}:{target_h}[{fix_label}]"
        )
        next_label = f"v_fix_{idx}"
        filter_parts.append(
            f"{current_label}[{fix_label}]overlay=x={x_pos}:y={y_pos}:shortest=1[{next_label}]"
        )
        current_label = f"[{next_label}]"
        input_idx += 1

    # BGM
    if bgm_file and os.path.isfile(bgm_file):
        bgm_loop = bool(read_value(ctx, "loop_bgm", True)) if ctx is not None else True
        if bgm_loop:
            base_cmd += ["-stream_loop", "-1"]
        base_cmd += ["-i", bgm_file]
        audio_label = "bgm_a"
        volume = float(read_value(ctx, "bgm_volume", 0.5)) if ctx is not None else 0.5
        filter_parts.append(f"[{input_idx}:a]volume={volume:.2f}[{audio_label}]")
        input_idx += 1

    def build_cmd(vcodec):
        temp_output = build_temp_output_path(output_path, "pipeline_temp", ctx)
        cmd = list(base_cmd)
        if filter_parts:
            cmd += ["-filter_complex", ";".join(filter_parts)]
        video_map = current_label if current_label != "[0:v]" else "0:v"
        cmd += ["-map", video_map]
        if audio_label:
            a_codec = get_container_compatible_acodec(output_path, ctx)
            cmd += ["-map", f"[{audio_label}]", "-c:a", a_codec, "-b:a", "192k"]
            if bgm_loop:
                # 循环音频无限长，-shortest 以视频时长为准
                cmd += ["-shortest"]
            else:
                # 非循环：用 -t 硬性限定输出时长 = 主视频时长，
                # 避免 BGM 比视频短时 -shortest 把视频截短。
                main_duration = float(main_meta.get("duration") or 0.0) if main_meta else 0.0
                if main_duration > 0:
                    cmd += ["-t", f"{main_duration:.3f}"]
                else:
                    cmd += ["-shortest"]
        else:
            cmd += ["-map", "0:a?", "-c:a", "copy"]
        cmd += ["-c:v", vcodec]
        if vcodec == "libx264":
            cmd += ["-preset", "medium"]
        cmd += ["-filter_threads", "0", "-threads", "0"]
        muxer = get_ffmpeg_muxer_for_output(output_path, ctx)
        # 后处理保持源视频时基，不强制改写 FPS，避免短视频被拉成长视频。
        cmd += ["-pix_fmt", "yuv420p"]
        if muxer:
            cmd += ["-f", muxer]
        cmd += [temp_output]
        return cmd, temp_output

    strict_codec = get_strict_ffmpeg_vcodec_for_output(output_path, ctx)
    if not strict_codec:
        _stage(ctx, 
            "POST-FAIL",
            f"编码器与容器不兼容: codec={get_selected_codec_name(ctx)}, ext={get_output_extension(output_path, ctx)}",
            log_func,
        )
        return False
    codec_candidates = [strict_codec]

    start_ts = time.time()
    for codec in codec_candidates:
        cmd, temp_output = build_cmd(codec)
        _stage(ctx, "POST-RUN", f"尝试编码器={codec}", log_func)
        result = _run_proc(ctx, 
            cmd,
            stage="POST",
            timeout_sec=900,
            retries=2,
            log_func=log_func,
        )
        if result is None:
            _stage(ctx, "POST-FAIL", f"编码器={codec}, 无可用执行结果", log_func)
            continue
        if result.returncode == 0 and os.path.exists(temp_output) and os.path.getsize(temp_output) > 1000:
            if not safe_replace_file(temp_output, output_path):
                _stage(ctx, "POST-FAIL", f"编码器={codec}, 文件替换失败", log_func)
                continue
            elapsed = time.time() - start_ts
            _stage(ctx, 
                "POST-OK",
                f"输出={output_path}, 编码器={codec}, 容器={get_output_extension(output_path, ctx)}, 耗时={elapsed:.2f}s",
                log_func,
            )
            log_output_probe(output_path, log_func, ctx)
            return True

        err = result.stderr.decode("utf-8", errors="ignore")
        _stage(ctx, 
            "POST-FAIL",
            f"编码器={codec}, 错误码={result.returncode}, 原因={err[:200]}",
            log_func,
        )
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except Exception:
                pass

    return False

def run_fixed_layers_ffmpeg_only(ctx, output_path, fixed_layers, log_func=None):
    """仅用FFmpeg处理固定图片图层（正常混合模式），用于高级视频混合场景提速。"""
    if not ctx.ffmpeg_available:
        return False
    if not fixed_layers or not os.path.isfile(output_path):
        return False

    def _log(msg):
        if log_func:
            log_func(msg)

    main_meta = probe_video_meta(output_path, ctx.ffprobe_executable, ctx.ffmpeg_executable,
                          ctx.startupinfo, ctx.fps_provider)
    if not main_meta:
        return False

    fixed_specs = collect_fixed_layer_specs_for_ffmpeg(ctx)
    if not fixed_specs:
        return False
    if any(spec.get("blend_mode", "正常") != "正常" for spec in fixed_specs):
        _log("固定图层包含高级混合模式，跳过FFmpeg固定图层加速")
        return False

    base_cmd = [ctx.ffmpeg_executable or "ffmpeg", "-y", "-i", output_path]
    filter_parts = []
    current_label = "[0:v]"
    input_idx = 1

    for idx, spec in enumerate(fixed_specs):
        if not os.path.isfile(spec["path"]):
            continue
        base_cmd += ["-loop", "1", "-i", spec["path"]]
        wm_img = safe_read_image_with_alpha(ctx, spec["path"])
        if wm_img is None:
            input_idx += 1
            continue
        wm_h, wm_w = wm_img.shape[:2]
        target_w, target_h, x_pos, y_pos = calc_overlay_geometry(ctx, 
            main_meta["width"],
            main_meta["height"],
            wm_w,
            wm_h,
            spec["size_mode"],
            spec["scale"],
            spec["position"],
        )
        fix_label = f"fix_only_{idx}"
        filter_parts.append(
            f"[{input_idx}:v]format=rgba,colorchannelmixer=aa={spec['opacity']:.3f},scale={target_w}:{target_h}[{fix_label}]"
        )
        next_label = f"v_fix_only_{idx}"
        filter_parts.append(
            f"{current_label}[{fix_label}]overlay=x={x_pos}:y={y_pos}:shortest=1[{next_label}]"
        )
        current_label = f"[{next_label}]"
        input_idx += 1

    if not filter_parts:
        return False

    strict_codec = get_strict_ffmpeg_vcodec_for_output(output_path, ctx)
    if not strict_codec:
        return False

    temp_output = build_temp_output_path(output_path, "fixed_ffmpeg_temp", ctx)
    cmd = list(base_cmd)
    cmd += ["-filter_complex", ";".join(filter_parts)]
    video_map = current_label if current_label != "[0:v]" else "0:v"
    cmd += ["-map", video_map, "-map", "0:a?", "-c:a", "copy", "-c:v", strict_codec]
    if strict_codec == "libx264":
        cmd += ["-preset", "medium"]
    muxer = get_ffmpeg_muxer_for_output(output_path, ctx)
    # 固定图层后处理同样不改 FPS，避免时长偏移。
    cmd += ["-pix_fmt", "yuv420p"]
    if muxer:
        cmd += ["-f", muxer]
    cmd += [temp_output]

    result = _run_proc(ctx, 
        cmd,
        stage="FIXED",
        timeout_sec=600,
        retries=2,
        log_func=log_func,
    )
    if result is None:
        return False
    if result.returncode == 0 and os.path.exists(temp_output) and os.path.getsize(temp_output) > 1000:
        if not safe_replace_file(temp_output, output_path):
            return False
        _log("固定图层FFmpeg加速处理成功")
        return True

    if os.path.exists(temp_output):
        try:
            os.remove(temp_output)
        except Exception:
            pass
    return False

def postprocess_video_output(ctx, output_path, fixed_layers, watermark_position, log_func=None, pipeline_start_time=None):
    """统一处理固定水印、视频水印与BGM"""
    def _log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)

    task_start_ts = float(pipeline_start_time) if pipeline_start_time else time.time()
    render_weight = float(read_value(ctx, "_progress_render_weight", 1.0))
    base_percent = int(max(0, min(100, round(render_weight * 100))))
    post_span = max(0, 100 - base_percent)

    def _post_progress(ratio, stage_text=None, force=False):
        if post_span <= 0:
            return
        ratio = max(0.0, min(1.0, float(ratio)))
        percent = base_percent + int(round(post_span * ratio))
        if stage_text:
            set_value(ctx, "_progress_phase_label", stage_text)
            try:
                notify(ctx, f"{stage_text}...")
            except Exception:
                pass
        info = f"任务进度: {percent}%"
        if stage_text:
            info = f"{info}（{stage_text}）"
        emit_set_absolute_progress(ctx, percent, info_text=info, force=force)

    def _finish_with_elapsed(note="任务完成"):
        emit_set_absolute_progress(ctx, 100, info_text="任务进度: 100%（完成）", force=True)
        elapsed = max(0.0, time.time() - task_start_ts)
        notify(ctx, f"{note}，耗时: {elapsed:.1f} 秒")
        _log(f"{note}，总耗时: {elapsed:.2f} 秒")

    _post_progress(0.05, "收尾中", force=True)

    current_video_blend_mode = get_video_watermark_blend_mode(ctx)
    ffmpeg_video_blend_supported = (
        get_ffmpeg_blend_mode(ctx, current_video_blend_mode) is not None
    )
    advanced_video_blend = (
        read_value(ctx, "use_watermark", False)
        and read_value(ctx, "watermark_type", "视频") == "视频"
        and current_video_blend_mode != "正常"
        and not ffmpeg_video_blend_supported
    )

    # 高级视频混合模式优先走分层链路：
    # 1) 固定图片图层（正常模式）先用FFmpeg提速；
    # 2) MOV视频水印继续走OpenCV高级混合，确保效果一致。
    if advanced_video_blend:
        _log("检测到视频水印高级混合模式：启用分层后处理链路")
        _post_progress(0.15, "水印中")
        fixed_done = False
        if fixed_layers:
            try:
                fixed_done = run_fixed_layers_ffmpeg_only(ctx, output_path, fixed_layers, _log)
            except Exception as e:
                _log(f"固定图层FFmpeg加速失败，将回退OpenCV: {str(e)}")
            if not fixed_done:
                try:
                    add_fixed_image_watermarks_to_video(ctx, output_path, fixed_layers)
                    fixed_done = True
                except Exception as e:
                    _log(f"固定水印处理失败: {str(e)}")
        if fixed_done:
            _log("固定图层处理完成")
        _post_progress(0.45, "水印中")

    else:
        # 优先使用一次性FFmpeg后处理（阶段3），失败时再回退原流程（阶段4）
        try:
            _post_progress(0.35, "水印中")
            unified_success = run_unified_postprocess_ffmpeg(ctx, 
                output_path,
                fixed_layers,
                watermark_position,
                _log,
            )
            if unified_success:
                log_output_probe(output_path, _log, ctx)
                _finish_with_elapsed("后处理完成")
                return
            _log("统一后处理失败，回退到兼容链路（不中断任务）")
            _post_progress(0.45, "水印中")
        except Exception as e:
            _log(f"统一后处理异常，回退兼容链路: {str(e)}")
            _post_progress(0.45, "水印中")

        # 固定图片水印（不跟随转场/特效）
        if fixed_layers:
            try:
                add_fixed_image_watermarks_to_video(ctx, output_path, fixed_layers)
            except Exception as e:
                _log(f"固定水印处理失败: {str(e)}")
        _post_progress(0.60, "水印中")

    # 视频水印（MOV）
    if read_value(ctx, "use_watermark", False) and read_value(ctx, "watermark_type", "视频") == "视频":
        watermark_base_path = read_value(ctx, "watermark_path", None)
        if watermark_base_path and os.path.exists(watermark_base_path):
            watermark_mode_value = read_value(ctx, "watermark_mode", "单文件")

            watermark_video_path = None
            if watermark_mode_value == "文件夹" and os.path.isdir(watermark_base_path):
                _log(f"检测到文件夹模式水印: {watermark_base_path}")
                watermark_files = get_watermark_files(ctx, watermark_base_path)
                if watermark_files:
                    video_idx = read_value(ctx, "_current_video_index", 0)
                    watermark_video_path = watermark_files[video_idx % len(watermark_files)]
                    _log(f"选择水印文件 [{video_idx % len(watermark_files) + 1}/{len(watermark_files)}]: {os.path.basename(watermark_video_path)}")
                else:
                    _log("文件夹中没有找到视频水印文件")
            else:
                if os.path.isfile(watermark_base_path):
                    watermark_video_path = watermark_base_path
                    _log(f"使用单文件水印: {watermark_video_path}")
                else:
                    _log(f"水印路径无效: {watermark_base_path}")

            if watermark_video_path and os.path.isfile(watermark_video_path):
                _log(f"开始添加视频水印: {os.path.basename(watermark_video_path)}")
                temp_output = build_temp_output_path(output_path, "watermark_temp", ctx)
                try:
                    watermark_success = add_video_watermark(ctx, 
                        main_video_path=output_path,
                        watermark_path=watermark_video_path,
                        output_path=temp_output,
                        position=watermark_position,
                        match_method=read_value(ctx, "watermark_match_method", "循环")
                    )
                    if watermark_success and os.path.exists(temp_output):
                        if os.path.exists(output_path):
                            os.remove(output_path)
                        os.rename(temp_output, output_path)
                        _log("视频水印添加成功")
                    else:
                        _log("视频水印添加失败")
                        if os.path.exists(temp_output):
                            os.remove(temp_output)
                except Exception as e:
                    _log(f"视频水印处理出错: {str(e)}")
                    if os.path.exists(temp_output):
                        os.remove(temp_output)
            else:
                _log("没有找到有效的水印文件")
    _post_progress(0.80, "水印中")

    # 背景音乐
    audio_strategy = read_value(ctx, "watermark_audio", "使用BGM") if ctx is not None else "使用BGM"
    if read_value(ctx, "use_bgm", False) and audio_strategy in ("使用BGM", "两者混合"):
        bgm_files = resolve_bgm_candidates(ctx)
        if bgm_files:
            _log(f"开始添加背景音乐: {os.path.dirname(bgm_files[0])}")
            if read_value(ctx, "random_bgm", False):
                import random
                bgm_file = random.choice(bgm_files)
            else:
                bgm_file = bgm_files[0]
            _log(f"选择音乐文件: {os.path.basename(bgm_file)}")
            try:
                volume = read_value(ctx, "bgm_volume", 0.5)
                bgm_success = add_audio_with_ffmpeg(output_path, bgm_file, volume, ctx)
                if bgm_success:
                    _log("背景音乐添加成功")
                else:
                    _log("背景音乐添加失败")
            except Exception as e:
                _log(f"添加背景音乐出错: {str(e)}")
        else:
            _log("BGM目录中没有找到音乐文件")
    _post_progress(0.95, "BGM中")

    # 末端容器/编码校验日志
    set_value(ctx, "_progress_phase_label", "收尾中")
    log_output_probe(output_path, _log, ctx)
    _finish_with_elapsed("后处理完成")
