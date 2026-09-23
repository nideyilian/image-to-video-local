"""水印与单图合成（与界面无关的渲染内核）。

从 ``src/gui/main_window.py`` 的 ``ImageToVideoTab`` 抽出：图片水印、视频水印、
混合模式与“单图 + 视频水印”合成都在这里（合并一个模块以避免循环 import）。
函数体逐字保留；``ctx`` 为第一个位置参数。本模块不导入任何 GUI 库。
"""

from __future__ import annotations

import os
import random
import subprocess
import time

import numpy as np

from ..utils.opencv_silent import import_cv2_silent
from .codec import (build_temp_output_path, get_container_compatible_acodec,
                    get_fallback_processing_fourcc, get_ffmpeg_muxer_for_output,
                    get_output_extension, get_selected_codec_name,
                    get_strict_ffmpeg_vcodec_for_output, log_output_probe,
                    reencode_video_to_selected_codec, resolve_processing_fourcc)
from .context import (RenderContext, emit_progress, emit_reset_overall_progress,
                      emit_reset_progress, notify, read_value)
from .controls import wait_for_processing_control
from .images import resize_with_aspect_ratio, safe_read_image
from .process import ensure_even_frame, log_pipeline_stage, probe_video_meta, safe_replace_file

cv2 = import_cv2_silent()


def _pipeline_log_file(ctx):
    return read_value(ctx, "_pipeline_log_file")


def verify_watermark_file(ctx):
    """验证水印文件是否有效"""
    try:
        if not read_value(ctx, "use_watermark", False):
            return True
        
        watermark_path = read_value(ctx, "watermark_path")
        
        if not watermark_path or not os.path.exists(watermark_path):
            notify(ctx, "水印文件路径无效")
            return False
        
        # 验证视频水印
        try:
            # 简单验证视频文件是否可以打开
            cap = cv2.VideoCapture(watermark_path)
            if not cap.isOpened():
                notify(ctx, "无法读取水印视频")
                cap.release()
                return False
            cap.release()
            return True
        except Exception as e:
            notify(ctx, f"水印视频验证失败: {str(e)}")
            return False
    
    except Exception as e:
        notify(ctx, f"验证水印文件时出错: {str(e)}")
        return False


def get_watermark_files(ctx, directory):
    """获取目录中的水印文件列表（支持图片和视频）"""
    watermark_files = []
    
    try:
        # 仅视频水印
        extensions = ('.mov', '.mp4', '.avi', '.mkv')
        
        # 遍历目录获取文件
        for file in os.listdir(directory):
            if file.lower().endswith(extensions):
                watermark_files.append(os.path.join(directory, file))
        
        # 按文件名排序
        watermark_files.sort()
        
    except Exception as e:
        notify(ctx, f"获取水印文件列表时出错: {str(e)}")
    
    return watermark_files


def calc_overlay_geometry(ctx, main_w, main_h, wm_w, wm_h, size_mode, scale_value, position):
    """计算叠加尺寸与位置。"""
    wm_ratio = wm_w / max(1, wm_h)
    main_ratio = main_w / max(1, main_h)

    if size_mode == "自适应覆盖":
        if wm_ratio > main_ratio:
            target_h = main_h
            target_w = int(target_h * wm_ratio)
        else:
            target_w = main_w
            target_h = int(target_w / wm_ratio)
    elif size_mode == "完全覆盖":
        target_w, target_h = main_w, main_h
    else:
        target_w = max(1, int(main_w * (float(scale_value) / 100.0)))
        target_h = max(1, int(target_w / wm_ratio))

    margin = 10 if size_mode == "固定比例" else 0
    if position == "左上":
        x_pos, y_pos = margin, margin
    elif position == "右上":
        x_pos, y_pos = main_w - target_w - margin, margin
    elif position == "左下":
        x_pos, y_pos = margin, main_h - target_h - margin
    elif position == "中心":
        x_pos, y_pos = (main_w - target_w) // 2, (main_h - target_h) // 2
    else:
        x_pos, y_pos = main_w - target_w - margin, main_h - target_h - margin

    return target_w, target_h, x_pos, y_pos

def select_video_watermark_file(ctx, log_func=None):
    """解析当前配置中的视频水印文件。"""
    if not (read_value(ctx, "use_watermark", False) and read_value(ctx, "watermark_type") == "视频"):
        return None

    watermark_base_path = read_value(ctx, "watermark_path")
    if not watermark_base_path or not os.path.exists(watermark_base_path):
        return None

    watermark_mode_value = read_value(ctx, "watermark_mode", "单文件")

    if watermark_mode_value == "文件夹" and os.path.isdir(watermark_base_path):
        watermark_files = get_watermark_files(ctx, watermark_base_path)
        if not watermark_files:
            return None
        video_idx = read_value(ctx, "_current_video_index", 0)
        selected = watermark_files[video_idx % len(watermark_files)]
        log_pipeline_stage("POST-CHECK", f"选择文件夹水印: {os.path.basename(selected)}", log_func,
                           _pipeline_log_file(ctx))
        return selected

    if os.path.isfile(watermark_base_path):
        log_pipeline_stage("POST-CHECK", f"使用单文件水印: {os.path.basename(watermark_base_path)}", log_func,
                           _pipeline_log_file(ctx))
        return watermark_base_path
    return None


def get_video_watermark_blend_mode(ctx):
    """获取视频水印混合模式。"""
    return read_value(ctx, "watermark_blend_mode", "正常")

def get_video_watermark_alpha(ctx, blend_mode):
    """根据混合模式返回更合理的默认强度。"""
    alpha_map = {
        "正常": 0.50,
        "滤色": 1.00,
        "叠加": 0.90,
        "正片叠底": 0.85,
        "变亮": 0.90,
        "变暗": 0.90,
        "相加": 0.95,
    }
    return float(alpha_map.get(blend_mode, 0.50))

def get_ffmpeg_blend_mode(ctx, blend_mode):
    """将UI混合模式映射为FFmpeg blend滤镜模式。"""
    mapping = {
        "滤色": "screen",
        "叠加": "overlay",
        "正片叠底": "multiply",
        "变亮": "lighten",
        "变暗": "darken",
        "相加": "addition",
    }
    return mapping.get(str(blend_mode), None)

