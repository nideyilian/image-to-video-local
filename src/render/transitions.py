"""转场渲染（与界面无关的渲染内核）。

从 ``src/gui/main_window.py`` 的 ``ImageToVideoTab`` 抽出，函数体逐字保留，
仅把 ``self.transition_engine`` 改为显式注入参数 ``transition_engine``。
本模块不导入任何 GUI 库。

注：``apply_fade/blinds/slide/dissolve/wipe_transition`` 目前在刚链中无调用点
（已被 ``TurboTransitionEngine`` 取代），为保持行为等价仍予保留。
"""

from __future__ import annotations

import numpy as np

from ..utils.opencv_silent import import_cv2_silent

cv2 = import_cv2_silent()


def get_default_transition_engine():
    """便捷获取 core 层的转场加速引擎（单例）。"""
    from ..core.transition_engine import get_turbo_transition_engine

    return get_turbo_transition_engine()


def apply_fade_transition(img1, img2, frame_idx, total_frames):
    """淡入淡出转场效果"""
    alpha = frame_idx / total_frames
    return cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)

def apply_blinds_transition(img1, img2, frame_idx, total_frames):
    """百叶窗转场效果"""
    result = img1.copy()
    h, w = img1.shape[:2]
    
    # 百叶窗条数 (在5-15之间，随机选择)
    blinds = 10
    
    # 计算每个百叶窗的高度
    blind_height = h // blinds
    
    # 计算当前应该显示多少百叶窗
    visible_blinds = int((frame_idx / total_frames) * blinds) + 1
    
    # 应用百叶窗效果
    for i in range(blinds):
        start_y = i * blind_height
        end_y = start_y + blind_height
        
        # 确保不超出图像边界
        if end_y > h:
            end_y = h
        
        if i < visible_blinds:
            # 如果百叶窗已经可见，显示img2
            result[start_y:end_y, :] = img2[start_y:end_y, :]
    
    return result

def apply_slide_transition(img1, img2, frame_idx, total_frames):
    """滑动转场效果"""
    result = img1.copy()
    h, w = img1.shape[:2]
    
    # 计算当前滑动的位置
    slide_pos = int((frame_idx / total_frames) * w)
    
    # 应用滑动效果(从右向左)
    result[:, (w-slide_pos):w] = img2[:, 0:slide_pos]
    
    return result

def apply_dissolve_transition(img1, img2, frame_idx, total_frames):
    """溶解转场效果"""
    alpha = frame_idx / total_frames
    
    # 创建随机噪声掩码
    noise = np.random.random(img1.shape[:2])
    mask = (noise < alpha).astype(np.float32)
    mask = np.expand_dims(mask, axis=2)
    mask = np.repeat(mask, 3, axis=2)
    
    # 应用掩码
    result = img1.copy()
    np.copyto(result, img2, where=(mask > 0.5))
    
    return result

def apply_wipe_transition(img1, img2, frame_idx, total_frames):
    """擦除转场效果"""
    result = img1.copy()
    h, w = img1.shape[:2]
    
    # 计算当前擦除的位置
    wipe_pos = int((frame_idx / total_frames) * h)
    
    # 应用擦除效果(从上到下)
    result[0:wipe_pos, :] = img2[0:wipe_pos, :]
    
    return result

