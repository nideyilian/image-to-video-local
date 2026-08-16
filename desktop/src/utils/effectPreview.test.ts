import { describe, expect, it } from "vitest";
import { quantizeEffectPreviewTime } from "../components/useEngineEffectPreview";

describe("quantizeEffectPreviewTime", () => {
  it("按帧率量化时间", () => {
    expect(quantizeEffectPreviewTime(0.1, 1, 10)).toBe(0.1);
    expect(quantizeEffectPreviewTime(0.104, 1, 10)).toBe(0.1);
    expect(quantizeEffectPreviewTime(0.106, 1, 10)).toBe(0.1);
  });

  it("超过时长自动回绕", () => {
    expect(quantizeEffectPreviewTime(1.1, 1, 10)).toBe(0.1);
    expect(quantizeEffectPreviewTime(2.5, 2, 30)).toBe(0.5);
  });

  it("负时间回绕", () => {
    expect(quantizeEffectPreviewTime(-0.1, 1, 10)).toBe(0.9);
  });

  it("非法输入回落安全值", () => {
    // duration/fps 非法时回落到 0.1s/1fps；0.5 是 0.1 的整数倍 → 第 0 帧
    expect(quantizeEffectPreviewTime(0.5, 0, 0)).toBe(0);
    expect(quantizeEffectPreviewTime(0.5, -1, -1)).toBe(0);
  });
});
