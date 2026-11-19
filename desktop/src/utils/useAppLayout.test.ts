/**
 * 窗口布局回归测试：拆分 hook 前先把现有行为钉住。
 *
 * 这些用例只覆盖「纯逻辑」部分（尺寸夹取、持久化格式、拖动方向），
 * 不涉及 DOM 渲染 —— 拆分时界面一行都不该变。
 */
import { describe, expect, it } from "vitest";
import {
  DEFAULT_LAYOUT,
  LAYOUT_LIMITS,
  clampLayoutSize,
  loadLayout,
  nudgeLayoutValue,
} from "./useAppLayout";

describe("clampLayoutSize", () => {
  it("超出上下限时夹到边界", () => {
    expect(clampLayoutSize("railWidth", 100)).toBe(LAYOUT_LIMITS.railWidth[0]);
    expect(clampLayoutSize("railWidth", 9999)).toBe(LAYOUT_LIMITS.railWidth[1]);
    expect(clampLayoutSize("inspectorWidth", 0)).toBe(LAYOUT_LIMITS.inspectorWidth[0]);
    expect(clampLayoutSize("manifestHeight", 99999)).toBe(LAYOUT_LIMITS.manifestHeight[1]);
  });

  it("区间内的值原样返回", () => {
    expect(clampLayoutSize("railWidth", 220)).toBe(220);
    expect(clampLayoutSize("inspectorWidth", 450)).toBe(450);
  });
});

describe("nudgeLayoutValue", () => {
  it("在边界处不会越界", () => {
    const [min, max] = LAYOUT_LIMITS.railWidth;
    expect(nudgeLayoutValue("railWidth", min, -8)).toBe(min);
    expect(nudgeLayoutValue("railWidth", max, 8)).toBe(max);
  });

  it("正常加减", () => {
    expect(nudgeLayoutValue("railWidth", 200, 8)).toBe(208);
    expect(nudgeLayoutValue("railWidth", 200, -8)).toBe(192);
  });
});

describe("loadLayout", () => {
  it("没有存储时返回默认值", () => {
    localStorage.clear();
    expect(loadLayout()).toEqual(DEFAULT_LAYOUT);
  });

  it("损坏的 JSON 不会抛错，回退默认值", () => {
    localStorage.setItem("image-to-video.layout.v3", "{不是合法json");
    expect(loadLayout()).toEqual(DEFAULT_LAYOUT);
    localStorage.clear();
  });

  it("越界的存储值会被夹回合法区间", () => {
    localStorage.setItem(
      "image-to-video.layout.v3",
      JSON.stringify({ railWidth: 20, inspectorWidth: 9999, manifestHeight: 1 }),
    );
    const layout = loadLayout();
    expect(layout.railWidth).toBe(LAYOUT_LIMITS.railWidth[0]);
    expect(layout.inspectorWidth).toBe(LAYOUT_LIMITS.inspectorWidth[1]);
    expect(layout.manifestHeight).toBe(LAYOUT_LIMITS.manifestHeight[0]);
    localStorage.clear();
  });

  it("折叠标志只认布尔 true", () => {
    localStorage.setItem(
      "image-to-video.layout.v3",
      JSON.stringify({ railCollapsed: "true", inspectorCollapsed: true }),
    );
    const layout = loadLayout();
    expect(layout.railCollapsed).toBe(false);
    expect(layout.inspectorCollapsed).toBe(true);
    localStorage.clear();
  });
});
