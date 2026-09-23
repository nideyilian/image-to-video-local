"""单图动态效果渲染（与界面无关的渲染内核）。

从 ``src/gui/main_window.py`` 的 ``ImageToVideoTab`` 抽出的纯无状态实现，
函数体逐字保留，仅去除 ``self`` 绑定。本模块不导入任何 GUI 库。
"""

from __future__ import annotations

import numpy as np

from ..utils.opencv_silent import import_cv2_silent

cv2 = import_cv2_silent()


def _center_crop(img, target_width, target_height):
    """从中心裁剪到目标尺寸"""
    if img is None:
        return None
    h, w = img.shape[:2]
    if h < target_height or w < target_width:
        return cv2.resize(img, (target_width, target_height))
    x_start = max((w - target_width) // 2, 0)
    y_start = max((h - target_height) // 2, 0)
    return img[y_start:y_start + target_height, x_start:x_start + target_width]


def apply_single_image_effect(img, effect_type, time_sec, duration_sec, intensity=100.0, speed=1.0):
    """单图视频特效：让静态图片产生运动感"""
    try:
        if img is None:
            return img
        h, w = img.shape[:2]
        time_sec = max(0.0, float(time_sec))
        duration_sec = max(0.001, float(duration_sec))
        # 速度按“每秒进度”计算，避免时长越长越慢
        progress = min(1.0, time_sec * max(0.01, float(speed)))
        intensity = max(1.0, float(intensity))
        speed = max(0.01, float(speed))
        intensity_scale = intensity / 100.0

        if effect_type == "无特效":
            return img

        # 兼容旧配置：将已移除的“单次运动”特效映射到循环复合特效
        legacy_effect_alias = {
            "心跳跃动": "心跳跳动",
            "轻微放大": "镜头呼吸",
            "轻微缩小": "脉冲放大",
            "左右平移": "左右晃动",
            "上下平移": "上下浮动",
            "旋转缩放": "旋转摆动",
            "缓慢推近": "摇摆推拉",
            "缓慢拉远": "双轴呼吸",
            "右下平移": "圆周漂移",
            "左上平移": "8字漂移",
        }
        effect_type = legacy_effect_alias.get(effect_type, effect_type)

        def _affine_transform(scale=1.0, angle=0.0, tx=0.0, ty=0.0):
            """统一仿射变换，避免重复代码。"""
            M = cv2.getRotationMatrix2D((w * 0.5, h * 0.5), angle, scale)
            M[0, 2] += tx
            M[1, 2] += ty
            return cv2.warpAffine(
                img, M, (w, h),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT
            )

        # 循环相位（不依赖视频总时长，始终无限循环）
        p1 = 2 * np.pi * 1.0 * speed * time_sec
        p2 = 2 * np.pi * 1.6 * speed * time_sec
        p3 = 2 * np.pi * 2.2 * speed * time_sec

        # 新增：20个无限循环复合特效
        if effect_type == "旋转呼吸":
            scale = 1.02 + 0.06 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
            angle = 5.0 * intensity_scale * np.sin(p2)
            return _affine_transform(scale=scale, angle=angle)

        if effect_type == "摇摆推拉":
            scale = 1.04 + 0.10 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
            angle = 3.5 * intensity_scale * np.sin(p2)
            tx = 0.015 * w * intensity_scale * np.sin(p3)
            return _affine_transform(scale=scale, angle=angle, tx=tx)

        if effect_type == "圆周漂移":
            scale = 1.08 + 0.03 * intensity_scale
            tx = 0.035 * w * intensity_scale * np.cos(p1)
            ty = 0.035 * h * intensity_scale * np.sin(p1)
            return _affine_transform(scale=scale, tx=tx, ty=ty)

        if effect_type == "螺旋摆动":
            radius = (0.015 + 0.02 * (0.5 - 0.5 * np.cos(p2))) * intensity_scale
            tx = radius * w * np.cos(p1)
            ty = radius * h * np.sin(p1)
            angle = 4.0 * intensity_scale * np.sin(p3)
            scale = 1.04 + 0.04 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
            return _affine_transform(scale=scale, angle=angle, tx=tx, ty=ty)

        if effect_type == "双轴呼吸":
            sx = 1.0 + 0.07 * intensity_scale * np.sin(p1)
            sy = 1.0 + 0.07 * intensity_scale * np.cos(p2)
            scaled = cv2.resize(img, (int(w * sx), int(h * sy)))
            return _center_crop(scaled, w, h)

        if effect_type == "心跳摇摆":
            beat = (0.5 - 0.5 * np.cos(p2)) ** 1.7
            scale = 1.0 + 0.12 * intensity_scale * beat
            angle = 2.5 * intensity_scale * np.sin(p1)
            return _affine_transform(scale=scale, angle=angle)

        if effect_type == "波浪平移":
            scale = 1.08 + 0.03 * intensity_scale
            tx = 0.04 * w * intensity_scale * np.sin(p1)
            ty = 0.025 * h * intensity_scale * np.sin(p2)
            return _affine_transform(scale=scale, tx=tx, ty=ty)

        if effect_type == "8字漂移":
            scale = 1.08 + 0.03 * intensity_scale
            tx = 0.04 * w * intensity_scale * np.sin(p1)
            ty = 0.03 * h * intensity_scale * np.sin(2 * p1)
            return _affine_transform(scale=scale, tx=tx, ty=ty)

        if effect_type == "径向脉冲旋转":
            pulse = 0.5 - 0.5 * np.cos(p3)
            scale = 1.03 + 0.10 * intensity_scale * pulse
            angle = 8.0 * intensity_scale * np.sin(p2)
            return _affine_transform(scale=scale, angle=angle)

        if effect_type == "镜头抖动呼吸":
            scale = 1.03 + 0.06 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
            tx = 0.01 * w * intensity_scale * np.sin(8 * p1)
            ty = 0.01 * h * intensity_scale * np.cos(7 * p1)
            return _affine_transform(scale=scale, tx=tx, ty=ty)

        if effect_type == "反向双旋":
            f1 = _affine_transform(scale=1.05 + 0.03 * intensity_scale, angle=6.0 * intensity_scale * np.sin(p1))
            f2 = _affine_transform(scale=1.05 + 0.03 * intensity_scale, angle=-6.0 * intensity_scale * np.sin(p1))
            alpha = 0.5 + 0.25 * np.sin(p2)
            return cv2.addWeighted(f1, alpha, f2, 1.0 - alpha, 0)

        if effect_type == "呼吸变焦扫光":
            scale = 1.02 + 0.08 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
            frame = _affine_transform(scale=scale)
            band_center = int((0.5 + 0.5 * np.sin(p2)) * w)
            band_width = max(10, int(w * (0.08 + 0.04 * intensity_scale)))
            x_arr = np.arange(w, dtype=np.float32)
            alpha_line = np.clip(1.0 - np.abs(x_arr - band_center) / band_width, 0.0, 1.0) * (0.15 + 0.22 * intensity_scale)
            alpha = np.repeat(alpha_line[np.newaxis, :], h, axis=0)[..., np.newaxis]
            return np.clip(frame.astype(np.float32) * (1.0 - alpha) + 255.0 * alpha, 0, 255).astype(np.uint8)

        if effect_type == "旋摆模糊脉冲":
            angle = 5.0 * intensity_scale * np.sin(p1)
            frame = _affine_transform(scale=1.04 + 0.04 * intensity_scale, angle=angle)
            blur_wave = 0.5 - 0.5 * np.cos(p2)
            ksize = max(1, int((1 + 8 * intensity_scale) * blur_wave) * 2 + 1)
            blurred = cv2.GaussianBlur(frame, (ksize, ksize), sigmaX=0)
            alpha = 0.25 + 0.45 * blur_wave
            return cv2.addWeighted(frame, 1 - alpha, blurred, alpha, 0)

        if effect_type == "透视呼吸摆动":
            tilt = (0.02 + 0.05 * intensity_scale) * np.sin(p1)
            dx = w * tilt
            src = np.float32([[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]])
            dst = np.float32([[dx, 0], [w - 1 - dx, 0], [-dx, h - 1], [w - 1 + dx, h - 1]])
            M = cv2.getPerspectiveTransform(src, dst)
            warped = cv2.warpPerspective(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            M2 = cv2.getRotationMatrix2D(
                (w * 0.5, h * 0.5),
                2.5 * intensity_scale * np.sin(p2),
                1.02 + 0.03 * intensity_scale
            )
            return cv2.warpAffine(warped, M2, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        if effect_type == "涡旋推拉":
            swirl = apply_single_image_effect(img, "漩涡旋转", time_sec, duration_sec, intensity, speed)
            scale = 1.03 + 0.08 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
            angle = 3.0 * intensity_scale * np.sin(p2)
            M = cv2.getRotationMatrix2D((w * 0.5, h * 0.5), angle, scale)
            return cv2.warpAffine(swirl, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        if effect_type == "变焦摇移":
            scale = 1.06 + 0.08 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
            tx = 0.03 * w * intensity_scale * np.sin(p2)
            ty = 0.03 * h * intensity_scale * np.cos(p2)
            return _affine_transform(scale=scale, tx=tx, ty=ty)

        if effect_type == "旋转漂移闪动":
            frame = _affine_transform(
                scale=1.05 + 0.03 * intensity_scale,
                angle=6.0 * intensity_scale * np.sin(p1),
                tx=0.02 * w * intensity_scale * np.sin(p2),
                ty=0.02 * h * intensity_scale * np.cos(p2),
            )
            glow = 0.08 + 0.18 * intensity_scale * (0.5 - 0.5 * np.cos(p3))
            return np.clip(frame.astype(np.float32) * (1.0 + glow), 0, 255).astype(np.uint8)

        if effect_type == "双频摆动":
            angle = (
                4.0 * intensity_scale * np.sin(p1)
                + 2.0 * intensity_scale * np.sin(2.7 * p1)
            )
            tx = 0.025 * w * intensity_scale * np.sin(p2)
            return _affine_transform(scale=1.04 + 0.03 * intensity_scale, angle=angle, tx=tx)

        if effect_type == "环形巡航":
            scale = 1.10 + 0.03 * intensity_scale
            tx = 0.045 * w * intensity_scale * np.cos(p1)
            ty = 0.035 * h * intensity_scale * np.sin(1.3 * p1)
            angle = 2.0 * intensity_scale * np.sin(p2)
            return _affine_transform(scale=scale, angle=angle, tx=tx, ty=ty)

        if effect_type == "呼吸鱼眼旋摆":
            fisheye = apply_single_image_effect(img, "鱼眼镜头", time_sec, duration_sec, intensity, speed)
            scale = 1.02 + 0.06 * intensity_scale * (0.5 - 0.5 * np.cos(p1))
            angle = 4.0 * intensity_scale * np.sin(p2)
            M = cv2.getRotationMatrix2D((w * 0.5, h * 0.5), angle, scale)
            return cv2.warpAffine(fisheye, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        if effect_type == "心跳跳动":
            # 两次心跳：快速放大-回落
            cycles = 2.0 * speed
            wave = 0.5 - 0.5 * np.cos(2 * np.pi * cycles * time_sec)
            scale = 1.0 + (0.10 * intensity_scale) * wave
            resized = cv2.resize(img, (int(w * scale), int(h * scale)))
            return _center_crop(resized, w, h)

        if effect_type == "反复缩放":
            # 平滑来回缩放（ping-pong）
            cycles = 1.5 * speed
            t = 0.5 - 0.5 * np.cos(2 * np.pi * cycles * time_sec)
            scale = (1.0 - 0.05 * intensity_scale) + (0.15 * intensity_scale) * t
            resized = cv2.resize(img, (int(w * scale), int(h * scale)))
            return _center_crop(resized, w, h)

        if effect_type == "轻微摇摆":
            # 轻微左右旋转摆动
            angle = (3.0 * intensity_scale) * np.sin(2 * np.pi * 1.0 * speed * time_sec)
            scale = 1.02 + 0.02 * intensity_scale
            resized = cv2.resize(img, (int(w * scale), int(h * scale)))
            rh, rw = resized.shape[:2]
            center = (rw // 2, rh // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(
                resized, M, (rw, rh),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT
            )
            return _center_crop(rotated, w, h)

        if effect_type == "左右晃动":
            # 水平往返移动
            scale = 1.04 + 0.06 * intensity_scale
            resized = cv2.resize(img, (int(w * scale), int(h * scale)))
            max_x = max(resized.shape[1] - w, 0)
            t = 0.5 - 0.5 * np.cos(2 * np.pi * 2.0 * speed * time_sec)
            x = int(max_x * t)
            return _center_crop(resized[:, x:x + w], w, h)

        if effect_type == "上下浮动":
            # 垂直往返移动
            scale = 1.04 + 0.06 * intensity_scale
            resized = cv2.resize(img, (int(w * scale), int(h * scale)))
            max_y = max(resized.shape[0] - h, 0)
            t = 0.5 - 0.5 * np.cos(2 * np.pi * 2.0 * speed * time_sec)
            y = int(max_y * t)
            return _center_crop(resized[y:y + h, :], w, h)

        if effect_type == "缓慢推近":
            # 缓慢推近
            scale = 1.0 + (0.12 * intensity_scale) * progress
            resized = cv2.resize(img, (int(w * scale), int(h * scale)))
            return _center_crop(resized, w, h)

        if effect_type == "缓慢拉远":
            # 缓慢拉远
            scale = (1.0 + 0.12 * intensity_scale) - (0.12 * intensity_scale) * progress
            resized = cv2.resize(img, (int(w * scale), int(h * scale)))
            return _center_crop(resized, w, h)

        if effect_type == "右下平移":
            # 向右下缓慢移动
            scale = 1.05 + 0.05 * intensity_scale
            resized = cv2.resize(img, (int(w * scale), int(h * scale)))
            max_x = max(resized.shape[1] - w, 0)
            max_y = max(resized.shape[0] - h, 0)
            x = int(max_x * progress)
            y = int(max_y * progress)
            return resized[y:y + h, x:x + w]

        if effect_type == "左上平移":
            # 向左上缓慢移动
            scale = 1.05 + 0.05 * intensity_scale
            resized = cv2.resize(img, (int(w * scale), int(h * scale)))
            max_x = max(resized.shape[1] - w, 0)
            max_y = max(resized.shape[0] - h, 0)
            x = int(max_x * (1.0 - progress))
            y = int(max_y * (1.0 - progress))
            return resized[y:y + h, x:x + w]

        if effect_type == "镜头呼吸":
            # 缓慢呼吸式缩放
            t = 0.5 - 0.5 * np.cos(2 * np.pi * 1.0 * speed * time_sec)
            scale = 1.01 + (0.06 * intensity_scale) * t
            resized = cv2.resize(img, (int(w * scale), int(h * scale)))
            return _center_crop(resized, w, h)

        if effect_type == "脉冲放大":
            # 周期性脉冲放大
            t = 0.5 - 0.5 * np.cos(2 * np.pi * 3.0 * speed * time_sec)
            scale = 1.0 + (0.08 * intensity_scale) * t
            resized = cv2.resize(img, (int(w * scale), int(h * scale)))
            return _center_crop(resized, w, h)

        if effect_type == "旋转摆动":
            # 旋转摆动，幅度稍大
            angle = (6.0 * intensity_scale) * np.sin(2 * np.pi * 1.5 * speed * time_sec)
            scale = 1.02 + 0.04 * intensity_scale
            resized = cv2.resize(img, (int(w * scale), int(h * scale)))
            rh, rw = resized.shape[:2]
            center = (rw // 2, rh // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(
                resized, M, (rw, rh),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT
            )
            return _center_crop(rotated, w, h)

        if effect_type == "水波扭曲":
            # 基于正弦场的水波位移
            y_coords, x_coords = np.indices((h, w), dtype=np.float32)
            cx, cy = w * 0.5, h * 0.5
            dx = x_coords - cx
            dy = y_coords - cy
            dist = np.sqrt(dx * dx + dy * dy) + 1e-6
            wave_amp = (6.0 + 10.0 * intensity_scale) * (0.8 + 0.2 * np.sin(2 * np.pi * 0.5 * speed * time_sec))
            wave_freq = 0.035
            wave_phase = 2 * np.pi * speed * time_sec * 2.0
            offset = wave_amp * np.sin(dist * wave_freq + wave_phase)
            map_x = (x_coords + dx / dist * offset).astype(np.float32)
            map_y = (y_coords + dy / dist * offset).astype(np.float32)
            return cv2.remap(img, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        if effect_type == "漩涡旋转":
            # 中心强、边缘弱的旋涡变换
            y_coords, x_coords = np.indices((h, w), dtype=np.float32)
            cx, cy = w * 0.5, h * 0.5
            x = x_coords - cx
            y = y_coords - cy
            r = np.sqrt(x * x + y * y)
            max_r = max(1.0, np.sqrt(cx * cx + cy * cy))
            base_theta = np.arctan2(y, x)
            swirl_strength = (2.8 * intensity_scale) * np.sin(2 * np.pi * 0.4 * speed * time_sec)
            theta = base_theta + swirl_strength * (1.0 - (r / max_r)) * (r / max_r)
            map_x = (cx + r * np.cos(theta)).astype(np.float32)
            map_y = (cy + r * np.sin(theta)).astype(np.float32)
            return cv2.remap(img, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        if effect_type == "鱼眼镜头":
            # 轻度桶形畸变，营造鱼眼镜头呼吸感
            y_coords, x_coords = np.indices((h, w), dtype=np.float32)
            cx, cy = w * 0.5, h * 0.5
            nx = (x_coords - cx) / max(1.0, cx)
            ny = (y_coords - cy) / max(1.0, cy)
            r2 = nx * nx + ny * ny
            k = (0.18 * intensity_scale) * np.sin(2 * np.pi * 0.6 * speed * time_sec)
            scale_d = 1.0 + k * r2
            map_x = (cx + nx * scale_d * cx).astype(np.float32)
            map_y = (cy + ny * scale_d * cy).astype(np.float32)
            return cv2.remap(img, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        if effect_type == "故障抖动":
            # RGB通道错位 + 条带位移
            shift = int((3 + 7 * intensity_scale) * np.sin(2 * np.pi * 3.0 * speed * time_sec))
            b, g, r = cv2.split(img)
            r_shift = np.roll(r, shift, axis=1)
            b_shift = np.roll(b, -shift, axis=1)
            glitch = cv2.merge([b_shift, g, r_shift])
            band_h = max(2, int(h * 0.06))
            band_y = int((0.5 - 0.5 * np.cos(2 * np.pi * 1.7 * speed * time_sec)) * max(1, h - band_h))
            band_offset = int((10 + 20 * intensity_scale) * np.sin(2 * np.pi * 6.0 * speed * time_sec))
            if band_h > 0:
                glitch[band_y:band_y + band_h, :] = np.roll(glitch[band_y:band_y + band_h, :], band_offset, axis=1)
            return glitch

        if effect_type == "镜像扫光":
            # 反射高光带横向扫过
            frame = img.copy().astype(np.float32)
            band_center = int(progress * w)
            band_width = max(10, int(w * (0.08 + 0.04 * intensity_scale)))
            x = np.arange(w, dtype=np.float32)
            dist = np.abs(x - band_center)
            alpha_line = np.clip(1.0 - dist / band_width, 0.0, 1.0) * (0.22 + 0.18 * intensity_scale)
            alpha = np.repeat(alpha_line[np.newaxis, :], h, axis=0)
            alpha = np.expand_dims(alpha, axis=2)
            light = np.full_like(frame, 255.0)
            mixed = frame * (1.0 - alpha) + light * alpha
            return np.clip(mixed, 0, 255).astype(np.uint8)

        if effect_type == "呼吸模糊":
            # 在清晰与轻模糊间呼吸切换
            blur_wave = 0.5 - 0.5 * np.cos(2 * np.pi * 1.3 * speed * time_sec)
            blur_strength = int((1 + 8 * intensity_scale) * blur_wave)
            ksize = max(1, blur_strength * 2 + 1)
            blurred = cv2.GaussianBlur(img, (ksize, ksize), sigmaX=0)
            alpha = 0.35 + 0.45 * blur_wave
            return cv2.addWeighted(img, 1.0 - alpha, blurred, alpha, 0)

        if effect_type == "径向拉伸":
            # 近似Zoom blur：多次缩放回贴并叠加
            layers = 5
            acc = img.astype(np.float32) * 0.35
            for i in range(1, layers + 1):
                t = i / layers
                s = 1.0 + (0.02 + 0.08 * intensity_scale) * t * (0.5 - 0.5 * np.cos(2 * np.pi * speed * time_sec))
                resized = cv2.resize(img, (int(w * s), int(h * s)))
                cropped = _center_crop(resized, w, h).astype(np.float32)
                acc += cropped * (0.65 / layers)
            return np.clip(acc, 0, 255).astype(np.uint8)

        if effect_type == "边缘闪烁":
            # 边缘提取 + 发光叠加
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 60, 140)
            edges = cv2.GaussianBlur(edges, (3, 3), 0)
            glow = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR).astype(np.float32)
            pulse = 0.15 + (0.45 * intensity_scale) * (0.5 - 0.5 * np.cos(2 * np.pi * 3.2 * speed * time_sec))
            frame = img.astype(np.float32)
            return np.clip(frame + glow * pulse, 0, 255).astype(np.uint8)

        if effect_type == "透视俯仰":
            # 模拟相机轻微俯仰透视
            tilt = (0.02 + 0.06 * intensity_scale) * np.sin(2 * np.pi * 0.8 * speed * time_sec)
            dx = w * tilt
            src = np.float32([[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]])
            dst = np.float32([[dx, 0], [w - 1 - dx, 0], [-dx, h - 1], [w - 1 + dx, h - 1]])
            M = cv2.getPerspectiveTransform(src, dst)
            warped = cv2.warpPerspective(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            return warped

        if effect_type == "滚动快门":
            # 按行位移模拟rolling shutter
            frame = img.copy()
            rows = np.arange(h, dtype=np.float32).reshape(-1, 1)
            phase = 2 * np.pi * (rows / max(1.0, h) * 4.0 + speed * time_sec * 2.0)
            line_shift = (3 + 10 * intensity_scale) * np.sin(phase)
            for y in range(h):
                shift = int(line_shift[y, 0])
                frame[y:y + 1, :] = np.roll(frame[y:y + 1, :], shift, axis=1)
            return frame

        if effect_type == "灵魂出窍":
            from ..core.video_effect_engine import apply_soul_out
            return apply_soul_out(img, time_sec, speed=speed, intensity=intensity_scale)

        return img
    except Exception:
        return img
