"""帧序生成与视频合成（与界面无关的渲染内核）。

从 ``src/gui/main_window.py`` 的 ``ImageToVideoTab`` 抽出，函数体逐字保留。
本模块不导入任何 GUI 库。
"""

from __future__ import annotations

import os
import time

import numpy as np

from ..utils.opencv_silent import import_cv2_silent
from .codec import (build_temp_output_path, get_output_extension, get_selected_codec_name,
                    resolve_cv_fourcc)
from .context import (RenderContext, emit_progress, emit_reset_overall_progress,
                      emit_reset_progress, emit_set_absolute_progress, notify, read_value,
                      should_cancel)
from .effects import apply_single_image_effect
from .encoder import create_video_with_ffmpeg, has_postprocess_work
from .images import resize_image, resize_with_aspect_ratio, safe_read_image
from .postprocess import postprocess_video_output
from .process import ensure_even_frame
from .controls import wait_for_processing_control
from .plan import VIDEO_EFFECTS, compute_video_frame_plan
from .transitions import apply_transition
from .watermark import (add_fixed_image_watermarks_to_video, apply_image_watermark_layers,
                        prepare_image_watermark_layers)

cv2 = import_cv2_silent()


def create_video(ctx, images, output_path, duration, fps, width=1920, height=1080,
                 apply_image_watermark=False, watermark_path=None, watermark_position="右下",
                 resize_mode="适应", maintain_aspect=True, transition_frames=15, transition_type="淡入淡出",
                 watermark_opacity=0.5, watermark_size=20, video_effect_type_override=None):
    """创建图片到视频的转换（支持码率控制+自动编码器切换+详细日志+文件日志）

    参数:
        images: 图片文件路径列表
        output_path: 输出视频文件路径
        duration: 每张图片的显示时长（秒），即用户设置的单张图片持续时间
        fps: 视频帧率
        width: 视频宽度
        height: 视频高度
        apply_image_watermark: 是否应用图片水印
        watermark_path: 水印图片路径
        watermark_position: 水印位置（"左上"、"右上"、"左下"、"右下"、"中心"）
        resize_mode: 图片调整大小模式（"适应"、"拉伸"、"填充"、"原始尺寸"）
        maintain_aspect: 是否保持宽高比
        transition_frames: 转场帧数
        transition_type: 转场效果类型
        watermark_opacity: 水印不透明度（0.0-1.0）
        watermark_size: 水印大小百分比
    """
    import traceback
    def log(msg):
        print(msg)
        try:
            with open("video_create_debug.log", "a", encoding="utf-8") as f:
                f.write(msg+"\n")
        except Exception:
            pass
    if not images or not output_path:
        msg = "没有选择图片或输出路径"
        notify(ctx, msg)
        log(msg)
        return False
    
    try:
        task_start_time = time.time()
        total_images = len(images)
        effect_type_for_video = (
            video_effect_type_override
            if video_effect_type_override in VIDEO_EFFECTS
            else read_value(ctx, "video_effect_type", "无特效")
        )
        msg = f"处理 {total_images} 张图片"
        notify(ctx, msg)
        log(msg)
        if total_images < 1:
            msg = "至少需要一张图片"
            notify(ctx, msg)
            log(msg)
            return False
        # 修改：每张图片的总时间包含转场时间，而不是额外添加
        total_time_per_img = duration  # 用户设置的每张图片总时间
        # 统一帧计划：总时长严格按设置（round 取整，余数由最后一张吸收）
        total_frames_per_img, transition_frames, display_frames_per_img, last_img_frames = compute_video_frame_plan(
            total_images, duration, fps, transition_frames, transition_type
        )
        total_frames = (total_images - 1) * total_frames_per_img + last_img_frames

        # 添加日志输出来确认时间计算
        static_time = display_frames_per_img / fps
        transition_time = transition_frames / fps
        total_video_duration = total_time_per_img * total_images  # 总时长就是图片数量×每张时间

        msg = f"每张图片总时长: {total_time_per_img}秒 (静态: {static_time:.2f}秒 + 转场: {transition_time:.2f}秒), 总视频时长: {total_video_duration:.2f}秒"
        notify(ctx, msg)
        log(msg)
        
        first_img = safe_read_image(images[0], ctx.notify, ctx.turbo_accelerator)
        if first_img is None:
            msg = f"无法加载图片: {images[0]}"
            notify(ctx, msg)
            log(msg)
            return False
        msg = f"首图shape: {first_img.shape}"
        notify(ctx, msg)
        log(msg)
        if resize_mode == "原始尺寸":
            h, w = first_img.shape[:2]
            out_w, out_h = w, h
        else:
            out_w, out_h = width, height
        prepared_layers = prepare_image_watermark_layers(ctx) if apply_image_watermark else []
        follow_layers = [l for l in prepared_layers if not l.get("fixed")]
        fixed_layers = [l for l in prepared_layers if l.get("fixed")]
        # 获取用户设置的码率
        target_bitrate = read_value(ctx, "bitrate", 5000)
        msg = f"目标码率设置: {target_bitrate} kbps"
        notify(ctx, msg)
        log(msg)

        # 阶段2：主渲染优先使用FFmpeg（统一编码出口）
        selected_codec_name = get_selected_codec_name(ctx)
        use_ffmpeg_primary = bool(ctx.ffmpeg_available)

        if use_ffmpeg_primary:
            msg = f"统一编排：主渲染使用FFmpeg，编码器={selected_codec_name}，目标码率={target_bitrate} kbps"
            notify(ctx, msg)
            log(msg)
            success = create_video_with_ffmpeg(ctx, 
                images, output_path, duration, fps, out_w, out_h,
                apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                transition_frames, transition_type, watermark_opacity,
                watermark_size, target_bitrate, log, effect_type_for_video
            )
            if success:
                postprocess_video_output(ctx, output_path, fixed_layers, watermark_position, log, pipeline_start_time=task_start_time)
                return True
            msg = "FFmpeg主渲染失败，自动降级到OpenCV编码链路继续处理"
            notify(ctx, msg)
            log(msg)
        else:
            msg = f"使用OpenCV创建视频（码率由编码器自动决定）"
            notify(ctx, msg)
            log(msg)

        selected_codec = resolve_cv_fourcc(ctx)
        if not selected_codec:
            msg = f"编码器不可用: {get_selected_codec_name(ctx)}"
            notify(ctx, msg)
            log(msg)
            if ctx.ffmpeg_available:
                msg = "尝试使用FFmpeg按指定编码器生成视频"
                notify(ctx, msg)
                log(msg)
                success = create_video_with_ffmpeg(ctx, 
                    images, output_path, duration, fps, out_w, out_h,
                    apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                    transition_frames, transition_type, watermark_opacity,
                    watermark_size, target_bitrate, log, effect_type_for_video
                )
                if success:
                    postprocess_video_output(ctx, output_path, fixed_layers, watermark_position, log, pipeline_start_time=task_start_time)
                return success
            return False

        fourcc = cv2.VideoWriter_fourcc(*selected_codec)
        video_writer = cv2.VideoWriter(output_path, fourcc, fps, (out_w, out_h))
        if video_writer.isOpened():
            msg = f"使用编码器: {selected_codec}"
            notify(ctx, msg)
            log(msg)
        else:
            msg = f"编码器 {selected_codec} 创建失败"
            notify(ctx, msg)
            log(msg)
            if ctx.ffmpeg_available:
                msg = "尝试使用FFmpeg按指定编码器生成视频"
                notify(ctx, msg)
                log(msg)
                success = create_video_with_ffmpeg(ctx, 
                    images, output_path, duration, fps, out_w, out_h,
                    apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                    transition_frames, transition_type, watermark_opacity,
                    watermark_size, target_bitrate, log, effect_type_for_video
                )
                if success:
                    postprocess_video_output(ctx, output_path, fixed_layers, watermark_position, log, pipeline_start_time=task_start_time)
                return success
            return False
            
        # 计算视频总帧数（统一帧计划已给出精确总帧数，含最后一图余数）
        msg = f"每张图片帧数: {total_frames_per_img} (静态: {display_frames_per_img}, 转场: {transition_frames}), 总帧数: {total_frames}, 实际视频时长: {total_frames/fps:.2f}秒"
        notify(ctx, msg)
        log(msg)
        
        if ctx is not None:
            render_weight = 0.82 if has_postprocess_work(ctx, fixed_layers) else 1.0
            emit_reset_progress(ctx, total_frames, render_weight=render_weight)
        frames_written = 0
        effect_enabled = (
            ctx is not None
            and read_value(ctx, "use_video_effect", False)
            and effect_type_for_video != "无特效"
        )
        last_good_frame = None
        for img_index, img_path in enumerate(images):
            msg = f"处理图片 {img_index+1}/{total_images}: {os.path.basename(img_path)}"
            notify(ctx, msg)
            log(msg)
            try:
                current_img = safe_read_image(img_path, ctx.notify, ctx.turbo_accelerator)
                if current_img is None:
                    # 图片加载失败：用上一张成功帧补位，保证总时长严格按设置生成
                    if last_good_frame is None:
                        msg = f"首图加载失败，无法按设定时长生成视频: {img_path}"
                        notify(ctx, msg)
                        log(msg)
                        video_writer.release()
                        return False
                    current_img = last_good_frame
                    msg = f"图片加载失败，用相邻帧补位保持时长: {img_path}"
                    notify(ctx, msg)
                    log(msg)
                else:
                    last_good_frame = current_img
                msg = f"图片{img_index+1} shape: {current_img.shape}"
                notify(ctx, msg)
                log(msg)
                if resize_mode != "原始尺寸":
                    current_img = resize_image(current_img, out_w, out_h, resize_mode, maintain_aspect)
                    if current_img is None:
                        msg = f"图片resize失败: {img_path}"
                        notify(ctx, msg)
                        log(msg)
                        continue
                if follow_layers:
                    current_img = apply_image_watermark_layers(ctx, current_img, follow_layers, image_index=img_index)
                current_img_processed = current_img

                # 最后一图静态帧数含总时长取整的余数（last_img_frames）
                is_last_img = (img_index == total_images - 1)
                static_frames = last_img_frames if is_last_img else display_frames_per_img

                # 特效帧：按每张图的静态展示阶段应用，支持多图视频
                if effect_enabled:
                    effect_frames = max(1, static_frames)
                    duration_sec = max(0.001, effect_frames / max(1, fps))
                    for frame_idx in range(effect_frames):
                        time_sec = frame_idx / max(1, fps)
                        frame = apply_single_image_effect(
                            current_img_processed,
                            effect_type_for_video,
                            time_sec,
                            duration_sec,
                            read_value(ctx, "video_effect_intensity", 100.0),
                            read_value(ctx, "video_effect_speed", 1.0)
                        )
                        video_writer.write(frame)
                        frames_written += 1
                        emit_progress(ctx, frames_written)
                else:
                    # 写入静态显示帧
                    for _ in range(static_frames):
                        video_writer.write(current_img_processed)
                        frames_written += 1
                        emit_progress(ctx, frames_written)

                # 处理转场；最后一图无需补帧（静态帧已含全部帧数）
                if not is_last_img:
                    next_img_path = images[img_index + 1]
                    next_img = safe_read_image(next_img_path, ctx.notify, ctx.turbo_accelerator)
                    if next_img is None:
                        # 下一张图加载失败：用当前帧占位，保证转场帧数不缺失（时长不变）
                        msg = f"无法加载下一张图片，用当前帧补位保持时长: {next_img_path}"
                        notify(ctx, msg)
                        log(msg)
                        next_img = current_img_processed
                    elif resize_mode != "原始尺寸":
                        next_img = resize_image(next_img, out_w, out_h, resize_mode, maintain_aspect)
                        if next_img is None:
                            msg = f"下一张图片resize失败，用当前帧补位保持时长: {next_img_path}"
                            notify(ctx, msg)
                            log(msg)
                            next_img = current_img_processed
                    if follow_layers:
                        next_img = apply_image_watermark_layers(ctx, next_img, follow_layers, image_index=img_index + 1)
                    apply_transition(current_img_processed, next_img, video_writer, transition_frames, transition_type, ctx.transition_engine)
                    frames_written += transition_frames
                    emit_progress(ctx, frames_written)
            except Exception as e:
                msg = f"处理图片 {img_path} 时出错: {str(e)}\n{traceback.format_exc()}"
                notify(ctx, msg)
                log(msg)
                continue
        video_writer.release()
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            if fixed_layers:
                add_fixed_image_watermarks_to_video(ctx, output_path, fixed_layers)
            msg = f"视频创建完成! 编码器: {selected_codec}, 路径: {output_path}, 大小: {os.path.getsize(output_path)} 字节"
            notify(ctx, msg)
            log(msg)
            return True
        else:
            msg = f"视频创建失败: 输出文件无效, 路径: {output_path}"
            notify(ctx, msg)
            log(msg)
            return False
    except Exception as e:
        import traceback
        msg = f"创建视频时出错: {str(e)}\n{traceback.format_exc()}"
        notify(ctx, msg)
        log(msg)
        if 'video_writer' in locals() and video_writer and video_writer.isOpened():
            video_writer.release()
        return False

