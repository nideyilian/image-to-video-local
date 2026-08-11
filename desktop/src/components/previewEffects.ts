import type { CSSProperties } from "react";

export type PreviewMotion =
  | "breathe"
  | "pulse"
  | "sway"
  | "pan-x"
  | "float-y"
  | "rotate-breathe"
  | "orbit"
  | "figure-eight"
  | "shake"
  | "blur"
  | "perspective"
  | "warp"
  | "fisheye"
  | "soul";

export type PreviewEffect = {
  motion: PreviewMotion;
  overlay?: "scan" | "flash" | "edge" | "glitch";
};

export const EFFECT_PRESETS: Record<string, PreviewEffect> = {
  心跳跳动: { motion: "pulse" },
  心跳跃动: { motion: "pulse" },
  反复缩放: { motion: "breathe" },
  轻微摇摆: { motion: "sway" },
  左右晃动: { motion: "pan-x" },
  上下浮动: { motion: "float-y" },
  镜头呼吸: { motion: "breathe" },
  脉冲放大: { motion: "pulse" },
  旋转摆动: { motion: "sway" },
  旋转呼吸: { motion: "rotate-breathe" },
  摇摆推拉: { motion: "rotate-breathe" },
  圆周漂移: { motion: "orbit" },
  螺旋摆动: { motion: "rotate-breathe" },
  双轴呼吸: { motion: "breathe" },
  心跳摇摆: { motion: "pulse" },
  波浪平移: { motion: "pan-x" },
  "8字漂移": { motion: "figure-eight" },
  径向脉冲旋转: { motion: "rotate-breathe" },
  镜头抖动呼吸: { motion: "shake" },
  反向双旋: { motion: "rotate-breathe" },
  呼吸变焦扫光: { motion: "breathe", overlay: "scan" },
  旋摆模糊脉冲: { motion: "blur" },
  透视呼吸摆动: { motion: "perspective" },
  涡旋推拉: { motion: "warp" },
  变焦摇移: { motion: "figure-eight" },
  旋转漂移闪动: { motion: "figure-eight", overlay: "flash" },
  双频摆动: { motion: "sway" },
  环形巡航: { motion: "orbit" },
  呼吸鱼眼旋摆: { motion: "fisheye" },
  水波扭曲: { motion: "warp" },
  漩涡旋转: { motion: "rotate-breathe" },
  鱼眼镜头: { motion: "fisheye" },
  故障抖动: { motion: "shake", overlay: "glitch" },
  镜像扫光: { motion: "pan-x", overlay: "scan" },
  呼吸模糊: { motion: "blur" },
  径向拉伸: { motion: "fisheye" },
  边缘闪烁: { motion: "breathe", overlay: "edge" },
  透视俯仰: { motion: "perspective" },
  滚动快门: { motion: "perspective" },
  灵魂出窍: { motion: "soul" },
};

export type PreviewEffectStyle = CSSProperties & {
  "--effect-duration": string;
  "--effect-scale": number;
  "--effect-scale-low": number;
  "--effect-scale-mid": number;
  "--effect-shift": string;
  "--effect-shift-neg": string;
  "--effect-angle": string;
  "--effect-angle-neg": string;
  "--effect-blur": string;
};

export type EffectConfig = {
  use_video_effect: boolean;
  video_effect_type: string;
  random_video_effect?: boolean;
  enabled_video_effects?: string[];
};

export function previewEffectType(config: EffectConfig): string {
  if (config.random_video_effect && config.enabled_video_effects?.length) return config.enabled_video_effects[0];
  return config.video_effect_type;
}

export function isEffectEnabled(config: EffectConfig): boolean {
  return config.use_video_effect && previewEffectType(config) !== "无特效";
}

export function effectClassNameFor(config: EffectConfig): string {
  if (!isEffectEnabled(config)) return "preview-media";
  const preset = EFFECT_PRESETS[previewEffectType(config)] ?? { motion: "breathe" as const };
  return `preview-media effect-${preset.motion}${preset.overlay ? ` effect-overlay-${preset.overlay}` : ""}`;
}

export function computeEffectStyle(rawIntensity: number, rawSpeed: number): PreviewEffectStyle {
  const intensity = Math.max(0.2, Math.min(3, Number(rawIntensity || 100) / 100));
  const speed = Math.max(0.2, Math.min(5, Number(rawSpeed || 1)));
  const shift = 3 * intensity;
  const angle = 4 * intensity;
  return {
    "--effect-duration": `${Math.max(0.45, 2.4 / speed).toFixed(2)}s`,
    "--effect-scale": Number((0.07 * intensity).toFixed(3)),
    "--effect-scale-low": Number((0.03 * intensity).toFixed(3)),
    "--effect-scale-mid": Number((0.05 * intensity).toFixed(3)),
    "--effect-shift": `${shift.toFixed(2)}%`,
    "--effect-shift-neg": `${(-shift).toFixed(2)}%`,
    "--effect-angle": `${angle.toFixed(2)}deg`,
    "--effect-angle-neg": `${(-angle).toFixed(2)}deg`,
    "--effect-blur": `${(1.4 * intensity).toFixed(2)}px`,
  };
}