def collect_fixed_layer_specs_for_ffmpeg(ctx):
    """收集可由FFmpeg一次性处理的固定图片图层。"""
    specs = []
    for layer in normalize_watermark_layers(ctx, ):
        if not layer.get("enabled", True):
            continue
        if layer.get("type", "图片") != "图片":
            continue
        if not bool(layer.get("fixed", False)):
            continue
        path = layer.get("path", "")
        if not path:
            continue

        selected_path = None
        if os.path.isdir(path):
            files = get_image_files_in_dir(ctx, path)
            if files:
                files.sort()
                if bool(layer.get("folder_random_single", False)):
                    selected_path = random.choice(files)
                else:
                    selected_path = files[0]
        elif os.path.isfile(path):
            selected_path = path

        if not selected_path:
            continue

        specs.append({
            "path": selected_path,
            "position": layer.get("position", "右下"),
            "size_mode": layer.get("size_mode", "自适应覆盖"),
            "scale": float(layer.get("scale", 20.0)),
            "blend_mode": layer.get("blend_mode", "正常"),
            "opacity": float(layer.get("opacity", 0.5)),
        })
    return specs


def apply_blend_mode(ctx, background, foreground, mode="正常", alpha=0.5):
    """
    应用不同的混合模式
    
    Args:
        background: 背景图像（主视频帧）
        foreground: 前景图像（水印）
        mode: 混合模式
        alpha: 透明度（0.0-1.0）
        
    Returns:
        混合后的图像
    """
    try:
        # 确保图像类型一致
        bg = background.astype(np.float32) / 255.0
        fg = foreground.astype(np.float32) / 255.0
        
        if mode == "正常":
            # 正常混合（Alpha混合）
            result = bg * (1 - alpha) + fg * alpha
            
        elif mode == "滤色":
            # 滤色模式 - 适合黑色背景，黑色变透明
            # Screen: 1 - (1-A) * (1-B)
            result = 1 - (1 - bg) * (1 - fg)
            # 应用透明度
            result = bg * (1 - alpha) + result * alpha
            
        elif mode == "叠加":
            # 叠加模式 - 根据背景亮度选择正片叠底或滤色
            # Overlay: if bg < 0.5: 2*A*B else 1-2*(1-A)*(1-B)
            mask = bg < 0.5
            result = np.where(mask, 2 * bg * fg, 1 - 2 * (1 - bg) * (1 - fg))
            result = bg * (1 - alpha) + result * alpha
            
        elif mode == "正片叠底":
            # 正片叠底 - 变暗效果
            # Multiply: A * B
            result = bg * fg
            result = bg * (1 - alpha) + result * alpha
            
        elif mode == "变亮":
            # 变亮模式 - 保留较亮的像素
            # Lighten: max(A, B)
            result = np.maximum(bg, fg)
            result = bg * (1 - alpha) + result * alpha
            
        elif mode == "变暗":
            # 变暗模式 - 保留较暗的像素
            # Darken: min(A, B)
            result = np.minimum(bg, fg)
            result = bg * (1 - alpha) + result * alpha
            
        elif mode == "相加":
            # 相加模式 - 线性减淡
            # Add: A + B
            result = bg + fg
            result = np.clip(result, 0, 1)
            result = bg * (1 - alpha) + result * alpha
            
        else:
            # 默认使用正常混合
            result = bg * (1 - alpha) + fg * alpha
        
        # 转换回uint8
        result = np.clip(result * 255, 0, 255).astype(np.uint8)
        return result
        
    except Exception as e:
        print(f"混合模式应用失败: {str(e)}")
        return background

def safe_read_image_with_alpha(ctx, img_path):
    """读取图片并保留透明通道（支持中文路径）"""
    try:
        if isinstance(img_path, str) and os.path.exists(img_path):
            img_array = np.fromfile(img_path, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_UNCHANGED)
            return img
        return None
    except Exception:
        return None

def normalize_watermark_layers(ctx):
    """统一水印图层配置（兼容单水印配置）"""
    layers = []
    if isinstance(read_value(ctx, "watermark_layers", []), list) and read_value(ctx, "watermark_layers", []):
        layers = read_value(ctx, "watermark_layers", [])
    return layers

def get_image_files_in_dir(ctx, directory):
    extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.tiff')
    try:
        return [
            os.path.join(directory, f)
            for f in os.listdir(directory)
            if f.lower().endswith(extensions)
        ]
    except Exception:
        return []

def prepare_image_watermark_layers(ctx):
    """加载图片水印图层（含多层）"""
    prepared = []
    for layer in normalize_watermark_layers(ctx, ):
        if not layer.get("enabled", True):
            continue
        if layer.get("type", "图片") != "图片":
            continue
        path = layer.get("path", "")
        if not path:
            continue
        files = []
        if os.path.isdir(path):
            files = get_image_files_in_dir(ctx, path)
            if files and bool(layer.get("folder_random_single", False)):
                files = [random.choice(files)]
        else:
            files = [path]
        images = []
        for f in files:
            wm_img = safe_read_image_with_alpha(ctx, f)
            if wm_img is not None:
                images.append(wm_img)
        if not images:
            continue
        prepared.append({
            "images": images,
            "position": layer.get("position", "右下"),
            "size_mode": layer.get("size_mode", "自适应覆盖"),
            "scale": layer.get("scale", 20.0),
            "blend_mode": layer.get("blend_mode", "正常"),
            "opacity": layer.get("opacity", 0.5),
            "fixed": bool(layer.get("fixed", False)),
            "folder_random_single": bool(layer.get("folder_random_single", False)),
        })
    return prepared

