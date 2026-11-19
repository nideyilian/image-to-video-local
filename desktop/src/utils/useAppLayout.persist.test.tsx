/**
 * 布局 hook 的写入行为：挂载后必须把当前布局写进 localStorage。
 *
 * 用真实的 React 渲染验证 —— 纯函数测试证明不了「effect 有没有跑」，
 * 而这正是搬迁 hook 时最容易漏的地方。
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_LAYOUT, useAppLayout } from "./useAppLayout";

// 告诉 React 当前处于测试环境，避免 act(...) 警告
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const LAYOUT_KEY = "image-to-video.layout.v3";

let container: HTMLDivElement | null = null;
let root: Root | null = null;

function renderProbe(): { current: ReturnType<typeof useAppLayout> | null } {
  const holder: { current: ReturnType<typeof useAppLayout> | null } = { current: null };
  function Probe() {
    holder.current = useAppLayout();
    return null;
  }
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root!.render(<Probe />));
  return holder;
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

describe("useAppLayout 持久化", () => {
  it("挂载后把默认布局写进 localStorage", () => {
    renderProbe();
    const raw = localStorage.getItem(LAYOUT_KEY);
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!)).toEqual(DEFAULT_LAYOUT);
  });

  it("改尺寸后写回新值", () => {
    const holder = renderProbe();
    act(() => holder.current!.nudgeLayout("railWidth", 8));
    const stored = JSON.parse(localStorage.getItem(LAYOUT_KEY)!);
    expect(stored.railWidth).toBe(DEFAULT_LAYOUT.railWidth + 8);
  });

  it("折叠状态也会落盘", () => {
    const holder = renderProbe();
    act(() => holder.current!.toggleRail());
    expect(JSON.parse(localStorage.getItem(LAYOUT_KEY)!).railCollapsed).toBe(true);
  });

  it("双击复位写回默认尺寸", () => {
    const holder = renderProbe();
    act(() => holder.current!.nudgeLayout("inspectorWidth", 40));
    expect(JSON.parse(localStorage.getItem(LAYOUT_KEY)!).inspectorWidth).not.toBe(DEFAULT_LAYOUT.inspectorWidth);
    act(() => holder.current!.resetLayoutSize("inspectorWidth"));
    expect(JSON.parse(localStorage.getItem(LAYOUT_KEY)!).inspectorWidth).toBe(DEFAULT_LAYOUT.inspectorWidth);
  });

  it("重新挂载时读回上次存的布局", () => {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify({ ...DEFAULT_LAYOUT, railWidth: 300 }));
    const holder = renderProbe();
    expect(holder.current!.layout.railWidth).toBe(300);
  });
});
