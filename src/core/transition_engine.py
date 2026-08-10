#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Turbo转场引擎 - 超高性能转场效果处理器
支持GPU加速、预计算和并行处理，大幅提升转场生成速度
"""

import cv2
import numpy as np
import threading
from collections import OrderedDict
import time
import random
from typing import List, Dict, Any, Optional, Callable, Tuple
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from enum import Enum
import psutil
import gc

# 导入统一的转场常量定义
from ..utils.transition_constants import TransitionEffect, ALL_TRANSITIONS, DEFAULT_ENABLED_TRANSITIONS

class TurboTransitionEngine:
    """超高性能转场引擎"""
    
    def __init__(self, max_workers: Optional[int] = None):
        self.max_workers = max_workers or min(4, multiprocessing.cpu_count())
        self.executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="TurboTransition"
        )
        
        # 转场缓存
        self.transition_cache: "OrderedDict[str, List[np.ndarray]]" = OrderedDict()
        self.cache_lock = threading.RLock()
        self.max_transition_cache = 32
        self.cache_memory_limit = 600 * 1024 * 1024
        self.cache_bytes = 0
        self.cache_cleanup_interval = 5.0
        self.cache_cleanup_threshold = 85
        self._last_cache_cleanup = 0.0
        
        # 性能统计
        self.stats = {
            'transitions_generated': 0,
            'total_time': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
        
        # 预计算的转场模板
        self.transition_templates = {}
        
        # 随机转场配置
        self.enabled_transitions = DEFAULT_ENABLED_TRANSITIONS.copy()
        self.random_mode = False
        
        print(f"[Turbo转场引擎] 初始化完成")
        print(f"   - 工作线程: {self.max_workers}")
        print(f"   - 支持转场类型: {len(TransitionEffect)}")
    
    def set_random_mode(self, enabled: bool, enabled_transitions: Optional[List[str]] = None):
        """
        设置随机转场模式
        
        Args:
            enabled: 是否启用随机模式
            enabled_transitions: 可用的转场效果列表（None表示使用默认）
        """
        self.random_mode = enabled
        if enabled_transitions:
            self.enabled_transitions = enabled_transitions
        print(f"[随机转场] {'启用' if enabled else '禁用'}")
        if enabled:
            print(f"   - 可选效果数: {len(self.enabled_transitions)}")
    
    def get_random_transition(self) -> str:
        """随机选择一个转场效果"""
        if not self.enabled_transitions:
            return "淡入淡出"
        return random.choice(self.enabled_transitions)
    
    def generate_transition_frames(self,
                                 img1: np.ndarray,
                                 img2: np.ndarray,
                                 transition_type: str,
                                 num_frames: int,
                                 use_cache: bool = True) -> List[np.ndarray]:
        """
        生成转场帧序列（超高性能版本）
        
        优化策略：
        1. 转场模板预计算和缓存
        2. 并行帧生成
        3. 向量化计算
        4. 内存优化
        """
        
        start_time = time.time()
        
        if num_frames <= 0:
            return []
        
        # 检查缓存
        if use_cache:
            cache_key = self._generate_cache_key(img1, img2, transition_type, num_frames)
            with self.cache_lock:
                if cache_key in self.transition_cache:
                    self.stats['cache_hits'] += 1
                    self.transition_cache.move_to_end(cache_key)
                    return self.transition_cache[cache_key]
        
        self.stats['cache_misses'] += 1
        
        # 生成转场帧（生成多2帧后去掉首尾，避免重复帧）
        generate_count = num_frames + 2 if num_frames > 1 else num_frames
        frames = self._generate_frames_optimized(img1, img2, transition_type, generate_count)
        if len(frames) >= num_frames + 2:
            frames = frames[1:-1]
        elif len(frames) > num_frames:
            frames = frames[:num_frames]
        
        # 缓存结果
        if use_cache and frames:
            with self.cache_lock:
                if cache_key in self.transition_cache:
                    self.cache_bytes -= self._estimate_frames_bytes(self.transition_cache[cache_key])
                    self.transition_cache.pop(cache_key, None)
                self.transition_cache[cache_key] = frames
                self.cache_bytes += self._estimate_frames_bytes(frames)
                self.transition_cache.move_to_end(cache_key)
                self._cleanup_transition_cache()
        
        # 更新统计
        processing_time = time.time() - start_time
        self.stats['transitions_generated'] += 1
        self.stats['total_time'] += processing_time
        
        return frames
    
    def _generate_frames_optimized(self,
                                 img1: np.ndarray,
                                 img2: np.ndarray,
                                 transition_type: str,
                                 num_frames: int) -> List[np.ndarray]:
        """优化的帧生成"""
        
        # 获取转场类型
        transition_enum = self._get_transition_enum(transition_type)
        
        # 根据转场类型选择生成方法
        if transition_enum == TransitionEffect.FADE:
            return self._fade_transition_vectorized(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.SLIDE_LEFT:
            return self._slide_transition_optimized(img1, img2, num_frames, "horizontal")
        elif transition_enum == TransitionEffect.SLIDE_UP:
            return self._slide_transition_optimized(img1, img2, num_frames, "vertical")
        elif transition_enum == TransitionEffect.CROSSFADE:
            return self._crossfade_transition_vectorized(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.ZOOM:
            return self._zoom_transition_optimized(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.CIRCLE_EXPAND:
            return self._circle_expand_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.PIXELATE:
            return self._pixelate_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.ROTATE:
            return self._rotate_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.BLINDS:
            return self._blinds_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.CHECKERBOARD:
            return self._checkerboard_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.WAVE:
            return self._wave_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.COLOR_MIX:
            return self._color_mix_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.BLOCK:
            return self._block_transition(img1, img2, num_frames)
        # 新增转场效果
        elif transition_enum == TransitionEffect.ZOOM_IN_IMPACT:
            return self._zoom_in_impact_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.ZOOM_OUT_EXPLODE:
            return self._zoom_out_explode_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.ROTATE_ZOOM:
            return self._rotate_zoom_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.ELASTIC_ZOOM:
            return self._elastic_zoom_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.FLIP_3D:
            return self._flip_3d_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.PUSH_IN:
            return self._push_in_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.DIAGONAL_WIPE:
            return self._diagonal_wipe_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.DOOR_OPEN:
            return self._door_open_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.FLASH_TRANSITION:
            return self._flash_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.SHATTER:
            return self._shatter_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.GLOW_SPREAD:
            return self._glow_spread_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.RADIAL_SWEEP:
            return self._radial_sweep_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.VORTEX_DISTORT:
            return self._vortex_distort_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.DIAMOND_REVEAL:
            return self._diamond_reveal_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.FOCUS_BLUR:
            return self._focus_blur_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.CURTAIN_VERTICAL:
            return self._curtain_transition(img1, img2, num_frames, direction="vertical")
        elif transition_enum == TransitionEffect.CURTAIN_HORIZONTAL:
            return self._curtain_transition(img1, img2, num_frames, direction="horizontal")
        elif transition_enum == TransitionEffect.LIQUID_BLEND:
            return self._liquid_blend_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.LIGHT_STREAK:
            return self._light_streak_transition(img1, img2, num_frames)
        elif transition_enum == TransitionEffect.CLOCK_WIPE:
            return self._clock_wipe_transition(img1, img2, num_frames)
        else:
            # 默认淡入淡出
            return self._fade_transition_vectorized(img1, img2, num_frames)
    
    def _get_transition_enum(self, transition_type: str) -> TransitionEffect:
        """获取转场类型枚举"""
        for enum_type in TransitionEffect:
            if enum_type.value == transition_type:
                return enum_type
        return TransitionEffect.FADE  # 默认
    
    def _fade_transition_vectorized(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """向量化淡入淡出转场"""
        frames = []
        
        # 预计算alpha值
        alphas = np.linspace(0, 1, num_frames)
        
        for alpha in alphas:
            # 向量化混合
            blended = (img1 * (1 - alpha) + img2 * alpha).astype(np.uint8)
            frames.append(blended)
        
        return frames

    def _estimate_frames_bytes(self, frames: List[np.ndarray]) -> int:
        return sum(frame.nbytes for frame in frames)

    def _cleanup_transition_cache(self):
        while self.transition_cache and (
            len(self.transition_cache) > self.max_transition_cache or self.cache_bytes > self.cache_memory_limit
        ):
            _, frames = self.transition_cache.popitem(last=False)
            self.cache_bytes -= self._estimate_frames_bytes(frames)

    def realtime_cleanup(self, force: bool = False):
        """实时缓存清理（轻量、带节流）"""
        now = time.time()
        if not force and (now - self._last_cache_cleanup) < self.cache_cleanup_interval:
            return
        self._last_cache_cleanup = now
        try:
            mem_percent = psutil.virtual_memory().percent
            need_cleanup = (
                force
                or mem_percent >= self.cache_cleanup_threshold
                or len(self.transition_cache) > self.max_transition_cache
                or self.cache_bytes > self.cache_memory_limit
            )
            if need_cleanup:
                with self.cache_lock:
                    self._cleanup_transition_cache()
                if mem_percent >= self.cache_cleanup_threshold:
                    gc.collect()
        except Exception:
            pass
    
    def _slide_transition_optimized(self, img1: np.ndarray, img2: np.ndarray, 
                                  num_frames: int, direction: str) -> List[np.ndarray]:
        """优化的滑动转场"""
        frames = []
        h, w = img1.shape[:2]
        
        # 预计算分割位置
        if direction == "horizontal":
            split_positions = np.linspace(0, w, num_frames, dtype=int)
        else:  # vertical
            split_positions = np.linspace(0, h, num_frames, dtype=int)
        
        for split_pos in split_positions:
            frame = np.zeros_like(img1)
            
            if direction == "horizontal":
                frame[:, :split_pos] = img2[:, :split_pos]
                frame[:, split_pos:] = img1[:, split_pos:]
            else:  # vertical
                frame[:split_pos, :] = img2[:split_pos, :]
                frame[split_pos:, :] = img1[split_pos:, :]
            
            frames.append(frame)
        
        return frames
    
    def _crossfade_transition_vectorized(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """向量化交叉溶解转场"""
        # 与淡入淡出相同，但可以添加更复杂的混合模式
        return self._fade_transition_vectorized(img1, img2, num_frames)
    
    def _zoom_transition_optimized(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """优化的缩放转场"""
        frames = []
        h, w = img1.shape[:2]
        
        # 预计算缩放参数
        progress_values = np.linspace(0, 1, num_frames)
        
        for progress in progress_values:
            frame = np.zeros_like(img1)
            
            # img2缩放（放大）
            scale2 = 0.5 + progress * 0.5
            new_h2, new_w2 = int(h * scale2), int(w * scale2)
            
            if new_h2 > 0 and new_w2 > 0:
                img2_scaled = cv2.resize(img2, (new_w2, new_h2))
                y2, x2 = (h - new_h2) // 2, (w - new_w2) // 2
                
                # 处理边界
                if new_h2 <= h and new_w2 <= w:
                    frame[y2:y2+new_h2, x2:x2+new_w2] = img2_scaled
                else:
                    # 裁剪过大的图片
                    crop_y = max(0, -y2)
                    crop_x = max(0, -x2)
                    crop_h = min(new_h2, h - max(0, y2))
                    crop_w = min(new_w2, w - max(0, x2))
                    
                    frame_y = max(0, y2)
                    frame_x = max(0, x2)
                    
                    if crop_h > 0 and crop_w > 0:
                        frame[frame_y:frame_y+crop_h, frame_x:frame_x+crop_w] = \
                            img2_scaled[crop_y:crop_y+crop_h, crop_x:crop_x+crop_w]
            
            # img1缩放（缩小）并叠加
            scale1 = 1.0 - progress * 0.5
            new_h1, new_w1 = int(h * scale1), int(w * scale1)
            
            if new_h1 > 0 and new_w1 > 0:
                img1_scaled = cv2.resize(img1, (new_w1, new_h1))
                y1, x1 = (h - new_h1) // 2, (w - new_w1) // 2
                
                # 混合
                alpha = 1 - progress
                overlay_region = frame[y1:y1+new_h1, x1:x1+new_w1]
                blended = cv2.addWeighted(overlay_region, 1 - alpha, img1_scaled, alpha, 0)
                frame[y1:y1+new_h1, x1:x1+new_w1] = blended
            
            frames.append(frame)
        
        return frames
    
    def _circle_expand_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """圆形扩展转场"""
        frames = []
        h, w = img1.shape[:2]
        center_x, center_y = w // 2, h // 2
        max_radius = int(np.sqrt(center_x**2 + center_y**2))
        
        # 预计算半径
        radii = np.linspace(0, max_radius, num_frames)
        
        # 预计算坐标网格
        y_coords, x_coords = np.ogrid[:h, :w]
        
        for radius in radii:
            # 创建圆形遮罩
            mask = (x_coords - center_x)**2 + (y_coords - center_y)**2 <= radius**2
            
            frame = img1.copy()
            frame[mask] = img2[mask]
            frames.append(frame)
        
        return frames
    
    def _pixelate_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """像素化转场"""
        frames = []
        h, w = img1.shape[:2]
        
        # 像素化级别从高到低
        pixel_sizes = np.linspace(min(h, w) // 4, 1, num_frames, dtype=int)
        
        for pixel_size in pixel_sizes:
            if pixel_size <= 1:
                frames.append(img2.copy())
                continue
            
            # 缩小再放大实现像素化
            small_h, small_w = h // pixel_size, w // pixel_size
            if small_h <= 0 or small_w <= 0:
                frames.append(img2.copy())
                continue
            
            # 对img1进行像素化
            img1_small = cv2.resize(img1, (small_w, small_h), interpolation=cv2.INTER_NEAREST)
            img1_pixelated = cv2.resize(img1_small, (w, h), interpolation=cv2.INTER_NEAREST)
            
            # 混合
            alpha = 1 - (pixel_size - 1) / (pixel_sizes[0] - 1)
            blended = cv2.addWeighted(img1_pixelated, 1 - alpha, img2, alpha, 0)
            frames.append(blended)
        
        return frames

    def _rotate_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """旋转转场"""
        frames = []
        h, w = img1.shape[:2]
        center = (w // 2, h // 2)

        # 旋转角度从0到360
        angles = np.linspace(0, 360, num_frames)

        for angle in angles:
            # 旋转img1
            rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            img1_rotated = cv2.warpAffine(img1, rotation_matrix, (w, h))

            # 根据角度混合
            alpha = angle / 360
            blended = cv2.addWeighted(img1_rotated, 1 - alpha, img2, alpha, 0)
            frames.append(blended)

        return frames

    def _blinds_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """百叶窗转场"""
        frames = []
        h, w = img1.shape[:2]

        # 百叶窗条数
        num_blinds = 10
        blind_height = h // num_blinds

        progress_values = np.linspace(0, 1, num_frames)

        for progress in progress_values:
            frame = img1.copy()

            # 每个百叶窗条的开启程度
            open_height = int(blind_height * progress)

            for i in range(num_blinds):
                y_start = i * blind_height
                y_end = min((i + 1) * blind_height, h)

                if open_height > 0:
                    # 从中间开始打开
                    blind_center = (y_start + y_end) // 2
                    open_start = max(y_start, blind_center - open_height // 2)
                    open_end = min(y_end, blind_center + open_height // 2)

                    frame[open_start:open_end, :] = img2[open_start:open_end, :]

            frames.append(frame)

        return frames

    def _checkerboard_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """棋盘格转场"""
        frames = []
        h, w = img1.shape[:2]

        # 棋盘格大小
        grid_size = 20
        progress_values = np.linspace(0, 1, num_frames)

        for progress in progress_values:
            frame = img1.copy()

            # 随机选择要切换的格子
            num_switches = int(progress * (h // grid_size) * (w // grid_size))

            for _ in range(num_switches):
                grid_y = np.random.randint(0, h // grid_size)
                grid_x = np.random.randint(0, w // grid_size)

                y_start = grid_y * grid_size
                y_end = min((grid_y + 1) * grid_size, h)
                x_start = grid_x * grid_size
                x_end = min((grid_x + 1) * grid_size, w)

                frame[y_start:y_end, x_start:x_end] = img2[y_start:y_end, x_start:x_end]

            frames.append(frame)

        return frames

    def _wave_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """波浪转场"""
        frames = []
        h, w = img1.shape[:2]

        progress_values = np.linspace(0, 1, num_frames)

        for progress in progress_values:
            frame = img1.copy()

            # 波浪参数
            amplitude = 20
            frequency = 0.02

            for y in range(h):
                # 计算波浪偏移
                wave_offset = int(amplitude * np.sin(frequency * y + progress * 2 * np.pi))
                wave_progress = (progress + wave_offset / w) % 1

                # 根据波浪进度混合
                split_x = int(w * wave_progress)
                if split_x > 0:
                    frame[y, :split_x] = img2[y, :split_x]

            frames.append(frame)

        return frames

    def _color_mix_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """颜色混合转场"""
        frames = []

        progress_values = np.linspace(0, 1, num_frames)

        for progress in progress_values:
            # 在HSV空间进行混合
            img1_hsv = cv2.cvtColor(img1, cv2.COLOR_BGR2HSV).astype(np.float32)
            img2_hsv = cv2.cvtColor(img2, cv2.COLOR_BGR2HSV).astype(np.float32)

            # 混合HSV通道
            mixed_hsv = img1_hsv * (1 - progress) + img2_hsv * progress
            mixed_hsv = np.clip(mixed_hsv, 0, 255).astype(np.uint8)

            # 转回BGR
            mixed_bgr = cv2.cvtColor(mixed_hsv, cv2.COLOR_HSV2BGR)
            frames.append(mixed_bgr)

        return frames
    
    def _block_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """方块过渡效果"""
        frames = []
        h, w = img1.shape[:2]
        
        # 方块大小和数量
        block_size = 40
        rows = (h + block_size - 1) // block_size
        cols = (w + block_size - 1) // block_size
        total_blocks = rows * cols
        
        # 预生成随机顺序
        block_indices = list(range(total_blocks))
        random.shuffle(block_indices)
        
        progress_values = np.linspace(0, 1, num_frames)
        
        for progress in progress_values:
            frame = img1.copy()
            
            # 计算应该显示的方块数量
            blocks_to_show = int(total_blocks * progress)
            
            # 显示对应数量的方块
            for idx in range(blocks_to_show):
                block_idx = block_indices[idx]
                row = block_idx // cols
                col = block_idx % cols
                
                y1 = row * block_size
                y2 = min(y1 + block_size, h)
                x1 = col * block_size
                x2 = min(x1 + block_size, w)
                
                frame[y1:y2, x1:x2] = img2[y1:y2, x1:x2]
            
            frames.append(frame)
        
        return frames

    def _zoom_in_impact_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """放大冲击转场 - 快速从小放大，有强烈冲击感"""
        frames = []
        h, w = img1.shape[:2]
        
        # 使用非线性进度（加速效果）
        progress_values = np.power(np.linspace(0, 1, num_frames), 0.5)
        
        for progress in progress_values:
            frame = img1.copy()
            
            # img2从0.1倍快速放大到1倍
            scale = 0.1 + progress * 0.9
            new_h, new_w = int(h * scale), int(w * scale)
            
            if new_h > 0 and new_w > 0:
                img2_scaled = cv2.resize(img2, (new_w, new_h))
                y_offset = (h - new_h) // 2
                x_offset = (w - new_w) // 2
                
                # 计算透明度（快速淡入）
                alpha = progress ** 0.5
                
                # 混合到中心位置
                if new_h <= h and new_w <= w:
                    overlay_region = frame[y_offset:y_offset+new_h, x_offset:x_offset+new_w]
                    blended = cv2.addWeighted(overlay_region, 1 - alpha, img2_scaled, alpha, 0)
                    frame[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = blended
                else:
                    frame = cv2.addWeighted(frame, 1 - alpha, img2, alpha, 0)
            
            frames.append(frame)
        
        return frames
    
    def _zoom_out_explode_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """缩小爆炸转场 - 图片缩小并爆炸散开"""
        frames = []
        h, w = img1.shape[:2]
        center = (w // 2, h // 2)
        
        progress_values = np.linspace(0, 1, num_frames)
        
        for progress in progress_values:
            # 缩小img1
            scale = 1.0 - progress * 0.9
            new_h, new_w = int(h * scale), int(w * scale)
            
            if new_h > 0 and new_w > 0 and scale > 0.1:
                img1_scaled = cv2.resize(img1, (new_w, new_h))
                
                # 计算随机散开偏移（爆炸效果）
                explosion_factor = progress ** 2
                offset_x = int(np.random.randn() * 20 * explosion_factor)
                offset_y = int(np.random.randn() * 20 * explosion_factor)
                
                y_offset = (h - new_h) // 2 + offset_y
                x_offset = (w - new_w) // 2 + offset_x
                
                # 以img2为基础
                frame = img2.copy()
                
                # 叠加缩小的img1（带透明度）
                alpha = 1 - progress
                
                # 确保不越界
                y1 = max(0, y_offset)
                y2 = min(h, y_offset + new_h)
                x1 = max(0, x_offset)
                x2 = min(w, x_offset + new_w)
                
                src_y1 = max(0, -y_offset)
                src_y2 = src_y1 + (y2 - y1)
                src_x1 = max(0, -x_offset)
                src_x2 = src_x1 + (x2 - x1)
                
                if y2 > y1 and x2 > x1 and src_y2 > src_y1 and src_x2 > src_x1:
                    overlay_region = frame[y1:y2, x1:x2]
                    src_region = img1_scaled[src_y1:src_y2, src_x1:src_x2]
                    if overlay_region.shape == src_region.shape:
                        blended = cv2.addWeighted(overlay_region, 1 - alpha, src_region, alpha, 0)
                        frame[y1:y2, x1:x2] = blended
                
                frames.append(frame)
            else:
                frames.append(img2.copy())
        
        return frames
    
    def _rotate_zoom_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """旋转放大转场 - 旋转同时放大"""
        frames = []
        h, w = img1.shape[:2]
        center = (w // 2, h // 2)
        
        progress_values = np.linspace(0, 1, num_frames)
        
        for progress in progress_values:
            # 旋转角度（旋转360度）
            angle = progress * 360
            
            # 缩放（从0.3倍到1倍）
            scale = 0.3 + progress * 0.7
            
            # 旋转矩阵
            rotation_matrix = cv2.getRotationMatrix2D(center, angle, scale)
            
            # 旋转img2
            img2_transformed = cv2.warpAffine(img2, rotation_matrix, (w, h), 
                                             borderMode=cv2.BORDER_CONSTANT, 
                                             borderValue=(0, 0, 0))
            
            # 与img1混合
            alpha = progress
            frame = cv2.addWeighted(img1, 1 - alpha, img2_transformed, alpha, 0)
            
            frames.append(frame)
        
        return frames
    
    def _elastic_zoom_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """弹性缩放转场 - 有回弹效果的缩放"""
        frames = []
        h, w = img1.shape[:2]
        
        progress_values = np.linspace(0, 1, num_frames)
        
        for progress in progress_values:
            # 弹性函数（有回弹）
            elastic_progress = progress
            if progress < 0.5:
                elastic_progress = progress * 2
            else:
                # 回弹效果
                elastic_progress = 1 + 0.2 * np.sin((progress - 0.5) * 2 * np.pi * 2)
            
            elastic_progress = np.clip(elastic_progress, 0, 1.2)
            
            # 缩放
            scale = 0.5 + elastic_progress * 0.7
            new_h, new_w = int(h * scale), int(w * scale)
            
            if new_h > 0 and new_w > 0:
                img2_scaled = cv2.resize(img2, (new_w, new_h))
                
                frame = img1.copy()
                
                # 居中放置
                y_offset = (h - new_h) // 2
                x_offset = (w - new_w) // 2
                
                alpha = progress
                
                if new_h <= h and new_w <= w:
                    overlay_region = frame[y_offset:y_offset+new_h, x_offset:x_offset+new_w]
                    blended = cv2.addWeighted(overlay_region, 1 - alpha, img2_scaled, alpha, 0)
                    frame[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = blended
                else:
                    # 裁剪
                    crop_y = (new_h - h) // 2
                    crop_x = (new_w - w) // 2
                    img2_cropped = img2_scaled[crop_y:crop_y+h, crop_x:crop_x+w]
                    frame = cv2.addWeighted(frame, 1 - alpha, img2_cropped, alpha, 0)
                
                frames.append(frame)
            else:
                frames.append(img1.copy())
        
        return frames
    
    def _flip_3d_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """3D翻转转场 - 立体翻转效果"""
        frames = []
        h, w = img1.shape[:2]
        
        progress_values = np.linspace(0, 1, num_frames)
        
        for progress in progress_values:
            # 翻转角度（0到180度）
            angle = progress * 180
            
            # 计算缩放因子（cos曲线）
            scale_x = abs(np.cos(np.radians(angle)))
            
            if angle < 90:
                # 前半段显示img1
                current_img = img1
            else:
                # 后半段显示img2
                current_img = img2
            
            # 水平缩放模拟翻转
            new_w = max(1, int(w * scale_x))
            img_scaled = cv2.resize(current_img, (new_w, h))
            
            # 创建黑色背景
            frame = np.zeros_like(img1)
            
            # 居中放置
            x_offset = (w - new_w) // 2
            frame[:, x_offset:x_offset+new_w] = img_scaled
            
            # 添加阴影效果
            shadow_alpha = 0.3 * (1 - scale_x)
            frame = (frame * (1 - shadow_alpha)).astype(np.uint8)
            
            frames.append(frame)
        
        return frames
    
    def _push_in_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """推入转场 - 新图推开旧图"""
        frames = []
        h, w = img1.shape[:2]
        
        progress_values = np.linspace(0, 1, num_frames)
        
        for progress in progress_values:
            frame = np.zeros_like(img1)
            
            # 计算推入位置
            push_pos = int(w * progress)
            
            # img1向左移动
            img1_offset = -push_pos
            if img1_offset + w > 0:
                x1_start = max(0, img1_offset)
                x1_end = min(w, img1_offset + w)
                src_x1_start = max(0, -img1_offset)
                src_x1_end = src_x1_start + (x1_end - x1_start)
                
                frame[:, x1_start:x1_end] = img1[:, src_x1_start:src_x1_end]
            
            # img2从右侧进入
            img2_offset = w - push_pos
            if img2_offset < w:
                x2_start = max(0, img2_offset)
                x2_end = w
                src_x2_start = 0
                src_x2_end = x2_end - x2_start
                
                frame[:, x2_start:x2_end] = img2[:, src_x2_start:src_x2_end]
            
            frames.append(frame)
        
        return frames
    
    def _diagonal_wipe_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """对角擦除转场 - 对角线快速扫过"""
        frames = []
        h, w = img1.shape[:2]
        
        # 创建坐标网格
        y_coords, x_coords = np.ogrid[:h, :w]
        
        progress_values = np.linspace(0, 1, num_frames)
        
        for progress in progress_values:
            # 对角线阈值
            diagonal_threshold = progress * (h + w)
            
            # 创建对角线遮罩
            mask = (x_coords + y_coords) < diagonal_threshold
            
            frame = img1.copy()
            frame[mask] = img2[mask]
            
            frames.append(frame)
        
        return frames
    
    def _door_open_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """门式打开转场 - 从中间向两边展开"""
        frames = []
        h, w = img1.shape[:2]
        center_x = w // 2
        
        progress_values = np.linspace(0, 1, num_frames)
        
        for progress in progress_values:
            frame = img1.copy()
            
            # 计算门打开的宽度
            door_width = int(center_x * progress)
            
            # 左门
            left_start = center_x - door_width
            # 右门
            right_end = center_x + door_width
            
            # 显示img2
            if door_width > 0:
                frame[:, left_start:right_end] = img2[:, left_start:right_end]
            
            frames.append(frame)
        
        return frames
    
    def _flash_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """闪光过渡转场 - 强光闪烁过渡"""
        frames = []
        
        progress_values = np.linspace(0, 1, num_frames)
        
        for progress in progress_values:
            # 闪光强度（中间最亮）
            flash_intensity = 1 - abs(2 * progress - 1)
            flash_intensity = flash_intensity ** 2  # 更锐利的闪光
            
            # 基础混合
            if progress < 0.5:
                base_frame = img1
                alpha = progress * 2
            else:
                base_frame = img2
                alpha = (progress - 0.5) * 2
            
            # 添加白色闪光
            white = np.ones_like(img1) * 255
            frame = cv2.addWeighted(base_frame, 1 - flash_intensity, white, flash_intensity, 0)
            
            frames.append(frame)
        
        return frames
    
    def _shatter_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """碎片飞散转场 - 图片碎裂飞散"""
        frames = []
        h, w = img1.shape[:2]
        
        # 碎片网格
        shard_size = 40
        rows = (h + shard_size - 1) // shard_size
        cols = (w + shard_size - 1) // shard_size
        
        # 为每个碎片生成随机运动参数
        np.random.seed(42)  # 固定种子保证可重复性
        shard_velocities = []
        for i in range(rows):
            for j in range(cols):
                vel_x = np.random.randn() * 50
                vel_y = np.random.randn() * 50 - 30  # 向上偏移
                rotation = np.random.randn() * 180
                shard_velocities.append((vel_x, vel_y, rotation))
        
        progress_values = np.linspace(0, 1, num_frames)
        
        for progress in progress_values:
            # 以img2为基础
            frame = img2.copy()
            
            # 绘制碎片（从后往前，避免遮挡）
            idx = 0
            for i in range(rows):
                for j in range(cols):
                    y1 = i * shard_size
                    y2 = min((i + 1) * shard_size, h)
                    x1 = j * shard_size
                    x2 = min((j + 1) * shard_size, w)
                    
                    # 提取碎片
                    shard = img1[y1:y2, x1:x2].copy()
                    
                    # 计算碎片位置（带加速度）
                    vel_x, vel_y, rotation = shard_velocities[idx]
                    offset_x = int(vel_x * progress ** 1.5)
                    offset_y = int(vel_y * progress ** 1.5)
                    angle = rotation * progress
                    
                    # 计算透明度（逐渐消失）
                    alpha = max(0, 1 - progress * 1.2)
                    
                    # 如果碎片还可见
                    if alpha > 0.01 and progress < 0.9:
                        # 计算新位置
                        new_x = x1 + offset_x
                        new_y = y1 + offset_y
                        
                        # 旋转碎片
                        shard_h, shard_w = shard.shape[:2]
                        if shard_h > 0 and shard_w > 0:
                            center = (shard_w // 2, shard_h // 2)
                            rot_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
                            shard_rotated = cv2.warpAffine(shard, rot_matrix, (shard_w, shard_h),
                                                          borderMode=cv2.BORDER_CONSTANT,
                                                          borderValue=(0, 0, 0))
                            
                            # 绘制到frame上（注意边界）
                            dst_y1 = max(0, new_y)
                            dst_y2 = min(h, new_y + shard_h)
                            dst_x1 = max(0, new_x)
                            dst_x2 = min(w, new_x + shard_w)
                            
                            src_y1 = max(0, -new_y)
                            src_y2 = src_y1 + (dst_y2 - dst_y1)
                            src_x1 = max(0, -new_x)
                            src_x2 = src_x1 + (dst_x2 - dst_x1)
                            
                            if dst_y2 > dst_y1 and dst_x2 > dst_x1:
                                shard_region = shard_rotated[src_y1:src_y2, src_x1:src_x2]
                                frame_region = frame[dst_y1:dst_y2, dst_x1:dst_x2]
                                
                                if shard_region.shape[:2] == frame_region.shape[:2]:
                                    blended = cv2.addWeighted(frame_region, 1 - alpha, shard_region, alpha, 0)
                                    frame[dst_y1:dst_y2, dst_x1:dst_x2] = blended
                    
                    idx += 1
            
            frames.append(frame)
        
        return frames

    def _glow_spread_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """光晕扩散转场"""
        frames = []
        h, w = img1.shape[:2]
        cx, cy = w // 2, h // 2
        max_r = int(np.hypot(cx, cy))
        progress_values = np.linspace(0, 1, num_frames)
        for progress in progress_values:
            radius = int(max_r * progress)
            mask = np.zeros((h, w), dtype=np.uint8)
            cv2.circle(mask, (cx, cy), max(1, radius), 255, -1)
            mask_f = cv2.GaussianBlur(mask, (0, 0), sigmaX=8, sigmaY=8).astype(np.float32) / 255.0
            mask_f = np.repeat(mask_f[:, :, None], 3, axis=2)
            glow = cv2.GaussianBlur(img2, (0, 0), sigmaX=10, sigmaY=10)
            blend_target = cv2.addWeighted(img2, 0.75, glow, 0.25, 0)
            frame = (img1 * (1 - mask_f) + blend_target * mask_f).astype(np.uint8)
            frames.append(frame)
        return frames

    def _radial_sweep_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """径向旋切转场"""
        frames = []
        h, w = img1.shape[:2]
        yy, xx = np.indices((h, w))
        cx, cy = w / 2.0, h / 2.0
        angles = (np.degrees(np.arctan2(yy - cy, xx - cx)) + 360.0) % 360.0
        progress_values = np.linspace(0, 1, num_frames)
        for progress in progress_values:
            threshold = progress * 360.0
            mask = angles <= threshold
            frame = img1.copy()
            frame[mask] = img2[mask]
            frames.append(frame)
        return frames

    def _vortex_distort_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """漩涡扭曲转场"""
        frames = []
        h, w = img1.shape[:2]
        cx, cy = w / 2.0, h / 2.0
        yy, xx = np.indices((h, w), dtype=np.float32)
        dx = xx - cx
        dy = yy - cy
        radius = np.sqrt(dx * dx + dy * dy)
        max_r = max(1.0, np.max(radius))
        base_angle = np.arctan2(dy, dx)
        progress_values = np.linspace(0, 1, num_frames)
        for progress in progress_values:
            twist = (1.0 - radius / max_r) * (1.0 - progress) * 2.2
            new_angle = base_angle + twist
            map_x = (cx + radius * np.cos(new_angle)).astype(np.float32)
            map_y = (cy + radius * np.sin(new_angle)).astype(np.float32)
            warped = cv2.remap(img1, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            frame = cv2.addWeighted(warped, 1 - progress, img2, progress, 0)
            frames.append(frame)
        return frames

    def _diamond_reveal_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """菱形开幕转场"""
        frames = []
        h, w = img1.shape[:2]
        yy, xx = np.indices((h, w))
        cx, cy = w // 2, h // 2
        dist = np.abs(xx - cx) + np.abs(yy - cy)
        max_d = max(1, np.max(dist))
        progress_values = np.linspace(0, 1, num_frames)
        for progress in progress_values:
            threshold = int(max_d * progress)
            mask = dist <= threshold
            frame = img1.copy()
            frame[mask] = img2[mask]
            frames.append(frame)
        return frames

    def _focus_blur_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """镜头虚焦转场"""
        frames = []
        progress_values = np.linspace(0, 1, num_frames)
        for progress in progress_values:
            blur_strength = max(1, int(1 + (1.0 - abs(progress - 0.5) * 2.0) * 16))
            k = blur_strength if blur_strength % 2 == 1 else blur_strength + 1
            b1 = cv2.GaussianBlur(img1, (k, k), 0)
            b2 = cv2.GaussianBlur(img2, (k, k), 0)
            frame = cv2.addWeighted(b1, 1 - progress, b2, progress, 0)
            frames.append(frame)
        return frames

    def _curtain_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int, direction: str) -> List[np.ndarray]:
        """拉幕转场（纵向/横向）"""
        frames = []
        h, w = img1.shape[:2]
        progress_values = np.linspace(0, 1, num_frames)
        for progress in progress_values:
            frame = img1.copy()
            if direction == "vertical":
                half = int((w // 2) * progress)
                if half > 0:
                    frame[:, (w // 2 - half):(w // 2 + half)] = img2[:, (w // 2 - half):(w // 2 + half)]
            else:
                half = int((h // 2) * progress)
                if half > 0:
                    frame[(h // 2 - half):(h // 2 + half), :] = img2[(h // 2 - half):(h // 2 + half), :]
            frames.append(frame)
        return frames

    def _liquid_blend_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """液态融合转场"""
        frames = []
        h, w = img1.shape[:2]
        yy, xx = np.indices((h, w), dtype=np.float32)
        progress_values = np.linspace(0, 1, num_frames)
        for progress in progress_values:
            wave = np.sin((xx / 30.0) + progress * np.pi * 3.5) * (1.0 - progress) * 12.0
            map_x = np.clip(xx + wave, 0, w - 1).astype(np.float32)
            map_y = yy.astype(np.float32)
            warped = cv2.remap(img1, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            frame = cv2.addWeighted(warped, 1 - progress, img2, progress, 0)
            frames.append(frame)
        return frames

    def _light_streak_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """流光擦拭转场"""
        frames = []
        h, w = img1.shape[:2]
        progress_values = np.linspace(0, 1, num_frames)
        for progress in progress_values:
            split = int(w * progress)
            frame = img1.copy()
            if split > 0:
                frame[:, :split] = img2[:, :split]
            streak_center = split
            if 0 < streak_center < w:
                band = max(6, w // 40)
                x1 = max(0, streak_center - band)
                x2 = min(w, streak_center + band)
                if x2 > x1:
                    flash = np.full((h, x2 - x1, 3), 255, dtype=np.uint8)
                    frame[:, x1:x2] = cv2.addWeighted(frame[:, x1:x2], 0.45, flash, 0.55, 0)
            frames.append(frame)
        return frames

    def _clock_wipe_transition(self, img1: np.ndarray, img2: np.ndarray, num_frames: int) -> List[np.ndarray]:
        """时钟扫描转场"""
        frames = []
        h, w = img1.shape[:2]
        yy, xx = np.indices((h, w))
        cx, cy = w / 2.0, h / 2.0
        # 12点方向开始，顺时针
        angles = (np.degrees(np.arctan2(xx - cx, cy - yy)) + 360.0) % 360.0
        progress_values = np.linspace(0, 1, num_frames)
        for progress in progress_values:
            threshold = progress * 360.0
            mask = angles <= threshold
            frame = img1.copy()
            frame[mask] = img2[mask]
            frames.append(frame)
        return frames

    def _generate_cache_key(self, img1: np.ndarray, img2: np.ndarray,
                          transition_type: str, num_frames: int) -> str:
        """生成缓存键"""
        # 使用图片形状+缩略图哈希，避免不同图片复用同一转场
        try:
            import zlib
            thumb_size = (32, 32)
            thumb1 = cv2.resize(img1, thumb_size, interpolation=cv2.INTER_AREA)
            thumb2 = cv2.resize(img2, thumb_size, interpolation=cv2.INTER_AREA)
            h1 = zlib.adler32(thumb1.tobytes())
            h2 = zlib.adler32(thumb2.tobytes())
            return f"{img1.shape}_{img2.shape}_{transition_type}_{num_frames}_{h1}_{h2}"
        except Exception:
            # 回退：仅使用形状
            return f"{img1.shape}_{img2.shape}_{transition_type}_{num_frames}"

    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        total_time = self.stats['total_time']
        transitions_generated = self.stats['transitions_generated']

        cache_requests = self.stats['cache_hits'] + self.stats['cache_misses']
        cache_hit_rate = (
            self.stats['cache_hits'] / cache_requests * 100
            if cache_requests > 0 else 0
        )

        return {
            'transitions_generated': transitions_generated,
            'total_time': total_time,
            'average_time': total_time / transitions_generated if transitions_generated > 0 else 0,
            'cache_hit_rate': f"{cache_hit_rate:.1f}%",
            'cache_hits': self.stats['cache_hits'],
            'cache_misses': self.stats['cache_misses'],
            'cache_size': len(self.transition_cache)
        }

    def clear_cache(self):
        """清理转场缓存"""
        with self.cache_lock:
            self.transition_cache.clear()
            print("[清理] 转场缓存已清理")

    def cleanup(self):
        """清理资源"""
        try:
            self.executor.shutdown(wait=True)
            self.clear_cache()
            print("[清理] Turbo转场引擎资源清理完成")
        except Exception as e:
            print(f"清理资源失败: {str(e)}")

    def __del__(self):
        """析构函数"""
        try:
            self.cleanup()
        except:
            pass

# 全局实例管理
_global_turbo_transition_engine = None
_engine_lock = threading.Lock()

def get_turbo_transition_engine() -> TurboTransitionEngine:
    """获取全局Turbo转场引擎实例"""
    global _global_turbo_transition_engine
    with _engine_lock:
        if _global_turbo_transition_engine is None:
            _global_turbo_transition_engine = TurboTransitionEngine()
        return _global_turbo_transition_engine

def cleanup_turbo_transition_engine():
    """清理Turbo转场引擎"""
    global _global_turbo_transition_engine
    with _engine_lock:
        if _global_turbo_transition_engine:
            _global_turbo_transition_engine.cleanup()
            _global_turbo_transition_engine = None

def print_turbo_transition_stats():
    """打印Turbo转场引擎统计信息"""
    engine = get_turbo_transition_engine()
    stats = engine.get_performance_stats()

    print("=" * 60)
    print("Turbo转场引擎性能统计")
    print("=" * 60)
    print(f"生成转场数量: {stats['transitions_generated']}")
    print(f"总处理时间: {stats['total_time']:.2f}秒")
    print(f"平均生成时间: {stats['average_time']:.3f}秒/转场")
    print(f"缓存命中率: {stats['cache_hit_rate']}")
    print(f"缓存大小: {stats['cache_size']}")
    print("=" * 60)

if __name__ == "__main__":
    # 测试代码
    engine = get_turbo_transition_engine()
    print("Turbo转场引擎测试完成")
    print_turbo_transition_stats()
