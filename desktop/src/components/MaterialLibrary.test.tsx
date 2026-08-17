/**
 * 素材库「从剪映导入」回归测试。
 *
 * 背景：`importJianying` 的 useCallback 依赖数组缺少 `jianying.source` 与
 * `jianying.cacheResult`，导致切到「内置资源（缓存）」扫描完成后，按钮回调仍
 * 持有旧的 `cacheResult: null`，点击「导入 BGM / 导入水印库」静默无反应。
 * 本用例覆盖：导入真正触发 engine 调用，且给出进行中与结果反馈。
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FALLBACK_CONFIG } from "../constants";
import type { LibraryImportResult } from "../types";
import { MaterialLibrary } from "./MaterialLibrary";

vi.mock("../engine", () => ({
  engine: {
    desktopRuntime: true,
    call: vi.fn(),
    subscribe: vi.fn(() => () => {}),
    toAssetUrl: (path: string) => path,
  },
}));

import { engine } from "../engine";

const callMock = vi.mocked(engine.call);

const CACHE_AUDIOS = [
  { path: "C:/JianyingPro/User Data/Cache/audio/1.mp3", name: "轻快纯音乐", draft: "" },
  { path: "C:/JianyingPro/User Data/Cache/audio/2.mp3", name: "氛围音效", draft: "" },
];
const CACHE_VIDEOS = [
  { path: "C:/JianyingPro/User Data/Cache/video/v1.mp4", name: "粒子特效", draft: "" },
];
const DRAFT_AUDIOS = [{ path: "C:/drafts/d1/audio/a1.mp3", name: "草稿BGM", draft: "草稿一" }];
const DRAFT_VIDEOS = [{ path: "C:/drafts/d1/video/v1.mp4", name: "视频一", draft: "草稿一" }];
const DRAFT_IMAGES = [{ path: "C:/drafts/d1/image/i1.png", name: "图片一", draft: "草稿一" }];
const DRAFT_EFFECTS = [{ path: "C:/drafts/d1/effect/e1.mp4", name: "特效一", draft: "草稿一" }];
const DRAFT_TRANSITIONS = [{ path: "C:/drafts/d1/transition/t1.mp4", name: "转场一", draft: "草稿一" }];

function baseImplementation(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
  switch (method) {
    case "library_dirs":
      return Promise.resolve({ library_root: "C:/lib", bgm_dir: "C:/lib/BGM", watermark_dir: "C:/lib/Watermark" });
    case "library_snapshot":
      return Promise.resolve({
        library_root: "C:/lib",
        bgm_dir: "C:/lib/BGM",
        watermark_dir: "C:/lib/Watermark",
        bgm: [],
        bgm_folders: [],
        watermark: [],
        watermark_folders: [],
      });
    case "jianying_cache_scan":
      return Promise.resolve({
        cache_root: "C:/JianyingPro/User Data/Cache",
        audios: CACHE_AUDIOS,
        videos: CACHE_VIDEOS,
        scanned_files: 4,
        truncated: false,
      });
    case "jianying_scan":
      return Promise.resolve({
        draft_root: "C:/drafts",
        drafts: [],
        audios: DRAFT_AUDIOS,
        videos: DRAFT_VIDEOS,
        images: DRAFT_IMAGES,
        effects: DRAFT_EFFECTS,
        transitions: DRAFT_TRANSITIONS,
      });
    case "library_import": {
      const paths = (params.paths as string[] | undefined) ?? [];
      return Promise.resolve({
        results: paths.map((path): LibraryImportResult => ({ name: path.split(/[\\/]/).pop() ?? path, path, status: "imported" })),
      });
    }
    default:
      return Promise.resolve({});
  }
}

let mountedRoot: Root | null = null;

function renderLibrary() {
  const notify = vi.fn();
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoot = root;
  act(() => {
    root.render(
      <MaterialLibrary
        open
        onClose={vi.fn()}
        config={FALLBACK_CONFIG}
        onChange={vi.fn()}
        notify={notify}
        onReveal={vi.fn()}
        onExtractBusyChange={vi.fn()}
      />,
    );
  });
  return { notify };
}

function buttonWithText(text: string): HTMLButtonElement | null {
  return [...document.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.includes(text)) ?? null;
}

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function importCalls() {
  return callMock.mock.calls.filter(([method]) => method === "library_import");
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  callMock.mockReset();
  callMock.mockImplementation(baseImplementation);
});

afterEach(() => {
  act(() => {
    mountedRoot?.unmount();
    mountedRoot = null;
  });
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

describe("从剪映导入 - 内置资源（缓存）", () => {
  it("点击「导入 BGM」真正发起导入，并有进行中与结果反馈", async () => {
    const { notify } = renderLibrary();
    await flush();

    // 打开「从剪映导入」对话框，切到「内置资源（缓存）」
    act(() => {
      buttonWithText("从剪映导入")!.click();
    });
    await flush();
    act(() => {
      buttonWithText("内置资源")!.click();
    });
    await flush();

    const importBgm = buttonWithText("导入 BGM");
    expect(importBgm).toBeTruthy();
    expect(importBgm!.textContent).toContain("2");
    expect(importBgm!.disabled).toBe(false);

    // 让「导入 BGM」挂起，以便观察进行中反馈（须在扫描完成后注册，避免被扫描调用消耗）
    let releaseImport: ((value: unknown) => void) | null = null;
    callMock.mockImplementationOnce((method, params = {}) => {
      if (method === "library_import") {
        return new Promise((resolve) => {
          releaseImport = resolve;
        });
      }
      return baseImplementation(method, params);
    });

    // 点击导入：任务挂起期间应显示进行中反馈
    act(() => {
      importBgm!.click();
    });
    await flush();
    const busyLine = document.querySelector(".library-jianying-busy");
    expect(busyLine).toBeTruthy();
    expect(busyLine!.textContent).toContain("正在导入 BGM");

    // 引擎返回 2 条导入成功
    await act(async () => {
      releaseImport!({
        results: [
          { name: "1.mp3", path: CACHE_AUDIOS[0].path, status: "imported" },
          { name: "2.mp3", path: CACHE_AUDIOS[1].path, status: "imported" },
        ],
      });
    });
    await flush();

    // 真正发起了 library_import（修复前这里没有任何调用）
    const calls = importCalls();
    expect(calls).toHaveLength(1);
    expect(calls[0][1]).toMatchObject({ kind: "bgm" });
    expect((calls[0][1] as { paths: string[] }).paths).toEqual(CACHE_AUDIOS.map((entry) => entry.path));

    // 反馈：toast + 对话框内汇总，进行中提示消失
    expect(notify).toHaveBeenCalledWith("success", "已从剪映导入 2 条 BGM");
    const summary = document.querySelector(".library-jianying-summary");
    expect(summary).toBeTruthy();
    expect(summary!.textContent).toContain("已从剪映导入 2 条 BGM");
    expect(summary!.classList.contains("is-success")).toBe(true);
    expect(document.querySelector(".library-jianying-busy")).toBeNull();
  });

  it("点击「导入水印库」把内置视频资源导入水印库", async () => {
    const { notify } = renderLibrary();
    await flush();
    act(() => {
      buttonWithText("从剪映导入")!.click();
    });
    await flush();
    act(() => {
      buttonWithText("内置资源")!.click();
    });
    await flush();

    const importWatermark = buttonWithText("导入水印库");
    expect(importWatermark).toBeTruthy();
    expect(importWatermark!.textContent).toContain("1");
    expect(importWatermark!.disabled).toBe(false);

    act(() => {
      importWatermark!.click();
    });
    await flush();

    const calls = importCalls();
    expect(calls).toHaveLength(1);
    expect(calls[0][1]).toMatchObject({ kind: "watermark" });
    expect((calls[0][1] as { paths: string[] }).paths).toEqual([CACHE_VIDEOS[0].path]);
    expect(notify).toHaveBeenCalledWith("success", "已从剪映导入 1 个素材到水印库");
  });
});

describe("从剪映导入 - 草稿素材", () => {
  it("「导入水印库」汇总视频/图片/特效/转场资源", async () => {
    const { notify } = renderLibrary();
    await flush();
    act(() => {
      buttonWithText("从剪映导入")!.click();
    });
    await flush();

    // 默认来源即为「草稿素材」
    const importWatermark = buttonWithText("导入水印库");
    expect(importWatermark).toBeTruthy();
    expect(importWatermark!.textContent).toContain("4");
    expect(importWatermark!.disabled).toBe(false);

    act(() => {
      importWatermark!.click();
    });
    await flush();

    const calls = importCalls();
    expect(calls).toHaveLength(1);
    expect(calls[0][1]).toMatchObject({ kind: "watermark" });
    expect((calls[0][1] as { paths: string[] }).paths).toEqual([
      DRAFT_VIDEOS[0].path,
      DRAFT_IMAGES[0].path,
      DRAFT_EFFECTS[0].path,
      DRAFT_TRANSITIONS[0].path,
    ]);
    expect(notify).toHaveBeenCalledWith("success", "已从剪映导入 4 个素材到水印库");
  });

  it("「导入 BGM」导入草稿音频", async () => {
    const { notify } = renderLibrary();
    await flush();
    act(() => {
      buttonWithText("从剪映导入")!.click();
    });
    await flush();

    const importBgm = buttonWithText("导入 BGM");
    expect(importBgm!.disabled).toBe(false);
    act(() => {
      importBgm!.click();
    });
    await flush();

    const calls = importCalls();
    expect(calls).toHaveLength(1);
    expect(calls[0][1]).toMatchObject({ kind: "bgm" });
    expect((calls[0][1] as { paths: string[] }).paths).toEqual([DRAFT_AUDIOS[0].path]);
    expect(notify).toHaveBeenCalledWith("success", "已从剪映导入 1 条 BGM");
  });
});