def apply_image_watermark_layer(ctx, image, layer, image_index=0):
    """应用单层图片水印"""
    if image is None:
        return image
    h, w = image.shape[:2]
    wm_images = layer.get("images", [])
    if not wm_images:
        return image
    # 文件夹多图水印：随机贴（每次从目录水印中随机选一张）。
    # 勾选"目录随机1个"时，_prepare_image_watermark_layers 已随机缩减为单张，
    # 整条视频固定使用该张；未勾选时每张图片/每帧随机贴一张。
    if len(wm_images) == 1:
        wm_img = wm_images[0]
    else:
        wm_img = random.choice(wm_images)

    wm_h, wm_w = wm_img.shape[:2]
    watermark_ratio = wm_w / max(1, wm_h)
    main_ratio = w / max(1, h)
    size_mode_value = layer.get("size_mode", "自适应覆盖")
    scale_value = float(layer.get("scale", 20.0))

    if size_mode_value == "自适应覆盖":
        if watermark_ratio > main_ratio:
            wm_target_height = h
            wm_target_width = int(wm_target_height * watermark_ratio)
        else:
            wm_target_width = w
            wm_target_height = int(wm_target_width / watermark_ratio)
    elif size_mode_value == "完全覆盖":
        wm_target_width = w
        wm_target_height = h
    else:
        watermark_size = int(w * (scale_value / 100.0))
        wm_target_width = max(1, watermark_size)
        wm_target_height = max(1, int(wm_target_width / watermark_ratio))

    # 调整水印大小
    if wm_target_width != wm_w or wm_target_height != wm_h:
        wm_resized = cv2.resize(wm_img, (wm_target_width, wm_target_height))
    else:
        wm_resized = wm_img

    # 计算位置
    margin = 10 if size_mode_value == "固定比例" else 0
    position = layer.get("position", "右下")
    if position == "左上":
        x_pos, y_pos = margin, margin
    elif position == "右上":
        x_pos, y_pos = w - wm_target_width - margin, margin
    elif position == "左下":
        x_pos, y_pos = margin, h - wm_target_height - margin
    elif position == "中心":
        x_pos, y_pos = (w - wm_target_width) // 2, (h - wm_target_height) // 2
    else:
        x_pos, y_pos = w - wm_target_width - margin, h - wm_target_height - margin

    # 裁剪到有效范围
    src_x_start = max(0, -x_pos)
    src_y_start = max(0, -y_pos)
    dst_x_start = max(0, x_pos)
    dst_y_start = max(0, y_pos)
    actual_w = min(wm_target_width - src_x_start, w - dst_x_start)
    actual_h = min(wm_target_height - src_y_start, h - dst_y_start)
    if actual_w <= 0 or actual_h <= 0:
        return image

    wm_crop = wm_resized[src_y_start:src_y_start+actual_h, src_x_start:src_x_start+actual_w]
    roi = image[dst_y_start:dst_y_start+actual_h, dst_x_start:dst_x_start+actual_w]

    blend_mode = layer.get("blend_mode", "正常")
    opacity = float(layer.get("opacity", 0.5))

    # 支持透明通道
    if wm_crop.shape[2] == 4:
        wm_rgb = wm_crop[:, :, :3]
        alpha_mask = (wm_crop[:, :, 3] / 255.0) * opacity
        blended_full = apply_blend_mode(ctx, roi, wm_rgb, mode=blend_mode, alpha=1.0)
        alpha_mask = np.expand_dims(alpha_mask, axis=2)
        result = roi * (1 - alpha_mask) + blended_full * alpha_mask
        image[dst_y_start:dst_y_start+actual_h, dst_x_start:dst_x_start+actual_w] = result.astype(np.uint8)
    else:
        blended = apply_blend_mode(ctx, roi, wm_crop[:, :, :3], mode=blend_mode, alpha=opacity)
        image[dst_y_start:dst_y_start+actual_h, dst_x_start:dst_x_start+actual_w] = blended

    return image

def apply_image_watermark_layers(ctx, image, layers, image_index=0):
    """应用多层图片水印"""
    result = image
    for layer in layers:
        result = apply_image_watermark_layer(ctx, result, layer, image_index=image_index)
    return result

