import type { VideoConfig, WatermarkLayer } from "./types";

export const RESOLUTIONS = [
  "1280x720",
  "1920x1080",
  "2560x1440",
  "3840x2160",
  "1080x1920",
  "720x1280",
  "1080x1080",
];

export const TRANSITIONS = [
  "淡入淡出", "左右滑动", "上下滑动", "交叉溶解", "缩放过渡", "圆形扩展",
  "百叶窗", "棋盘格", "像素化", "旋转变换", "波浪", "颜色混合", "方块过渡",
  "放大冲击", "缩小爆炸", "旋转放大", "弹性缩放", "3D翻转", "推入效果",
  "对角擦除", "门式打开", "闪光过渡", "碎片飞散", "光晕扩散", "径向旋切",
  "漩涡扭曲", "菱形开幕", "镜头虚焦", "纵向拉幕", "横向拉幕", "液态融合",
  "流光擦拭", "时钟扫描",
];

export const VIDEO_EFFECTS = [
  "心跳跳动", "反复缩放", "轻微摇摆", "左右晃动", "上下浮动", "镜头呼吸",
  "脉冲放大", "旋转摆动", "旋转呼吸", "摇摆推拉", "圆周漂移", "螺旋摆动",
  "双轴呼吸", "心跳摇摆", "波浪平移", "8字漂移", "径向脉冲旋转",
  "镜头抖动呼吸", "反向双旋", "呼吸变焦扫光", "旋摆模糊脉冲", "透视呼吸摆动",
  "涡旋推拉", "变焦摇移", "旋转漂移闪动", "双频摆动", "环形巡航",
  "呼吸鱼眼旋摆", "水波扭曲", "漩涡旋转", "鱼眼镜头", "故障抖动",
  "镜像扫光", "呼吸模糊", "径向拉伸", "边缘闪烁", "透视俯仰", "滚动快门",
  "灵魂出窍",
];

export const BLEND_MODES = ["正常", "滤色", "叠加", "正片叠底", "变亮", "变暗", "相加"];
export const WATERMARK_POSITIONS = ["左上", "右上", "左下", "右下", "中心"];
export const WATERMARK_SIZE_MODES = ["固定比例", "自适应覆盖", "完全覆盖"];

export const DEFAULT_WATERMARK_LAYER: WatermarkLayer = {
  enabled: true,
  path: "",
  position: "中心",
  fixed: false,
  folder_random_single: false,
  size_mode: "自适应覆盖",
  scale: 100,
  blend_mode: "正常",
  opacity: 1,
};

export const FALLBACK_CONFIG: VideoConfig = {
  input_dir: "",
  output_dir: "",
  num_images: 1,
  duration: 8,
  total_duration: 0,
  fps: 30,
  video_count: 1,
  video_format: "mp4",
  resolution_preset: "1280x720",
  resolution_presets: RESOLUTIONS,
  keep_aspect_ratio: true,
  use_transition: true,
  transition_type: TRANSITIONS[0],
  random_transition: false,
  enabled_transitions: [...TRANSITIONS],
  use_video_effect: false,
  video_effect_type: "无特效",
  random_video_effect: false,
  enabled_video_effects: [...VIDEO_EFFECTS],
  video_effect_intensity: 100,
  video_effect_speed: 1.3,
  use_bgm: false,
  bgm_dir: "",
  random_bgm: false,
  bgm_volume: 0.5,
  loop_bgm: false,
  codec: "H264",
  use_watermark: false,
  watermark_type: "视频",
  watermark_position: "中心",
  watermark_match_method: "循环",
  watermark_audio: "使用BGM",
  watermark_size_mode: "自适应覆盖",
  watermark_scale: 100,
  use_image_watermark: false,
  watermark_layers: [],
  watermark_mode: "单文件",
  watermark_path: "",
  watermark_blend_mode: "正常",
  use_date_prefix: true,
  use_first_image_name: false,
  custom_prefix: "video",
  image_selection_mode: "随机选择",
  bitrate: 2000,
  _qt_watermark_defaults_v2: true,
};
