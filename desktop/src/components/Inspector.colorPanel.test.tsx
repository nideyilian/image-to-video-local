/**
 * 调色面板的结构断言。
 *
 * ## 为什么用测试而不是截图
 *
 * 这个界面跑在 Tauri 窗口里，截图有硬伤：窗口不在前台时不会重绘，
 * `PrintWindow` 抓到的是旧画面 —— 我因此误判过两次（一次看到「转场特效」页、
 * 一次看到「水印」页，都是过期内容）。而本机不允许 `Add-Type`，
 * 也就无法模拟点击把窗口切到前台。
 *
 * 所以这里直接断言渲染出来的 DOM：标签是不是成对、是不是分别落在
 * 滑杆的左右两端。这比截图可靠 —— 它检查的是「结构对不对」，
 * 不是「某一帧像素长什么样」。
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FALLBACK_CONFIG } from "../constants";
import { Inspector } from "./Inspector";

let mountedRoot: Root | null = null;
let container: HTMLDivElement | null = null;

function renderInspector() {
  const onChange = vi.fn();
  container = document.createElement("div");
  document.body.appendChild(container);
  mountedRoot = createRoot(container);
  act(() => {
    mountedRoot!.render(
      <Inspector
        config={FALLBACK_CONFIG}
        onChange={onChange}
        onBrowseDirectory={vi.fn()}
        onBrowseFile={vi.fn()}
        activeTab="motion"
        onActiveTabChange={vi.fn()}
        validationIssues={[]}
        onOpenLibraryTab={vi.fn()}
        subfolderScan={null}
        paramSchema={{}}
        onParamChange={vi.fn()}
      />,
    );
  });
  return { onChange };
}

afterEach(() => {
  act(() => mountedRoot?.unmount());
  mountedRoot = null;
  container?.remove();
  container = null;
});

describe("调色面板", () => {
  it("四个参数都是滑杆，不是数字输入框", () => {
    renderInspector();
    const sliders = [...container!.querySelectorAll<HTMLInputElement>('input[type="range"]')];
    // 调色四项 + 可能存在的其它滑杆，至少要有四个调色的
    const labels = sliders.map((slider) => slider.getAttribute("aria-label"));
    for (const name of ["亮度", "对比度", "饱和度", "色温"]) {
      expect(labels, `「${name}」应该是滑杆`).toContain(name);
    }
  });

  it("范围是 -100 到 100", () => {
    renderInspector();
    const slider = [...container!.querySelectorAll<HTMLInputElement>('input[type="range"]')].find(
      (item) => item.getAttribute("aria-label") === "亮度",
    );
    expect(slider).toBeTruthy();
    expect(slider!.min).toBe("-100");
    expect(slider!.max).toBe("100");
  });

  it("端点标签成对贴在滑杆两端，且左端是低值含义", () => {
    renderInspector();
    const expected: Array<[string, string, string]> = [
      ["亮度", "暗", "亮"],
      ["对比度", "平", "硬"],
      ["饱和度", "灰", "艳"],
      ["色温", "冷", "暖"],
    ];

    const ends = [...container!.querySelectorAll(".color-slider-ends")];
    expect(ends.length, "应该有四组端点标签").toBe(4);

    for (const [name, low, high] of expected) {
      const slider = [...container!.querySelectorAll<HTMLInputElement>('input[type="range"]')].find(
        (item) => item.getAttribute("aria-label") === name,
      );
      expect(slider, `找不到「${name}」的滑杆`).toBeTruthy();

      // 端点标签必须是这个滑杆所在 .color-slider 里的 .color-slider-ends
      const wrapper = slider!.closest(".color-slider");
      expect(wrapper, `「${name}」的滑杆应该包在 .color-slider 里`).toBeTruthy();
      const endLabels = [...wrapper!.querySelectorAll(".color-slider-ends span")].map(
        (node) => node.textContent,
      );
      expect(endLabels, `「${name}」的端点标签不对`).toEqual([low, high]);
    }
  });

  it("端点标签在 DOM 里位于滑杆之后（视觉上在下方）", () => {
    renderInspector();
    const wrapper = container!.querySelector(".color-slider");
    expect(wrapper).toBeTruthy();
    const children = [...wrapper!.children].map((node) => node.className);
    const sliderIndex = children.findIndex((name) => name.includes("range-input"));
    const endsIndex = children.findIndex((name) => name.includes("color-slider-ends"));
    expect(sliderIndex, "找不到滑杆").toBeGreaterThanOrEqual(0);
    expect(endsIndex, "找不到端点标签").toBeGreaterThan(sliderIndex);
  });

  it("值为 0 时数字弱化，调过后正常显示", () => {
    renderInspector();
    const zeros = [...container!.querySelectorAll(".color-slider-head strong.is-zero")];
    // FALLBACK_CONFIG 四个都是 0，应该全部带 is-zero
    expect(zeros.length, "四项全 0 时四个数字都该弱化").toBe(4);
  });

  it("拖动滑杆会把值传给 onChange（用对字段名）", () => {
    const { onChange } = renderInspector();
    const slider = [...container!.querySelectorAll<HTMLInputElement>('input[type="range"]')].find(
      (item) => item.getAttribute("aria-label") === "亮度",
    )!;
    // 模拟用户拖动：改 value 并触发 input/change
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setter.call(slider, "42");
    act(() => {
      slider.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(onChange, "拖动滑杆必须触发 onChange").toHaveBeenCalled();
    expect(onChange).toHaveBeenCalledWith("color_brightness", 42);
  });

  it("双击滑杆把该项单独归零", () => {
    const { onChange } = renderInspector();
    const wrapper = container!.querySelector(".color-slider")!;
    act(() => {
      wrapper.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    });
    expect(onChange).toHaveBeenCalledWith("color_brightness", 0);
  });
});