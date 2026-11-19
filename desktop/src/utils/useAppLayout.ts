/**
 * 主界面窗口布局：三块可拖动分隔条 + 折叠状态 + 持久化。
 *
 * 从 `App.tsx` 抽出来的第一块 —— 它和业务逻辑完全无关，
 * 只关心「三块面板各多宽/多高、是否折叠」，改布局不会碰到队列或预览。
 */
import { useCallback, useEffect, useState, type PointerEvent as ReactPointerEvent } from "react";

const LAYOUT_KEY = "image-to-video.layout.v3";

export type LayoutState = {
  railWidth: number;
  inspectorWidth: number;
  manifestHeight: number;
  railCollapsed: boolean;
  inspectorCollapsed: boolean;
};

export type LayoutSizeKey = "railWidth" | "inspectorWidth" | "manifestHeight";

export const DEFAULT_LAYOUT: LayoutState = {
  railWidth: 216,
  inspectorWidth: 440,
  manifestHeight: 267,
  railCollapsed: false,
  inspectorCollapsed: false,
};

export const LAYOUT_LIMITS: Record<LayoutSizeKey, [number, number]> = {
  railWidth: [168, 360],
  inspectorWidth: [400, 580],
  manifestHeight: [267, 420],
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

/** 把某个尺寸夹进它的合法区间。 */
export function clampLayoutSize(key: LayoutSizeKey, value: number): number {
  const [min, max] = LAYOUT_LIMITS[key];
  return clamp(value, min, max);
}

/** 方向键微调一个尺寸，结果同样夹在区间内。 */
export function nudgeLayoutValue(key: LayoutSizeKey, current: number, delta: number): number {
  return clampLayoutSize(key, current + delta);
}

export function loadLayout(): LayoutState {
  try {
    const stored = JSON.parse(localStorage.getItem(LAYOUT_KEY) || "{}") as Partial<LayoutState>;
    return {
      railWidth: clamp(Number(stored.railWidth) || DEFAULT_LAYOUT.railWidth, ...LAYOUT_LIMITS.railWidth),
      inspectorWidth: clamp(Number(stored.inspectorWidth) || DEFAULT_LAYOUT.inspectorWidth, ...LAYOUT_LIMITS.inspectorWidth),
      manifestHeight: clamp(Number(stored.manifestHeight) || DEFAULT_LAYOUT.manifestHeight, ...LAYOUT_LIMITS.manifestHeight),
      railCollapsed: stored.railCollapsed === true,
      inspectorCollapsed: stored.inspectorCollapsed === true,
    };
  } catch {
    return DEFAULT_LAYOUT;
  }
}

export function useAppLayout() {
  const [layout, setLayout] = useState<LayoutState>(loadLayout);

  useEffect(() => {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
  }, [layout]);

  const nudgeLayout = useCallback((key: LayoutSizeKey, delta: number) => {
    setLayout((current) => ({ ...current, [key]: nudgeLayoutValue(key, current[key], delta) }));
  }, []);

  /** 拖动分隔条。方向按面板所在侧取正负，与原来的实现逐行一致。 */
  const beginLayoutResize = useCallback((key: LayoutSizeKey, event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const origin = layout[key];
    const originX = event.clientX;
    const originY = event.clientY;
    const isRow = key === "manifestHeight";
    const direction = key === "railWidth" ? 1 : -1;
    const [min, max] = LAYOUT_LIMITS[key];

    document.body.classList.add(isRow ? "is-resizing-rows" : "is-resizing-columns");

    const move = (moveEvent: PointerEvent) => {
      const pointerDelta = isRow ? moveEvent.clientY - originY : moveEvent.clientX - originX;
      setLayout((current) => ({ ...current, [key]: clamp(origin + pointerDelta * direction, min, max) }));
    };
    const stop = () => {
      document.body.classList.remove("is-resizing-rows", "is-resizing-columns");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  }, [layout]);

  const resetLayoutSize = useCallback((key: LayoutSizeKey) => {
    setLayout((current) => ({ ...current, [key]: DEFAULT_LAYOUT[key] }));
  }, []);

  const toggleRail = useCallback(() => {
    setLayout((current) => ({ ...current, railCollapsed: !current.railCollapsed }));
  }, []);

  const toggleInspector = useCallback(() => {
    setLayout((current) => ({ ...current, inspectorCollapsed: !current.inspectorCollapsed }));
  }, []);

  /** 展开检查器（例如跳转到某个校验项时要保证它可见）。 */
  const expandInspector = useCallback(() => {
    setLayout((current) => (current.inspectorCollapsed ? { ...current, inspectorCollapsed: false } : current));
  }, []);

  return {
    layout,
    setLayout,
    nudgeLayout,
    beginLayoutResize,
    resetLayoutSize,
    toggleRail,
    toggleInspector,
    expandInspector,
  };
}