def add_fixed_image_watermarks_to_video(ctx, input_path, layers):
    """为已生成的视频添加固定图片水印图层"""
    if not layers:
        return True
    try:
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            return False
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        temp_output = build_temp_output_path(input_path, "fixed_wm_temp", ctx)
        selected_codec = resolve_processing_fourcc(ctx)
        needs_reencode = False
        if not selected_codec:
            selected_codec = get_fallback_processing_fourcc(ctx)
            needs_reencode = bool(selected_codec)
            if not selected_codec:
                notify(ctx, f"固定水印编码器不可用: {get_selected_codec_name(ctx)}")
                cap.release()
                return False
            notify(ctx, 
                f"固定水印阶段使用中间编码器: {selected_codec}，完成后将转码为 {get_selected_codec_name(ctx)}"
            )
        fourcc = cv2.VideoWriter_fourcc(*selected_codec)
        writer = cv2.VideoWriter(temp_output, fourcc, fps, (width, height))
        if not writer.isOpened():
            notify(ctx, f"固定水印编码器创建失败: {selected_codec}")
            cap.release()
            return False

        idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame = apply_image_watermark_layers(ctx, frame, layers, image_index=idx)
            writer.write(frame)
            idx += 1
            if idx % max(1, total // 100) == 0:
                notify(ctx, f"固定水印处理中: {int(idx / max(1, total) * 100)}%")

        cap.release()
        writer.release()

        if os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
            final_temp = temp_output
            if needs_reencode:
                reencoded = build_temp_output_path(input_path, "fixed_wm_reencoded", ctx)
                if not reencode_video_to_selected_codec(temp_output, reencoded, ctx.notify, ctx):
                    try:
                        os.remove(temp_output)
                    except Exception:
                        pass
                    return False
                try:
                    os.remove(temp_output)
                except Exception:
                    pass
                final_temp = reencoded
            os.remove(input_path)
            os.rename(final_temp, input_path)
            # 动画叠加层（ffmpeg ProRes MOV overlay）
            apply_ffmpeg_animated_overlays_stage(ctx, input_path)
            return True
        return False
    except Exception:
        return False

def apply_ffmpeg_animated_overlays_stage(ctx, video_path: str) -> None:
    """
    在静态水印处理后调用：将动画叠加层（ProRes MOV with alpha）合成到视频上。
    从 read_value(ctx, "watermark_layers", []) 中检测有 seq_overlay_path 的图层，使用 ffmpeg overlay 滤镜合成。
    """
    try:
        animated_layers = normalize_watermark_layers(ctx, )
        from ..services.video_service import apply_ffmpeg_animated_overlays
        apply_ffmpeg_animated_overlays(
            video_path,
            animated_layers,
            status_callback=ctx.notify,
        )
    except Exception:
        pass

def add_video_watermark(ctx, main_video_path, watermark_path, output_path, position="右下", match_method="循环"):
    """使用OpenCV给视频添加视频水印
    
    Args:
        main_video_path: 主视频文件路径
        watermark_path: 水印视频文件路径
        output_path: 输出视频文件路径
        position: 水印位置 ("左上", "右上", "左下", "右下", "中心")
        match_method: 水印匹配方法 ("循环", "拉伸", "单次")
        
    Returns:
        bool: 成功返回True，失败返回False
    """
    import traceback
    
    # 自定义日志函数
    def log(msg):
        print(msg)
        try:
            with open("video_watermark_debug.log", "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass
    
    try:
        # 打开主视频
        log(f"打开主视频: {main_video_path}")
        main_cap = cv2.VideoCapture(main_video_path)
        if not main_cap.isOpened():
            log(f"无法打开主视频: {main_video_path}")
            return False
        
        # 获取主视频的基本信息
        main_width = int(main_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        main_height = int(main_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        main_fps = main_cap.get(cv2.CAP_PROP_FPS)
        main_frame_count = int(main_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        main_duration = main_frame_count / main_fps
        
        log(f"主视频信息: {main_width}x{main_height}, {main_fps}fps, {main_frame_count}帧, 时长:{main_duration:.2f}秒")
        
        # 打开水印视频
        log(f"打开水印视频: {watermark_path}")
        watermark_cap = cv2.VideoCapture(watermark_path)
        if not watermark_cap.isOpened():
            log(f"无法打开水印视频: {watermark_path}")
            main_cap.release()
            return False
        
        # 获取水印视频的基本信息
        wm_width = int(watermark_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        wm_height = int(watermark_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        wm_fps = watermark_cap.get(cv2.CAP_PROP_FPS)
        wm_frame_count = int(watermark_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        wm_duration = wm_frame_count / max(0.0001, wm_fps)
        
        # OpenCV 解码会丢弃 alpha 通道；优先用 FFmpeg 解码 RGBA 帧保留透明通道
        wm_alpha_frames = None
        try:
            from ..utils.ffmpeg_runtime import read_video_frames_rgba

            wm_alpha_frames = read_video_frames_rgba(
                ctx.ffmpeg_executable or "ffmpeg",
                watermark_path,
            )
        except Exception:
            wm_alpha_frames = None
        if wm_alpha_frames is not None:
            wm_frame_count = min(wm_frame_count, len(wm_alpha_frames))
            log(f"已通过 FFmpeg 解码 {len(wm_alpha_frames)} 帧 RGBA 水印（保留透明通道）")
        
        log(f"水印视频信息: {wm_width}x{wm_height}, {wm_fps}fps, {wm_frame_count}帧, 时长:{wm_duration:.2f}秒")
        
        # 获取水印大小模式和缩放比例
        size_mode_value = read_value(ctx, "watermark_size_mode", "自适应覆盖")
        scale_value = read_value(ctx, "watermark_scale", 20.0)
        
        # 计算水印大小 - 根据模式自适应
        watermark_ratio = wm_width / wm_height
        main_ratio = main_width / main_height
        
        if size_mode_value == "自适应覆盖":
            # 自适应覆盖：保持比例，完全覆盖主视频（可能会裁剪水印）
            if watermark_ratio > main_ratio:
                # 水印更宽，按高度适配
                wm_target_height = main_height
                wm_target_width = int(wm_target_height * watermark_ratio)
            else:
                # 水印更高，按宽度适配
                wm_target_width = main_width
                wm_target_height = int(wm_target_width / watermark_ratio)
            log(f"自适应覆盖模式: 水印比例={watermark_ratio:.2f}, 主视频比例={main_ratio:.2f}")
        elif size_mode_value == "完全覆盖":
            # 完全覆盖：拉伸到完全匹配主视频大小（不保持比例）
            wm_target_width = main_width
            wm_target_height = main_height
            log(f"完全覆盖模式: 拉伸到主视频大小")
        else:
            # 固定比例模式：按百分比缩放
            watermark_size = int(main_width * (scale_value / 100.0))
            wm_target_width = watermark_size
            wm_target_height = int(wm_target_width / watermark_ratio)
            log(f"固定比例模式: 缩放{scale_value}%")
        
        log(f"调整后的水印大小: {wm_target_width}x{wm_target_height} (原始: {wm_width}x{wm_height})")
        
        # 确定水印位置
        margin = 10 if size_mode_value == "固定比例" else 0  # 自适应模式无边距
        
        if position == "左上":
            x_pos = margin
            y_pos = margin
        elif position == "右上":
            x_pos = main_width - wm_target_width - margin
            y_pos = margin
        elif position == "左下":
            x_pos = margin
            y_pos = main_height - wm_target_height - margin
        elif position == "中心":
            x_pos = (main_width - wm_target_width) // 2
            y_pos = (main_height - wm_target_height) // 2
        else:  # 默认右下
            x_pos = main_width - wm_target_width - margin
            y_pos = main_height - wm_target_height - margin
        
        log(f"水印位置: {position} ({x_pos}, {y_pos}), 边距: {margin}px")
        
        # 创建输出写入器：优先FFmpeg管道编码（避免中间重编码），失败则回退OpenCV写入
        log(f"创建输出视频: {output_path}")
        stage_output = output_path
        use_ffmpeg_pipe = False
        ffmpeg_proc = None
        video_writer = None
        selected_codec = None
        needs_reencode = False

        if ctx.ffmpeg_available:
            strict_vcodec = get_strict_ffmpeg_vcodec_for_output(output_path, ctx)
            if strict_vcodec:
                muxer = get_ffmpeg_muxer_for_output(output_path, ctx)
                ffmpeg_cmd = [
                    ctx.ffmpeg_executable or "ffmpeg", "-y",
                    "-f", "rawvideo",
                    "-pix_fmt", "bgr24",
                    "-s", f"{main_width}x{main_height}",
                    "-r", str(max(1, int(round(main_fps)))),
                    "-i", "-",
                    "-an",
                    "-c:v", strict_vcodec,
                    "-pix_fmt", "yuv420p",
                    "-r", str(max(1, int(round(main_fps)))),
                ]
                if strict_vcodec == "libx264":
                    ffmpeg_cmd += ["-preset", "medium"]
                if muxer:
                    ffmpeg_cmd += ["-f", muxer]
                ffmpeg_cmd += [stage_output]
                try:
                    ffmpeg_proc = subprocess.Popen(
                        ffmpeg_cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        startupinfo=ctx.startupinfo,
                    )
                    use_ffmpeg_pipe = True
                    log(f"使用FFmpeg管道编码: {strict_vcodec}")
                except Exception as pipe_err:
                    log(f"FFmpeg管道编码初始化失败，回退OpenCV: {str(pipe_err)}")

        if not use_ffmpeg_pipe:
            selected_codec = resolve_processing_fourcc(ctx)
            if not selected_codec:
                selected_codec = get_fallback_processing_fourcc(ctx)
                needs_reencode = bool(selected_codec)
                if not selected_codec:
                    log(f"编码器不可用: {get_selected_codec_name(ctx)}")
                    main_cap.release()
                    watermark_cap.release()
                    return False
                log(f"水印阶段使用中间编码器: {selected_codec}，完成后将转码为 {get_selected_codec_name(ctx)}")
            if needs_reencode:
                stage_output = build_temp_output_path(output_path, "wm_stage", ctx)
            fourcc = cv2.VideoWriter_fourcc(*selected_codec)
            video_writer = cv2.VideoWriter(stage_output, fourcc, main_fps, (main_width, main_height))
            if video_writer.isOpened():
                log(f"使用编码器: {selected_codec}")
            else:
                log(f"编码器 {selected_codec} 创建失败")
                main_cap.release()
                watermark_cap.release()
                return False
        
        # 处理帧
        main_frame_idx = 0
        wm_frame_idx = 0
        total_frames_processed = 0
        blend_mode = read_value(ctx, "watermark_blend_mode", "正常")
        blend_alpha = get_video_watermark_alpha(ctx, blend_mode)
        
        # 设置进度更新间隔
        progress_update_interval = max(1, main_frame_count // 100)

        # 预计算ROI裁剪参数（位置固定，无需每帧重复计算）
        src_x_start = max(0, -x_pos)
        src_y_start = max(0, -y_pos)
        dst_x_start = max(0, x_pos)
        dst_y_start = max(0, y_pos)
        actual_w = min(wm_target_width - src_x_start, main_width - dst_x_start)
        actual_h = min(wm_target_height - src_y_start, main_height - dst_y_start)
        if actual_w <= 0 or actual_h <= 0:
            log(f"无效的裁剪区域: actual_w={actual_w}, actual_h={actual_h}")
            main_cap.release()
            watermark_cap.release()
            video_writer.release()
            return False
        
        # 计算主视频和水印视频的总帧数比例，用于同步播放
        if match_method == "拉伸":
            # 对于拉伸匹配，将水印视频时长拉伸到主视频时长
            wm_speed_ratio = main_frame_count / max(1, wm_frame_count)
            log(f"拉伸匹配 - 水印速度比例: {wm_speed_ratio:.4f}")
        else:
            wm_speed_ratio = 1.0

        # 顺序解码缓存，避免逐帧CAP_PROP_POS_FRAMES随机跳转导致的性能损耗
        wm_read_idx = 0
        wm_last_idx = -1
        wm_last_frame = None
        resized_last_idx = -1
        resized_last_frame = None

        def _reset_watermark_capture():
            nonlocal watermark_cap, wm_read_idx, wm_last_idx, wm_last_frame, resized_last_idx, resized_last_frame
            try:
                watermark_cap.release()
            except Exception:
                pass
            watermark_cap = cv2.VideoCapture(watermark_path)
            if not watermark_cap.isOpened():
                return False
            wm_read_idx = 0
            wm_last_idx = -1
            wm_last_frame = None
            resized_last_idx = -1
            resized_last_frame = None
            return True

        def _get_wm_frame_by_index(target_idx):
            nonlocal wm_read_idx, wm_last_idx, wm_last_frame
            if target_idx < 0 or target_idx >= wm_frame_count:
                return None
            if wm_alpha_frames is not None:
                return wm_alpha_frames[target_idx].copy()
            if target_idx == wm_last_idx and wm_last_frame is not None:
                return wm_last_frame
            if target_idx < wm_read_idx:
                if not _reset_watermark_capture():
                    return None
            while wm_read_idx <= target_idx:
                ret_wm, frame_wm = watermark_cap.read()
                if not ret_wm:
                    return None
                wm_last_frame = frame_wm
                wm_last_idx = wm_read_idx
                wm_read_idx += 1
            return wm_last_frame
        
        # 记录帧处理开始时间
        start_time = time.time()
        log(f"开始处理视频帧, 匹配方法: {match_method}")
        
        while True:
            # 读取主视频帧
            ret, main_frame = main_cap.read()
            if not ret:
                break  # 主视频读取完毕
            
            # 如果是"单次"匹配方式且水印已播放完，不再添加水印
            if match_method == "单次" and wm_frame_idx >= wm_frame_count:
                if use_ffmpeg_pipe:
                    ffmpeg_proc.stdin.write(main_frame.tobytes())
                else:
                    video_writer.write(main_frame)
                main_frame_idx += 1
                continue
            
            # 根据匹配方法计算水印帧索引
            if match_method == "拉伸":
                current_wm_idx = int(main_frame_idx * wm_speed_ratio) % wm_frame_count
            elif match_method == "循环":
                current_wm_idx = wm_frame_idx % wm_frame_count
            else:  # 单次
                current_wm_idx = wm_frame_idx

            wm_frame = _get_wm_frame_by_index(current_wm_idx)
            if wm_frame is not None:
                # 缩放缓存：同一帧索引重复使用时不重复resize（拉伸模式常见）
                if current_wm_idx == resized_last_idx and resized_last_frame is not None:
                    wm_frame_resized = resized_last_frame
                else:
                    if wm_frame.shape[1] == wm_target_width and wm_frame.shape[0] == wm_target_height:
                        wm_frame_resized = wm_frame
                    else:
                        wm_frame_resized = cv2.resize(wm_frame, (wm_target_width, wm_target_height))
                    resized_last_idx = current_wm_idx
                    resized_last_frame = wm_frame_resized

                try:
                    # 裁剪水印帧到实际区域
                    wm_crop = wm_frame_resized[
                        src_y_start:src_y_start + actual_h,
                        src_x_start:src_x_start + actual_w
                    ]
                    # 获取主视频对应区域
                    roi = main_frame[
                        dst_y_start:dst_y_start + actual_h,
                        dst_x_start:dst_x_start + actual_w
                    ]
                    # 确保尺寸匹配
                    if wm_crop.shape[:2] == roi.shape[:2]:
                        if wm_crop.shape[2] == 4:
                            # RGBA 水印：按 alpha 通道合成（透明区域透出主画面）
                            wm_rgb = wm_crop[:, :, :3]
                            alpha_mask = (wm_crop[:, :, 3].astype(np.float32) / 255.0) * blend_alpha
                            blended_full = apply_blend_mode(ctx, roi, wm_rgb, mode=blend_mode, alpha=1.0)
                            alpha_mask = np.expand_dims(alpha_mask, axis=2)
                            result = roi.astype(np.float32) * (1 - alpha_mask) + blended_full * alpha_mask
                            main_frame[
                                dst_y_start:dst_y_start + actual_h,
                                dst_x_start:dst_x_start + actual_w
                            ] = result.astype(np.uint8)
                        else:
                            blended = apply_blend_mode(ctx, roi, wm_crop, mode=blend_mode, alpha=blend_alpha)
                            main_frame[
                                dst_y_start:dst_y_start + actual_h,
                                dst_x_start:dst_x_start + actual_w
                            ] = blended
                    else:
                        log(f"尺寸不匹配: wm_crop={wm_crop.shape}, roi={roi.shape}")
                except Exception as e:
                    log(f"水印帧处理失败: {str(e)}")
            
            # 写入输出视频
            if use_ffmpeg_pipe:
                ffmpeg_proc.stdin.write(main_frame.tobytes())
            else:
                video_writer.write(main_frame)
            
            # 更新帧索引
            main_frame_idx += 1
            wm_frame_idx += 1
            total_frames_processed += 1
            
            # 定期更新进度
            if main_frame_idx % progress_update_interval == 0:
                progress = (main_frame_idx / main_frame_count) * 100
                elapsed = time.time() - start_time
                fps = main_frame_idx / max(0.1, elapsed)
                remaining = (main_frame_count - main_frame_idx) / max(1, fps)
                
                notify(ctx, f"添加视频水印: {progress:.1f}%, 速度: {fps:.1f}fps, 剩余: {remaining:.1f}秒")
                log(f"进度: {main_frame_idx}/{main_frame_count} ({progress:.1f}%), 速度: {fps:.1f}fps")
        
        # 释放资源
        main_cap.release()
        watermark_cap.release()
        if use_ffmpeg_pipe:
            if ffmpeg_proc and ffmpeg_proc.stdin:
                ffmpeg_proc.stdin.close()
                ffmpeg_proc.stdin = None
            ff_stdout, ff_stderr = ffmpeg_proc.communicate()
            if ffmpeg_proc.returncode != 0:
                err = ff_stderr.decode("utf-8", errors="ignore") if ff_stderr else ""
                log(f"FFmpeg管道编码失败: {err[:300]}")
                try:
                    main_cap.release()
                    watermark_cap.release()
                except Exception:
                    pass
                return False
        else:
            video_writer.release()
        
        # 计算总处理时间
        total_time = time.time() - start_time
        log(f"视频水印添加完成，共处理 {total_frames_processed} 帧，耗时 {total_time:.2f} 秒")
        
        # 验证输出视频
        if os.path.exists(stage_output) and os.path.getsize(stage_output) > 0:
            if (not use_ffmpeg_pipe) and needs_reencode:
                if not reencode_video_to_selected_codec(stage_output, output_path, log, ctx):
                    try:
                        os.remove(stage_output)
                    except Exception:
                        pass
                    notify(ctx, "视频水印添加失败：重编码失败")
                    return False
                try:
                    os.remove(stage_output)
                except Exception:
                    pass
            notify(ctx, f"视频水印添加成功: {output_path}")
            return True
        else:
            log(f"输出视频无效: {stage_output}")
            notify(ctx, "视频水印添加失败：输出文件无效")
            return False
            
    except Exception as e:
        log(f"添加视频水印时出错: {str(e)}\n{traceback.format_exc()}")
        notify(ctx, f"添加视频水印失败: {str(e)}")
        
        # 尝试清理资源
        try:
            if 'main_cap' in locals() and main_cap is not None:
                main_cap.release()
            if 'watermark_cap' in locals() and watermark_cap is not None:
                watermark_cap.release()
            if 'video_writer' in locals() and video_writer is not None and video_writer.isOpened():
                video_writer.release()
            if 'ffmpeg_proc' in locals() and ffmpeg_proc is not None:
                try:
                    if ffmpeg_proc.stdin:
                        ffmpeg_proc.stdin.close()
                except Exception:
                    pass
                try:
                    ffmpeg_proc.kill()
                except Exception:
                    pass
        except Exception:
            pass
            
        return False

def resize_image_hq(ctx, image, target_width, target_height, resize_mode="适应", maintain_aspect=True):
    """高质量图片resize方法

    Args:
        image: 输入图片
        target_width: 目标宽度
        target_height: 目标高度
        resize_mode: resize模式
        maintain_aspect: 是否保持宽高比

    Returns:
        处理后的图片
    """
    try:
        if image is None:
            return None

        h, w = image.shape[:2]

        if resize_mode == "原始尺寸":
            return image
        elif resize_mode == "拉伸":
            # 直接拉伸到目标尺寸，使用高质量插值
            return cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
        elif resize_mode == "适应":
            if maintain_aspect:
                # 保持宽高比，适应目标尺寸
                scale = min(target_width / w, target_height / h)
                new_w = int(w * scale)
                new_h = int(h * scale)

                # 高质量resize
                resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

                # 创建目标尺寸的黑色背景
                result = np.zeros((target_height, target_width, 3), dtype=np.uint8)

                # 计算居中位置
                y_offset = (target_height - new_h) // 2
                x_offset = (target_width - new_w) // 2

                # 将resize后的图片放在中心
                result[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized

                return result
            else:
                return cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
        elif resize_mode == "填充":
            # 裁剪填充模式
            scale = max(target_width / w, target_height / h)
            new_w = int(w * scale)
            new_h = int(h * scale)

            # 高质量resize
            resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

            # 计算裁剪位置（居中裁剪）
            y_start = (new_h - target_height) // 2
            x_start = (new_w - target_width) // 2

            # 裁剪到目标尺寸
            result = resized[y_start:y_start+target_height, x_start:x_start+target_width]

            return result
        else:
            # 默认使用适应模式
            return resize_image_hq(ctx, image, target_width, target_height, "适应", maintain_aspect)

    except Exception as e:
        print(f"高质量resize图片时出错: {str(e)}")
        # 回退到普通resize
        try:
            return cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
        except:
            return None

def create_single_image_video(ctx, image_path, watermark_video_path, output_path, width, height, position="右下", match_method="循环"):
    """创建单图转视频：将单张图片与视频水印组合成视频

    Args:
        image_path: 单张图片路径
        watermark_video_path: 视频水印路径（.mov文件）
        output_path: 输出视频路径
        width: 输出视频宽度
        height: 输出视频高度
        position: 水印位置
        match_method: 水印匹配方法

    Returns:
        bool: 成功返回True，失败返回False
    """
    import traceback
    import time

    def log(msg):
        print(f"[单图转视频] {msg}")
        _log_to_file = read_value(ctx, "log_to_file")
        if _log_to_file is not None:
            _log_to_file(f"[单图转视频] {msg}")

    try:
        log(f"开始单图转视频处理")
        log(f"图片: {image_path}")
        log(f"视频水印: {watermark_video_path}")
        log(f"输出: {output_path}")

        # 读取单张图片
        image = safe_read_image(image_path, ctx.notify, ctx.turbo_accelerator)
        if image is None:
            log(f"无法读取图片: {image_path}")
            notify(ctx, "无法读取图片")
            return False

        # 高质量调整图片大小
        image = resize_image_hq(ctx, image, width, height, "适应", True)
        if image is None:
            log(f"图片resize失败")
            notify(ctx, "图片处理失败")
            return False

        # 打开视频水印
        watermark_cap = cv2.VideoCapture(watermark_video_path)
        if not watermark_cap.isOpened():
            log(f"无法打开视频水印: {watermark_video_path}")
            notify(ctx, "无法打开视频水印")
            return False

        # 获取视频水印信息
        watermark_fps = watermark_cap.get(cv2.CAP_PROP_FPS)
        watermark_frame_count = int(watermark_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        watermark_width = int(watermark_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        watermark_height = int(watermark_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        watermark_duration = watermark_frame_count / watermark_fps if watermark_fps > 0 else 0

        log(f"视频水印信息: {watermark_width}x{watermark_height}, {watermark_fps}fps, {watermark_frame_count}帧, {watermark_duration:.2f}秒")

        # 检查是否使用FFmpeg进行高质量输出
        use_ffmpeg_for_quality = ctx.ffmpeg_available
        target_bitrate = read_value(ctx, "bitrate", 8000)  # 默认高码率

        if use_ffmpeg_for_quality:
            log(f"使用FFmpeg创建高质量单图转视频，码率: {target_bitrate} kbps")
            return create_single_image_video_with_ffmpeg(ctx, 
                image_path, watermark_video_path, output_path, width, height,
                position, watermark_fps, watermark_frame_count, target_bitrate, log
            )
        else:
            log("使用OpenCV创建单图转视频（质量由编码器决定）")

        # 创建输出视频写入器（优先用户编码器，失败时自动回退）
        selected_codec = resolve_processing_fourcc(ctx)
        if not selected_codec:
            log(f"编码器不可用: {get_selected_codec_name(ctx)}")
            notify(ctx, "无法创建输出视频")
            watermark_cap.release()
            return False
        if selected_codec != get_selected_codec_name(ctx):
            log(f"单图转视频阶段编码器映射: {get_selected_codec_name(ctx)} -> {selected_codec}")
        try:
            fourcc = cv2.VideoWriter_fourcc(*selected_codec)
            video_writer = cv2.VideoWriter(output_path, fourcc, watermark_fps, (width, height))
            if video_writer.isOpened():
                log(f"使用编码器: {selected_codec}")
            else:
                log(f"编码器 {selected_codec} 创建失败")
                notify(ctx, "无法创建输出视频")
                watermark_cap.release()
                return False
        except Exception as e:
            log(f"编码器 {selected_codec} 失败: {str(e)}")
            notify(ctx, "无法创建输出视频")
            watermark_cap.release()
            return False

        log(f"开始合成视频，总帧数: {watermark_frame_count}")
        notify(ctx, f"正在合成单图转视频，时长: {watermark_duration:.1f}秒...")

        # 重置进度
        if ctx is not None and ctx.reset_progress is not None:
            emit_reset_progress(ctx, watermark_frame_count)

        start_time = time.time()
        processed_frames = 0

        # 逐帧处理
        for frame_idx in range(watermark_frame_count):
            # 读取水印帧
            ret, watermark_frame = watermark_cap.read()
            if not ret:
                log(f"无法读取水印帧 {frame_idx}")
                break

            # 高质量调整水印帧大小以匹配输出尺寸
            if watermark_frame.shape[:2] != (height, width):
                watermark_frame = cv2.resize(watermark_frame, (width, height), interpolation=cv2.INTER_LANCZOS4)

            # 将图片作为背景，水印作为前景进行高质量合成
            result_frame = blend_image_with_video_frame_hq(ctx, image, watermark_frame, position)

            # 写入帧
            video_writer.write(result_frame)
            processed_frames += 1

            # 更新进度
            if ctx is not None and ctx.progress is not None:
                emit_progress(ctx, processed_frames)

            # 定期更新状态
            if frame_idx % 30 == 0:  # 每30帧更新一次
                elapsed = time.time() - start_time
                fps = processed_frames / max(0.1, elapsed)
                remaining = (watermark_frame_count - processed_frames) / max(1, fps)
                progress = (processed_frames / watermark_frame_count) * 100

                notify(ctx, f"单图转视频: {progress:.1f}%, 速度: {fps:.1f}fps, 剩余: {remaining:.1f}秒")

        # 释放资源
        watermark_cap.release()
        video_writer.release()

        # 验证输出
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            total_time = time.time() - start_time
            log(f"单图转视频完成，处理了 {processed_frames} 帧，耗时 {total_time:.2f} 秒")
            notify(ctx, f"单图转视频完成: {output_path}")
            return True
        else:
            log("输出视频无效")
            notify(ctx, "单图转视频失败：输出文件无效")
            return False

    except Exception as e:
        log(f"单图转视频处理出错: {str(e)}")
        log(traceback.format_exc())
        notify(ctx, f"单图转视频失败: {str(e)}")

        # 清理资源
        try:
            if 'watermark_cap' in locals() and watermark_cap is not None:
                watermark_cap.release()
            if 'video_writer' in locals() and video_writer is not None:
                video_writer.release()
        except Exception:
            pass

        return False

def blend_image_with_video_frame_hq(ctx, background_image, video_frame, position="右下"):
    """高质量将背景图片与视频帧进行混合

    Args:
        background_image: 背景图片
        video_frame: 视频帧
        position: 混合位置

    Returns:
        混合后的帧
    """
    try:
        # 确保两个图像尺寸相同
        if background_image.shape != video_frame.shape:
            video_frame = cv2.resize(video_frame, (background_image.shape[1], background_image.shape[0]),
                                   interpolation=cv2.INTER_LANCZOS4)

        # 转换为浮点数进行高精度计算
        bg_float = background_image.astype(np.float64)
        fg_float = video_frame.astype(np.float64)

        # 根据位置决定混合方式
        if position == "中心":
            # 中心位置：高质量alpha混合
            alpha = 0.6  # 视频帧的透明度，稍微降低以保持背景可见性
            result = bg_float * (1 - alpha) + fg_float * alpha
        elif position == "右下":
            # 右下角：将视频帧作为水印叠加
            # 创建一个基于视频帧亮度的alpha通道
            gray_fg = cv2.cvtColor(video_frame, cv2.COLOR_BGR2GRAY)
            alpha_mask = gray_fg.astype(np.float64) / 255.0
            alpha_mask = np.stack([alpha_mask, alpha_mask, alpha_mask], axis=2)

            # 使用亮度作为混合权重，保持细节
            alpha_strength = 0.7
            alpha_mask = alpha_mask * alpha_strength

            result = bg_float * (1 - alpha_mask) + fg_float * alpha_mask
        else:
            # 其他位置：智能混合
            # 检测视频帧中的主要内容区域
            gray_fg = cv2.cvtColor(video_frame, cv2.COLOR_BGR2GRAY)
            _, mask = cv2.threshold(gray_fg, 30, 255, cv2.THRESH_BINARY)
            mask_float = mask.astype(np.float64) / 255.0
            mask_3d = np.stack([mask_float, mask_float, mask_float], axis=2)

            # 在有内容的区域使用较高的混合比例
            alpha_content = 0.8
            alpha_background = 0.3

            alpha_mask = mask_3d * alpha_content + (1 - mask_3d) * alpha_background
            result = bg_float * (1 - alpha_mask) + fg_float * alpha_mask

        # 转换回uint8并确保值在有效范围内
        result = np.clip(result, 0, 255).astype(np.uint8)
        return result

    except Exception as e:
        print(f"高质量混合图像时出错: {str(e)}")
        # 如果混合失败，返回简单的alpha混合
        try:
            alpha = 0.6
            result = cv2.addWeighted(background_image, 1-alpha, video_frame, alpha, 0)
            return result
        except:
            return video_frame

def blend_image_with_video_frame(ctx, background_image, video_frame, position="右下"):
    """兼容性方法：调用高质量混合方法"""
    return blend_image_with_video_frame_hq(ctx, background_image, video_frame, position)

def create_single_image_video_with_ffmpeg(ctx, image_path, watermark_video_path, output_path,
                                        width, height, position, watermark_fps, watermark_frame_count,
                                        target_bitrate, log_func):
    """使用FFmpeg创建高质量单图转视频

    Args:
        image_path: 单张图片路径
        watermark_video_path: 视频水印路径
        output_path: 输出视频路径
        width: 输出视频宽度
        height: 输出视频高度
        position: 混合位置
        watermark_fps: 水印视频帧率
        watermark_frame_count: 水印视频帧数
        target_bitrate: 目标码率
        log_func: 日志函数

    Returns:
        bool: 成功返回True，失败返回False
    """
    try:
        import tempfile
        import shutil

        log_func(f"开始使用FFmpeg创建高质量单图转视频，码率: {target_bitrate} kbps")

        # 创建临时目录存放帧图片
        temp_dir = tempfile.mkdtemp(prefix="single_img_ffmpeg_")
        log_func(f"创建临时目录: {temp_dir}")

        try:
            # 读取单张图片
            image = safe_read_image(image_path, ctx.notify, ctx.turbo_accelerator)
            if image is None:
                log_func(f"无法读取图片: {image_path}")
                return False

            # 高质量调整图片大小
            image = cv2.resize(image, (width, height), interpolation=cv2.INTER_LANCZOS4)

            # 打开视频水印
            watermark_cap = cv2.VideoCapture(watermark_video_path)
            if not watermark_cap.isOpened():
                log_func(f"无法打开视频水印: {watermark_video_path}")
                return False

            log_func(f"开始生成高质量帧图片，总帧数: {watermark_frame_count}")

            if ctx is not None and ctx.reset_progress is not None:
                emit_reset_progress(ctx, watermark_frame_count)

            # 逐帧处理并保存为PNG（无损）
            for frame_idx in range(watermark_frame_count):
                # 读取水印帧
                ret, watermark_frame = watermark_cap.read()
                if not ret:
                    log_func(f"无法读取水印帧 {frame_idx}")
                    break

                # 高质量调整水印帧大小
                if watermark_frame.shape[:2] != (height, width):
                    watermark_frame = cv2.resize(watermark_frame, (width, height),
                                               interpolation=cv2.INTER_LANCZOS4)

                # 高质量图像混合
                result_frame = blend_image_with_video_frame_hq(ctx, image, watermark_frame, position)
                result_frame = ensure_even_frame(result_frame)

                # 保存为PNG格式（无损）
                frame_filename = os.path.join(temp_dir, f"frame_{frame_idx:06d}.png")
                # 使用最高质量保存PNG
                cv2.imwrite(frame_filename, result_frame, [cv2.IMWRITE_PNG_COMPRESSION, 0])

                # 更新进度
                if ctx is not None and ctx.progress is not None:
                    emit_progress(ctx, frame_idx + 1)

                # 定期更新状态
                if frame_idx % 30 == 0:
                    progress = ((frame_idx + 1) / watermark_frame_count) * 100
                    notify(ctx, f"生成高质量帧: {progress:.1f}%")

            watermark_cap.release()
            log_func(f"生成了 {watermark_frame_count} 帧高质量图片")

            # 使用FFmpeg将帧图片合成高质量视频
            log_func("开始使用FFmpeg合成高质量视频...")
            notify(ctx, "正在使用FFmpeg合成高质量视频...")

            strict_vcodec = get_strict_ffmpeg_vcodec_for_output(output_path, ctx)
            if not strict_vcodec:
                log_func(
                    f"编码器与容器不兼容: codec={get_selected_codec_name(ctx)}, ext={get_output_extension(output_path, ctx)}"
                )
                return False
            codec_candidates = [strict_vcodec]
            muxer = get_ffmpeg_muxer_for_output(output_path, ctx)

            for vcodec in codec_candidates:
                ffmpeg_cmd = [
                    ctx.ffmpeg_executable or "ffmpeg", "-y",  # 覆盖输出文件
                    "-framerate", str(watermark_fps),  # 输入帧率
                    "-i", os.path.join(temp_dir, "frame_%06d.png"),  # 输入图片序列
                    "-c:v", vcodec,
                ]
                if vcodec == "libx264":
                    ffmpeg_cmd += [
                        "-preset", "slow",
                        "-crf", "18",
                        "-profile:v", "high",
                        "-level", "4.1",
                    ]
                ffmpeg_cmd += [
                    "-b:v", f"{target_bitrate}k",
                    "-maxrate", f"{int(target_bitrate * 1.2)}k",
                    "-bufsize", f"{int(target_bitrate * 2)}k",
                    "-pix_fmt", "yuv420p",
                    "-r", str(watermark_fps),
                ]
                if muxer:
                    ffmpeg_cmd += ["-f", muxer]
                ffmpeg_cmd += [output_path]

                log_func(f"FFmpeg高质量命令[{vcodec}]: {' '.join(ffmpeg_cmd)}")
                result = subprocess.run(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    startupinfo=ctx.startupinfo
                )

                if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    log_func(f"FFmpeg高质量视频合成成功，编码器={vcodec}")
                    log_func(f"高质量单图转视频完成: {output_path}")
                    log_func(f"文件大小: {os.path.getsize(output_path)} 字节")
                    log_output_probe(output_path, log_func, ctx)
                    notify(ctx, f"高质量单图转视频完成: {output_path}")
                    return True

                stderr_output = result.stderr.decode('utf-8', errors='ignore')
                log_func(f"FFmpeg执行失败[{vcodec}]，错误码: {result.returncode}")
                log_func(f"错误信息: {stderr_output[:300]}")

            log_func("所有容器兼容编码器均失败")
            return False

        finally:
            # 清理临时目录
            try:
                shutil.rmtree(temp_dir)
                log_func(f"清理临时目录: {temp_dir}")
            except Exception as e:
                log_func(f"清理临时目录失败: {str(e)}")

    except Exception as e:
        log_func(f"使用FFmpeg创建高质量单图转视频时出错: {str(e)}")
        import traceback
        log_func(traceback.format_exc())
        return False
