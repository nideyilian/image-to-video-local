"""渲染计划所需的共享常量与纯计算（与界面无关）。

从 ``src/gui/main_window.py`` 抽出：``VIDEO_EFFECTS`` 与 ``compute_video_frame_plan``。
两者都被 compositor / encoder / job 共用，放在底层可避免循环 import。
"""

from __future__ import annotations


VIDEO_EFFECTS = [
    "无特效",
    "心跳跳动",
    "反复缩放",
    "轻微摇摆",
    "左右晃动",
    "上下浮动",
    "镜头呼吸",
    "脉冲放大",
    "旋转摆动",
    # 新增：无限循环复合特效（20个）
    "旋转呼吸",
    "摇摆推拉",
    "圆周漂移",
    "螺旋摆动",
    "双轴呼吸",
    "心跳摇摆",
    "波浪平移",
    "8字漂移",
    "径向脉冲旋转",
    "镜头抖动呼吸",
    "反向双旋",
    "呼吸变焦扫光",
    "旋摆模糊脉冲",
    "透视呼吸摆动",
    "涡旋推拉",
    "变焦摇移",
    "旋转漂移闪动",
    "双频摆动",
    "环形巡航",
    "呼吸鱼眼旋摆",
    "水波扭曲",
    "漩涡旋转",
    "鱼眼镜头",
    "故障抖动",
    "镜像扫光",
    "呼吸模糊",
    "径向拉伸",
    "边缘闪烁",
    "透视俯仰",
    "滚动快门",
    "灵魂出窍",
]


def compute_video_frame_plan(total_images: int, duration: float, fps: int,
                             transition_frames: int = 0, transition_type: str = "无转场"):
    """按用户设置时长精确计算帧计划（三处渲染入口共用，保证输出时长严格按设置）。

    Returns:
        (frames_per_img, transition_frames, display_frames_per_img, last_img_frames)
        - frames_per_img:      每图基准总帧数（静态 + 转场）
        - transition_frames:   每段转场帧数（只减不增，不会把总时长撑大）
        - display_frames_per_img: 每图静态帧数（非最后一张）
        - last_img_frames:     最后一图应写的总帧数（吸收总时长取整的余数）

    规则：
    1. 每图帧数用 round 而非 int()，消除截断与浮点误差；
    2. 总帧数 = round(图片数 × 时长 × 帧率)，余数由最后一张吸收，
       使实际总时长与设置偏差不超过半帧；
    3. 不做"每图至少 0.5 秒静态显示"的钳制，避免每图时长 < 0.5 秒时
       视频被强制撑长。
    """
    frames_per_img = max(1, int(round(duration * fps)))
    if transition_frames > 0 and transition_type != "无转场":
        transition_frames = min(transition_frames, max(0, frames_per_img // 3))
        display_frames_per_img = max(0, frames_per_img - transition_frames)
    else:
        transition_frames = 0
        display_frames_per_img = frames_per_img
    total_frames = max(total_images, int(round(total_images * duration * fps)))
    last_img_frames = total_frames - (total_images - 1) * frames_per_img
    if last_img_frames < 1:
        last_img_frames = 1
    return frames_per_img, transition_frames, display_frames_per_img, last_img_frames
