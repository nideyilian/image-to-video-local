import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import {
  ArrowDown,
  ArrowLeftRight,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clapperboard,
  FileVideo,
  Folder,
  FolderOpen,
  FolderPlus,
  Image as ImageIcon,
  Layers,
  LayoutGrid,
  List,
  Loader2,
  Move,
  Music,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Scissors,
  Search,
  Sparkles,
  Stamp,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { DEFAULT_WATERMARK_LAYER, TRANSITIONS, VIDEO_EFFECTS } from "../constants";
import { engine } from "../engine";
import { AddVideoSource } from "./AddVideoSource";
import { BgmCover } from "./BgmCover";
import { EffectLibraryPanel } from "./EffectLibraryPanel";
import type {
  LibraryDirs,
  LibraryExtractResult,
  LibraryExtractSummary,
  LibraryFolder,
  LibraryImportResult,
  LibraryItem,
  LibraryKind,
  LibraryMoveResult,
  VideoConfig,
} from "../types";

const LIBRARY_KEY = "image-to-video.library.v1";
const VIEW_KEY = "image-to-video.library.view";

const BGM_FILTERS = [{ name: "音频文件", extensions: ["mp3", "wav", "m4a", "aac", "ogg", "flac", "wma", "aiff"] }];
const WATERMARK_FILTERS = [
  { name: "图片文件", extensions: ["png", "jpg", "jpeg", "webp", "bmp", "gif", "tiff"] },
  { name: "视频文件", extensions: ["mp4", "mov", "avi", "mkv", "webm", "m4v", "flv", "wmv", "ts", "mpg", "mpeg"] },
];

type ViewMode = "list" | "card";
type SortKey = "name" | "duration" | "size" | "added";
type LibraryTab = LibraryKind | "effect" | "transition";

function formatBytes(bytes: number) {
  if (!bytes || bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds: number | null | undefined) {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return "—";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes > 0 ? `${minutes}:${String(rest).padStart(2, "0")}` : `${rest} 秒`;
}

function loadStoredDirs(): Partial<LibraryDirs> {
  try {
    const raw = JSON.parse(localStorage.getItem(LIBRARY_KEY) || "{}") as Partial<LibraryDirs>;
    return raw && typeof raw === "object" ? raw : {};
  } catch {
    return {};
  }
}

function loadViewMode(kind: LibraryKind): ViewMode {
  try {
    const raw = localStorage.getItem(`${VIEW_KEY}.${kind}`);
    return raw === "card" ? "card" : "list";
  } catch {
    return "list";
  }
}

type TreeNode = { name: string; relative: string; count: number; children: TreeNode[] };

function buildTree(folders: LibraryFolder[]): TreeNode[] {
  const nodes = new Map<string, TreeNode>();
  for (const folder of folders) {
    nodes.set(folder.relative, { name: folder.name, relative: folder.relative, count: folder.count, children: [] });
  }
  const roots: TreeNode[] = [];
  for (const node of nodes.values()) {
    const index = node.relative.lastIndexOf("/");
    if (index === -1) {
      roots.push(node);
    } else {
      const parent = nodes.get(node.relative.slice(0, index));
      if (parent) parent.children.push(node);
      else roots.push(node);
    }
  }
  const sortNodes = (list: TreeNode[]) => {
    list.sort((a, b) => a.name.localeCompare(b.name, "zh-Hans-CN"));
    list.forEach((node) => sortNodes(node.children));
  };
  sortNodes(roots);
  return roots;
}

function ancestorsOf(folder: string): string[] {
  const parts = folder.split("/").filter(Boolean);
  const ancestors: string[] = [];
  let prefix = "";
  for (let index = 0; index < parts.length - 1; index += 1) {
    prefix = prefix ? `${prefix}/${parts[index]}` : parts[index];
    ancestors.push(prefix);
  }
  return ancestors;
}

type ExtractStatus = {
  open: boolean;
  running: boolean;
  taskId: string | null;
  folder: string;
  files: string[];
  results: LibraryExtractResult[];
  summary: LibraryExtractSummary | null;
  total: number;
  done: number;
  avoidDuplicates: boolean;
  saveFolder: string;
};

type JianyingEntry = { path: string; name: string; draft: string };

type JianyingScanResult = {
  draft_root: string;
  drafts: Array<{ name: string; path: string; counts: { audio: number; video: number; image: number; effect: number; transition: number } }>;
  audios: JianyingEntry[];
  videos: JianyingEntry[];
  images: JianyingEntry[];
  effects: JianyingEntry[];
  transitions: JianyingEntry[];
};

type JianyingCacheResult = {
  cache_root: string;
  audios: JianyingEntry[];
  videos: JianyingEntry[];
  scanned_files: number;
  truncated: boolean;
};

type JianyingDialogState = {
  open: boolean;
  scanning: boolean;
  busy: boolean;
  error: string | null;
  source: "draft" | "cache";
  result: JianyingScanResult | null;
  cacheResult: JianyingCacheResult | null;
  importing: "bgm" | "watermark" | null;
  summary: { ok: boolean; text: string } | null;
};

const IDLE_JIANYING: JianyingDialogState = {
  open: false,
  scanning: false,
  busy: false,
  error: null,
  source: "draft",
  result: null,
  cacheResult: null,
  importing: null,
  summary: null,
};

const IDLE_EXTRACT: ExtractStatus = {
  open: false,
  running: false,
  taskId: null,
  folder: "",
  files: [],
  results: [],
  summary: null,
  total: 0,
  done: 0,
  avoidDuplicates: true,
  saveFolder: "",
};

const STATUS_LABELS: Record<string, { label: string; className: string }> = {
  saved: { label: "已保存", className: "is-saved" },
  duplicate: { label: "重复跳过", className: "is-duplicate" },
  no_audio: { label: "无音轨", className: "is-no-audio" },
  cancelled: { label: "已取消", className: "is-no-audio" },
  failed: { label: "失败", className: "is-failed" },
};

const SORT_OPTIONS: Array<{ value: SortKey; label: string }> = [
  { value: "name", label: "按名称" },
  { value: "duration", label: "按时长" },
  { value: "size", label: "按大小" },
  { value: "added", label: "按入库时间" },
];

export function MaterialLibrary({ open, onClose, config, onChange, notify, onReveal, onExtractBusyChange, requestTab, onConsumeTabRequest }: {
  open: boolean;
  onClose: () => void;
  config: VideoConfig;
  onChange: <K extends keyof VideoConfig>(key: K, value: VideoConfig[K]) => void;
  notify: (kind: "info" | "success" | "error", message: string) => void;
  onReveal: (path: string) => void;
  onExtractBusyChange?: (busy: boolean) => void;
  /** 外部请求打开素材库时定位到的标签页（如检查器「在素材库配置」） */
  requestTab?: "effect" | "transition" | null;
  onConsumeTabRequest?: () => void;
}) {
  const [tab, setTab] = useState<LibraryTab>("bgm");
  const [dirs, setDirs] = useState<LibraryDirs | null>(null);
  const [bgm, setBgm] = useState<LibraryItem[]>([]);
  const [bgmFolders, setBgmFolders] = useState<LibraryFolder[]>([]);
  const [watermark, setWatermark] = useState<LibraryItem[]>([]);
  const [watermarkFolders, setWatermarkFolders] = useState<LibraryFolder[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentFolder, setCurrentFolder] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<ViewMode>(() => loadViewMode("bgm"));
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDesc, setSortDesc] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [moveOpen, setMoveOpen] = useState(false);
  const [marquee, setMarquee] = useState<{ x0: number; y0: number; x1: number; y1: number; additive: boolean } | null>(null);
  const marqueeRef = useRef<{ startX: number; startY: number; currentX: number; currentY: number; additive: boolean; active: boolean } | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const itemRefs = useRef<Map<string, HTMLElement>>(new Map());
  const [creatingUnder, setCreatingUnder] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [folderDraft, setFolderDraft] = useState("");
  const [playingPath, setPlayingPath] = useState<string | null>(null);
  const [extract, setExtract] = useState<ExtractStatus>(IDLE_EXTRACT);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [videoPreview, setVideoPreview] = useState<{ path: string; name: string } | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const mountedRef = useRef(true);

  const desktopRuntime = engine.desktopRuntime;
  const libraryBase = tab === "bgm" ? dirs?.bgm_dir ?? "" : dirs?.watermark_dir ?? "";
  const items = tab === "bgm" ? bgm : watermark;
  const folders = tab === "bgm" ? bgmFolders : watermarkFolders;
  const tree = useMemo(() => buildTree(folders), [folders]);

  const persistDirs = useCallback((next: LibraryDirs) => {
    setDirs(next);
    try {
      localStorage.setItem(LIBRARY_KEY, JSON.stringify({ bgm_dir: next.bgm_dir, watermark_dir: next.watermark_dir }));
    } catch {
      /* 存储失败不影响使用 */
    }
  }, []);

  const refresh = useCallback(async (nextDirs?: LibraryDirs) => {
    if (!engine.desktopRuntime) return;
    const target = nextDirs ?? dirs;
    if (!target) return;
    setLoading(true);
    setError(null);
    try {
      const snapshot = await engine.call<LibrarySnapshotLike>(
        "library_snapshot",
        { bgm_dir: target.bgm_dir, watermark_dir: target.watermark_dir },
        60_000,
      );
      if (!mountedRef.current) return;
      setDirs({
        library_root: snapshot.library_root,
        bgm_dir: snapshot.bgm_dir,
        watermark_dir: snapshot.watermark_dir,
      });
      setBgm(snapshot.bgm);
      setBgmFolders(snapshot.bgm_folders);
      setWatermark(snapshot.watermark);
      setWatermarkFolders(snapshot.watermark_folders);
      setSelected(new Set());
    } catch (err) {
      if (!mountedRef.current) return;
      setError(err instanceof Error ? err.message : "读取素材库失败");
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [dirs]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      onExtractBusyChange?.(false);
    };
  }, [onExtractBusyChange]);

  useEffect(() => {
    localStorage.setItem(`${VIEW_KEY}.${tab}`, viewMode);
  }, [tab, viewMode]);

  useEffect(() => {
    if (!open) return;
    void (async () => {
      if (!engine.desktopRuntime) return;
      let nextDirs: LibraryDirs | null = dirs;
      if (!nextDirs) {
        const stored = loadStoredDirs();
        const defaults = await engine.call<LibraryDirs>("library_dirs", {}, 15_000);
        nextDirs = {
          bgm_dir: stored.bgm_dir || defaults.bgm_dir,
          watermark_dir: stored.watermark_dir || defaults.watermark_dir,
          library_root: defaults.library_root,
        };
        setDirs(nextDirs);
      }
      await refresh(nextDirs);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // 响应外部标签页定位请求（检查器「在素材库配置」）
  useEffect(() => {
    if (!open || !requestTab) return;
    setTab(requestTab);
    onConsumeTabRequest?.();
  }, [open, onConsumeTabRequest, requestTab]);

  useEffect(() => {
    if (open) return;
    audioRef.current?.pause();
    setVideoPreview(null);
    setVideoUrl(null);
    setPlayingPath(null);
  }, [open]);

  useEffect(() => {
    setViewMode(loadViewMode(tab === "watermark" ? "watermark" : "bgm"));
    setCurrentFolder("");
    setSearch("");
    setSelected(new Set());
  }, [tab]);

  useEffect(() => {
    if (!engine.desktopRuntime) return;
    const unsubscribe = engine.subscribe((event) => {
      if (event.type !== "event" || !event.event.startsWith("library.extract")) return;
      const payload = event.payload;
      const taskId = String(payload.task_id ?? "");
      if (!taskId) return;
      if (event.event === "library.extract.done") {
        const summary = payload.summary as LibraryExtractSummary | undefined;
        onExtractBusyChange?.(false);
        if (summary) {
          notify(
            summary.saved ? "success" : summary.failed || summary.cancelled ? "error" : "info",
            `拆解完成：成功 ${summary.saved}${summary.duplicate ? ` · 重复跳过 ${summary.duplicate}` : ""}${summary.no_audio ? ` · 无音轨 ${summary.no_audio}` : ""}${summary.failed ? ` · 失败 ${summary.failed}` : ""}${summary.cancelled ? ` · 已取消 ${summary.cancelled}` : ""}`,
          );
        }
      }
      setExtract((current) => {
        if (current.taskId && current.taskId !== taskId) return current;
        if (event.event === "library.extract.done") {
          const summary = payload.summary as LibraryExtractSummary | undefined;
          void refresh();
          return {
            ...current,
            running: false,
            taskId: null,
            summary: summary ?? null,
            total: summary?.total ?? current.total,
            done: summary?.total ?? current.done,
          };
        }
        const result = payload.result as LibraryExtractResult | undefined;
        if (!result) return current;
        const nextResults = current.results.some((item) => item.video === result.video)
          ? current.results.map((item) => item.video === result.video ? result : item)
          : [...current.results, result];
        return {
          ...current,
          results: nextResults,
          total: Number(payload.total ?? current.total),
          done: Number(payload.done ?? current.done),
        };
      });
    });
    return () => { unsubscribe(); };
  }, [notify, onExtractBusyChange, refresh]);

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusTimer = window.setTimeout(() => dialogRef.current?.querySelector<HTMLElement>("button:not(:disabled), input:not(:disabled)")?.focus(), 0);
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        if (marqueeRef.current) {
          marqueeRef.current = null;
          setMarquee(null);
          document.body.classList.remove("is-marquee-active");
          return;
        }
        if (videoPreview) {
          setVideoPreview(null);
          setVideoUrl(null);
          setPlayingPath(null);
          return;
        }
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled)"));
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.body.classList.add("is-modal-open");
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("keydown", handleKeyDown);
      document.body.classList.remove("is-modal-open");
      previousFocus?.focus();
    };
  }, [open, onClose, videoPreview]);

  const selectFolder = useCallback((folder: string) => {
    setCurrentFolder(folder);
    setSearch("");
    setSelected(new Set());
    if (folder) {
      setExpanded((current) => {
        const next = new Set(current);
        ancestorsOf(folder).forEach((ancestor) => next.add(ancestor));
        return next;
      });
    }
  }, []);

  const toggleExpanded = useCallback((relative: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(relative)) next.delete(relative);
      else next.add(relative);
      return next;
    });
  }, []);

  // ---------- 视图数据 ----------

  const visibleItems = useMemo(() => {
    const query = search.trim().toLowerCase();
    const inScope = (item: LibraryItem) => {
      if (!query) return item.folder === currentFolder;
      return item.folder === currentFolder || (currentFolder ? item.folder.startsWith(`${currentFolder}/`) : true);
    };
    let list = items.filter((item) => inScope(item) && (!query || item.name.toLowerCase().includes(query)));
    const direction = sortDesc ? -1 : 1;
    list = [...list].sort((a, b) => {
      let result = 0;
      if (sortKey === "name") result = a.name.localeCompare(b.name, "zh-Hans-CN");
      else if (sortKey === "size") result = a.size_bytes - b.size_bytes;
      else if (sortKey === "added") result = String(a.added_at ?? "").localeCompare(String(b.added_at ?? ""));
      else {
        const av = a.duration ?? -1;
        const bv = b.duration ?? -1;
        result = av === bv ? a.name.localeCompare(b.name, "zh-Hans-CN") : av - bv;
      }
      return result * direction || a.name.localeCompare(b.name, "zh-Hans-CN");
    });
    return list;
  }, [currentFolder, items, search, sortDesc, sortKey]);

  const toggleSelected = useCallback((path: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const registerItemRef = useCallback((path: string) => (element: HTMLLIElement | null) => {
    if (element) itemRefs.current.set(path, element);
    else itemRefs.current.delete(path);
  }, []);

  // ---------- 操作 ----------

  const importFiles = useCallback(async (kind: LibraryKind, folder: string) => {
    if (!engine.desktopRuntime) return notify("info", "导入素材需要在 Tauri 桌面窗口中运行");
    if (!dirs) return;
    const filters = kind === "bgm" ? BGM_FILTERS : WATERMARK_FILTERS;
    const picked = await openDialog({ multiple: true, directory: false, title: kind === "bgm" ? "选择要导入 BGM 库的音频" : "选择要导入水印库的图片", filters });
    if (!picked || !picked.length) return;
    const result = await engine.call<{ results: LibraryImportResult[] }>(
      "library_import",
      {
        kind,
        paths: picked,
        folder,
        bgm_dir: dirs.bgm_dir,
        watermark_dir: dirs.watermark_dir,
      },
      300_000,
    );
    const imported = result.results.filter((item) => item.status === "imported").length;
    const duplicates = result.results.filter((item) => item.status === "duplicate").length;
    const failed = result.results.filter((item) => item.status === "failed").length;
    notify(
      failed && !imported ? "error" : "success",
      imported
        ? `已导入 ${imported} 个素材${duplicates ? `，跳过重复 ${duplicates} 个` : ""}${failed ? `，失败 ${failed} 个` : ""}`
        : duplicates
          ? `未导入新素材：${duplicates} 个与库中已有内容重复`
          : `导入失败 ${failed} 个素材`,
    );
    await refresh();
  }, [dirs, notify, refresh]);

  const removeItems = useCallback(async (kind: LibraryKind, paths: string[]) => {
    if (!dirs) return;
    let removed = 0;
    for (const path of paths) {
      try {
        await engine.call("library_remove", { kind, path, bgm_dir: dirs.bgm_dir, watermark_dir: dirs.watermark_dir });
        removed += 1;
      } catch {
        /* 单个失败继续处理其余 */
      }
    }
    notify("success", `已删除 ${removed} 个素材`);
    await refresh();
  }, [dirs, notify, refresh]);

  const moveItems = useCallback(async (kind: LibraryKind, paths: string[], folder: string) => {
    if (!dirs) return;
    try {
      const result = await engine.call<{ results: LibraryMoveResult[] }>("library_move", {
        kind,
        paths,
        folder,
        bgm_dir: dirs.bgm_dir,
        watermark_dir: dirs.watermark_dir,
      }, 60_000);
      const moved = result.results.filter((item) => item.status === "moved").length;
      const duplicates = result.results.filter((item) => item.status === "duplicate").length;
      notify(
        moved ? "success" : "info",
        moved
          ? `已移动 ${moved} 个素材${duplicates ? `，跳过重复 ${duplicates} 个` : ""}`
          : `没有素材被移动${duplicates ? `（${duplicates} 个与目标文件夹重复）` : ""}`,
      );
      setMoveOpen(false);
      if (folder) {
        setCurrentFolder(folder);
        setExpanded((current) => {
          const next = new Set(current);
          ancestorsOf(folder).forEach((ancestor) => next.add(ancestor));
          return next;
        });
      }
      await refresh();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "移动失败");
    }
  }, [dirs, notify, refresh]);

  const createFolder = useCallback(async (parent: string, name: string) => {
    if (!dirs) return;
    const folder = parent ? `${parent}/${name}` : name;
    try {
      await engine.call("library_create_folder", {
        kind: tab,
        folder,
        bgm_dir: dirs.bgm_dir,
        watermark_dir: dirs.watermark_dir,
      });
      setCreatingUnder(null);
      setFolderDraft("");
      if (parent) {
        setExpanded((current) => new Set(current).add(parent));
      }
      await refresh();
      selectFolder(folder);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "新建文件夹失败");
    }
  }, [dirs, notify, refresh, selectFolder, tab]);

  const renameFolder = useCallback(async (folder: string, newName: string) => {
    if (!dirs) return;
    try {
      const result = await engine.call<{ folder: string }>("library_rename_folder", {
        kind: tab,
        folder,
        new_name: newName,
        bgm_dir: dirs.bgm_dir,
        watermark_dir: dirs.watermark_dir,
      });
      setRenaming(null);
      setFolderDraft("");
      if (currentFolder === folder || currentFolder.startsWith(`${folder}/`)) {
        const suffix = currentFolder === folder ? "" : currentFolder.slice(folder.length);
        setCurrentFolder(`${result.folder}${suffix}`);
      }
      await refresh();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "重命名失败");
    }
  }, [currentFolder, dirs, notify, refresh, tab]);

  const deleteFolder = useCallback(async (folder: string) => {
    if (!dirs) return;
    try {
      await engine.call("library_delete_folder", {
        kind: tab,
        folder,
        bgm_dir: dirs.bgm_dir,
        watermark_dir: dirs.watermark_dir,
      });
      if (currentFolder === folder) setCurrentFolder("");
      await refresh();
      notify("success", `已删除文件夹 ${folder}`);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "删除文件夹失败");
    }
  }, [currentFolder, dirs, notify, refresh, tab]);

  const changeDir = useCallback(async () => {
    if (!engine.desktopRuntime) return notify("info", "更换目录需要在 Tauri 桌面窗口中运行");
    const selected = await openDialog({ directory: true, multiple: false, title: tab === "bgm" ? "选择 BGM 库目录" : "选择水印库目录" });
    if (typeof selected !== "string" || !dirs) return;
    const next = tab === "bgm"
      ? { ...dirs, bgm_dir: selected }
      : { ...dirs, watermark_dir: selected };
    persistDirs(next);
    setCurrentFolder("");
    await refresh(next);
  }, [dirs, notify, persistDirs, refresh, tab]);

  const togglePlay = useCallback(async (item: LibraryItem) => {
    if (!engine.desktopRuntime) return notify("info", "音频试听需要在 Tauri 桌面窗口中运行");
    if (playingPath === item.path) {
      audioRef.current?.pause();
      setPlayingPath(null);
      return;
    }
    audioRef.current?.pause();
    try {
      const preview = await engine.call<{ preview_path: string }>("library_preview_audio", { path: item.path }, 130_000);
      const audio = audioRef.current;
      if (!audio) return;
      audio.src = engine.toAssetUrl(preview.preview_path);
      audio.onended = () => setPlayingPath(null);
      audio.onerror = () => {
        setPlayingPath(null);
        notify("error", "音频播放失败");
      };
      setPlayingPath(item.path);
      void audio.play().catch(() => {
        setPlayingPath(null);
        notify("error", "音频播放失败");
      });
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "试听失败");
    }
  }, [notify, playingPath]);

  // 视频水印素材：点击播放 → 弹出放大播放器（引擎按需转码为 WebView 可播放格式）
  const openVideoPreview = useCallback(async (item: LibraryItem) => {
    if (!engine.desktopRuntime) return notify("info", "视频预览需要在 Tauri 桌面窗口中运行");
    audioRef.current?.pause();
    setVideoPreview({ path: item.path, name: item.name });
    setVideoUrl(null);
    setPlayingPath(item.path);
    try {
      const preview = await engine.call<{ preview_path: string }>("library_preview_video", { path: item.path }, 130_000);
      setVideoUrl(engine.toAssetUrl(preview.preview_path));
    } catch (err) {
      setVideoPreview(null);
      setVideoUrl(null);
      setPlayingPath(null);
      notify("error", err instanceof Error ? err.message : "视频预览失败");
    }
  }, [notify]);

  const applyBgmDir = useCallback(() => {
    if (!dirs) return;
    onChange("bgm_dir", dirs.bgm_dir);
    onChange("use_bgm", true);
    notify("success", "已把 BGM 库设为音频目录并开启 BGM");
  }, [dirs, notify, onChange]);

  const applyWatermarkDir = useCallback(() => {
    if (!dirs) return;
    onChange("watermark_path", dirs.watermark_dir);
    onChange("watermark_mode", "文件夹");
    onChange("use_watermark", true);
    notify("success", "已把水印库设为水印路径（文件夹模式）");
  }, [dirs, notify, onChange]);

  const addWatermarkLayer = useCallback((item: LibraryItem) => {
    onChange("watermark_layers", [
      ...config.watermark_layers,
      { ...DEFAULT_WATERMARK_LAYER, path: item.path, enabled: true },
    ]);
    notify("success", `已把 ${item.name} 加入图片水印图层`);
  }, [config.watermark_layers, notify, onChange]);

  const addToBgmFiles = useCallback((paths: string[]) => {
    if (!paths.length) return;
    const current = config.bgm_files ?? [];
    const next = [...current];
    for (const path of paths) {
      if (!next.includes(path)) next.push(path);
    }
    onChange("bgm_files", next);
    notify("success", `已把 ${paths.length} 个 BGM 素材设为当前工作区 BGM`);
  }, [config.bgm_files, notify, onChange]);

  const useAsVideoWatermark = useCallback((item: LibraryItem) => {
    onChange("watermark_path", item.path);
    onChange("watermark_mode", "单文件");
    onChange("use_watermark", true);
    notify("success", `已把 ${item.name} 设为视频水印（单文件模式）`);
  }, [notify, onChange]);

  const selectAllVisible = useCallback(() => {
    setSelected(new Set(visibleItems.map((item) => item.path)));
  }, [visibleItems]);

  // ---------- 圈选（框选） ----------

  const isInteractiveTarget = (target: EventTarget | null) => {
    const element = target instanceof HTMLElement ? target : null;
    if (!element) return false;
    return Boolean(element.closest("button, input, select, a, .library-tree, .library-toolbar, .library-selection-bar, .library-breadcrumb, .library-search, .library-sort, .library-view-toggle"));
  };

  const beginMarquee = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || isInteractiveTarget(event.target)) return;
    const additive = event.ctrlKey || event.shiftKey;
    marqueeRef.current = { startX: event.clientX, startY: event.clientY, currentX: event.clientX, currentY: event.clientY, additive, active: false };
    const onMove = (moveEvent: PointerEvent) => {
      const state = marqueeRef.current;
      if (!state) return;
      const dx = moveEvent.clientX - state.startX;
      const dy = moveEvent.clientY - state.startY;
      if (!state.active && Math.hypot(dx, dy) < 5) return;
      if (!state.active) {
        state.active = true;
        document.body.classList.add("is-marquee-active");
        if (!additive) setSelected(new Set());
      }
      state.currentX = moveEvent.clientX;
      state.currentY = moveEvent.clientY;
      setMarquee({
        x0: Math.min(state.startX, state.currentX),
        y0: Math.min(state.startY, state.currentY),
        x1: Math.max(state.startX, state.currentX),
        y1: Math.max(state.startY, state.currentY),
        additive,
      });
    };
    const onUp = () => {
      const state = marqueeRef.current;
      marqueeRef.current = null;
      setMarquee(null);
      document.body.classList.remove("is-marquee-active");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      if (!state) return;
      if (!state.active) {
        if (!state.additive) setSelected(new Set());
        return;
      }
      const rect = {
        left: Math.min(state.startX, state.currentX),
        top: Math.min(state.startY, state.currentY),
        right: Math.max(state.startX, state.currentX),
        bottom: Math.max(state.startY, state.currentY),
      };
      const paths: string[] = [];
      for (const [path, element] of itemRefs.current) {
        if (!element.isConnected) continue;
        const bounds = element.getBoundingClientRect();
        if (bounds.left <= rect.right && bounds.right >= rect.left && bounds.top <= rect.bottom && bounds.bottom >= rect.top) {
          paths.push(path);
        }
      }
      setSelected((current) => {
        const next = new Set(state.additive ? current : []);
        paths.forEach((path) => next.add(path));
        return next;
      });
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }, []);

  // 拆解弹窗的添加入口已统一到 AddVideoSource 组件（点击 / 拖拽 / 文件夹三合一）
  const addExtractFiles = useCallback((paths: string[]) => {
    setExtract((current) => ({
      ...current,
      files: Array.from(new Set([...current.files, ...paths])),
    }));
  }, []);

  const setExtractFolder = useCallback((folder: string) => {
    setExtract((current) => ({ ...current, folder }));
  }, []);

  const startExtract = useCallback(async () => {
    if (!engine.desktopRuntime) return notify("info", "批量拆 BGM 需要在 Tauri 桌面窗口中运行");
    if (!dirs) return;
    if (!extract.files.length && !extract.folder) return notify("error", "请先选择视频文件或视频文件夹");
    setExtract((current) => ({ ...current, running: true, results: [], summary: null, done: 0, total: 0 }));
    onExtractBusyChange?.(true);
    try {
      const started = await engine.call<{ task_id: string; total: number }>("library_extract_bgm", {
        paths: extract.files,
        folder: extract.folder || undefined,
        save_folder: extract.saveFolder,
        bgm_dir: dirs.bgm_dir,
        options: { avoid_duplicates: extract.avoidDuplicates },
      }, 30_000);
      setExtract((current) => ({ ...current, taskId: started.task_id, total: started.total }));
    } catch (err) {
      setExtract((current) => ({ ...current, running: false, taskId: null }));
      onExtractBusyChange?.(false);
      notify("error", err instanceof Error ? err.message : "拆 BGM 任务启动失败");
    }
  }, [dirs, extract.avoidDuplicates, extract.files, extract.folder, extract.saveFolder, notify, onExtractBusyChange]);

  const cancelExtract = useCallback(async () => {
    if (!extract.taskId) return;
    try {
      await engine.call("library_extract_cancel", { task_id: extract.taskId });
    } catch {
      /* 任务可能已结束 */
    }
  }, [extract.taskId]);

  // ---------- 从剪映导入 ----------

  const [jianying, setJianying] = useState<JianyingDialogState>(IDLE_JIANYING);

  const scanJianying = useCallback(async (root?: string, source: "draft" | "cache" = jianying.source) => {
    if (!engine.desktopRuntime) return notify("info", "从剪映导入需要在 Tauri 桌面窗口中运行");
    setJianying((current) => ({ ...current, source, scanning: true, error: null, result: null, cacheResult: null, summary: null }));
    try {
      if (source === "cache") {
        const result = await engine.call<JianyingCacheResult>("jianying_cache_scan", { cache_root: root ?? "" }, 120_000);
        setJianying((current) => ({ ...current, scanning: false, cacheResult: result }));
      } else {
        const result = await engine.call<JianyingScanResult>("jianying_scan", { draft_root: root ?? "" }, 60_000);
        setJianying((current) => ({ ...current, scanning: false, result }));
      }
    } catch (err) {
      setJianying((current) => ({
        ...current,
        scanning: false,
        error: err instanceof Error ? err.message : "扫描剪映失败",
      }));
    }
  }, [jianying.source, notify]);

  const switchJianyingSource = useCallback((source: "draft" | "cache") => {
    if (source === jianying.source) return;
    void scanJianying(undefined, source);
  }, [jianying.source, scanJianying]);

  const pickDraftRoot = useCallback(async () => {
    if (!engine.desktopRuntime) return notify("info", "选择目录需要在 Tauri 桌面窗口中运行");
    const title = jianying.source === "cache"
      ? "选择剪映缓存目录（User Data\\Cache）"
      : "选择剪映草稿目录（com.lveditor.draft）";
    const picked = await openDialog({ directory: true, multiple: false, title });
    if (typeof picked === "string") await scanJianying(picked);
  }, [jianying.source, notify, scanJianying]);

  const importJianying = useCallback(async (kind: "bgm" | "watermark") => {
    if (!dirs) return;
    const source = jianying.source === "cache" ? jianying.cacheResult : jianying.result;
    if (!source) {
      notify(
        "info",
        jianying.source === "cache"
          ? "内置资源还没有扫描完成，请稍候或点击「重新扫描」后再导入。"
          : "草稿素材还没有扫描完成，请稍候或点击「重新扫描」后再导入。",
      );
      return;
    }
    const entries = kind === "bgm"
      ? source.audios
      : jianying.source === "cache" || !("images" in source)
        ? source.videos
        : [...source.videos, ...source.images, ...source.effects, ...source.transitions];
    if (!entries.length) {
      notify("info", kind === "bgm" ? "没有可导入的 BGM / 音效素材。" : "没有可导入的水印素材。");
      return;
    }
    setJianying((current) => ({ ...current, busy: true, importing: kind, summary: null }));
    try {
      const result = await engine.call<{ results: LibraryImportResult[] }>(
        "library_import",
        {
          kind,
          paths: entries.map((entry) => entry.path),
          folder: "",
          bgm_dir: dirs.bgm_dir,
          watermark_dir: dirs.watermark_dir,
        },
        300_000,
      );
      const imported = result.results.filter((item) => item.status === "imported").length;
      const duplicates = result.results.filter((item) => item.status === "duplicate").length;
      const failed = result.results.filter((item) => item.status === "failed").length;
      const message = kind === "bgm"
        ? `已从剪映导入 ${imported} 条 BGM${duplicates ? `，跳过重复 ${duplicates} 条` : ""}${failed ? `，失败 ${failed} 条` : ""}`
        : `已从剪映导入 ${imported} 个素材到水印库${duplicates ? `，跳过重复 ${duplicates} 个` : ""}${failed ? `，失败 ${failed} 个` : ""}`;
      notify(failed && !imported ? "error" : "success", message);
      setJianying((current) => ({ ...current, summary: { ok: !failed || imported > 0, text: message } }));
      await refresh();
    } catch (err) {
      const message = err instanceof Error ? err.message : "从剪映导入失败";
      notify("error", message);
      setJianying((current) => ({ ...current, summary: { ok: false, text: message } }));
    } finally {
      setJianying((current) => ({ ...current, busy: false, importing: null }));
    }
  }, [dirs, jianying.source, jianying.result, jianying.cacheResult, notify, refresh]);

  const openJianying = useCallback(() => {
    setJianying((current) => ({ ...current, open: true, summary: null }));
    void scanJianying();
  }, [scanJianying]);

  const commitFolderDraft = useCallback(() => {
    const name = folderDraft.trim();
    if (!name) return;
    if (creatingUnder !== null) void createFolder(creatingUnder, name);
    else if (renaming !== null) void renameFolder(renaming, name);
  }, [createFolder, creatingUnder, folderDraft, renameFolder, renaming]);

  if (!open) return null;

  const breadcrumbParts = currentFolder ? currentFolder.split("/") : [];
  const selectedCount = selected.size;
  const totalCount = items.length;

  const dialog = (
    <div className="library-backdrop" role="presentation" onMouseDown={onClose}>
      <section ref={dialogRef} className="library-dialog" role="dialog" aria-modal="true" aria-labelledby="library-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
        <header className="library-dialog-heading">
          <span className="library-dialog-icon"><List size={21} /></span>
          <span>
            <small>素材中心</small>
            <strong id="library-dialog-title">素材库</strong>
          </span>
          <span className="library-heading-hint">{libraryBase}</span>
          <button type="button" className="update-close" onClick={onClose} aria-label="关闭素材库"><X size={17} /></button>
        </header>

        <div className="library-tabs" role="tablist" aria-label="素材库分类">
          <button type="button" role="tab" aria-selected={tab === "bgm"} className={tab === "bgm" ? "is-active" : ""} onClick={() => setTab("bgm")}>
            <Music size={14} />BGM 库<span className="library-count">{bgm.length}</span>
          </button>
          <button type="button" role="tab" aria-selected={tab === "watermark"} className={tab === "watermark" ? "is-active" : ""} onClick={() => setTab("watermark")}>
            <ImageIcon size={14} />水印库<span className="library-count">{watermark.length}</span>
          </button>
          <button type="button" role="tab" aria-selected={tab === "effect"} className={tab === "effect" ? "is-active" : ""} onClick={() => setTab("effect")}>
            <Sparkles size={14} />特效<span className="library-count">{VIDEO_EFFECTS.length}</span>
          </button>
          <button type="button" role="tab" aria-selected={tab === "transition"} className={tab === "transition" ? "is-active" : ""} onClick={() => setTab("transition")}>
            <ArrowLeftRight size={14} />转场<span className="library-count">{TRANSITIONS.length}</span>
          </button>
        </div>

        <div className={`library-body library-body-split${tab === "effect" || tab === "transition" ? " is-effect-tab" : ""}`}>
          {!desktopRuntime ? (
            <div className="library-desktop-only"><CircleAlert size={16} />素材库功能需要在 Tauri 桌面窗口中运行。</div>
          ) : null}

          {tab === "effect" || tab === "transition" ? (
            <EffectLibraryPanel kind={tab} config={config} onChange={onChange} notify={notify} />
          ) : (
          <>
          {/* 文件夹树 */}
          <aside className="library-tree" aria-label="素材库文件夹">
            <div className="library-tree-head">
              <strong>分类</strong>
              <button type="button" className="icon-button" onClick={() => setCreatingUnder("")} aria-label="新建文件夹"><FolderPlus size={14} /></button>
            </div>
            <div className="library-tree-scroll">
              <button type="button" className={`library-tree-node is-root${currentFolder === "" ? " is-active" : ""}`} onClick={() => selectFolder("")}>
                <FolderOpen size={14} /><span>全部</span><small>{totalCount}</small>
              </button>
              {creatingUnder === "" ? (
                <span className="library-tree-node">
                  <span className="library-tree-chevron-empty" />
                  <Folder size={14} />
                  <input autoFocus className="library-folder-input" placeholder="文件夹名称" value={folderDraft} onChange={(event) => setFolderDraft(event.target.value)} onKeyDown={(event) => {
                    if (event.key === "Enter") commitFolderDraft();
                    if (event.key === "Escape") { setCreatingUnder(null); setFolderDraft(""); }
                  }} />
                </span>
              ) : null}
              <FolderNode
                nodes={tree}
                depth={0}
                currentFolder={currentFolder}
                expanded={expanded}
                creatingUnder={creatingUnder}
                renaming={renaming}
                folderDraft={folderDraft}
                onFolderDraft={setFolderDraft}
                onSelect={selectFolder}
                onToggle={toggleExpanded}
                onStartCreate={(parent) => { setCreatingUnder(parent); setRenaming(null); setFolderDraft(""); }}
                onStartRename={(folder) => { setRenaming(folder); setCreatingUnder(null); setFolderDraft(folder.split("/").pop() ?? ""); }}
                onDelete={deleteFolder}
                onCommit={commitFolderDraft}
                onCancelEdit={() => { setCreatingUnder(null); setRenaming(null); setFolderDraft(""); }}
              />
            </div>
          </aside>

          {/* 内容区 */}
          <div className="library-content" ref={contentRef} onPointerDown={beginMarquee} data-marquee-root>
            <div className="library-toolbar">
              <nav className="library-breadcrumb" aria-label="当前位置">
                <button type="button" className={currentFolder === "" ? "is-active" : ""} onClick={() => selectFolder("")}>全部</button>
                {breadcrumbParts.map((part, index) => {
                  const folder = breadcrumbParts.slice(0, index + 1).join("/");
                  return (
                    <span key={folder}>
                      <ChevronRight size={12} />
                      <button type="button" className={currentFolder === folder ? "is-active" : ""} onClick={() => selectFolder(folder)}>{part}</button>
                    </span>
                  );
                })}
              </nav>
              <span className="library-toolbar-actions">
                <span className="library-search">
                  <Search size={13} />
                  <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索素材" aria-label="搜索素材" />
                  {search ? <button type="button" className="icon-button" onClick={() => setSearch("")} aria-label="清除搜索"><X size={12} /></button> : null}
                </span>
                <span className="library-sort">
                  <select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)} aria-label="排序方式">
                    {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                  <button type="button" className="icon-button" onClick={() => setSortDesc((value) => !value)} aria-label={sortDesc ? "升序" : "降序"}>
                    {sortDesc ? <ArrowDown size={14} /> : <ArrowUp size={14} />}
                  </button>
                </span>
                <span className="library-view-toggle" role="group" aria-label="视图模式">
                  <button type="button" className={viewMode === "list" ? "is-active" : ""} onClick={() => setViewMode("list")} aria-label="列表模式"><List size={14} /></button>
                  <button type="button" className={viewMode === "card" ? "is-active" : ""} onClick={() => setViewMode("card")} aria-label="卡片模式"><LayoutGrid size={14} /></button>
                </span>
                {tab === "bgm" ? (
                  <button type="button" className="library-accent-button" onClick={() => setExtract((current) => ({ ...current, open: true, saveFolder: currentFolder }))} disabled={!desktopRuntime}><Scissors size={14} />批量拆BGM</button>
                ) : null}
                {tab === "bgm" || tab === "watermark" ? (
                  <button type="button" className="quiet-button" onClick={openJianying} disabled={!desktopRuntime || loading}><Clapperboard size={14} />从剪映导入</button>
                ) : null}
                <button type="button" className="quiet-button" onClick={() => importFiles(tab, currentFolder)} disabled={!desktopRuntime || loading}><Upload size={14} />导入</button>
                <button type="button" className="quiet-button" onClick={changeDir} disabled={!desktopRuntime}><FolderOpen size={14} />更换目录</button>
                <button type="button" className="quiet-button" onClick={() => onReveal(currentFolder ? `${libraryBase}\\${currentFolder.replace(/\//g, "\\")}` : libraryBase)} disabled={!libraryBase}><FolderOpen size={14} />打开</button>
                <button type="button" className="icon-button" onClick={() => void refresh()} disabled={loading} aria-label="刷新素材库"><RefreshCw size={14} className={loading ? "is-spinning" : ""} /></button>
              </span>
            </div>

            {selectedCount > 0 ? (
              <div className="library-selection-bar">
                <span>已选 {selectedCount} 项</span>
                <button type="button" className="quiet-button" onClick={selectAllVisible}><Check size={14} />全选当前</button>
                {tab === "bgm" ? (
                  <button type="button" className="quiet-button" onClick={() => addToBgmFiles(Array.from(selected))}><Music size={14} />选用为BGM</button>
                ) : null}
                <button type="button" className="quiet-button" onClick={() => setMoveOpen(true)}><Move size={14} />移动到…</button>
                <button type="button" className="quiet-button danger-text" onClick={() => void removeItems(tab, Array.from(selected))}><Trash2 size={14} />删除</button>
                <button type="button" className="quiet-button" onClick={() => setSelected(new Set())}><X size={14} />取消选择</button>
              </div>
            ) : null}

            {error ? <div className="library-error"><CircleAlert size={15} />{error}</div> : null}

            {tab === "bgm" ? (
              viewMode === "list" ? (
                <ul className="library-list">
                  {!loading && !visibleItems.length ? (
                    <li className="library-empty">
                      {currentFolder
                        ? <>这个文件夹还是空的。导入音频会保存到当前文件夹，或点击「批量拆BGM」从视频提取。</>
                        : <>BGM 库还是空的：点击「导入」，或使用「批量拆BGM」从视频中提取背景音乐。</>}
                    </li>
                  ) : null}
                  {visibleItems.map((item) => {
                    const isPlaying = playingPath === item.path;
                    const isSelected = selected.has(item.path);
                    return (
                      <li key={item.path} ref={registerItemRef(item.path)} className={`library-row${isSelected ? " is-selected" : ""}`}>
                        <input type="checkbox" className="library-checkbox" checked={isSelected} onChange={() => toggleSelected(item.path)} aria-label={`选择 ${item.name}`} />
                        <BgmCover path={item.path} size="small" />
                        <span className="library-row-main">
                          <strong title={item.path}>{item.name}</strong>
                          <small>{item.folder ? `${item.folder} · ` : ""}{formatBytes(item.size_bytes)} · {formatDuration(item.duration)}{item.added_at ? ` · 入库于 ${item.added_at}` : ""}</small>
                        </span>
                        <span className="library-row-actions">
                          <button type="button" className="icon-button" onClick={() => void togglePlay(item)} aria-label={isPlaying ? "停止试听" : "试听"}>
                            {isPlaying ? <Pause size={15} /> : <Play size={15} />}
                          </button>
                          <button type="button" className="icon-button" onClick={() => addToBgmFiles([item.path])} aria-label={`选用为BGM ${item.name}`} title="选用为当前工作区BGM"><Plus size={14} /></button>
                          <button type="button" className="icon-button" onClick={() => { setSelected(new Set([item.path])); setMoveOpen(true); }} aria-label={`移动 ${item.name}`}><Move size={14} /></button>
                          <button type="button" className="icon-button danger" onClick={() => void removeItems("bgm", [item.path])} aria-label={`删除 ${item.name}`}><Trash2 size={15} /></button>
                        </span>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <ul className="library-grid">
                  {!loading && !visibleItems.length ? (
                    <li className="library-empty">
                      {currentFolder
                        ? <>这个文件夹还是空的。导入音频会保存到当前文件夹，或点击「批量拆BGM」从视频提取。</>
                        : <>BGM 库还是空的：点击「导入」，或使用「批量拆BGM」从视频中提取背景音乐。</>}
                    </li>
                  ) : null}
                  {visibleItems.map((item) => {
                    const isPlaying = playingPath === item.path;
                    const isSelected = selected.has(item.path);
                    return (
                      <li key={item.path} ref={registerItemRef(item.path)} className={`library-card${isSelected ? " is-selected" : ""}`}>
                        <span className="library-card-check"><input type="checkbox" className="library-checkbox" checked={isSelected} onChange={() => toggleSelected(item.path)} aria-label={`选择 ${item.name}`} /></span>
                        <BgmCover
                          path={item.path}
                          overlay={
                            <>
                              {isPlaying ? <span className="library-bgm-cover-playing"><Pause size={16} /></span> : null}
                              {item.duration != null ? <span className="library-bgm-cover-badge">{formatDuration(item.duration)}</span> : null}
                            </>
                          }
                        />
                        <span className="library-card-meta">
                          <strong title={item.path}>{item.name}</strong>
                          <small>{item.folder ? `${item.folder} · ` : ""}{formatBytes(item.size_bytes)}</small>
                        </span>
                        <span className="library-card-actions">
                          <button type="button" className="icon-button" onClick={() => void togglePlay(item)} aria-label={isPlaying ? "停止试听" : "试听"}>
                            {isPlaying ? <Pause size={14} /> : <Play size={14} />}
                          </button>
                          <button type="button" className="icon-button" onClick={() => addToBgmFiles([item.path])} aria-label={`选用为BGM ${item.name}`} title="选用为当前工作区BGM"><Plus size={13} /></button>
                          <button type="button" className="icon-button" onClick={() => { setSelected(new Set([item.path])); setMoveOpen(true); }} aria-label={`移动 ${item.name}`}><Move size={13} /></button>
                          <button type="button" className="icon-button danger" onClick={() => void removeItems("bgm", [item.path])} aria-label={`删除 ${item.name}`}><Trash2 size={14} /></button>
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )
            ) : viewMode === "list" ? (
              <ul className="library-list">
                {!loading && !visibleItems.length ? (
                  <li className="library-empty">
                    {currentFolder
                      ? <>这个文件夹还是空的。导入的图片会保存到当前文件夹。</>
                      : <>水印库还是空的：点击「导入」把 Logo / 水印素材放进库中。</>}
                  </li>
                ) : null}
                {visibleItems.map((item) => {
                  const isSelected = selected.has(item.path);
                  const isVideo = item.type === "video";
                  const isPlaying = playingPath === item.path;
                  return (
                    <li key={item.path} ref={registerItemRef(item.path)} className={`library-row${isSelected ? " is-selected" : ""}`}>
                      <input type="checkbox" className="library-checkbox" checked={isSelected} onChange={() => toggleSelected(item.path)} aria-label={`选择 ${item.name}`} />
                      {isVideo ? (
                        <button type="button" className="library-thumb-play" onClick={() => void openVideoPreview(item)} aria-label={`播放预览 ${item.name}`} title="放大播放预览">
                          <span className="library-thumb-play-hint"><Play size={16} /></span>
                          <span className="library-thumb-wrap">
                            <WatermarkThumb path={item.path} size="small" />
                            {isPlaying ? <span className="library-thumb-playing"><Pause size={10} /></span> : null}
                            <span className="library-thumb-badge"><Play size={9} />{formatDuration(item.duration)}</span>
                          </span>
                        </button>
                      ) : (
                        <span className="library-thumb-wrap">
                          <WatermarkThumb path={item.path} size="small" />
                        </span>
                      )}
                      <span className="library-row-main">
                        <strong title={item.path}>{item.name}</strong>
                        <small>{item.folder ? `${item.folder} · ` : ""}{isVideo ? `${formatDuration(item.duration)} · ` : ""}{formatBytes(item.size_bytes)}{item.added_at ? ` · 入库于 ${item.added_at}` : ""}</small>
                      </span>
                      <span className="library-row-actions">
                        {isVideo ? <button type="button" className="icon-button" onClick={() => void openVideoPreview(item)} aria-label="放大播放预览" title="放大播放预览"><Play size={14} /></button> : null}
                        {isVideo ? <button type="button" className="quiet-button" onClick={() => useAsVideoWatermark(item)}><Stamp size={13} />用作视频水印</button> : null}
                        <button type="button" className="quiet-button" onClick={() => addWatermarkLayer(item)}><Plus size={13} />加入水印图层</button>
                        <button type="button" className="icon-button" onClick={() => { setSelected(new Set([item.path])); setMoveOpen(true); }} aria-label={`移动 ${item.name}`}><Move size={14} /></button>
                        <button type="button" className="icon-button danger" onClick={() => void removeItems("watermark", [item.path])} aria-label={`删除 ${item.name}`}><Trash2 size={15} /></button>
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <ul className="library-grid">
                {!loading && !visibleItems.length ? (
                  <li className="library-empty">
                    {currentFolder
                      ? <>这个文件夹还是空的。导入的图片会保存到当前文件夹。</>
                      : <>水印库还是空的：点击「导入」把 Logo / 水印素材放进库中。</>}
                  </li>
                ) : null}
                {visibleItems.map((item) => {
                  const isSelected = selected.has(item.path);
                  const isVideo = item.type === "video";
                  const isPlaying = playingPath === item.path;
                  return (
                    <li key={item.path} ref={registerItemRef(item.path)} className={`library-card${isSelected ? " is-selected" : ""}`}>
                      <span className="library-card-check"><input type="checkbox" className="library-checkbox" checked={isSelected} onChange={() => toggleSelected(item.path)} aria-label={`选择 ${item.name}`} /></span>
                      {isVideo ? (
                        <button type="button" className="library-thumb-play" onClick={() => void openVideoPreview(item)} aria-label={`播放预览 ${item.name}`} title="放大播放预览">
                          <span className="library-thumb-play-hint"><Play size={16} /></span>
                          <span className="library-thumb-wrap">
                            <WatermarkThumb path={item.path} />
                            {isPlaying ? <span className="library-thumb-playing"><Pause size={12} /></span> : null}
                            <span className="library-thumb-badge"><Play size={10} />{formatDuration(item.duration)}</span>
                          </span>
                        </button>
                      ) : (
                        <span className="library-thumb-wrap">
                          <WatermarkThumb path={item.path} />
                        </span>
                      )}
                      <span className="library-card-meta">
                        <strong title={item.path}>{item.name}</strong>
                        <small>{item.folder ? `${item.folder} · ` : ""}{isVideo ? `${formatDuration(item.duration)} · ` : ""}{formatBytes(item.size_bytes)}</small>
                      </span>
                      <span className="library-card-actions">
                        {isVideo ? <button type="button" className="icon-button" onClick={() => useAsVideoWatermark(item)} aria-label={`用作视频水印 ${item.name}`} title="用作视频水印（设为导出水印）"><Stamp size={14} /></button> : null}
                        <button type="button" className="icon-button" onClick={() => addWatermarkLayer(item)} aria-label={`加入水印图层 ${item.name}`} title="加入水印图层"><Layers size={14} /></button>
                        <button type="button" className="icon-button" onClick={() => { setSelected(new Set([item.path])); setMoveOpen(true); }} aria-label={`移动 ${item.name}`} title="移动"><Move size={13} /></button>
                        <button type="button" className="icon-button danger" onClick={() => void removeItems("watermark", [item.path])} aria-label={`删除 ${item.name}`} title="删除"><Trash2 size={14} /></button>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
            {marquee ? (
              <div
                className="library-marquee"
                style={{
                  left: marquee.x0,
                  top: marquee.y0,
                  width: marquee.x1 - marquee.x0,
                  height: marquee.y1 - marquee.y0,
                }}
                aria-hidden="true"
              />
            ) : null}
          </div>
          </>
          )}
        </div>

        <footer className="library-dialog-footer">
          <span>
            {tab === "bgm" ? (
              <button type="button" className="quiet-button" onClick={applyBgmDir} disabled={!dirs}><Check size={13} />用作BGM目录</button>
            ) : tab === "watermark" ? (
              <button type="button" className="quiet-button" onClick={applyWatermarkDir} disabled={!dirs}><Check size={13} />设为水印目录</button>
            ) : (
              <span className="effect-footer-hint">悬停卡片播放动画预览；「选用」设为当前{tab === "effect" ? "特效" : "转场"}，「+」加入随机池。</span>
            )}
          </span>
          <span className="library-dialog-footer-hint">素材库默认位于「文档 / 图转视频素材库」；导入与拆解会自动识别重复内容并跳过。</span>
          <button type="button" className="library-primary-button" onClick={onClose}>完成</button>
        </footer>
      </section>

      {moveOpen ? (
        <div className="library-backdrop library-backdrop-inner" role="presentation" onMouseDown={() => setMoveOpen(false)}>
          <section className="library-move-dialog" role="dialog" aria-modal="true" aria-labelledby="library-move-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="library-dialog-heading">
              <span className="library-dialog-icon"><Move size={20} /></span>
              <span>
                <small>移动素材</small>
                <strong id="library-move-title">移动到文件夹（{selectedCount} 项）</strong>
              </span>
              <button type="button" className="update-close" onClick={() => setMoveOpen(false)} aria-label="关闭移动窗口"><X size={17} /></button>
            </header>
            <div className="library-move-body">
              <MoveFolderList folders={tree} currentFolder={currentFolder} onPick={(folder) => void moveItems(tab as LibraryKind, Array.from(selected), folder)} />
            </div>
          </section>
        </div>
      ) : null}

      {extract.open ? (
        <div className="library-backdrop library-backdrop-inner" role="presentation" onMouseDown={() => { if (!extract.running) setExtract((current) => ({ ...current, open: false })); }}>
          <section className="library-extract-dialog" role="dialog" aria-modal="true" aria-labelledby="library-extract-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="library-dialog-heading">
              <span className="library-dialog-icon"><Scissors size={21} /></span>
              <span>
                <small>一键批量拆 BGM</small>
                <strong id="library-extract-title">从视频提取背景音乐</strong>
              </span>
              <button type="button" className="update-close" onClick={() => setExtract((current) => ({ ...current, open: false }))} disabled={extract.running} aria-label="关闭拆 BGM 窗口"><X size={17} /></button>
            </header>

            <div className="library-extract-body">
              <AddVideoSource
                running={extract.running}
                onAddFiles={addExtractFiles}
                onSetFolder={setExtractFolder}
                notify={notify}
              />
              <div className="library-extract-source-row">
                <label className="library-field">
                  <span>保存到</span>
                  <select value={extract.saveFolder} disabled={extract.running} onChange={(event) => setExtract((current) => ({ ...current, saveFolder: event.target.value }))} aria-label="保存到文件夹">
                    <option value="">BGM 库根目录</option>
                    {bgmFolders.map((folder) => <option key={folder.relative} value={folder.relative}>{folder.relative}</option>)}
                  </select>
                </label>
                <label className="library-check"><input type="checkbox" checked={extract.avoidDuplicates} disabled={extract.running} onChange={(event) => setExtract((current) => ({ ...current, avoidDuplicates: event.target.checked }))} /><span>识别避重：全库已有相同 BGM 自动跳过</span></label>
              </div>
              {extract.files.length || extract.folder ? (
                <ul className="library-extract-sources">
                  {extract.folder ? (
                    <li>
                      <FolderOpen size={13} /><span title={extract.folder}>{extract.folder}（文件夹，递归查找）</span>
                      {!extract.running ? <button type="button" className="icon-button danger" onClick={() => setExtract((current) => ({ ...current, folder: "" }))} aria-label="移除文件夹"><X size={13} /></button> : null}
                    </li>
                  ) : null}
                  {extract.files.slice(0, 200).map((file) => (
                    <li key={file}>
                      <FileVideo size={13} /><span title={file}>{file}</span>
                      {!extract.running ? <button type="button" className="icon-button danger" onClick={() => setExtract((current) => ({ ...current, files: current.files.filter((item) => item !== file) }))} aria-label="移除视频"><X size={13} /></button> : null}
                    </li>
                  ))}
                  {extract.files.length > 200 ? <li className="library-extract-more">…还有 {extract.files.length - 200} 个文件</li> : null}
                </ul>
              ) : null}

              {extract.running || extract.results.length ? (
                <div className="library-extract-progress">
                  <div className="library-extract-progress-head">
                    <strong>{extract.running ? `正在拆解 ${extract.done} / ${extract.total || "…"}` : "拆解完成"}</strong>
                    {extract.summary ? (
                      <span>
                        成功 {extract.summary.saved} · 重复跳过 {extract.summary.duplicate} · 无音轨 {extract.summary.no_audio}{extract.summary.cancelled ? ` · 已取消 ${extract.summary.cancelled}` : ""} · 失败 {extract.summary.failed}
                      </span>
                    ) : null}
                  </div>
                  {extract.running ? (
                    <div className="update-progress" aria-label={`拆解进度 ${extract.total ? Math.round((extract.done / extract.total) * 100) : 0}%`}>
                      <span style={{ transform: `scaleX(${extract.total ? Math.min(1, extract.done / extract.total) : 0})` }} />
                      <small>{extract.total ? `${Math.round((extract.done / extract.total) * 100)}%` : "准备中…"}</small>
                    </div>
                  ) : null}
                  <ul className="library-extract-results">
                    {extract.results.map((result) => {
                      const meta = STATUS_LABELS[result.status] ?? STATUS_LABELS.failed;
                      return (
                        <li key={result.video}>
                          <span className={`library-extract-status ${meta.className}`}>{meta.label}</span>
                          <span className="library-extract-name" title={result.video}>
                            {result.name}
                            {result.reason ? <small>{result.reason}</small> : null}
                          </span>
                          {result.status === "saved" && result.duration ? <span className="library-extract-duration">{formatDuration(result.duration)}</span> : null}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ) : null}
            </div>

            <footer className="library-dialog-footer">
              <span>提取结果将保存到：{extract.saveFolder ? `${dirs?.bgm_dir ?? ""}\\${extract.saveFolder.replace(/\//g, "\\")}` : dirs?.bgm_dir ?? ""}</span>
              <span className="library-dialog-footer-actions">
                <button type="button" className="quiet-button" onClick={() => void cancelExtract()} disabled={!extract.running}>取消任务</button>
                <button type="button" className="library-accent-button" onClick={() => void startExtract()} disabled={extract.running || (!extract.files.length && !extract.folder)}>
                  {extract.running ? <Loader2 className="is-spinning" size={14} /> : <Scissors size={14} />}
                  {extract.running ? "拆解中…" : "开始批量拆 BGM"}
                </button>
              </span>
            </footer>
          </section>
        </div>
      ) : null}

      {jianying.open ? (
        <div className="library-backdrop library-backdrop-inner" role="presentation" onMouseDown={() => { if (!jianying.scanning && !jianying.busy) setJianying((current) => ({ ...current, open: false })); }}>
          <section className="library-move-dialog library-jianying-dialog" role="dialog" aria-modal="true" aria-labelledby="library-jianying-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="library-dialog-heading">
              <span className="library-dialog-icon"><Clapperboard size={20} /></span>
              <span>
                <small>从剪映导入</small>
                <strong id="library-jianying-title">导入剪映素材到素材库</strong>
              </span>
              <button type="button" className="update-close" onClick={() => setJianying((current) => ({ ...current, open: false }))} disabled={jianying.scanning || jianying.busy} aria-label="关闭从剪映导入窗口"><X size={17} /></button>
            </header>

            <div className="library-move-body">
              <div className="library-jianying-source" role="group" aria-label="导入来源">
                <button type="button" className={jianying.source === "draft" ? "is-active" : ""} onClick={() => switchJianyingSource("draft")} disabled={jianying.scanning || jianying.busy}>草稿素材</button>
                <button type="button" className={jianying.source === "cache" ? "is-active" : ""} onClick={() => switchJianyingSource("cache")} disabled={jianying.scanning || jianying.busy}>内置资源（缓存）</button>
              </div>

              {jianying.scanning ? (
                <div className="library-jianying-empty">
                  <Loader2 className="is-spinning" size={18} />
                  <span>{jianying.source === "cache" ? "正在扫描剪映内置资源缓存…" : "正在扫描剪映草稿箱…"}</span>
                </div>
              ) : jianying.error ? (
                <div className="library-jianying-empty">
                  <CircleAlert size={18} />
                  <span>{jianying.error}</span>
                  <button type="button" className="quiet-button" onClick={() => void pickDraftRoot()}><FolderOpen size={13} />手动选择{jianying.source === "cache" ? "缓存" : "草稿"}目录</button>
                </div>
              ) : jianying.source === "cache" && jianying.cacheResult ? (
                <>
                  <p className="library-jianying-note" title={jianying.cacheResult.cache_root}>
                    内置资源缓存：{jianying.cacheResult.cache_root}
                    <small>已扫描 {jianying.cacheResult.scanned_files} 个文件 · 仅包含已下载到本地的内置资源</small>
                  </p>
                  {jianying.cacheResult.truncated ? <p className="library-jianying-warn">缓存文件较多，已提前停止扫描，部分资源可能未列出。</p> : null}
                  <div className="library-jianying-stats">
                    <span><strong>{jianying.cacheResult.audios.length}</strong> 条内置 BGM / 音效</span>
                    <span><strong>{jianying.cacheResult.videos.length}</strong> 个内置视频资源（特效 / 转场）</span>
                  </div>
                  {jianying.cacheResult.audios.length ? (
                    <ul className="library-jianying-list">
                      {jianying.cacheResult.audios.slice(0, 8).map((entry) => (
                        <li key={entry.path}>
                          <Music size={12} />
                          <span title={entry.path}>{entry.name}</span>
                          <small>{entry.draft}</small>
                        </li>
                      ))}
                      {jianying.cacheResult.audios.length > 8 ? <li className="library-jianying-more">…还有 {jianying.cacheResult.audios.length - 8} 条</li> : null}
                    </ul>
                  ) : null}
                  <p className="library-jianying-hint">
                    未下载的云端资源请先在剪映中使用或下载；视频资源导入水印库后可作视频水印叠加（透明视频保留 alpha）。
                    剪映内置模板与曲库资源仅供个人本地使用。
                  </p>
                  {jianying.busy ? (
                    <p className="library-jianying-busy">
                      <Loader2 className="is-spinning" size={13} />
                      <span>正在导入{jianying.importing === "bgm" ? " BGM / 音效" : "水印素材"}…{jianying.importing === "bgm" ? "（自动避重，请稍候）" : ""}</span>
                    </p>
                  ) : null}
                  {jianying.summary ? (
                    <p className={`library-jianying-summary${jianying.summary.ok ? " is-success" : " is-error"}`}>
                      {jianying.summary.ok ? <Check size={13} /> : <CircleAlert size={13} />}
                      <span>{jianying.summary.text}</span>
                    </p>
                  ) : null}
                  <div className="library-jianying-actions">
                    <button type="button" className="library-accent-button" onClick={() => void importJianying("bgm")} disabled={jianying.busy || !jianying.cacheResult.audios.length}>
                      {jianying.busy ? <Loader2 className="is-spinning" size={13} /> : <Music size={13} />}导入 BGM（{jianying.cacheResult.audios.length}）
                    </button>
                    <button type="button" className="library-accent-button" onClick={() => void importJianying("watermark")} disabled={jianying.busy || !jianying.cacheResult.videos.length}>
                      {jianying.busy ? <Loader2 className="is-spinning" size={13} /> : <ImageIcon size={13} />}导入水印库（{jianying.cacheResult.videos.length}）
                    </button>
                    <button type="button" className="quiet-button" onClick={() => void pickDraftRoot()} disabled={jianying.busy}><FolderOpen size={13} />更换目录</button>
                    <button type="button" className="quiet-button" onClick={() => void scanJianying()} disabled={jianying.busy}><RefreshCw size={13} />重新扫描</button>
                  </div>
                </>
              ) : jianying.source === "draft" && jianying.result ? (
                <>
                  <p className="library-jianying-note" title={jianying.result.draft_root}>
                    草稿箱：{jianying.result.draft_root}
                    <small>共 {jianying.result.drafts.length} 个草稿</small>
                  </p>
                  <div className="library-jianying-stats">
                    <span><strong>{jianying.result.audios.length}</strong> 条 BGM / 音效</span>
                    <span><strong>{jianying.result.videos.length}</strong> 个视频</span>
                    <span><strong>{jianying.result.images.length}</strong> 张图片</span>
                    <span><strong>{jianying.result.effects.length}</strong> 个特效资源</span>
                    <span><strong>{jianying.result.transitions.length}</strong> 个转场资源</span>
                  </div>
                  {jianying.result.audios.length ? (
                    <ul className="library-jianying-list">
                      {jianying.result.audios.slice(0, 8).map((entry) => (
                        <li key={entry.path}>
                          <Music size={12} />
                          <span title={entry.path}>{entry.name}</span>
                          <small>{entry.draft}</small>
                        </li>
                      ))}
                      {jianying.result.audios.length > 8 ? <li className="library-jianying-more">…还有 {jianying.result.audios.length - 8} 条</li> : null}
                    </ul>
                  ) : null}
                  <p className="library-jianying-hint">
                    BGM 导入会自动避重（已有相同内容跳过）；视频 / 图片 / 特效与转场资源导入水印库，可作视频水印叠加使用。
                    剪映内置模板与曲库资源仅供个人本地使用；纯云端模板（无本地文件）无法导入。
                  </p>
                  {jianying.busy ? (
                    <p className="library-jianying-busy">
                      <Loader2 className="is-spinning" size={13} />
                      <span>正在导入{jianying.importing === "bgm" ? " BGM / 音效" : "水印素材"}…{jianying.importing === "bgm" ? "（自动避重，请稍候）" : ""}</span>
                    </p>
                  ) : null}
                  {jianying.summary ? (
                    <p className={`library-jianying-summary${jianying.summary.ok ? " is-success" : " is-error"}`}>
                      {jianying.summary.ok ? <Check size={13} /> : <CircleAlert size={13} />}
                      <span>{jianying.summary.text}</span>
                    </p>
                  ) : null}
                  <div className="library-jianying-actions">
                    <button type="button" className="library-accent-button" onClick={() => void importJianying("bgm")} disabled={jianying.busy || !jianying.result.audios.length}>
                      {jianying.busy ? <Loader2 className="is-spinning" size={13} /> : <Music size={13} />}导入 BGM（{jianying.result.audios.length}）
                    </button>
                    <button type="button" className="library-accent-button" onClick={() => void importJianying("watermark")} disabled={jianying.busy || !(jianying.result.videos.length + jianying.result.images.length + jianying.result.effects.length + jianying.result.transitions.length)}>
                      {jianying.busy ? <Loader2 className="is-spinning" size={13} /> : <ImageIcon size={13} />}导入水印库（{jianying.result.videos.length + jianying.result.images.length + jianying.result.effects.length + jianying.result.transitions.length}）
                    </button>
                    <button type="button" className="quiet-button" onClick={() => void pickDraftRoot()} disabled={jianying.busy}><FolderOpen size={13} />更换目录</button>
                    <button type="button" className="quiet-button" onClick={() => void scanJianying()} disabled={jianying.busy}><RefreshCw size={13} />重新扫描</button>
                  </div>
                </>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}

      {videoPreview ? (
        <div className="library-backdrop library-backdrop-inner library-video-backdrop" role="presentation" onMouseDown={() => { setVideoPreview(null); setVideoUrl(null); setPlayingPath(null); }}>
          <section className="library-video-player" role="dialog" aria-modal="true" aria-label={`播放预览 ${videoPreview.name}`} onMouseDown={(event) => event.stopPropagation()}>
            <header className="library-dialog-heading">
              <span className="library-dialog-icon"><Clapperboard size={20} /></span>
              <span>
                <small>视频水印预览</small>
                <strong title={videoPreview.name}>{videoPreview.name}</strong>
              </span>
              <button type="button" className="update-close" onClick={() => { setVideoPreview(null); setVideoUrl(null); setPlayingPath(null); }} aria-label="关闭视频预览"><X size={17} /></button>
            </header>
            <div className="library-video-player-body">
              {videoUrl ? (
                <video
                  key={videoUrl}
                  className="library-video-player-media"
                  src={videoUrl}
                  controls
                  autoPlay
                  playsInline
                  onEnded={() => setPlayingPath(null)}
                />
              ) : (
                <div className="library-video-player-loading">
                  <Loader2 className="is-spinning" size={20} />
                  <span>正在准备视频预览…</span>
                </div>
              )}
            </div>
          </section>
        </div>
      ) : null}

      <audio ref={audioRef} className="library-audio" />
    </div>
  );

  return createPortal(dialog, document.body);
}

function FolderNode({ nodes, depth, currentFolder, expanded, creatingUnder, renaming, folderDraft, onFolderDraft, onSelect, onToggle, onStartCreate, onStartRename, onDelete, onCommit, onCancelEdit }: {
  nodes: TreeNode[];
  depth: number;
  currentFolder: string;
  expanded: Set<string>;
  creatingUnder: string | null;
  renaming: string | null;
  folderDraft: string;
  onFolderDraft: (value: string) => void;
  onSelect: (folder: string) => void;
  onToggle: (folder: string) => void;
  onStartCreate: (parent: string) => void;
  onStartRename: (folder: string) => void;
  onDelete: (folder: string) => void;
  onCommit: () => void;
  onCancelEdit: () => void;
}) {
  return (
    <>
      {nodes.map((node) => {
        const isExpanded = expanded.has(node.relative);
        const isActive = currentFolder === node.relative;
        const isEditing = creatingUnder === node.relative || renaming === node.relative;
        return (
          <div key={node.relative}>
            <span className={`library-tree-node${isActive ? " is-active" : ""}`} style={{ paddingLeft: 10 + depth * 16 }} role="treeitem" aria-expanded={isExpanded} aria-selected={isActive}>
              {node.children.length ? (
                <button type="button" className="library-tree-chevron" onClick={() => onToggle(node.relative)} aria-label={isExpanded ? `折叠 ${node.name}` : `展开 ${node.name}`}>
                  {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                </button>
              ) : <span className="library-tree-chevron-empty" />}
              <button type="button" className="library-tree-folder" onClick={() => onSelect(node.relative)}>
                {isExpanded ? <FolderOpen size={14} /> : <Folder size={14} />}
                {isEditing ? (
                  <input
                    autoFocus
                    className="library-folder-input"
                    value={folderDraft}
                    onChange={(event) => onFolderDraft(event.target.value)}
                    onClick={(event) => event.stopPropagation()}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") onCommit();
                      if (event.key === "Escape") onCancelEdit();
                    }}
                  />
                ) : <span>{node.name}</span>}
                <small>{node.count}</small>
              </button>
              <span className="library-tree-actions">
                <button type="button" className="icon-button" onClick={() => onStartCreate(node.relative)} aria-label={`在 ${node.name} 下新建文件夹`}><FolderPlus size={12} /></button>
                <button type="button" className="icon-button" onClick={() => onStartRename(node.relative)} aria-label={`重命名 ${node.name}`}><Pencil size={12} /></button>
                <button type="button" className="icon-button danger" onClick={() => onDelete(node.relative)} aria-label={`删除文件夹 ${node.name}`}><Trash2 size={12} /></button>
              </span>
            </span>
            {creatingUnder === node.relative ? (
              <span className="library-tree-node" style={{ paddingLeft: 10 + (depth + 1) * 16 }}>
                <span className="library-tree-chevron-empty" />
                <Folder size={14} />
                <input autoFocus className="library-folder-input" placeholder="文件夹名称" value={folderDraft} onChange={(event) => onFolderDraft(event.target.value)} onKeyDown={(event) => {
                  if (event.key === "Enter") onCommit();
                  if (event.key === "Escape") onCancelEdit();
                }} />
              </span>
            ) : null}
            {isExpanded && node.children.length ? (
              <FolderNode
                nodes={node.children}
                depth={depth + 1}
                currentFolder={currentFolder}
                expanded={expanded}
                creatingUnder={creatingUnder}
                renaming={renaming}
                folderDraft={folderDraft}
                onFolderDraft={onFolderDraft}
                onSelect={onSelect}
                onToggle={onToggle}
                onStartCreate={onStartCreate}
                onStartRename={onStartRename}
                onDelete={onDelete}
                onCommit={onCommit}
                onCancelEdit={onCancelEdit}
              />
            ) : null}
          </div>
        );
      })}
    </>
  );
}

function MoveFolderList({ folders, currentFolder, onPick }: {
  folders: TreeNode[];
  currentFolder: string;
  onPick: (folder: string) => void;
}) {
  const rows: Array<{ relative: string; name: string; depth: number }> = [];
  const walk = (nodes: TreeNode[], depth: number) => {
    for (const node of nodes) {
      rows.push({ relative: node.relative, name: node.name, depth });
      walk(node.children, depth + 1);
    }
  };
  walk(folders, 0);
  return (
    <ul className="library-move-list">
      <li>
        <button type="button" className={currentFolder === "" ? "is-active" : ""} onClick={() => onPick("")}>
          <FolderOpen size={14} /><span>库根目录</span>
        </button>
      </li>
      {rows.map((row) => (
        <li key={row.relative}>
          <button type="button" style={{ paddingLeft: 12 + row.depth * 16 }} className={currentFolder === row.relative ? "is-active" : ""} onClick={() => onPick(row.relative)}>
            <Folder size={14} /><span>{row.relative}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function WatermarkThumb({ path, size = "normal" }: { path: string; size?: "small" | "normal" }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void engine.call<{ preview_path: string }>("preview_thumbnail", { path, max_width: 240, max_height: 240 }, 30_000)
      .then((result) => {
        if (!cancelled) setUrl(engine.toAssetUrl(result.preview_path));
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => { cancelled = true; };
  }, [path]);

  if (url) return <img className={`library-thumb${size === "small" ? " is-small" : ""}`} src={url} alt="" />;
  return (
    <span className={`library-thumb-placeholder${size === "small" ? " is-small" : ""}`}>
      {failed ? <CircleAlert size={18} /> : <Loader2 className="is-spinning" size={18} />}
    </span>
  );
}

type LibrarySnapshotLike = LibraryDirs & {
  bgm: LibraryItem[];
  bgm_folders: LibraryFolder[];
  watermark: LibraryItem[];
  watermark_folders: LibraryFolder[];
};