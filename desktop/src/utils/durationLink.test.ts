import { describe, expect, it } from "vitest";
import { FALLBACK_CONFIG, SUBFOLDER_SELECTION_MODE } from "../constants";
import type { SubfolderScan, VideoConfig } from "../types";
import { applyDurationLink, imagesPerVideo, manualDurationPatch, perImageDuration } from "./durationLink";

function configWith(patch: Partial<VideoConfig>): VideoConfig {
  return { ...structuredClone(FALLBACK_CONFIG), ...patch };
}

function scanWith(...counts: number[]): SubfolderScan {
  return {
    count: counts.reduce((sum, value) => sum + value, 0),
    groups: counts.map((count, index) => ({
      name: String(index + 1),
      count,
      firstPath: `D:\\素材\\${index + 1}\\01.png`,
      firstName: "01.png",
    })),
    skipped: [],
    combinationTotal: counts.reduce((product, value) => product * value, 1),
  };
}

describe("imagesPerVideo", () => {
  it("子文件夹模式下由子文件夹个数决定，与「图片数」无关", () => {
    const config = configWith({ image_selection_mode: SUBFOLDER_SELECTION_MODE, num_images: 50 });
    expect(imagesPerVideo(config, scanWith(5, 3, 2))).toBe(3);
  });

  it("尚未扫描时返回 0，避免算出错误时长", () => {
    const config = configWith({ image_selection_mode: SUBFOLDER_SELECTION_MODE, num_images: 50 });
    expect(imagesPerVideo(config, null)).toBe(0);
  });

  it("其它模式使用「图片数」", () => {
    expect(imagesPerVideo(configWith({ image_selection_mode: "随机选择", num_images: 6 }), scanWith(5, 3, 2))).toBe(6);
    expect(imagesPerVideo(configWith({ image_selection_mode: "按名称排序", num_images: 0 }), null)).toBe(0);
  });
});

describe("perImageDuration", () => {
  it("总时长能整除时得到整数", () => {
    expect(perImageDuration(9, 3)).toBe(3);
  });

  it("除不尽时保留 4 位小数（后端 1e-3 容差内可回算槽位数）", () => {
    expect(perImageDuration(10, 3)).toBe(3.3333);
    const duration = perImageDuration(10, 3) as number;
    expect(Math.abs(10 / duration - 3)).toBeLessThan(1e-3);
  });

  it("总时长或图片数无效时不给出结果", () => {
    expect(perImageDuration(0, 3)).toBeNull();
    expect(perImageDuration(9, 0)).toBeNull();
  });
});

describe("applyDurationLink", () => {
  it("填入总时长后自动算出单图时长", () => {
    const config = configWith({ image_selection_mode: SUBFOLDER_SELECTION_MODE, total_duration: 9, duration: 8 });
    expect(applyDurationLink(config, scanWith(5, 3, 2))).toEqual({ duration: 3, changed: true });
  });

  it("总时长为 0（自动）时不动手填的单图时长", () => {
    const config = configWith({ image_selection_mode: "随机选择", total_duration: 0, duration: 8 });
    expect(applyDurationLink(config, null)).toEqual({ duration: 8, changed: false });
  });

  it("图片数变化后同步重算（6 张 → 3 张，单图时长翻倍）", () => {
    const base = { image_selection_mode: "随机选择", total_duration: 12, duration: 2 };
    expect(applyDurationLink(configWith({ ...base, num_images: 6 }), null).duration).toBe(2);
    expect(applyDurationLink(configWith({ ...base, num_images: 3 }), null).duration).toBe(4);
  });

  it("子文件夹个数变化后同步重算", () => {
    const config = configWith({ image_selection_mode: SUBFOLDER_SELECTION_MODE, total_duration: 12, duration: 4 });
    expect(applyDurationLink(config, scanWith(5, 3, 2)).duration).toBe(4);
    expect(applyDurationLink(config, scanWith(5, 3, 2, 1, 1, 1)).duration).toBe(2);
  });

  it("子文件夹模式下扫描未完成时保持原值，不把时长算成 0", () => {
    const config = configWith({ image_selection_mode: SUBFOLDER_SELECTION_MODE, total_duration: 9, duration: 8 });
    expect(applyDurationLink(config, null)).toEqual({ duration: 8, changed: false });
  });
});

describe("manualDurationPatch", () => {
  it("手改单图时长时把总时长归零，两者不互相打回", () => {
    expect(manualDurationPatch()).toEqual({ total_duration: 0 });
  });
});
