import { SUBFOLDER_SELECTION_MODE } from "../constants";
import type { SubfolderScan, VideoConfig } from "../types";

/**
 * 每个视频实际使用的图片张数。
 * 「按子文件夹抽取」下一个子文件夹出一张，因此由子文件夹个数决定；其余模式取「图片数」。
 */
export function imagesPerVideo(config: VideoConfig, scan: SubfolderScan | null | undefined): number {
  if (config.image_selection_mode === SUBFOLDER_SELECTION_MODE) {
    return scan?.groups.length ?? 0;
  }
  const value = Math.trunc(Number(config.num_images) || 0);
  return value > 0 ? value : 0;
}

/**
 * 总时长 ÷ 每视频图片数，保留 4 位小数。
 * 保留位数与后端 `timeline_slot_count` 的 1e-3 容差配套：回算槽位数时不会被
 * 舍入误差判成「不是整数倍」。
 */
export function perImageDuration(totalDuration: number, count: number): number | null {
  const total = Number(totalDuration) || 0;
  if (total <= 0 || count <= 0) return null;
  return Math.round((total / count) * 10_000) / 10_000;
}

export type DurationLinkResult = {
  /** 联动后应当写入的单图时长。 */
  duration: number;
  /** 是否真的产生了变化（false 时调用方可原样保留）。 */
  changed: boolean;
};

/**
 * 「总时长 → 单图时长」联动。
 *
 * 总时长大于 0 时由系统接管单图时长，等于 总时长 ÷ 每视频图片数；
 * 总时长为 0（自动）时不动用户手填的单图时长。
 * 图片数变化后（改图片数、切换选图方式、重新扫描目录）再次调用即可同步结果。
 */
export function applyDurationLink(
  config: VideoConfig,
  scan: SubfolderScan | null | undefined,
): DurationLinkResult {
  const linked = perImageDuration(Number(config.total_duration) || 0, imagesPerVideo(config, scan));
  if (linked === null || linked === config.duration) {
    return { duration: config.duration, changed: false };
  }
  return { duration: linked, changed: true };
}

/**
 * 用户手改「单图时长」时的处理：总时长与单图时长不能同时生效，
 * 手改单图时长即表示放弃总时长，因此把总时长归零（回到自动）。
 */
export function manualDurationPatch(): { total_duration: number } {
  return { total_duration: 0 };
}
