"""视频编码与容器写出（与界面无关的渲染内核）。

从 ``src/gui/main_window.py`` 的 ``ImageToVideoTab`` 抽出，函数体逐字保留。
本模块不导入任何 GUI 库。
"""

from __future__ import annotations

import os
import subprocess
import time

import numpy as np

from ..utils.opencv_silent import import_cv2_silent
from .codec import (build_temp_output_path, get_ffmpeg_muxer_for_output,
                    get_output_extension, get_selected_codec_name,
                    get_strict_ffmpeg_vcodec_for_output, log_output_probe)
from .controls import wait_for_processing_control
from .context import (RenderContext, emit_progress, emit_reset_overall_progress,
                      emit_reset_progress, emit_set_absolute_progress, notify, read_value,
                      should_cancel)
from .effects import apply_single_image_effect
from .images import resize_image, resize_with_aspect_ratio, safe_read_image
from .plan import VIDEO_EFFECTS, compute_video_frame_plan
from .process import ensure_even_frame, log_pipeline_stage, probe_video_meta, safe_replace_file
from .watermark import add_fixed_image_watermarks_to_video, apply_image_watermark_layers

cv2 = import_cv2_silent()


def _stage(ctx, stage, message, log_func=None):
    log_pipeline_stage(stage, message, log_func, read_value(ctx, "_pipeline_log_file"))


def has_postprocess_work(ctx, fixed_layers=None):
    """判断是否存在渲染后处理任务（固定图层/视频水印/BGM）。"""
    has_fixed = bool(fixed_layers)
    has_video_wm = bool(
        read_value(ctx, "use_watermark", False)
        and read_value(ctx, "watermark_type", "视频") == "视频"
        and read_value(ctx, "watermark_path", None)
        and os.path.exists(read_value(ctx, "watermark_path", None))
    )
    has_bgm = bool(
        read_value(ctx, "use_bgm", False)
        and (
            bool(read_value(ctx, "_bgm_files"))
            or (
                read_value(ctx, "bgm_dir", None)
                and os.path.exists(read_value(ctx, "bgm_dir", None))
            )
        )
    )
    return has_fixed or has_video_wm or has_bgm


