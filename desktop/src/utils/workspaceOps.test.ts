import { describe, expect, it } from "vitest";
import { FALLBACK_CONFIG } from "../constants";
import type { Workspace } from "../types";
import {
  applyPresetToConfig,
  duplicateWorkspaceList,
  extractPresetConfig,
  formatBytes,
  formatDuration,
  moveCutWorkspaceList,
  reorderWorkspaceList,
} from "./workspaceOps";

function makeWorkspace(id: string, name: string): Workspace {
  return {
    id,
    name,
    config: structuredClone(FALLBACK_CONFIG),
    imageCount: null,
    preview: null,
    validationErrors: [],
    validationIssues: [],
    dirty: false,
  };
}

describe("reorderWorkspaceList", () => {
  const list = [makeWorkspace("a", "A"), makeWorkspace("b", "B"), makeWorkspace("c", "C")];

  it("把首项移动到末尾（after）", () => {
    const next = reorderWorkspaceList(list, "a", "c", "after");
    expect(next.map((w) => w.id)).toEqual(["b", "c", "a"]);
  });

  it("把末项移动到开头（before）", () => {
    const next = reorderWorkspaceList(list, "c", "a", "before");
    expect(next.map((w) => w.id)).toEqual(["c", "a", "b"]);
  });

  it("插入到目标之后", () => {
    const next = reorderWorkspaceList(list, "c", "a", "after");
    expect(next.map((w) => w.id)).toEqual(["a", "c", "b"]);
  });

  it("拖到自身位置不变化", () => {
    expect(reorderWorkspaceList(list, "b", "b", "before")).toBe(list);
  });

  it("未知 id 不变化且不抛错", () => {
    expect(reorderWorkspaceList(list, "x", "a", "before")).toBe(list);
    expect(reorderWorkspaceList(list, "a", "x", "before")).toBe(list);
  });
});

describe("duplicateWorkspaceList", () => {
  it("在源项之后插入副本并改名", () => {
    const list = [makeWorkspace("a", "A"), makeWorkspace("b", "B")];
    const { list: next, next: copy } = duplicateWorkspaceList(list, "a");
    expect(next.map((w) => w.name)).toEqual(["A", "A 副本", "B"]);
    expect(copy.id).not.toBe("a");
    expect(copy.name).toBe("A 副本");
    expect(copy.preview).toBeNull();
  });

  it("未知 id 原样返回", () => {
    const list = [makeWorkspace("a", "A")];
    expect(duplicateWorkspaceList(list, "x").list).toBe(list);
  });
});

describe("moveCutWorkspaceList", () => {
  it("剪切移动：源移除并插入目标之后", () => {
    const list = [makeWorkspace("a", "A"), makeWorkspace("b", "B"), makeWorkspace("c", "C")];
    const next = moveCutWorkspaceList(list, "c", "a");
    expect(next.map((w) => w.id)).toEqual(["a", "c", "b"]);
  });

  it("剪切到自身位置不变化", () => {
    const list = [makeWorkspace("a", "A"), makeWorkspace("b", "B")];
    expect(moveCutWorkspaceList(list, "a", "a")).toBe(list);
  });
});

describe("preset config", () => {
  it("提取预设剔除路径类字段", () => {
    const config = {
      ...structuredClone(FALLBACK_CONFIG),
      input_dir: "D:/输入",
      output_dir: "D:/输出",
      bgm_dir: "D:/BGM",
      watermark_path: "D:/wm.png",
      resolution_preset: "1920x1080",
      fps: 60,
    };
    const preset = extractPresetConfig(config);
    expect(preset.resolution_preset).toBe("1920x1080");
    expect(preset.fps).toBe(60);
    expect(preset.input_dir).toBeUndefined();
    expect(preset.output_dir).toBeUndefined();
    expect(preset.bgm_dir).toBeUndefined();
    expect(preset.watermark_path).toBeUndefined();
  });

  it("应用预设保留输入/输出目录", () => {
    const config = {
      ...structuredClone(FALLBACK_CONFIG),
      input_dir: "D:/输入",
      output_dir: "D:/输出",
      fps: 30,
    };
    const next = applyPresetToConfig(config, { fps: 60, resolution_preset: "720x1280" });
    expect(next.fps).toBe(60);
    expect(next.resolution_preset).toBe("720x1280");
    expect(next.input_dir).toBe("D:/输入");
    expect(next.output_dir).toBe("D:/输出");
  });
});

describe("formatters", () => {
  it("formatBytes", () => {
    expect(formatBytes(0)).toBe("—");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });

  it("formatDuration", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(0)).toBe("—");
    expect(formatDuration(8)).toBe("8 秒");
    expect(formatDuration(90)).toBe("1:30");
  });
});