def apply_transition(img1, img2, video_writer, num_frames, transition_type="淡入淡出",
                     transition_engine=None):
    """应用转场效果并写入到视频"""
    try:
        # 优先统一走Turbo转场引擎（支持新增高级转场）
        if transition_engine and num_frames > 0 and transition_type != "无转场":
            try:
                frames = transition_engine.generate_transition_frames(
                    img1, img2, transition_type, num_frames, use_cache=True
                )
                if frames:
                    for frame in frames:
                        video_writer.write(frame)
                    return
            except Exception:
                pass

        h, w = img1.shape[:2]
        
        # 确保两张图片尺寸相同
        if img1.shape != img2.shape:
            img2 = cv2.resize(img2, (w, h))
        
        print(f"应用转场效果: {transition_type}, 总帧数: {num_frames}")
        
        for i in range(num_frames):
            # 计算过渡比例（避开0和1，避免重复帧）
            alpha = (i + 1) / (num_frames + 1) if num_frames > 0 else 1
            
            # 根据转场类型应用不同效果
            try:
                if transition_type == "淡入淡出":
                    # 淡入淡出效果
                    frame = cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)
                
                elif transition_type == "左右滑动":
                    # 水平滑动效果 - 从右向左滑动
                    result = img1.copy()
                    slide_pos = int(alpha * w)
                    result[:, (w-slide_pos):w] = img2[:, 0:slide_pos]
                    frame = result
                
                elif transition_type == "上下滑动":
                    # 垂直滑动效果 - 从上到下滑动
                    result = img1.copy()
                    slide_pos = int(alpha * h)
                    result[0:slide_pos, :] = img2[0:slide_pos, :]
                    frame = result
                
                elif transition_type == "交叉溶解":
                    # 使用随机噪声创建溶解效果
                    mask = np.random.random(img1.shape[:2])
                    mask = (mask < alpha).astype(np.float32)
                    mask = np.expand_dims(mask, axis=2)
                    mask = np.repeat(mask, 3, axis=2)
                    
                    result = img1.copy() * (1-mask) + img2 * mask
                    frame = result.astype(np.uint8)
                
                elif transition_type == "缩放过渡":
                    # 缩放过渡效果
                    center_y, center_x = h//2, w//2
                    max_size = max(h, w)
                    scaling = int(max_size * alpha)
                    
                    # 创建掩码
                    mask = np.zeros((h, w), dtype=np.uint8)
                    cv2.circle(mask, (center_x, center_y), scaling, 255, -1)
                    
                    # 应用掩码
                    mask_3ch = cv2.merge([mask, mask, mask])
                    frame = np.where(mask_3ch > 128, img2, img1)
                
                elif transition_type == "方块过渡":
                    # 创建方块过渡效果
                    block_size = max(1, int(50 * (1 - alpha)))  # 块大小从大到小
                    
                    # 创建方块掩码
                    mask = np.zeros((h, w), dtype=np.uint8)
                    for y in range(0, h, block_size*2):
                        for x in range(0, w, block_size*2):
                            y2 = min(y + block_size, h)
                            x2 = min(x + block_size, w)
                            mask[y:y2, x:x2] = 255
                    
                    # 进度控制显示区域
                    progress_mask = np.zeros((h, w), dtype=np.uint8)
                    progress_height = int(h * alpha)
                    progress_mask[0:progress_height, :] = 255
                    
                    # 结合两个掩码
                    final_mask = cv2.bitwise_and(mask, progress_mask)
                    final_mask_3ch = cv2.merge([final_mask, final_mask, final_mask])
                    
                    # 应用掩码
                    frame = np.where(final_mask_3ch > 128, img2, img1)
                
                elif transition_type == "圆形扩展":
                    # 从中心扩展的圆形
                    center_y, center_x = h//2, w//2
                    radius = int(np.sqrt(center_x**2 + center_y**2) * alpha)
                    
                    # 创建圆形掩码
                    mask = np.zeros((h, w), dtype=np.uint8)
                    cv2.circle(mask, (center_x, center_y), radius, 255, -1)
                    
                    # 应用掩码
                    mask_3ch = cv2.merge([mask, mask, mask])
                    frame = np.where(mask_3ch > 128, img2, img1)
                
                elif transition_type == "百叶窗":
                    # 创建交错线条效果 (对应main_with_presets.py中的"交错效果")
                    stripe_width = max(1, int(h * 0.05))  # 条纹宽度为图像高度的5%
                    result = img1.copy()
                    
                    # 根据进度增加第二张图片的条纹数量
                    num_stripes = int(h / stripe_width * alpha)
                    
                    for j in range(num_stripes):
                        y_start = j * stripe_width
                        y_end = min(y_start + stripe_width, h)
                        result[y_start:y_end, :] = img2[y_start:y_end, :]
                    
                    frame = result
                
                elif transition_type == "像素化":
                    # 像素化效果
                    max_block = max(1, min(h, w) // 10)
                    block_size = max(1, int(max_block * (1 - alpha)))
                    
                    if block_size > 1:
                        # 对第二张图像进行像素化
                        temp = cv2.resize(img2, (w // block_size, h // block_size), interpolation=cv2.INTER_LINEAR)
                        pixelated = cv2.resize(temp, (w, h), interpolation=cv2.INTER_NEAREST)
                        
                        # 根据进度混合原图和像素化图像
                        frame = cv2.addWeighted(img1, 1 - alpha, pixelated, alpha, 0)
                    else:
                        frame = cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)
                
                elif transition_type == "旋转变换":
                    # 旋转过渡效果
                    center_x, center_y = w // 2, h // 2
                    
                    # 计算旋转角度 (0-90度)
                    angle = 90 * alpha
                    
                    # 创建旋转矩阵和应用到第二张图片
                    M = cv2.getRotationMatrix2D((center_x, center_y), angle, 1.0)
                    rotated = cv2.warpAffine(img2, M, (w, h))
                    
                    # 创建圆形掩码
                    mask = np.zeros((h, w), dtype=np.uint8)
                    radius = int(min(w, h) * 0.5 * alpha)
                    cv2.circle(mask, (center_x, center_y), radius, 255, -1)
                    
                    # 应用掩码
                    mask_3ch = cv2.merge([mask, mask, mask])
                    frame = np.where(mask_3ch > 128, rotated, img1)
                
                else:
                    # 默认使用淡入淡出
                    print(f"未识别的转场效果 '{transition_type}'，使用默认淡入淡出")
                    frame = cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)
            
            except Exception as e:
                # 如果特效应用失败，回退到基本的淡入淡出
                print(f"应用转场效果 {transition_type} 失败: {str(e)}，原因: {type(e).__name__}")
                print(f"图像尺寸: img1={img1.shape}, img2={img2.shape}")
                frame = cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)
            
            # 确保帧有效
            if frame is None or frame.shape[0] == 0 or frame.shape[1] == 0:
                print(f"转场生成的帧无效，使用基本帧")
                frame = cv2.addWeighted(img1, 1 - alpha, img2, alpha, 0)
                
            # 写入帧
            video_writer.write(frame)
        
        print(f"转场效果 '{transition_type}' 应用完成")
            
    except Exception as e:
        print(f"转场效果处理失败: {str(e)}, 类型: {type(e).__name__}")
        print(f"图像尺寸: img1={img1.shape if img1 is not None else None}, img2={img2.shape if img2 is not None else None}")
        
        # 错误处理 - 写入两张静态图片作为应急方案
        if video_writer.isOpened():
            # 各写一半帧
            half_frames = num_frames // 2
            for _ in range(half_frames):
                if img1 is not None and img1.size > 0:
                    video_writer.write(img1)
                else:
                    # 如果img1无效，创建黑色图像
                    blank = np.zeros((h, w, 3), dtype=np.uint8)
                    video_writer.write(blank)
                    
            for _ in range(num_frames - half_frames):
                if img2 is not None and img2.size > 0:
                    video_writer.write(img2)
                else:
                    # 如果img2无效，创建黑色图像
                    blank = np.zeros((h, w, 3), dtype=np.uint8)
                    video_writer.write(blank)
