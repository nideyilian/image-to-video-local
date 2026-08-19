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

vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: vi.fn(),
}));

import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { engine } from "../engine";

const callMock = vi.mocked(engine.call);
const openDialogMock = vi.mocked(openDialog);

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
    case "library_preview_video":
      return Promise.resolve({ preview_path: "C:/tmp/video-preview.mp4", transcoded: true });
    case "library_remove_batch": {
      const paths = (params.paths as string[] | undefined) ?? [];
      return Promise.resolve({
        results: paths.map((path) => ({ name: path.split(/[\\/]/).pop() ?? path, path, status: "removed" })),
      });
    }
    case "library_rename":
      return Promise.resolve({ renamed: true, name: String(params.new_name ?? ""), path: String(params.path ?? "") });
    case "library_get_tags":
      return Promise.resolve({ tags: [] });
    case "library_smart_folders_list":
      return Promise.resolve({ folders: [] });
    case "library_set_metadata":
      return Promise.resolve({
        path: String(params.path ?? ""),
        tags: Array.isArray(params.tags) ? params.tags : [],
        starred: Boolean(params.starred),
        note: String(params.note ?? ""),
      });
    case "library_find_duplicates":
      return Promise.resolve({ groups: [], scanned: 0 });
    case "library_rename_batch":
      return Promise.resolve({ results: [], pattern: String(params.pattern ?? "") });
    case "library_smart_folders_save":
      return Promise.resolve({ folders: Array.isArray(params.folders) ? params.folders : [] });
    default:
      return Promise.resolve({});
  }
}

let mountedRoot: Root | null = null;

function renderLibrary(initialOpen = true) {
  const notify = vi.fn();
  const onChange = vi.fn();
  const onClose = vi.fn();
  const onReveal = vi.fn();
  const onExtractBusyChange = vi.fn();
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoot = root;
  const render = (open: boolean) => {
    act(() => {
      root.render(
        <MaterialLibrary
          open={open}
          onClose={onClose}
          config={FALLBACK_CONFIG}
          onChange={onChange}
          notify={notify}
          onReveal={onReveal}
          onExtractBusyChange={onExtractBusyChange}
        />,
      );
    });
  };
  render(initialOpen);
  return { notify, onClose, rerender: render };
}

function buttonWithText(text: string): HTMLButtonElement | null {
  return [...document.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.includes(text)) ?? null;
}

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function importCalls() {
  return callMock.mock.calls.filter(([method]) => method === "library_import");
}

