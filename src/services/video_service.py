#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
视频生成服务
提供统一的视频生成接口，整合转场效果、音频和水印
"""

import cv2
import numpy as np
import os
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable
import logging
import time

from ..models import ProcessingOptions, ProcessingResult, VideoSettings
from ..exceptions import VideoGenerationError, FFmpegError
from .image_service import ImageProcessingService

logger = logging.getLogger(__name__)

class VideoGenerationService:
    """视频生成服务"""
    
    def __init__(self, image_service: ImageProcessingService):
        self.image_service = image_service
        self._progress_callback: Optional[Callable[[int], None]] = None
    
    def set_progress_callback(self, callback: Callable[[int], None]):
        """设置进度回调函数"""
        self._progress_callback = callback
    
    def generate_video(
        self, 
        image_paths: List[Path], 
        options: ProcessingOptions
    ) -> ProcessingResult:
        """生成视频
        
        Args:
            image_paths: 图片路径列表
            options: 处理选项
            
        Returns:
            ProcessingResult: 处理结果
        """
        start_time = time.time()
        
        try:
            # 验证输入
            if not image_paths:
                raise VideoGenerationError("图片列表不能为空")
            
            if not options.output_path:
                raise VideoGenerationError("必须指定输出路径")
            
            # 获取视频设置
            video_settings = options.video_settings
            
            # 解析分辨率
            width, height = self._parse_resolution(video_settings.resolution)
            
            # 准备视频写入器
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            video_writer = cv2.VideoWriter(
                str(options.output_path),
                fourcc,
                video_settings.fps,
                (width, height)
            )
            
            if not video_writer.isOpened():
                raise VideoGenerationError("无法创建视频文件")
            
            try:
                # 处理图片并生成帧
                total_frames = len(image_paths) * int(video_settings.fps * video_settings.duration)
                if options.transition_settings.enabled:
                    total_frames += (len(image_paths) - 1) * int(video_settings.fps * options.transition_settings.duration)
                
                current_frame = 0
                
                for i, image_path in enumerate(image_paths):
                    # 加载并处理图片
                    image = self.image_service.load_image(image_path, (width, height))
                    
                    # 应用水印（如果启用）
                    if options.watermark_settings.enabled:
                        image = self._apply_watermark(image, options.watermark_settings)
                    
                    # 生成图片显示帧
                    frames_per_image = int(video_settings.fps * video_settings.duration)
                    for frame_idx in range(frames_per_image):
                        video_writer.write(image)
                        current_frame += 1
                        self._update_progress(current_frame, total_frames)
                    
                    # 生成转场帧（除了最后一张图片）
                    if i < len(image_paths) - 1 and options.transition_settings.enabled:
                        next_image = self.image_service.load_image(image_paths[i + 1], (width, height))
                        if options.watermark_settings.enabled:
                            next_image = self._apply_watermark(next_image, options.watermark_settings)
                        
                        transition_frames = self._generate_transition_frames(
                            image, next_image, options.transition_settings, video_settings.fps
                        )
                        
                        for frame in transition_frames:
                            video_writer.write(frame)
                            current_frame += 1
                            self._update_progress(current_frame, total_frames)
                
                return ProcessingResult(
                    success=True,
                    output_path=options.output_path,
                    processing_time=time.time() - start_time,
                    stats={
                        'total_frames': current_frame,
                        'image_count': len(image_paths),
                        'video_duration': current_frame / video_settings.fps
                    }
                )
                
            finally:
                video_writer.release()
                
        except Exception as e:
            error_msg = f"视频生成失败: {e}"
            logger.error(error_msg)
            return ProcessingResult(
                success=False,
                error_message=error_msg,
                processing_time=time.time() - start_time
            )
    
    def _parse_resolution(self, resolution: str) -> tuple:
        """解析分辨率字符串"""
        try:
            width, height = map(int, resolution.split('x'))
            return width, height
        except:
            raise VideoGenerationError(f"无效的分辨率格式: {resolution}")
    
    def _apply_watermark(self, image: np.ndarray, watermark_settings) -> np.ndarray:
        """应用水印"""
        if not watermark_settings.image_path or not watermark_settings.image_path.exists():
            return image
        
        try:
            # 加载水印图片
            watermark = cv2.imread(str(watermark_settings.image_path), cv2.IMREAD_UNCHANGED)
            if watermark is None:
                return image
            
            # 缩放水印
            h, w = image.shape[:2]
            wh, ww = watermark.shape[:2]
            scale = min(w * watermark_settings.scale / ww, h * watermark_settings.scale / wh)
            new_ww = int(ww * scale)
            new_wh = int(wh * scale)
            watermark = cv2.resize(watermark, (new_ww, new_wh))
            
            # 计算位置
            x, y = self._calculate_watermark_position(
                (w, h), (new_ww, new_wh), watermark_settings.position
            )
            
            # 应用水印
            result = image.copy()
            if watermark.shape[2] == 4:  # 带透明通道
                # 处理透明度
                alpha = watermark[:, :, 3] / 255.0 * watermark_settings.opacity
                for c in range(3):
                    result[y:y+new_wh, x:x+new_ww, c] = (
                        alpha * watermark[:, :, c] + 
                        (1 - alpha) * result[y:y+new_wh, x:x+new_ww, c]
                    )
            else:
                # 简单覆盖
                cv2.addWeighted(
                    result[y:y+new_wh, x:x+new_ww], 1 - watermark_settings.opacity,
                    watermark[:, :, :3], watermark_settings.opacity,
                    0, result[y:y+new_wh, x:x+new_ww]
                )
            
            return result
            
        except Exception as e:
            logger.warning(f"水印应用失败: {e}")
            return image
    
    def _calculate_watermark_position(self, image_size: tuple, watermark_size: tuple, position: str) -> tuple:
        """计算水印位置"""
        img_w, img_h = image_size
        wm_w, wm_h = watermark_size
        
        margin = 20  # 边距
        
        positions = {
            'top-left': (margin, margin),
            'top-right': (img_w - wm_w - margin, margin),
            'bottom-left': (margin, img_h - wm_h - margin),
            'bottom-right': (img_w - wm_w - margin, img_h - wm_h - margin),
            'center': ((img_w - wm_w) // 2, (img_h - wm_h) // 2)
        }
        
        return positions.get(position, positions['bottom-right'])
    
    def _generate_transition_frames(
        self, 
        image1: np.ndarray, 
        image2: np.ndarray, 
        transition_settings,
        fps: int
    ) -> List[np.ndarray]:
        """生成转场帧"""
        frames = []
        total_frames = int(fps * transition_settings.duration)
        
        for i in range(total_frames):
            # 计算进度值，避免0和1以防止重复帧
            # 使用 (i + 1) / (total_frames + 1) 生成不包含端点的均匀分布
            progress = (i + 1) / (total_frames + 1)
            frame = self._apply_transition_effect(
                image1, image2, progress, transition_settings.type
            )
            frames.append(frame)
        
        return frames
    
    def _apply_transition_effect(
        self, 
        image1: np.ndarray, 
        image2: np.ndarray, 
        progress: float,
        transition_type
    ) -> np.ndarray:
        """应用转场效果"""
        # 简化的转场效果实现
        if hasattr(transition_type, 'value'):
            effect_name = transition_type.value
        else:
            effect_name = str(transition_type)
        
        if effect_name == "淡入淡出":
            return cv2.addWeighted(image1, 1 - progress, image2, progress, 0)
        elif effect_name == "左右滑动":
            h, w = image1.shape[:2]
            offset = int(w * progress)
            result = np.zeros_like(image1)
            # 左侧显示image1的右部分
            if offset < w:
                result[:, :w-offset] = image1[:, offset:]
            # 右侧显示image2的左部分
            if offset > 0:
                result[:, w-offset:] = image2[:, :offset]
            return result
        else:
            # 默认使用淡入淡出
            return cv2.addWeighted(image1, 1 - progress, image2, progress, 0)
    
    def _update_progress(self, current: int, total: int):
        """更新进度"""
        if self._progress_callback:
            progress = int((current / total) * 100) if total > 0 else 0
            self._progress_callback(progress)


def apply_ffmpeg_animated_overlays(video_path: str,
                                   overlay_layers: List[Dict],
                                   ffmpeg_path: Optional[str] = None,
                                   status_callback: Optional[Callable[[str], None]] = None) -> bool:
    """
    使用 ffmpeg 将动画叠加层（ProRes MOV with alpha）合成到已生成的视频上。
    在 OpenCV 静态水印处理之后调用，用于 .seq → ProRes MOV 的动画效果叠加。
    
    Args:
        video_path: 已生成的视频文件路径（会被替换为合成后的版本）
        overlay_layers: 水印图层列表，每项包含 path/seq_overlay_path/position/blend_mode/opacity/size_mode
        ffmpeg_path: ffmpeg 可执行文件路径，None 则自动查找
        status_callback: 状态回调函数
    
    Returns:
        是否成功
    """
    if not video_path or not os.path.isfile(video_path):
        return False

    # 过滤出有动画叠加层路径的图层
    animated = []
    for layer in (overlay_layers or []):
        seq_path = layer.get("seq_overlay_path") or layer.get("path", "")
        if seq_path and os.path.isfile(seq_path):
            ext = os.path.splitext(seq_path)[1].lower()
            if ext in ('.mov', '.mp4', '.webm'):
                animated.append({
                    "path": seq_path,
                    "position": layer.get("position", "中心"),
                    "opacity": float(layer.get("opacity", 1.0)),
                    "blend_mode": layer.get("blend_mode", "正常"),
                    "size_mode": layer.get("size_mode", "自适应覆盖"),
                })

    if not animated:
        return True  # 无动画叠加层，不算失败

    if status_callback:
        status_callback(f"正在合成 {len(animated)} 个动画叠加层...")

    # 获取 ffmpeg
    if not ffmpeg_path:
        try:
            from ..utils.ffmpeg_utils import find_ffmpeg_silent
            ffmpeg_path = find_ffmpeg_silent()
        except Exception:
            pass
    if not ffmpeg_path:
        if status_callback:
            status_callback("ffmpeg 未找到，无法合成动画叠加层")
        return False

    import subprocess

    # 构建 ffmpeg overlay 滤镜链
    # 格式: -i input.mp4 -i overlay1.mov -i overlay2.mov ...
    #        -filter_complex "[1:v]setpts=PTS-STARTPTS,format=rgba,colorchannelmixer=aa=OP1[o1];
    #                        [2:v]setpts=PTS-STARTPTS,format=rgba,colorchannelmixer=aa=OP2[o2];
    #                        [0:v][o1]overlay=X1:Y1:shortest=1:format=auto[v1];
    #                        [v1][o2]overlay=X2:Y2:shortest=1:format=auto[out]"
    #        -map "[out]" -map 0:a -c:a copy -y output.mp4

    inputs = [video_path]
    filter_parts = []

    # 缩放滤镜：将叠加层缩放到主视频尺寸
    scale_filter = "scale=iw:ih"

    for i, ov in enumerate(animated):
        inputs.append(ov["path"])
        idx = i + 1  # [1], [2], ...

        # 透明度
        opacity = ov["opacity"]
        alpha_filter = f"format=rgba,colorchannelmixer=aa={opacity:.4f}"

        # 叠加层标签
        ov_label = f"o{idx}"
        filter_parts.append(f"[{idx}:v]{alpha_filter}[{ov_label}_raw]")

        # 合成到主视频
        x_expr = "(main_w-overlay_w)/2" if ov["position"] == "中心" else {
            "左上": "10",
            "右上": "main_w-overlay_w-10",
            "左下": "10",
            "右下": "main_w-overlay_w-10",
        }.get(ov["position"], "10")

        y_expr = "(main_h-overlay_h)/2" if ov["position"] == "中心" else {
            "左上": "10",
            "右上": "10",
            "左下": "main_h-overlay_h-10",
            "右下": "main_h-overlay_h-10",
        }.get(ov["position"], "main_h-overlay_h-10")

        prev_label = f"v{i}" if i > 0 else "0:v"
        out_label = f"v{i + 1}" if i < len(animated) - 1 else "out"

        filter_parts.append(
            f"[{prev_label}][{ov_label}_raw]overlay={x_expr}:{y_expr}:shortest=1:format=auto[{out_label}]"
        )

    filter_complex = ";".join(filter_parts)

    # 输出文件（临时 + 替换）
    temp_output = video_path + ".overlay_temp.mp4"

    cmd = [ffmpeg_path, "-y", "-i"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a",
        "-c:a", "copy",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        temp_output,
    ]

    try:
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )

        if result.returncode != 0:
            if status_callback:
                status_callback(f"ffmpeg 叠加合成失败: {result.stderr[:200]}")
            return False

        if os.path.isfile(temp_output) and os.path.getsize(temp_output) > 0:
            os.replace(temp_output, video_path)
            if status_callback:
                status_callback(f"动画叠加层合成完成")
            return True

        return False

    except subprocess.TimeoutExpired:
        if status_callback:
            status_callback("ffmpeg 叠加合成超时")
        return False
    except Exception as e:
        if status_callback:
            status_callback(f"ffmpeg 叠加合成异常: {str(e)[:100]}")
        return False
    finally:
        try:
            if os.path.isfile(temp_output):
                os.remove(temp_output)
        except Exception:
            pass