def create_video_turbo_enhanced(ctx, images, output_path, duration, fps, width=1920, height=1080,
                 apply_image_watermark=False, watermark_path=None, watermark_position="右下",
                 resize_mode="适应", maintain_aspect=True, transition_frames=15, transition_type="淡入淡出",
                 watermark_opacity=0.5, watermark_size=20, video_effect_type_override=None):
    """使用Turbo增强的视频创建方法 - 高性能优化版本
    
    主要优化：
    1. 并行图片处理
    2. Turbo缓存加速
    3. 优化的转场处理
    4. 批量帧写入
    """
    import traceback
    import time
    
    def log(msg):
        print(f"[Turbo] {msg}")
        notify(ctx, f"[Turbo] {msg}")
        try:
            with open("video_create_turbo.log", "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except Exception:
            pass
    
    if not images or not output_path:
        log("没有选择图片或输出路径")
        return False
    
    start_time = time.time()
    
    try:
        total_images = len(images)
        log(f"开始Turbo增强处理 {total_images} 张图片")
        effect_type_for_video = (
            video_effect_type_override
            if video_effect_type_override in VIDEO_EFFECTS
            else read_value(ctx, "video_effect_type", "无特效")
        )
        
        if total_images < 1:
            log("至少需要一张图片")
            return False
        
        # 计算帧数和转场设置（统一帧计划：总时长严格按设置，余数由最后一张吸收）
        total_time_per_img = duration
        total_frames_per_img, transition_frames, display_frames_per_img, last_img_frames = compute_video_frame_plan(
            total_images, duration, fps, transition_frames, transition_type
        )
        total_frames = (total_images - 1) * total_frames_per_img + last_img_frames
        
        static_time = display_frames_per_img / fps
        transition_time = transition_frames / fps
        total_video_duration = total_time_per_img * total_images
        
        log(f"每张图片总时长: {total_time_per_img}秒 (静态: {static_time:.2f}秒 + 转场: {transition_time:.2f}秒)")
        log(f"总视频时长: {total_video_duration:.2f}秒, 转场类型: {transition_type}")
        
        prepared_layers = prepare_image_watermark_layers(ctx) if apply_image_watermark else []
        follow_layers = [l for l in prepared_layers if not l.get("fixed")]
        fixed_layers = [l for l in prepared_layers if l.get("fixed")]

        path_index_map = {p: i for i, p in enumerate(images)}

        # Turbo并行预加载所有图片
        log("开始Turbo并行图片预加载...")
        preload_start = time.time()
        
        # 使用Turbo加速器并行加载图片
        if ctx.turbo_accelerator and ctx.turbo_accelerator.enabled:
            processed_images = ctx.turbo_accelerator.parallel_image_processing(
                images, 
                lambda *a, **kw: turbo_preprocess_image(ctx, *a, **kw),
                width, height, resize_mode, maintain_aspect,
                apply_image_watermark, follow_layers, watermark_position, 
                watermark_opacity, watermark_size, path_index_map
            )
        else:
            # 回退到串行处理
            processed_images = []
            for img_path in images:
                if not wait_for_processing_control(ctx=ctx):
                    raise InterruptedError("用户取消处理")
                processed_img = turbo_preprocess_image(ctx, 
                    img_path, width, height, resize_mode, maintain_aspect,
                    apply_image_watermark, follow_layers, watermark_position,
                    watermark_opacity, watermark_size, path_index_map
                )
                processed_images.append(processed_img)
        
        # 不再过滤失败图片：保留完整路径列表，失败项以 None 占位，
        # 渲染层用相邻帧补位，保证输出时长严格按设置生成（不会因缺图变短）。
        valid_image_paths = list(images)
        valid_images = list(processed_images)
        failed_count = sum(1 for img in valid_images if img is None)
        if failed_count:
            log(f"警告: {failed_count} 张图片加载失败，将用相邻帧补位以保持设定时长")
            if failed_count == total_images:
                log("所有图片都加载失败")
                return False
        
        preload_time = time.time() - preload_start
        log(f"Turbo预加载完成: {preload_time:.2f}秒, 成功加载 {len(valid_images)} 张图片")
        
        # 创建视频写入器
        if resize_mode == "原始尺寸":
            first_valid = next((img for img in valid_images if img is not None), None)
            if first_valid is not None:
                h, w = first_valid.shape[:2]
                out_w, out_h = w, h
            else:
                out_w, out_h = width, height
        else:
            out_w, out_h = width, height
        
        # 阶段2：主渲染优先使用FFmpeg（统一编码出口）
        if ctx.ffmpeg_available:
            log(f"统一编排：主渲染使用FFmpeg，编码器={get_selected_codec_name(ctx)}")
            target_bitrate = read_value(ctx, "bitrate", 5000)
            success = create_video_with_ffmpeg(ctx, 
                valid_image_paths, output_path, duration, fps, out_w, out_h,
                apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                transition_frames, transition_type, watermark_opacity,
                watermark_size, target_bitrate, log, effect_type_for_video,
                preprocessed_images=valid_images
            )
            if success:
                postprocess_video_output(ctx, output_path, fixed_layers, watermark_position, log, pipeline_start_time=start_time)
                return True
            log("FFmpeg主渲染失败，自动降级到OpenCV编码链路继续处理")

        # 使用用户选择的编码器
        selected_codec = resolve_cv_fourcc(ctx)
        if not selected_codec:
            log(f"编码器不可用: {get_selected_codec_name(ctx)}")
            if ctx.ffmpeg_available:
                log("尝试使用FFmpeg按指定编码器生成视频")
                target_bitrate = read_value(ctx, "bitrate", 5000)
                success = create_video_with_ffmpeg(ctx, 
                    valid_image_paths, output_path, duration, fps, out_w, out_h,
                    apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                    transition_frames, transition_type, watermark_opacity,
                    watermark_size, target_bitrate, log, effect_type_for_video,
                    preprocessed_images=valid_images
                )
                if success:
                    postprocess_video_output(ctx, output_path, fixed_layers, watermark_position, log, pipeline_start_time=start_time)
                return success
            return False

        fourcc = cv2.VideoWriter_fourcc(*selected_codec)
        video_writer = cv2.VideoWriter(output_path, fourcc, fps, (out_w, out_h))
        if video_writer.isOpened():
            log(f"使用编码器: {selected_codec}")
        else:
            log(f"编码器 {selected_codec} 创建失败")
            if ctx.ffmpeg_available:
                log("尝试使用FFmpeg按指定编码器生成视频")
                target_bitrate = read_value(ctx, "bitrate", 5000)
                success = create_video_with_ffmpeg(ctx, 
                    valid_image_paths, output_path, duration, fps, out_w, out_h,
                    apply_image_watermark, follow_layers, fixed_layers, watermark_position,
                    transition_frames, transition_type, watermark_opacity,
                    watermark_size, target_bitrate, log, effect_type_for_video,
                    preprocessed_images=valid_images
                )
                if success:
                    postprocess_video_output(ctx, output_path, fixed_layers, watermark_position, log, pipeline_start_time=start_time)
                return success
            return False
        
        # 计算总帧数（统一帧计划已给出精确总帧数，含最后一图余数）
        log(f"开始视频生成: 总帧数 {total_frames}")
        
        if ctx is not None:
            render_weight = 0.82 if has_postprocess_work(ctx, fixed_layers) else 1.0
            emit_reset_progress(ctx, total_frames, render_weight=render_weight)
        
        frames_written = 0
        encoding_start = time.time()
        effect_enabled = (
            ctx is not None
            and read_value(ctx, "use_video_effect", False)
            and effect_type_for_video != "无特效"
        )
        
        # 高效帧写入循环
        last_good_frame = None
        for img_index, current_img in enumerate(valid_images):
            if not wait_for_processing_control(ctx=ctx):
                raise InterruptedError("用户取消处理")
            # 图片加载失败的槽位用上一张成功帧补位，保证总时长严格按设置生成
            if current_img is None:
                if last_good_frame is None:
                    log(f"首图加载失败，无法生成视频: {valid_image_paths[img_index]}")
                    video_writer.release()
                    return False
                current_img = last_good_frame
                log(f"图片加载失败，用相邻帧补位保持时长: {valid_image_paths[img_index]}")
            else:
                last_good_frame = current_img
            log(f"处理图片 {img_index+1}/{total_images}")

            # 最后一图静态帧数含总时长取整的余数（last_img_frames）
            is_last_img = (img_index == total_images - 1)
            static_frames = last_img_frames if is_last_img else display_frames_per_img

            # 特效帧：按每张图的静态展示阶段应用，支持多图视频
            if effect_enabled:
                effect_frames = max(1, static_frames)
                duration_sec = max(0.001, effect_frames / max(1, fps))
                for frame_idx in range(effect_frames):
                    if not wait_for_processing_control(ctx=ctx):
                        raise InterruptedError("用户取消处理")
                    time_sec = frame_idx / max(1, fps)
                    frame = apply_single_image_effect(
                        current_img,
                        effect_type_for_video,
                        time_sec,
                        duration_sec,
                        read_value(ctx, "video_effect_intensity", 100.0),
                        read_value(ctx, "video_effect_speed", 1.0)
                    )
                    video_writer.write(frame)
                    frames_written += 1
                    if frames_written % 30 == 0:
                        emit_progress(ctx, frames_written)
                emit_progress(ctx, frames_written)
            else:
                # 批量写入静态帧
                for _ in range(static_frames):
                    if not wait_for_processing_control(ctx=ctx):
                        raise InterruptedError("用户取消处理")
                    video_writer.write(current_img)
                    frames_written += 1
                    if frames_written % 30 == 0:  # 每30帧更新一次进度
                        emit_progress(ctx, frames_written)
            
            # 处理转场（当前视频统一使用同一种转场）；最后一图无需补帧
            if transition_frames > 0 and not is_last_img:
                next_img = valid_images[img_index + 1]
                if next_img is None:
                    next_img = current_img  # 加载失败用当前帧占位，保持帧数不变
                written_transition = turbo_write_transition_frames(ctx, 
                    video_writer, current_img, next_img, 
                    transition_frames, transition_type
                )
                frames_written += written_transition
                if written_transition < transition_frames and should_cancel(ctx):
                    raise InterruptedError("用户取消处理")
                emit_progress(ctx, frames_written)
        
        video_writer.release()
        encoding_time = time.time() - encoding_start
        total_time = time.time() - start_time
        
        # 验证输出文件
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            file_size = os.path.getsize(output_path)
            image_speed = (total_images / total_time) if total_time > 0 else 0.0
            frame_speed = (frames_written / encoding_time) if encoding_time > 0 else 0.0
            log(f"Turbo视频创建成功!")
            log(f"编码器: {selected_codec}, 文件大小: {file_size} 字节")
            log(f"性能统计: 预加载 {preload_time:.2f}秒, 编码 {encoding_time:.2f}秒, 总耗时 {total_time:.2f}秒")
            log(f"处理速度: {image_speed:.2f} 张/秒, {frame_speed:.1f} 帧/秒")
            
            # 更新Turbo统计
            if ctx.turbo_accelerator:
                ctx.turbo_accelerator.stats['videos_created'] += 1
            
            postprocess_video_output(ctx, output_path, fixed_layers, watermark_position, log, pipeline_start_time=start_time)
            
            return True
        else:
            log("视频创建失败: 输出文件无效")
            return False
            
    except InterruptedError:
        if 'video_writer' in locals() and video_writer and video_writer.isOpened():
            video_writer.release()
        log("已取消当前视频生成")
        return False
    except Exception as e:
        import traceback
        error_msg = f"Turbo增强视频创建出错: {str(e)}\n{traceback.format_exc()}"
        log(error_msg)
        if 'video_writer' in locals() and video_writer and video_writer.isOpened():
            video_writer.release()
        return False

def turbo_preprocess_image(ctx, img_path, width, height, resize_mode, maintain_aspect,
                           apply_watermark, watermark_layers, watermark_position,
                           watermark_opacity, watermark_size, path_index_map=None):
    """
Turbo图片预处理 - 并行优化版本
    
    包括: 加载 -> resize -> 水印
    """
    try:
        # 使用Turbo加速读取
        img = safe_read_image(img_path, ctx.notify, ctx.turbo_accelerator)
        if img is None:
            return None
        
        # resize处理
        if resize_mode != "原始尺寸":
            img = resize_image(img, width, height, resize_mode, maintain_aspect)
            if img is None:
                return None
        
        # 水印处理
        if apply_watermark and watermark_layers:
            try:
                image_index = 0
                if path_index_map and img_path in path_index_map:
                    image_index = path_index_map[img_path]
                img = apply_image_watermark_layers(ctx, img, watermark_layers, image_index=image_index)
            except Exception as e:
                print(f"水印处理失败: {str(e)}")
        
        return img
        
    except Exception as e:
        print(f"Turbo图片预处理失败 {img_path}: {str(e)}")
        return None

def turbo_write_transition_frames(ctx, video_writer, img1, img2, num_frames, transition_type):
    """
    Turbo转场帧写入 - 使用高性能转场引擎
    
    使用转场引擎批量生成帧后写入，提升性能和效果
    """
    frames_written = 0
    try:
        if num_frames <= 0 or transition_type == "无转场":
            return 0
        
        h, w = img1.shape[:2]
        
        # 确保两张图片尺寸相同
        if img1.shape != img2.shape:
            img2 = cv2.resize(img2, (w, h))
        
        # 使用转场引擎生成转场帧
        if ctx.transition_engine:
            try:
                # 使用高性能转场引擎批量生成所有转场帧
                transition_frames_list = ctx.transition_engine.generate_transition_frames(
                    img1, img2, transition_type, num_frames, use_cache=True
                )
                
                # 批量写入帧
                for frame in transition_frames_list:
                    if not wait_for_processing_control(ctx=ctx):
                        return frames_written
                    if frame is not None and frame.shape[0] > 0 and frame.shape[1] > 0:
                        video_writer.write(frame)
                    else:
                        # 帧无效，使用原图
                        video_writer.write(img1)
                    frames_written += 1
                
                return frames_written
                
            except Exception as e:
                print(f"[WARN] 转场引擎生成失败: {e}, 回退到基本实现")
        
        # 回退方案：使用基本的淡入淡出
        print(f"[WARN] 转场引擎不可用，使用基本淡入淡出")
        for i in range(num_frames):
            if not wait_for_processing_control(ctx=ctx):
                return frames_written
            alpha = i / (num_frames - 1) if num_frames > 1 else 1
            frame = cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)
            video_writer.write(frame)
            frames_written += 1
            
    except Exception as e:
        print(f"Turbo转场帧写入失败: {str(e)}")
        # 如果转场失败，用静态帧填充
        for _ in range(num_frames):
            if not wait_for_processing_control(ctx=ctx):
                break
            video_writer.write(img1)
            frames_written += 1
    return frames_written

# --- 背景音乐：实现已抽到渲染内核 src.render.audio ---