function snapshotCalls() {
  return callMock.mock.calls.filter(([method]) => method === "library_snapshot");
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  // jsdom 未实现媒体元素的 play/pause，桩掉以免触发 “Not implemented” 噪音
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  callMock.mockReset();
  callMock.mockImplementation(baseImplementation);
  openDialogMock.mockReset();
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

describe("素材库快照缓存", () => {
  it("首次打开扫描一次，关闭后再打开直接复用快照，不再重复扫描", async () => {
    const { rerender } = renderLibrary();
    await flush();
    expect(snapshotCalls()).toHaveLength(1);

    // 关闭后重新打开：不应再次发起 library_snapshot
    rerender(false);
    await flush();
    rerender(true);
    await flush();
    expect(snapshotCalls()).toHaveLength(1);
  });
});

describe("视频水印放大预览", () => {
  it("竖屏视频预览弹出竖板播放器，而非固定横板", async () => {
    // 让快照返回一个竖屏水印视频
    callMock.mockImplementation((method, params = {}) => {
      if (method === "library_snapshot") {
        return Promise.resolve({
          library_root: "C:/lib",
          bgm_dir: "C:/lib/BGM",
          watermark_dir: "C:/lib/Watermark",
          bgm: [],
          bgm_folders: [],
          watermark: [{ name: "竖屏水印.mp4", path: "C:/lib/Watermark/portrait.mp4", folder: "", type: "video", size_bytes: 1024, duration: 3, added_at: "2026-08-17T00:00:00Z", duplicate_key: "abc" }],
          watermark_folders: [],
        });
      }
      return baseImplementation(method, params);
    });

    renderLibrary();
    await flush();

    // 切到水印库标签
    act(() => {
      buttonWithText("水印库")!.click();
    });
    await flush();

    // 点击缩略图上的播放按钮
    const playButton = document.querySelector<HTMLButtonElement>(".library-thumb-play");
    expect(playButton).toBeTruthy();
    act(() => {
      playButton!.click();
    });
    await flush();

    // 播放器已出现，且此刻元数据未就绪（默认横板 + 隐藏画面）
    expect(callMock.mock.calls.some(([method]) => method === "library_preview_video")).toBe(true);
    const player = document.querySelector(".library-video-player");
    expect(player).toBeTruthy();
    expect(player!.classList.contains("is-portrait")).toBe(false);

    // 模拟元数据加载：1080×1920 竖屏 → 变为竖板
    const video = document.querySelector<HTMLVideoElement>("video");
    expect(video).toBeTruthy();
    Object.defineProperty(video, "videoWidth", { value: 1080, configurable: true });
    Object.defineProperty(video, "videoHeight", { value: 1920, configurable: true });
    await act(async () => {
      video!.dispatchEvent(new Event("loadedmetadata", { bubbles: false }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(player!.classList.contains("is-portrait")).toBe(true);
    expect(document.querySelector(".library-video-player-loading")).toBeNull();
  });

  it("横屏视频预览保持横板播放器", async () => {
    callMock.mockImplementation((method, params = {}) => {
      if (method === "library_snapshot") {
        return Promise.resolve({
          library_root: "C:/lib",
          bgm_dir: "C:/lib/BGM",
          watermark_dir: "C:/lib/Watermark",
          bgm: [],
          bgm_folders: [],
          watermark: [{ name: "横屏水印.mp4", path: "C:/lib/Watermark/landscape.mp4", folder: "", type: "video", size_bytes: 1024, duration: 3, added_at: "2026-08-17T00:00:00Z", duplicate_key: "abc" }],
          watermark_folders: [],
        });
      }
      return baseImplementation(method, params);
    });

    renderLibrary();
    await flush();
    act(() => {
      buttonWithText("水印库")!.click();
    });
    await flush();
    act(() => {
      document.querySelector<HTMLButtonElement>(".library-thumb-play")!.click();
    });
    await flush();

    const video = document.querySelector<HTMLVideoElement>("video");
    Object.defineProperty(video, "videoWidth", { value: 1920, configurable: true });
    Object.defineProperty(video, "videoHeight", { value: 1080, configurable: true });
    await act(async () => {
      video!.dispatchEvent(new Event("loadedmetadata", { bubbles: false }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(document.querySelector(".library-video-player")!.classList.contains("is-portrait")).toBe(false);
  });

  it("点击视频预览空白处只关闭预览，不关闭素材库", async () => {
    callMock.mockImplementation((method, params = {}) => {
      if (method === "library_snapshot") {
        return Promise.resolve({
          library_root: "C:/lib",
          bgm_dir: "C:/lib/BGM",
          watermark_dir: "C:/lib/Watermark",
          bgm: [],
          bgm_folders: [],
          watermark: [{ name: "横屏水印.mp4", path: "C:/lib/Watermark/landscape.mp4", folder: "", type: "video", size_bytes: 1024, duration: 3, added_at: "2026-08-17T00:00:00Z", duplicate_key: "abc" }],
          watermark_folders: [],
        });
      }
      return baseImplementation(method, params);
    });

    const { onClose } = renderLibrary();
    await flush();
    act(() => {
      buttonWithText("水印库")!.click();
    });
    await flush();
    act(() => {
      document.querySelector<HTMLButtonElement>(".library-thumb-play")!.click();
    });
    await flush();

    // 预览已打开
    expect(document.querySelector(".library-video-player")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();

    // 点击空白处（backdrop）
    const backdrop = document.querySelector<HTMLElement>(".library-video-backdrop");
    expect(backdrop).toBeTruthy();
    act(() => {
      backdrop!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    await flush();

    // 只关闭了预览，素材库仍在（修复前此处会冒泡到主 backdrop 触发 onClose）
    expect(document.querySelector(".library-video-player")).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("删除确认与图片预览", () => {
  function mockWatermarkSnapshot(type: "image" | "video", name: string) {
    callMock.mockImplementation((method, params = {}) => {
      if (method === "library_snapshot") {
        return Promise.resolve({
          library_root: "C:/lib",
          bgm_dir: "C:/lib/BGM",
          watermark_dir: "C:/lib/Watermark",
          bgm: [],
          bgm_folders: [],
          watermark: [{ name, path: `C:/lib/Watermark/${name}`, folder: "", type, size_bytes: 1024, duration: type === "video" ? 3 : null, added_at: "2026-08-17T00:00:00Z", duplicate_key: "abc" }],
          watermark_folders: [],
        });
      }
      return baseImplementation(method, params);
    });
  }

  it("删除素材需确认，确认后才移入回收站", async () => {
    mockWatermarkSnapshot("image", "logo.png");
    const { notify } = renderLibrary();
    await flush();
    act(() => {
      buttonWithText("水印库")!.click();
    });
    await flush();

    // 点击行内删除按钮 → 出现确认弹窗，尚未真正删除
    const deleteButton = document.querySelector<HTMLButtonElement>("button[aria-label='删除 logo.png']");
    expect(deleteButton).toBeTruthy();
    act(() => {
      deleteButton!.click();
    });
    await flush();

    const confirmDialog = document.querySelector(".library-confirm-dialog");
    expect(confirmDialog).toBeTruthy();
    expect(confirmDialog!.textContent).toContain("确定删除「logo.png」");
    expect(callMock.mock.calls.some(([method]) => method === "library_remove_batch")).toBe(false);

    // 点击「移入回收站」
    const confirmButton = [...confirmDialog!.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.includes("移入回收站"));
    expect(confirmButton).toBeTruthy();
    act(() => {
      confirmButton!.click();
    });
    await flush();

    const removeCalls = callMock.mock.calls.filter(([method]) => method === "library_remove_batch");
    expect(removeCalls).toHaveLength(1);
    expect(removeCalls[0][1]).toMatchObject({ kind: "watermark", paths: ["C:/lib/Watermark/logo.png"] });
    expect(document.querySelector(".library-confirm-dialog")).toBeNull();
    expect(notify).toHaveBeenCalledWith("success", "已把 1 个素材移入回收站");
  });

  it("取消确认时不删除", async () => {
    mockWatermarkSnapshot("image", "logo.png");
    renderLibrary();
    await flush();
    act(() => {
      buttonWithText("水印库")!.click();
    });
    await flush();

    act(() => {
      document.querySelector<HTMLButtonElement>("button[aria-label='删除 logo.png']")!.click();
    });
    await flush();
    expect(document.querySelector(".library-confirm-dialog")).toBeTruthy();

    // 点击取消
    const cancelButton = [...document.querySelector(".library-confirm-dialog")!.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.includes("取消"));
    act(() => {
      cancelButton!.click();
    });
    await flush();

    expect(document.querySelector(".library-confirm-dialog")).toBeNull();
    expect(callMock.mock.calls.some(([method]) => method === "library_remove_batch")).toBe(false);
  });

  it("图片水印点击缩略图弹出放大预览", async () => {
    mockWatermarkSnapshot("image", "logo.png");
    renderLibrary();
    await flush();
    act(() => {
      buttonWithText("水印库")!.click();
    });
    await flush();

    const thumb = document.querySelector<HTMLButtonElement>(".library-thumb-play");
    expect(thumb).toBeTruthy();
    act(() => {
      thumb!.click();
    });
    await flush();

    const img = document.querySelector<HTMLImageElement>(".library-image-player-media");
    expect(img).toBeTruthy();
    expect(img!.getAttribute("src")).toContain("logo.png");
  });
});

describe("重命名 / 类型筛选 / 搜索增强", () => {
  function mockWatermarkItems(items: Array<{ name: string; folder: string; type: "image" | "video" }>) {
    callMock.mockImplementation((method, params = {}) => {
      if (method === "library_snapshot") {
        return Promise.resolve({
          library_root: "C:/lib",
          bgm_dir: "C:/lib/BGM",
          watermark_dir: "C:/lib/Watermark",
          bgm: [],
          bgm_folders: [],
          watermark: items.map((item) => ({ ...item, path: `C:/lib/Watermark/${item.name}`, size_bytes: 1024, duration: item.type === "video" ? 3 : null, added_at: "2026-08-17T00:00:00Z", duplicate_key: "abc" })),
          watermark_folders: [],
        });
      }
      return baseImplementation(method, params);
    });
  }

  it("重命名素材：弹窗输入新名，调用 library_rename 且保留扩展名", async () => {
    mockWatermarkItems([{ name: "logo.png", folder: "", type: "image" }]);
    renderLibrary();
    await flush();
    act(() => {
      buttonWithText("水印库")!.click();
    });
    await flush();

    // 点击重命名按钮 → 弹窗出现，输入框预填去除扩展名的名称
    act(() => {
      document.querySelector<HTMLButtonElement>("button[aria-label='重命名 logo.png']")!.click();
    });
    await flush();
    const dialog = document.querySelector(".library-confirm-dialog");
    expect(dialog).toBeTruthy();
    const input = dialog!.querySelector<HTMLInputElement>(".library-rename-input");
    expect(input).toBeTruthy();
    expect(input!.value).toBe("logo");

    // 输入新名并确认
    act(() => {
      setInputValue(input!, "新Logo");
    });
    const confirmButton = [...dialog!.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.includes("重命名"));
    act(() => {
      confirmButton!.click();
    });
    await flush();

    const renameCalls = callMock.mock.calls.filter(([method]) => method === "library_rename");
    expect(renameCalls).toHaveLength(1);
    expect(renameCalls[0][1]).toMatchObject({ kind: "watermark", path: "C:/lib/Watermark/logo.png", new_name: "新Logo" });
    expect(document.querySelector(".library-confirm-dialog")).toBeNull();
  });

  it("水印库类型筛选：按 图片/视频 过滤", async () => {
    mockWatermarkItems([
      { name: "logo.png", folder: "", type: "image" },
      { name: "clip.mp4", folder: "", type: "video" },
    ]);
    renderLibrary();
    await flush();
    act(() => {
      buttonWithText("水印库")!.click();
    });
    await flush();

    const count = () => document.querySelectorAll(".library-row").length;
    expect(count()).toBe(2);

    const typeFilter = document.querySelector(".library-type-filter")!;
    const chip = (label: string) => [...typeFilter.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === label)!;

    act(() => { chip("视频").click(); });
    await flush();
    expect(count()).toBe(1);
    expect(document.querySelector(".library-row")!.textContent).toContain("clip.mp4");

    act(() => { chip("图片").click(); });
    await flush();
    expect(count()).toBe(1);
    expect(document.querySelector(".library-row")!.textContent).toContain("logo.png");

    act(() => { chip("全部").click(); });
    await flush();
    expect(count()).toBe(2);
  });

  it("搜索匹配文件名与所在文件夹", async () => {
    mockWatermarkItems([{ name: "logo.png", folder: "海报/Logo", type: "image" }]);
    renderLibrary();
    await flush();
    act(() => {
      buttonWithText("水印库")!.click();
    });
    await flush();

    // 根目录下不显示子文件夹内容
    expect(document.querySelectorAll(".library-row").length).toBe(0);

    // 搜索文件夹名「海报」应命中（修复前只匹配文件名，无法命中）
    const searchInput = document.querySelector<HTMLInputElement>("input[aria-label='搜索素材']")!;
    act(() => {
      setInputValue(searchInput, "海报");
    });
    // 等待 150ms 搜索 debounce 生效
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 220));
    });
    expect(document.querySelectorAll(".library-row").length).toBe(1);
    expect(document.querySelector(".library-row")!.textContent).toContain("logo.png");
  });
});

describe("导入状态提醒", () => {
  it("导入素材时显示进行中状态与开始/完成提醒", async () => {
    openDialogMock.mockResolvedValue(["C:/audio/1.mp3", "C:/audio/2.mp3"]);
    const { notify } = renderLibrary();
    await flush();

    // 让 library_import 挂起，以便观察「导入中」状态
    let releaseImport: ((value: unknown) => void) | null = null;
    callMock.mockImplementationOnce((method, params = {}) => {
      if (method === "library_import") {
        return new Promise((resolve) => {
          releaseImport = resolve;
        });
      }
      return baseImplementation(method, params);
    });

    // 空状态点击「导入音频」
    const importButton = buttonWithText("导入音频");
    expect(importButton).toBeTruthy();
    act(() => {
      importButton!.click();
    });
    await flush();

    // 开始提醒 + 进行中状态（按钮变为「导入中」并禁用）
    expect(notify).toHaveBeenCalledWith("info", "正在导入 2 个素材…");
    const busyButton = [...document.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.includes("导入中"));
    expect(busyButton).toBeTruthy();
    expect(busyButton!.disabled).toBe(true);

    // 完成
    await act(async () => {
      releaseImport!({
        results: [
          { name: "1.mp3", path: "C:/audio/1.mp3", status: "imported" },
          { name: "2.mp3", path: "C:/audio/2.mp3", status: "imported" },
        ],
      });
    });
    await flush();
    expect(notify).toHaveBeenCalledWith("success", "已导入 2 个素材");
  });
});

describe("Eagle 风格素材管理", () => {
  type MockItem = { name: string; folder?: string; type?: string; starred?: boolean; tags?: string[]; note?: string; duration?: number | null };
  function mockItems(kind: "bgm" | "watermark", items: MockItem[]) {
    callMock.mockImplementation((method, params = {}) => {
      if (method === "library_snapshot") {
        const base: Record<string, unknown> = {
          library_root: "C:/lib",
          bgm_dir: "C:/lib/BGM",
          watermark_dir: "C:/lib/Watermark",
          bgm: [],
          bgm_folders: [],
          watermark: [],
          watermark_folders: [],
        };
        const list = items.map((item) => ({
          name: item.name,
          path: `C:/lib/${kind === "bgm" ? "BGM" : "Watermark"}/${item.name}`,
          folder: item.folder ?? "",
          type: item.type ?? (kind === "bgm" ? "audio" : "image"),
          size_bytes: 2048,
          duration: item.duration ?? null,
          added_at: "2026-08-17T00:00:00Z",
          duplicate_key: item.name,
          tags: item.tags ?? [],
          starred: Boolean(item.starred),
          note: item.note ?? "",
        }));
        base[kind === "bgm" ? "bgm" : "watermark"] = list;
        return Promise.resolve(base);
      }
      return baseImplementation(method, params);
    });
  }

  it("详情面板：加标签 / 星标 / 备注并保存", async () => {
    mockItems("watermark", [{ name: "logo.png" }]);
    renderLibrary();
    await flush();
    act(() => { buttonWithText("水印库")!.click(); });
    await flush();

    // 点击素材名打开详情
    act(() => { document.querySelector<HTMLButtonElement>(".library-item-name")!.click(); });
    await flush();
    expect(document.querySelector(".library-detail-panel")).toBeTruthy();

    // 加标签
    const tagInput = document.querySelector<HTMLInputElement>("input[aria-label='新增标签']")!;
    act(() => { setInputValue(tagInput, "品牌"); });
    act(() => { document.querySelector<HTMLButtonElement>(".library-detail-tag-input button")!.click(); });

    // 收藏
    act(() => { document.querySelector<HTMLButtonElement>(".library-star-toggle")!.click(); });

    // 备注
    const note = document.querySelector<HTMLTextAreaElement>(".library-detail-note")!;
    act(() => {
      const textareaSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      textareaSetter.call(note, "主视觉 logo");
      note.dispatchEvent(new Event("input", { bubbles: true }));
    });

    // 保存
    const saveButton = [...document.querySelectorAll<HTMLButtonElement>(".library-detail-panel button")].find((button) => button.textContent?.includes("保存"));
    act(() => { saveButton!.click(); });
    await flush();

    const metadataCalls = callMock.mock.calls.filter(([method]) => method === "library_set_metadata");
    expect(metadataCalls).toHaveLength(1);
    expect(metadataCalls[0][1]).toMatchObject({
      kind: "watermark",
      path: "C:/lib/Watermark/logo.png",
      tags: ["品牌"],
      starred: true,
      note: "主视觉 logo",
    });
  });

  it("星标筛选：只看收藏素材", async () => {
    mockItems("watermark", [
      { name: "收藏图.png", starred: true },
      { name: "普通图.png" },
    ]);
    renderLibrary();
    await flush();
    act(() => { buttonWithText("水印库")!.click(); });
    await flush();
    expect(document.querySelectorAll(".library-row").length).toBe(2);

    act(() => { document.querySelector<HTMLButtonElement>(".library-star-filter")!.click(); });
    await flush();
    expect(document.querySelectorAll(".library-row").length).toBe(1);
    expect(document.querySelector(".library-row")!.textContent).toContain("收藏图.png");
  });

  it("批量重命名：模板预览并调用引擎", async () => {
    mockItems("bgm", [{ name: "歌一.wav" }, { name: "歌二.wav" }]);
    renderLibrary();
    await flush();

    // 全选两个素材
    act(() => {
      const checkboxes = [...document.querySelectorAll<HTMLInputElement>(".library-checkbox")];
      checkboxes.forEach((checkbox) => checkbox.click());
    });
    await flush();
    const renameButton = buttonWithText("批量重命名");
    expect(renameButton).toBeTruthy();
    act(() => { renameButton!.click(); });
    await flush();

    // 预览：默认模板 {n}-{name} → 01/02（中文按拼音排序，歌二在前）
    expect(document.querySelector(".library-rename-batch-dialog")).toBeTruthy();
    expect(document.querySelectorAll(".library-rename-batch-row").length).toBe(2);
    const previewNames = [...document.querySelectorAll<HTMLElement>(".library-rename-batch-row em")].map((element) => element.textContent ?? "");
    expect(previewNames.filter((name) => name.startsWith("01-"))).toHaveLength(1);
    expect(previewNames.join(" ")).toContain("歌一.wav");
    expect(previewNames.join(" ")).toContain("歌二.wav");

    const applyButton = [...document.querySelectorAll<HTMLButtonElement>(".library-rename-batch-dialog button")].find((button) => button.textContent?.includes("重命名"));
    act(() => { applyButton!.click(); });
    await flush();

    const renameCalls = callMock.mock.calls.filter(([method]) => method === "library_rename_batch");
    expect(renameCalls).toHaveLength(1);
    expect(renameCalls[0]?.[1]).toMatchObject({ kind: "bgm", pattern: "{n}-{name}", start_index: 1 });
    expect(renameCalls[0]?.[1]?.paths as string[] | undefined).toHaveLength(2);
  });

  it("智能文件夹：新建规则、保存并筛选", async () => {
    mockItems("bgm", [
      { name: "长歌.wav", duration: 120 },
      { name: "短歌.wav", duration: 10 },
    ]);
    renderLibrary();
    await flush();

    // 侧栏「智能文件夹」新建按钮 → 编辑器
    const createButton = document.querySelector<HTMLButtonElement>(".library-smart-list button[aria-label='新建智能文件夹']");
    expect(createButton).toBeTruthy();
    act(() => { createButton!.click(); });
    await flush();

    const nameInput = document.querySelector<HTMLInputElement>("input[aria-label='智能文件夹名称']")!;
    act(() => { setInputValue(nameInput, "长音频"); });
    await flush();

    // 添加一条条件（默认「类型=图片」），再改为「时长 > 60」
    act(() => {
      [...document.querySelectorAll<HTMLButtonElement>(".library-smart-editor button")].find((button) => button.textContent?.includes("添加条件"))!.click();
    });
    await flush();
    act(() => {
      const fieldSelect = document.querySelector<HTMLSelectElement>(".library-smart-condition select")!;
      const selectSetter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
      selectSetter.call(fieldSelect, "duration");
      fieldSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await flush();
    act(() => {
      const opSelect = document.querySelectorAll<HTMLSelectElement>(".library-smart-condition select")[1]!;
      const selectSetter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
      selectSetter.call(opSelect, "gt");
      opSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await flush();
    const valueInput = document.querySelector<HTMLInputElement>(".library-smart-condition input")!;
    expect(valueInput).toBeTruthy();
    act(() => { setInputValue(valueInput, "60"); });
    await flush();

    const saveButton = [...document.querySelectorAll<HTMLButtonElement>(".library-smart-editor button")].find((button) => button.textContent?.includes("保存"));
    act(() => { saveButton!.click(); });
    await flush();

    const saveCalls = callMock.mock.calls.filter(([method]) => method === "library_smart_folders_save");
    expect(saveCalls).toHaveLength(1);
    expect(saveCalls[0][1]).toMatchObject({
      folders: [{ name: "长音频", kind: "bgm", conditions: [{ field: "duration", op: "gt", value: "60" }] }],
    });

    // 点击智能文件夹 → 只显示时长 > 60 的素材
    act(() => { document.querySelector<HTMLButtonElement>(".library-smart-item")!.click(); });
    await flush();
    expect(document.querySelectorAll(".library-row").length).toBe(1);
    expect(document.querySelector(".library-row")!.textContent).toContain("长歌.wav");
  });
});
