import type { VideoConfig, Workspace } from "../types";

/** 按拖拽语义重排工作区数组：把 dragId 项插入到 targetId 项之前/之后。 */
export function reorderWorkspaceList<T extends { id: string }>(
  list: T[],
  dragId: string,
  targetId: string,
  position: "before" | "after" = "before",
): T[] {
  if (dragId === targetId) return list;
  const from = list.findIndex((item) => item.id === dragId);
  const to = list.findIndex((item) => item.id === targetId);
  if (from < 0 || to < 0) return list;
  const copy = [...list];
  const [moved] = copy.splice(from, 1);
  const targetIndex = copy.findIndex((item) => item.id === targetId);
  const insertAt = position === "before" ? Math.max(0, targetIndex) : targetIndex + 1;
  copy.splice(insertAt, 0, moved);
  return copy;
}

/** 复制工作区（追加副本），返回新列表与副本。 */
export function duplicateWorkspaceList(list: Workspace[], id: string): { list: Workspace[]; next: Workspace } {
  const index = list.findIndex((workspace) => workspace.id === id);
  if (index < 0) return { list, next: list[0] };
  const source = list[index];
  const next: Workspace = {
    ...source,
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`,
    name: `${source.name} 副本`,
    preview: null,
    validationErrors: [],
    validationIssues: [],
    dirty: false,
  };
  const copy = [...list];
  copy.splice(index + 1, 0, next);
  return { list: copy, next };
}

/** 剪切移动工作区：从列表移除 sourceId，插入到 targetId 之后；目标相同则原样返回。 */
export function moveCutWorkspaceList(list: Workspace[], sourceId: string, targetId: string): Workspace[] {
  if (sourceId === targetId) return list;
  const source = list.find((workspace) => workspace.id === sourceId);
  if (!source) return list;
  const rest = list.filter((workspace) => workspace.id !== sourceId);
  const targetIndex = rest.findIndex((workspace) => workspace.id === targetId);
  if (targetIndex < 0) return list;
  rest.splice(targetIndex + 1, 0, source);
  return rest;
}

/** 提取可保存为预设的参数子集（剔除路径类字段）。 */
const PATH_KEYS = new Set([
  "input_dir",
  "output_dir",
  "bgm_dir",
  "bgm_files",
  "watermark_path",
  "watermark_layers",
  "width",
  "height",
  "_qt_watermark_defaults_v2",
]);

export function extractPresetConfig(config: VideoConfig): Partial<VideoConfig> {
  const preset: Partial<VideoConfig> = {};
  for (const [key, value] of Object.entries(config)) {
    if (!PATH_KEYS.has(key)) preset[key as keyof VideoConfig] = value as never;
  }
  return preset;
}

/** 应用预设到工作区配置（保留输入/输出目录）。 */
export function applyPresetToConfig(config: VideoConfig, preset: Partial<VideoConfig>): VideoConfig {
  return {
    ...config,
    ...preset,
    input_dir: config.input_dir,
    output_dir: config.output_dir,
  };
}

export function formatBytes(bytes: number) {
  if (!bytes || bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDuration(seconds: number | null | undefined) {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return "—";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes > 0 ? `${minutes}:${String(rest).padStart(2, "0")}` : `${rest} 秒`;
}