def create_video_with_ffmpeg(ctx, images, output_path, duration, fps, width, height,
                            apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                            transition_frames, transition_type, watermark_opacity,
                            watermark_size, target_bitrate, log_func, video_effect_type_override=None,
                            preprocessed_images=None):
    """使用FFmpeg创建视频并控制码率

    Args:
        images: 图片文件路径列表
        output_path: 输出视频文件路径
        duration: 每张图片的显示时长（秒）
        fps: 视频帧率
        width: 视频宽度
        height: 视频高度
        apply_image_watermark: 是否应用图片水印
        watermark_images: 水印图片列表
        watermark_position: 水印位置
        transition_frames: 转场帧数
        transition_type: 转场效果类型
        watermark_opacity: 水印不透明度
        watermark_size: 水印大小百分比
        target_bitrate: 目标码率（kbps）
        log_func: 日志函数
        preprocessed_images: 与 images 对齐的预处理帧列表（可选，用于复用Turbo预处理结果）

    Returns:
        bool: 成功返回True，失败返回False
    """
    ffmpeg_proc = None
    try:
        log_func(f"开始使用FFmpeg管道创建视频，目标码率: {target_bitrate} kbps")

        strict_vcodec = get_strict_ffmpeg_vcodec_for_output(output_path, ctx)
        if not strict_vcodec:
            log_func(
                f"编码器与容器不兼容: codec={get_selected_codec_name(ctx)}, ext={get_output_extension(output_path, ctx)}"
            )
            return False
        muxer = get_ffmpeg_muxer_for_output(output_path, ctx)
        ffmpeg_cmd = [
            ctx.ffmpeg_executable or "ffmpeg", "-y",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-i", "-",
            "-an",
            "-c:v", strict_vcodec,
            "-b:v", f"{target_bitrate}k",
            "-maxrate", f"{int(target_bitrate * 1.1)}k",
            "-bufsize", f"{int(target_bitrate * 1.5)}k",
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
        ]
        if strict_vcodec == "libx264":
            ffmpeg_cmd += ["-preset", "medium"]
        if muxer:
            ffmpeg_cmd += ["-f", muxer]
        ffmpeg_cmd += [output_path]
        log_func(f"管道编码命令[{strict_vcodec}]: {' '.join(ffmpeg_cmd)}")

        ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=ctx.startupinfo,
        )

        total_images = len(images)
        total_time_per_img = duration
        # 统一帧计划：总时长严格按设置（round 取整，余数由最后一张吸收）
        total_frames_per_img, transition_frames, display_frames_per_img, last_img_frames = compute_video_frame_plan(
            total_images, duration, fps, transition_frames, transition_type
        )
        total_frames = (total_images - 1) * total_frames_per_img + last_img_frames
        static_time = display_frames_per_img / fps
        transition_time = transition_frames / fps
        log_func(
            f"每张图片总时长: {total_time_per_img}秒 (静态: {static_time:.2f}秒 + 转场: {transition_time:.2f}秒), "
            f"总帧数: {total_frames}, 实际视频时长: {total_frames / max(1, fps):.2f}秒"
        )
        if ctx is not None:
            render_weight = 0.82 if has_postprocess_work(ctx, fixed_layers) else 1.0
            emit_reset_progress(ctx, total_frames, render_weight=render_weight)

        frame_count = 0
        # 降低 UI/桥接更新频率，减少导出过程中 Python 与 GUI 开销。
        progress_interval = max(12, min(60, int(max(1, fps) // 2)))
        use_preprocessed_frames = (
            isinstance(preprocessed_images, list)
            and len(preprocessed_images) == len(images)
        )
        if preprocessed_images is not None and not use_preprocessed_frames:
            log_func("预处理帧数量与图片数量不一致，回退实时读取链路")
        if use_preprocessed_frames:
            log_func("FFmpeg渲染复用Turbo预处理帧，跳过重复读图/缩放/跟随水印")
        effect_type_for_video = (
            video_effect_type_override
            if video_effect_type_override in VIDEO_EFFECTS
            else read_value(ctx, "video_effect_type", "无特效")
        )
        effect_enabled = (
            ctx is not None
            and read_value(ctx, "use_video_effect", False)
            and effect_type_for_video != "无特效"
        )

        def ensure_runtime_control():
            if not wait_for_processing_control(ctx=ctx):
                raise InterruptedError("用户取消处理")

        def write_frame(frame):
            nonlocal frame_count
            ensure_runtime_control()
            frame = ensure_even_frame(frame)
            if frame is None:
                return False
            h, w = frame.shape[:2]
            if w != width or h != height:
                frame = cv2.resize(frame, (width, height))
            if ffmpeg_proc.stdin is None:
                return False
            ffmpeg_proc.stdin.write(frame.tobytes())
            frame_count += 1
            if frame_count % progress_interval == 0:
                emit_progress(ctx, frame_count)
            return True

        def load_processed_frame(img_path, image_index):
            if use_preprocessed_frames:
                frame = preprocessed_images[image_index]
                if frame is None:
                    log_func(f"预处理帧为空，跳过: {img_path}")
                    return None
                return ensure_even_frame(frame)

            frame = safe_read_image(img_path, ctx.notify, ctx.turbo_accelerator)
            if frame is None:
                log_func(f"无法加载图片: {img_path}")
                return None
            frame = resize_image(frame, width, height, "适应", True)
            if frame is None:
                log_func(f"图片resize失败: {img_path}")
                return None
            if follow_layers:
                frame = apply_image_watermark_layers(ctx, 
                    frame, follow_layers, image_index=image_index
                )
            return ensure_even_frame(frame)

        last_good_frame = None
        for img_index, img_path in enumerate(images):
            ensure_runtime_control()
            log_func(f"处理图片 {img_index + 1}/{total_images}: {os.path.basename(img_path)}")
            current_img = load_processed_frame(img_path, img_index)
            if current_img is None:
                # 图片加载失败：用上一张成功帧补位，保证总时长严格按设置生成
                if last_good_frame is None:
                    log_func(f"首图加载失败，无法按设定时长生成视频: {img_path}")
                    return False
                current_img = last_good_frame
                log_func(f"图片加载失败，用相邻帧补位保持时长: {img_path}")
            else:
                last_good_frame = current_img

            is_last_img = (img_index == total_images - 1)
            static_frames = last_img_frames if is_last_img else display_frames_per_img

            if effect_enabled:
                effect_frames = max(1, static_frames)
                duration_sec = max(0.001, effect_frames / max(1, fps))
                for frame_idx in range(effect_frames):
                    ensure_runtime_control()
                    time_sec = frame_idx / max(1, fps)
                    frame = apply_single_image_effect(
                        current_img,
                        effect_type_for_video,
                        time_sec,
                        duration_sec,
                        read_value(ctx, "video_effect_intensity", 100.0),
                        read_value(ctx, "video_effect_speed", 1.0)
                    )
                    if not write_frame(frame):
                        raise BrokenPipeError("FFmpeg管道写入失败")
            else:
                for _ in range(static_frames):
                    ensure_runtime_control()
                    if not write_frame(current_img):
                        raise BrokenPipeError("FFmpeg管道写入失败")

            # 最后一张图：静态帧已含全部帧数（last_img_frames），无需再补帧
            if not is_last_img:
                ensure_runtime_control()
                next_img_path = images[img_index + 1]
                next_img = load_processed_frame(next_img_path, img_index + 1)
                if next_img is None:
                    # 下一张图加载失败：用当前帧占位，保证转场帧数不缺失（时长不变）
                    next_img = current_img
                if transition_frames > 0 and transition_type != "无转场":
                    transition_frames_list = None
                    if ctx.transition_engine:
                        try:
                            transition_frames_list = ctx.transition_engine.generate_transition_frames(
                                current_img, next_img, transition_type, transition_frames, use_cache=True
                            )
                        except Exception as trans_err:
                            log_func(f"转场引擎失败，回退基础转场: {str(trans_err)}")
                            transition_frames_list = None

                    if transition_frames_list:
                        for transition_frame in transition_frames_list:
                            ensure_runtime_control()
                            if not write_frame(transition_frame):
                                raise BrokenPipeError("FFmpeg管道写入失败")
                    else:
                        # 回退：至少保持可见过渡
                        for t_frame in range(transition_frames):
                            ensure_runtime_control()
                            progress = (t_frame + 1) / (transition_frames + 1)
                            transition_frame = cv2.addWeighted(
                                current_img, 1 - progress, next_img, progress, 0
                            )
                            if not write_frame(transition_frame):
                                raise BrokenPipeError("FFmpeg管道写入失败")

        if ffmpeg_proc.stdin:
            ffmpeg_proc.stdin.close()
            ffmpeg_proc.stdin = None
        # 结束前强制刷新一次进度，保证 UI 最终状态准确。
        emit_progress(ctx, frame_count)
        _, stderr_data = ffmpeg_proc.communicate()
        if ffmpeg_proc.returncode != 0:
            stderr_output = stderr_data.decode('utf-8', errors='ignore') if stderr_data else ""
            log_func(f"FFmpeg管道编码失败[{strict_vcodec}]，错误码: {ffmpeg_proc.returncode}")
            log_func(f"错误信息: {stderr_output[:300]}")
            return False

        log_func(f"FFmpeg管道写入完成，共输出 {frame_count} 帧")
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            log_func(f"FFmpeg视频合成成功，编码器={strict_vcodec}")
            log_func(f"视频文件创建成功: {output_path}")
            log_func(f"文件大小: {os.path.getsize(output_path)} 字节")
            log_output_probe(output_path, log_func, ctx)
            if fixed_layers:
                add_fixed_image_watermarks_to_video(ctx, output_path, fixed_layers)
            return True

        log_func("FFmpeg管道编码结束但输出文件无效")
        return False

    except InterruptedError:
        try:
            if ffmpeg_proc is not None:
                if ffmpeg_proc.stdin:
                    ffmpeg_proc.stdin.close()
                ffmpeg_proc.terminate()
                try:
                    ffmpeg_proc.wait(timeout=2)
                except Exception:
                    ffmpeg_proc.kill()
        except Exception:
            pass
        log_func("已取消当前视频生成")
        return False
    except Exception as e:
        try:
            if ffmpeg_proc is not None:
                if ffmpeg_proc.stdin:
                    ffmpeg_proc.stdin.close()
                ffmpeg_proc.kill()
        except Exception:
            pass
        log_func(f"使用FFmpeg管道创建视频时出错: {str(e)}")
        import traceback
        log_func(traceback.format_exc())
        return False
