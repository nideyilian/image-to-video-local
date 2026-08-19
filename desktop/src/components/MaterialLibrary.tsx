import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent as ReactDragEvent, type PointerEvent as ReactPointerEvent, type RefObject } from "react";
import { createPortal } from "react-dom";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import {
  ArrowDown,
  ArrowLeftRight,
  ArrowRight,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clapperboard,
  FileVideo,
  Folder,
  FolderCog,
  FolderOpen,
  FolderPlus,
  GitCompareArrows,
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
  SlidersHorizontal,
  Sparkles,
  Stamp,
  Star,
  StickyNote,
  Tag,
  Trash2,
  Upload,
  Wand2,
  X,
} from "lucide-react";
import { DEFAULT_WATERMARK_LAYER, TRANSITIONS, VIDEO_EFFECTS } from "../constants";
import { engine } from "../engine";
import { AddVideoSource } from "./AddVideoSource";
import { BgmCover } from "./BgmCover";
import { EffectLibraryPanel } from "./EffectLibraryPanel";
import type {
  LibraryDirs,
  LibraryDupResult,
  LibraryExtractResult,
  LibraryExtractSummary,
  LibraryFolder,
  LibraryImportResult,
  LibraryItem,
  LibraryKind,
  LibraryMoveResult,
  LibraryRenameBatchResult,
  LibrarySmartFolder,
  LibrarySmartFolderCondition,
  LibraryTagCount,
  VideoConfig,
} from "../types";

const LIBRARY_KEY = "image-to-video.library.v1";
const VIEW_KEY = "image-to-video.library.view";
const THUMB_KEY = "image-to-video.library.thumb";

const THUMB_MIN = 96;
const THUMB_MAX = 280;

function loadThumbSize(): number {
  try {
    const raw = Number(localStorage.getItem(THUMB_KEY));
    if (Number.isFinite(raw) && raw >= THUMB_MIN && raw <= THUMB_MAX) return Math.round(raw);
  } catch {
    /* 忽略 */
  }
  return 176;
}

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

function formatAddedAt(iso: string | null | undefined) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatClock(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function recountFolderCounts(items: LibraryItem[], folders: LibraryFolder[]): LibraryFolder[] {
  return folders.map((folder) => {
    const count = items.filter((item) => item.folder === folder.relative || item.folder.startsWith(`${folder.relative}/`)).length;
    return { ...folder, count };
  });
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

function conditionValue(item: LibraryItem, field: LibrarySmartFolderCondition["field"]): string | number | boolean {
  if (field === "type") return item.type;
  if (field === "duration") return item.duration ?? -1;
  if (field === "size") return item.size_bytes;
  if (field === "folder") return item.folder;
  if (field === "name") return item.name;
  if (field === "tag") return item.tags.join(" ");
  if (field === "starred") return item.starred;
  return "";
}

function matchesCondition(item: LibraryItem, condition: LibrarySmartFolderCondition): boolean {
  const actual = conditionValue(item, condition.field);
  const op = condition.op;
  const expected = condition.value;
  if (op === "exists") {
    if (condition.field === "tag") return item.tags.length > 0;
    if (condition.field === "starred") return item.starred;
    return String(actual).trim().length > 0;
  }
  if (op === "eq") {
    if (typeof actual === "number") return actual === Number(expected);
    return String(actual).toLowerCase() === String(expected ?? "").toLowerCase();
  }
  if (op === "ne") {
    if (typeof actual === "number") return actual !== Number(expected);
    return String(actual).toLowerCase() !== String(expected ?? "").toLowerCase();
  }
  if (op === "gt") return Number(actual) > Number(expected);
  if (op === "lt") return Number(actual) < Number(expected);
  if (op === "contains") return String(actual).toLowerCase().includes(String(expected ?? "").toLowerCase());
  return false;
}

function matchesSmartFolder(item: LibraryItem, folder: LibrarySmartFolder): boolean {
  return folder.conditions.every((condition) => matchesCondition(item, condition));
}

const SMART_FIELD_NAMES: Record<string, string> = {
  type: "类型", duration: "时长(秒)", size: "大小(字节)", folder: "文件夹", name: "名称", tag: "标签", starred: "收藏",
};
const SMART_OP_NAMES: Record<string, string> = {
  eq: "=", ne: "≠", gt: ">", lt: "<", contains: "包含", exists: "存在",
};

function smartFolderRuleSummary(folder: LibrarySmartFolder): string {
  if (!folder.conditions.length) return "无条件（显示全部）";
  return folder.conditions
    .map((condition) => {
      const field = SMART_FIELD_NAMES[condition.field] ?? condition.field;
      const op = SMART_OP_NAMES[condition.op] ?? condition.op;
      return condition.op === "exists" ? `${field} 存在` : `${field} ${op} ${String(condition.value ?? "")}`;
    })
    .join(" 且 ");
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
  const [importingCount, setImportingCount] = useState(0);
  const [currentFolder, setCurrentFolder] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<ViewMode>(() => loadViewMode("bgm"));
  const [search, setSearch] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [filterType, setFilterType] = useState<"all" | "image" | "video">("all");
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
  // 视频预览的宽高比（height/width）；null 表示元数据尚未就绪
  const [videoAspect, setVideoAspect] = useState<number | null>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const mountedRef = useRef(true);
  const videoMetaTimerRef = useRef<number | null>(null);
  const visibleItemsRef = useRef<LibraryItem[]>([]);
  const searchTimerRef = useRef<number | null>(null);
  const [imagePreview, setImagePreview] = useState<{ path: string; name: string } | null>(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [confirm, setConfirm] = useState<{ title: string; message: string; confirmLabel: string; onConfirm: () => void } | null>(null);
  const [renameOpen, setRenameOpen] = useState<{ kind: LibraryKind; path: string; name: string } | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  // ---------- Eagle 风格素材管理：标签 / 星标 / 备注 / 去重 / 批量重命名 / 缩略图 / 智能文件夹 ----------
  const [tagFilter, setTagFilter] = useState("");
  const [starFilter, setStarFilter] = useState(false);
  const [allTags, setAllTags] = useState<LibraryTagCount[]>([]);
  const [detail, setDetail] = useState<LibraryItem | null>(null);
  const [detailDraft, setDetailDraft] = useState<{ tags: string[]; note: string; starred: boolean }>({ tags: [], note: "", starred: false });
  const [detailTagDraft, setDetailTagDraft] = useState("");
  const [dupOpen, setDupOpen] = useState(false);
  const [dupState, setDupState] = useState<{ scanning: boolean; result: LibraryDupResult | null; checked: Set<string> }>({ scanning: false, result: null, checked: new Set() });
  const [batchRenameOpen, setBatchRenameOpen] = useState(false);
  const [batchRename, setBatchRename] = useState<{ pattern: string; startIndex: number; items: LibraryItem[]; preview: Array<{ old: string; next: string; ok: boolean; reason?: string }>; applying: boolean }>({ pattern: "", startIndex: 1, items: [], preview: [], applying: false });
  const [thumbSize, setThumbSize] = useState(() => loadThumbSize());
  const [smartFolders, setSmartFolders] = useState<LibrarySmartFolder[]>([]);
  const [smartFolderOpen, setSmartFolderOpen] = useState(false);
  const [smartFolderEdit, setSmartFolderEdit] = useState<LibrarySmartFolder | null>(null);
  const [activeSmartFolder, setActiveSmartFolder] = useState<string | null>(null);

  const closeVideoPreview = useCallback(() => {
    if (videoMetaTimerRef.current !== null) {
      window.clearTimeout(videoMetaTimerRef.current);
      videoMetaTimerRef.current = null;
    }
    setVideoPreview(null);
    setVideoUrl(null);
    setVideoAspect(null);
    setPlayingPath(null);
  }, []);

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

  const refreshTags = useCallback(async () => {
    if (!engine.desktopRuntime || !dirs) return;
    try {
      const result = await engine.call<{ tags?: LibraryTagCount[] }>(
        "library_get_tags",
        { kind: tab, bgm_dir: dirs.bgm_dir, watermark_dir: dirs.watermark_dir },
        15_000,
      );
      if (!mountedRef.current) return;
      setAllTags(Array.isArray(result?.tags) ? result.tags : []);
    } catch {
      /* 标签加载失败不阻塞使用 */
    }
  }, [dirs, tab]);

  const loadSmartFolders = useCallback(async () => {
    if (!engine.desktopRuntime || !dirs) return;
    try {
      const result = await engine.call<{ folders?: LibrarySmartFolder[] }>(
        "library_smart_folders_list",
        { bgm_dir: dirs.bgm_dir },
        15_000,
      );
      if (!mountedRef.current) return;
      setSmartFolders(Array.isArray(result?.folders) ? result.folders : []);
    } catch {
      /* 智能文件夹读取失败不阻塞使用 */
    }
  }, [dirs]);

  useEffect(() => {
    if (!open) return;
    void refreshTags();
    void loadSmartFolders();
  }, [open, refreshTags, loadSmartFolders]);

  useEffect(() => {
    if (!open) return;
    void refreshTags();
  }, [items, open, refreshTags]);

  useEffect(() => {
    localStorage.setItem(`${VIEW_KEY}.${tab}`, viewMode);
  }, [tab, viewMode]);

  useEffect(() => {
    if (!open) return;
    void (async () => {
      if (!engine.desktopRuntime) return;
      // 已加载过快照则直接复用，避免每次进入都重新扫描整个库；外部改动可点「刷新」
      if (dirs) return;
      const stored = loadStoredDirs();
      const defaults = await engine.call<LibraryDirs>("library_dirs", {}, 15_000);
      const nextDirs: LibraryDirs = {
        bgm_dir: stored.bgm_dir || defaults.bgm_dir,
        watermark_dir: stored.watermark_dir || defaults.watermark_dir,
        library_root: defaults.library_root,
      };
      setDirs(nextDirs);
      await refresh(nextDirs);
    })();
  }, [open, dirs, refresh]);

  // 响应外部标签页定位请求（检查器「在素材库配置」）
  useEffect(() => {
    if (!open || !requestTab) return;
    setTab(requestTab);
    onConsumeTabRequest?.();
  }, [open, onConsumeTabRequest, requestTab]);

  useEffect(() => {
    if (open) return;
    audioRef.current?.pause();
    closeVideoPreview();
    setImagePreview(null);
    setImageFailed(false);
    setConfirm(null);
    setRenameOpen(null);
    setDetail(null);
    setDetailTagDraft("");
    setDupOpen(false);
    setBatchRenameOpen(false);
    setSmartFolderOpen(false);
    setSmartFolderEdit(null);
  }, [open, closeVideoPreview]);

  useEffect(() => {
    setViewMode(loadViewMode(tab === "watermark" ? "watermark" : "bgm"));
    setCurrentFolder("");
    setSearch("");
    setSearchDraft("");
    setFilterType("all");
    setSelected(new Set());
    setTagFilter("");
    setStarFilter(false);
    setActiveSmartFolder(null);
  }, [tab]);

  useEffect(() => {
    try {
      localStorage.setItem(THUMB_KEY, String(thumbSize));
    } catch {
      /* 忽略 */
    }
  }, [thumbSize]);

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
        if (imagePreview) {
          setImagePreview(null);
          setImageFailed(false);
          return;
        }
        if (renameOpen) {
          setRenameOpen(null);
          return;
        }
        if (confirm) {
          setConfirm(null);
          return;
        }
        if (videoPreview) {
          closeVideoPreview();
          return;
        }
        if (detail) {
          setDetail(null);
          setDetailTagDraft("");
          return;
        }
        if (dupOpen) {
          setDupOpen(false);
          return;
        }
        if (batchRenameOpen) {
          setBatchRenameOpen(false);
          return;
        }
        if (smartFolderOpen) {
          setSmartFolderOpen(false);
          setSmartFolderEdit(null);
          return;
        }
        onClose();
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
        event.preventDefault();
        setSelected(new Set(visibleItemsRef.current.map((item) => item.path)));
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
  }, [open, onClose, videoPreview, imagePreview, renameOpen, confirm, closeVideoPreview, detail, dupOpen, batchRenameOpen, smartFolderOpen]);

  const selectFolder = useCallback((folder: string) => {
    setCurrentFolder(folder);
    setSearch("");
    setSearchDraft("");
    setSelected(new Set());
    if (folder) {
      setExpanded((current) => {
        const next = new Set(current);
        ancestorsOf(folder).forEach((ancestor) => next.add(ancestor));
        return next;
      });
    }
  }, []);

  const handleSearchChange = useCallback((value: string) => {
    setSearchDraft(value);
    if (searchTimerRef.current !== null) {
      window.clearTimeout(searchTimerRef.current);
    }
    searchTimerRef.current = window.setTimeout(() => setSearch(value), 150);
  }, []);

  const clearSearch = useCallback(() => {
    setSearch("");
    setSearchDraft("");
    if (searchTimerRef.current !== null) {
      window.clearTimeout(searchTimerRef.current);
      searchTimerRef.current = null;
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
    const activeSmart = activeSmartFolder ? smartFolders.find((folder) => folder.id === activeSmartFolder) ?? null : null;
    const inScope = (item: LibraryItem) => {
      if (activeSmart) return matchesSmartFolder(item, activeSmart);
      if (!query) return item.folder === currentFolder;
      return item.folder === currentFolder || (currentFolder ? item.folder.startsWith(`${currentFolder}/`) : true);
    };
    let list = items.filter((item) =>
      inScope(item)
      && (filterType === "all" || item.type === filterType)
      && (!starFilter || item.starred)
      && (!tagFilter || item.tags.includes(tagFilter))
      && (!query || `${item.name} ${item.folder} ${(item.tags ?? []).join(" ")}`.toLowerCase().includes(query)),
    );
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
  }, [activeSmartFolder, currentFolder, filterType, items, search, smartFolders, sortDesc, sortKey, starFilter, tagFilter]);

  useEffect(() => {
    visibleItemsRef.current = visibleItems;
  }, [visibleItems]);

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
    if (importingCount > 0) return notify("info", "已有素材正在导入，请稍候");
    const filters = kind === "bgm" ? BGM_FILTERS : WATERMARK_FILTERS;
    const picked = await openDialog({ multiple: true, directory: false, title: kind === "bgm" ? "选择要导入 BGM 库的音频" : "选择要导入水印库的图片", filters });
    if (!picked || !picked.length) return;
    setImportingCount(picked.length);
    notify("info", `正在导入 ${picked.length} 个素材…`);
    try {
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
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "导入失败");
    } finally {
      setImportingCount(0);
    }
  }, [dirs, importingCount, notify, refresh]);

  const removeItems = useCallback(async (kind: LibraryKind, paths: string[]) => {
    if (!dirs) return;
    let removed: Array<{ name: string; path: string; status: string; reason?: string }> = [];
    try {
      const result = await engine.call<{ results: Array<{ name: string; path: string; status: string; reason?: string }> }>(
        "library_remove_batch",
        { kind, paths, bgm_dir: dirs.bgm_dir, watermark_dir: dirs.watermark_dir },
        300_000,
      );
      removed = result.results.filter((item) => item.status === "removed");
      const failed = result.results.filter((item) => item.status === "failed").length;
      const firstError = result.results.find((item) => item.status === "failed")?.reason ?? "";
      if (removed.length && !failed) {
        notify("success", `已把 ${removed.length} 个素材移入回收站`);
      } else if (removed.length && failed) {
        notify("error", `已把 ${removed.length} 个素材移入回收站，${failed} 个失败：${firstError}`);
      } else {
        notify("error", `移入回收站失败：${firstError || "未知错误"}`);
      }
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "移入回收站失败");
    }
    if (!removed.length) return;
    // 本地增量更新，避免删除后全量重扫
    const removedPaths = new Set(removed.map((item) => item.path));
    if (kind === "bgm") {
      const nextItems = bgm.filter((item) => !removedPaths.has(item.path));
      setBgm(nextItems);
      setBgmFolders(recountFolderCounts(nextItems, bgmFolders));
    } else {
      const nextItems = watermark.filter((item) => !removedPaths.has(item.path));
      setWatermark(nextItems);
      setWatermarkFolders(recountFolderCounts(nextItems, watermarkFolders));
    }
    setSelected((current) => {
      const next = new Set(current);
      removedPaths.forEach((path) => next.delete(path));
      return next;
    });
  }, [bgm, bgmFolders, dirs, notify, watermark, watermarkFolders]);

  const requestRemove = useCallback((kind: LibraryKind, paths: string[]) => {
    const name = paths.length === 1 ? (paths[0].split(/[\\/]/).pop() ?? paths[0]) : "";
    setConfirm({
      title: "删除素材",
      message: paths.length === 1
        ? `确定删除「${name}」吗？删除后会移入系统回收站，可在回收站中还原。`
        : `确定删除这 ${paths.length} 个素材吗？删除后会移入系统回收站，可在回收站中还原。`,
      confirmLabel: "移入回收站",
      onConfirm: () => { void removeItems(kind, paths); },
    });
  }, [removeItems]);

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

  // ---------- 拖拽移动：把「移动」按钮当作拖拽手柄，拖到左侧文件夹即移动 ----------
  const dragPathsRef = useRef<string[]>([]);
  const [dropTarget, setDropTarget] = useState<string | null>(null);

  const beginItemDrag = useCallback((item: LibraryItem) => (event: ReactDragEvent<HTMLElement>) => {
    const paths = selected.has(item.path) ? Array.from(selected) : [item.path];
    dragPathsRef.current = paths;
    event.dataTransfer.effectAllowed = "move";
    try {
      event.dataTransfer.setData("text/plain", paths.join("\n"));
    } catch {
      /* 某些环境不支持 setData，忽略 */
    }
  }, [selected]);

  const clearItemDrag = useCallback(() => {
    dragPathsRef.current = [];
    setDropTarget(null);
  }, []);

  const handleFolderDragOver = useCallback((folder: string) => (event: ReactDragEvent<HTMLElement>) => {
    if (!dragPathsRef.current.length) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDropTarget(folder);
  }, []);

  const handleFolderDrop = useCallback((folder: string) => (event: ReactDragEvent<HTMLElement>) => {
    event.preventDefault();
    const paths = dragPathsRef.current;
    dragPathsRef.current = [];
    setDropTarget(null);
    if (!paths.length || !dirs) return;
    void moveItems(tab as LibraryKind, paths, folder);
  }, [dirs, moveItems, tab]);

  const handleFolderDragLeave = useCallback((folder: string) => () => {
    setDropTarget((current) => (current === folder ? null : current));
  }, []);

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
      notify("success", `已把文件夹「${folder}」移入回收站`);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "删除文件夹失败");
    }
  }, [currentFolder, dirs, notify, refresh, tab]);

  const requestDeleteFolder = useCallback((folder: string) => {
    const count = folders.find((item) => item.relative === folder)?.count ?? 0;
    if (count > 0) {
      notify("info", `「${folder}」内还有 ${count} 个素材，请先移走或删除后再删除该文件夹。`);
      return;
    }
    setConfirm({
      title: "删除文件夹",
      message: `确定删除文件夹「${folder}」吗？删除后会移入系统回收站。`,
      confirmLabel: "移入回收站",
      onConfirm: () => { void deleteFolder(folder); },
    });
  }, [deleteFolder, folders, notify]);

  const renameItem = useCallback(async (kind: LibraryKind, path: string, newName: string) => {
    if (!dirs) return;
    try {
      const result = await engine.call<{ renamed: boolean; name: string; path: string }>(
        "library_rename",
        { kind, path, new_name: newName, bgm_dir: dirs.bgm_dir, watermark_dir: dirs.watermark_dir },
        60_000,
      );
      // 本地增量更新：改名字/路径，不重新全量扫描
      const nextPath = result.path;
      const updater = (item: LibraryItem) => (item.path === path ? { ...item, name: result.name, path: nextPath } : item);
      if (kind === "bgm") {
        setBgm((current) => current.map(updater));
      } else {
        setWatermark((current) => current.map(updater));
      }
      setSelected((current) => {
        if (!current.has(path)) return current;
        const next = new Set(current);
        next.delete(path);
        next.add(nextPath);
        return next;
      });
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "重命名失败");
    }
  }, [dirs, notify]);

  const requestRename = useCallback((kind: LibraryKind, item: LibraryItem) => {
    const stem = item.name.replace(/\.[^.]*$/, "");
    setRenameOpen({ kind, path: item.path, name: item.name });
    setRenameDraft(stem);
  }, []);

  const commitRename = useCallback(() => {
    if (!renameOpen) return;
    const stem = renameDraft.trim();
    if (!stem) return;
    const target = renameOpen;
    setRenameOpen(null);
    void renameItem(target.kind, target.path, stem);
  }, [renameDraft, renameItem, renameOpen]);

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
    notify("success", `已切换到新的${tab === "bgm" ? " BGM" : "水印"}目录（原目录文件不会被移动或删除）`);
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
      audio.onended = () => {
        setPlayingPath(null);
      };
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

  const seekAudio = useCallback((ratio: number) => {
    const audio = audioRef.current;
    if (!audio || !Number.isFinite(audio.duration) || audio.duration <= 0) return;
    audio.currentTime = Math.max(0, Math.min(1, ratio)) * audio.duration;
  }, []);

  // 视频水印素材：点击播放 → 弹出放大播放器（引擎按需转码为 WebView 可播放格式）
  const openVideoPreview = useCallback(async (item: LibraryItem) => {
    if (!engine.desktopRuntime) return notify("info", "视频预览需要在 Tauri 桌面窗口中运行");
    audioRef.current?.pause();
    setVideoPreview({ path: item.path, name: item.name });
    setVideoUrl(null);
    setVideoAspect(null);
    setPlayingPath(item.path);
    if (videoMetaTimerRef.current !== null) {
      window.clearTimeout(videoMetaTimerRef.current);
      videoMetaTimerRef.current = null;
    }
    try {
      const preview = await engine.call<{ preview_path: string }>("library_preview_video", { path: item.path }, 130_000);
      setVideoUrl(engine.toAssetUrl(preview.preview_path));
      // 兜底：元数据迟迟未就绪时按默认横板展示，避免一直停在加载态
      videoMetaTimerRef.current = window.setTimeout(() => {
        setVideoAspect((aspect) => (aspect === null ? 0 : aspect));
      }, 10_000);
    } catch (err) {
      closeVideoPreview();
      notify("error", err instanceof Error ? err.message : "视频预览失败");
    }
  }, [closeVideoPreview, notify]);

  const openImagePreview = useCallback((item: LibraryItem) => {
    if (!engine.desktopRuntime) return notify("info", "图片预览需要在 Tauri 桌面窗口中运行");
    setImagePreview({ path: item.path, name: item.name });
    setImageFailed(false);
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

  // ---------- Eagle 风格素材管理：标签 / 星标 / 备注 / 去重 / 批量重命名 / 智能文件夹 ----------

  const applyMetadata = useCallback(async (item: LibraryItem, patch: { tags?: string[]; starred?: boolean; note?: string }) => {
    if (!engine.desktopRuntime) return notify("info", "素材元数据需要在 Tauri 桌面窗口中运行");
    if (!dirs) return;
    try {
      const result = await engine.call<{ tags: string[]; starred: boolean; note: string }>("library_set_metadata", {
        kind: tab,
        path: item.path,
        bgm_dir: dirs.bgm_dir,
        watermark_dir: dirs.watermark_dir,
        ...patch,
      }, 30_000);
      const nextItem: LibraryItem = { ...item, tags: result.tags, starred: result.starred, note: result.note };
      if (tab === "bgm") setBgm((current) => current.map((entry) => entry.path === item.path ? nextItem : entry));
      else setWatermark((current) => current.map((entry) => entry.path === item.path ? nextItem : entry));
      if (detail?.path === item.path) setDetailDraft({ tags: result.tags, note: result.note, starred: result.starred });
      void refreshTags();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "保存素材元数据失败");
    }
  }, [detail, dirs, notify, refreshTags, tab]);

  const toggleStar = useCallback((item: LibraryItem) => {
    void applyMetadata(item, { starred: !item.starred });
  }, [applyMetadata]);

  const openDetail = useCallback((item: LibraryItem) => {
    setDetail(item);
    setDetailDraft({ tags: item.tags ?? [], note: item.note ?? "", starred: item.starred });
    setDetailTagDraft("");
  }, []);

  const closeDetail = useCallback(() => {
    setDetail(null);
    setDetailTagDraft("");
  }, []);

  const saveDetail = useCallback(() => {
    if (!detail) return;
    void applyMetadata(detail, { tags: detailDraft.tags, note: detailDraft.note, starred: detailDraft.starred });
  }, [applyMetadata, detail, detailDraft]);

  const addDetailTag = useCallback(() => {
    const tag = detailTagDraft.trim();
    if (!tag) return;
    setDetailDraft((current) => (current.tags.includes(tag) ? current : { ...current, tags: [...current.tags, tag] }));
    setDetailTagDraft("");
  }, [detailTagDraft]);

  const removeDetailTag = useCallback((tag: string) => {
    setDetailDraft((current) => ({ ...current, tags: current.tags.filter((entry) => entry !== tag) }));
  }, []);

  const scanDuplicates = useCallback(async () => {
    if (!engine.desktopRuntime) return notify("info", "查找重复素材需要在 Tauri 桌面窗口中运行");
    if (!dirs) return;
    setDupState((current) => ({ ...current, scanning: true }));
    try {
      const result = await engine.call<LibraryDupResult>("library_find_duplicates", {
        kind: tab,
        bgm_dir: dirs.bgm_dir,
        watermark_dir: dirs.watermark_dir,
      }, 300_000);
      const checked = new Set<string>();
      for (const group of result.groups) {
        group.duplicates.forEach((item) => checked.add(item.path));
      }
      setDupState({ scanning: false, result, checked });
    } catch (err) {
      setDupState((current) => ({ ...current, scanning: false }));
      notify("error", err instanceof Error ? err.message : "查找重复素材失败");
    }
  }, [dirs, notify, tab]);

  const toggleDupChecked = useCallback((path: string) => {
    setDupState((current) => {
      const next = new Set(current.checked);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return { ...current, checked: next };
    });
  }, []);

  const toggleDupGroup = useCallback((group: LibraryDupResult["groups"][number], checked: boolean) => {
    setDupState((current) => {
      const next = new Set(current.checked);
      const paths = [group.representative, ...group.duplicates].map((item) => item.path);
      for (const path of paths) {
        if (checked) next.add(path);
        else next.delete(path);
      }
      return { ...current, checked: next };
    });
  }, []);

  const deleteCheckedDuplicates = useCallback(async () => {
    if (!dirs) return;
    const paths = Array.from(dupState.checked);
    if (!paths.length) return notify("info", "没有选中的重复素材");
    try {
      const result = await engine.call<{ results: Array<{ status: string }> }>("library_remove_batch", {
        kind: tab,
        paths,
        bgm_dir: dirs.bgm_dir,
        watermark_dir: dirs.watermark_dir,
      }, 300_000);
      const removed = result.results.filter((item) => item.status === "removed").length;
      notify(removed ? "success" : "error", removed ? `已把 ${removed} 个重复素材移入回收站` : "没有素材被删除");
      setDupOpen(false);
      await refresh();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "删除重复素材失败");
    }
  }, [dirs, dupState.checked, notify, refresh, tab]);

  const computeRenamePreview = useCallback((items: LibraryItem[], pattern: string, startIndex: number) => {
    if (!pattern.trim()) return [];
    const now = new Date();
    const pad2 = (value: number) => String(value).padStart(2, "0");
    const dateStamp = `${now.getFullYear()}${pad2(now.getMonth() + 1)}${pad2(now.getDate())}`;
    const padWidth = Math.max(2, String(startIndex + items.length - 1).length);
    const seen = new Set<string>();
    return items.map((item, offset) => {
      const dot = item.name.lastIndexOf(".");
      const stem = dot > 0 ? item.name.slice(0, dot) : item.name;
      const suffix = dot > 0 ? item.name.slice(dot) : "";
      const number = String(startIndex + offset).padStart(padWidth, "0");
      const nextStem = pattern.replace(/\{name\}/g, stem).replace(/\{n\}/g, number).replace(/\{date\}/g, dateStamp);
      const next = `${nextStem}${suffix}`;
      let ok = true;
      let reason = "";
      if (!nextStem.trim() || /[<>:"/\\|?*]/.test(nextStem)) {
        ok = false;
        reason = "生成的文件名包含非法字符";
      } else if (seen.has(next)) {
        ok = false;
        reason = `与「${next}」重名`;
      }
      seen.add(next);
      return { old: item.name, next, ok, reason };
    });
  }, []);

  const openBatchRename = useCallback(() => {
    const order = visibleItems.filter((item) => selected.has(item.path));
    if (!order.length) return notify("info", "请先选择要重命名的素材");
    setBatchRename({
      pattern: "{n}-{name}",
      startIndex: 1,
      items: order,
      preview: computeRenamePreview(order, "{n}-{name}", 1),
      applying: false,
    });
    setBatchRenameOpen(true);
  }, [computeRenamePreview, notify, selected, visibleItems]);

  const updateBatchRenameDraft = useCallback((patch: Partial<{ pattern: string; startIndex: number }>) => {
    setBatchRename((current) => {
      const next = { ...current, ...patch };
      next.preview = computeRenamePreview(next.items, next.pattern, next.startIndex);
      return next;
    });
  }, [computeRenamePreview]);

  const applyBatchRename = useCallback(async () => {
    if (!engine.desktopRuntime) return notify("info", "批量重命名需要在 Tauri 桌面窗口中运行");
    if (!dirs) return;
    if (batchRename.preview.some((item) => !item.ok)) return notify("error", "有不可用的名称，请调整模板");
    setBatchRename((current) => ({ ...current, applying: true }));
    try {
      const result = await engine.call<{ results: LibraryRenameBatchResult[] }>("library_rename_batch", {
        kind: tab,
        paths: batchRename.items.map((item) => item.path),
        bgm_dir: dirs.bgm_dir,
        watermark_dir: dirs.watermark_dir,
        pattern: batchRename.pattern,
        start_index: batchRename.startIndex,
      }, 60_000);
      const renamed = result.results.filter((item) => item.status === "renamed").length;
      const failed = result.results.filter((item) => item.status === "failed").length;
      notify(failed && !renamed ? "error" : "success", `已重命名 ${renamed} 个素材${failed ? `，失败 ${failed} 个` : ""}`);
      setBatchRenameOpen(false);
      await refresh();
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "批量重命名失败");
    } finally {
      setBatchRename((current) => ({ ...current, applying: false }));
    }
  }, [batchRename.items, batchRename.pattern, batchRename.preview, dirs, notify, refresh, tab]);

  const persistSmartFolders = useCallback(async (next: LibrarySmartFolder[]) => {
    if (!engine.desktopRuntime || !dirs) return;
    try {
      await engine.call("library_smart_folders_save", { bgm_dir: dirs.bgm_dir, folders: next }, 30_000);
      setSmartFolders(next);
      if (activeSmartFolder && !next.some((folder) => folder.id === activeSmartFolder)) {
        setActiveSmartFolder(null);
      }
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "保存智能文件夹失败");
    }
  }, [activeSmartFolder, dirs, notify]);

  const openSmartFolderCreate = useCallback(() => {
    setSmartFolderEdit({ id: `smart-${Date.now()}`, name: "", kind: tab === "watermark" ? "watermark" : "bgm", conditions: [] });
    setSmartFolderOpen(true);
  }, [tab]);

  const saveSmartFolderEdit = useCallback(async () => {
    if (!smartFolderEdit) return;
    if (!smartFolderEdit.name.trim()) return notify("error", "请输入智能文件夹名称");
    const exists = smartFolders.some((folder) => folder.id === smartFolderEdit.id);
    const next = exists
      ? smartFolders.map((folder) => (folder.id === smartFolderEdit.id ? smartFolderEdit : folder))
      : [...smartFolders, smartFolderEdit];
    await persistSmartFolders(next);
    setSmartFolderOpen(false);
    setSmartFolderEdit(null);
  }, [notify, persistSmartFolders, smartFolderEdit, smartFolders]);

  const deleteSmartFolder = useCallback((id: string) => {
    void persistSmartFolders(smartFolders.filter((folder) => folder.id !== id));
  }, [persistSmartFolders, smartFolders]);

  const selectSmartFolder = useCallback((id: string) => {
    setActiveSmartFolder((current) => (current === id ? null : id));
    setCurrentFolder("");
    setSearch("");
    setSearchDraft("");
    setSelected(new Set());
  }, []);

  const changeThumbSize = useCallback((value: number) => {
    setThumbSize(Math.max(THUMB_MIN, Math.min(THUMB_MAX, Math.round(value))));
  }, []);

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
              <button type="button" className={`library-tree-node is-root${currentFolder === "" ? " is-active" : ""}${dropTarget === "" ? " is-drop-target" : ""}`} onClick={() => selectFolder("")} onDragOver={handleFolderDragOver("")} onDrop={handleFolderDrop("")} onDragLeave={handleFolderDragLeave("")}>
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
                dropTarget={dropTarget}
                onFolderDraft={setFolderDraft}
                onSelect={selectFolder}
                onToggle={toggleExpanded}
                onStartCreate={(parent) => { setCreatingUnder(parent); setRenaming(null); setFolderDraft(""); }}
                onStartRename={(folder) => { setRenaming(folder); setCreatingUnder(null); setFolderDraft(folder.split("/").pop() ?? ""); }}
                onDelete={requestDeleteFolder}
                onCommit={commitFolderDraft}
                onCancelEdit={() => { setCreatingUnder(null); setRenaming(null); setFolderDraft(""); }}
                onFolderDragOver={handleFolderDragOver}
                onFolderDrop={handleFolderDrop}
                onFolderDragLeave={handleFolderDragLeave}
              />
            </div>
            <div className="library-smart-list">
              <div className="library-tree-head">
                <strong>智能文件夹</strong>
                <button type="button" className="icon-button" onClick={openSmartFolderCreate} aria-label="新建智能文件夹" title="新建智能文件夹"><FolderCog size={14} /></button>
              </div>
              <div className="library-smart-scroll">
                {smartFolders.filter((folder) => folder.kind === tab).length ? (
                  smartFolders.filter((folder) => folder.kind === tab).map((folder) => (
                    <button
                      key={folder.id}
                      type="button"
                      className={`library-smart-item${activeSmartFolder === folder.id ? " is-active" : ""}`}
                      onClick={() => selectSmartFolder(folder.id)}
                      title={smartFolderRuleSummary(folder)}
                    >
                      <FolderCog size={13} />
                      <span>{folder.name}</span>
                      <small>{items.filter((item) => matchesSmartFolder(item, folder)).length}</small>
                    </button>
                  ))
                ) : (
                  <span className="library-smart-empty">按规则自动归类素材</span>
                )}
                <button type="button" className="library-smart-manage" onClick={() => setSmartFolderOpen(true)}>管理智能文件夹…</button>
              </div>
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
                  <input value={searchDraft} onChange={(event) => handleSearchChange(event.target.value)} placeholder="搜索素材" aria-label="搜索素材" />
                  {searchDraft ? <button type="button" className="icon-button" onClick={clearSearch} aria-label="清除搜索"><X size={12} /></button> : null}
                </span>
                {tab === "watermark" ? (
                  <span className="library-type-filter" role="group" aria-label="类型筛选">
                    <button type="button" className={filterType === "all" ? "is-active" : ""} onClick={() => setFilterType("all")}>全部</button>
                    <button type="button" className={filterType === "image" ? "is-active" : ""} onClick={() => setFilterType("image")}>图片</button>
                    <button type="button" className={filterType === "video" ? "is-active" : ""} onClick={() => setFilterType("video")}>视频</button>
                  </span>
                ) : null}
                <span className="library-sort">
                  <select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)} aria-label="排序方式">
                    {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                  <button type="button" className="icon-button" onClick={() => setSortDesc((value) => !value)} aria-label={sortDesc ? "升序" : "降序"}>
                    {sortDesc ? <ArrowDown size={14} /> : <ArrowUp size={14} />}
                  </button>
                </span>
                <button
                  type="button"
                  className={`library-star-filter${starFilter ? " is-active" : ""}`}
                  onClick={() => setStarFilter((value) => !value)}
                  aria-label="只看收藏"
                  title="只看收藏"
                >
                  <Star size={14} fill={starFilter ? "currentColor" : "none"} />
                </button>
                {allTags.length ? (
                  <span className="library-tag-filter">
                    <Tag size={13} />
                    <select value={tagFilter} onChange={(event) => setTagFilter(event.target.value)} aria-label="按标签筛选">
                      <option value="">全部标签</option>
                      {allTags.map((tag) => <option key={tag.name} value={tag.name}>{tag.name}（{tag.count}）</option>)}
                    </select>
                  </span>
                ) : null}
                <span className="library-view-toggle" role="group" aria-label="视图模式">
                  <button type="button" className={viewMode === "list" ? "is-active" : ""} onClick={() => setViewMode("list")} aria-label="列表模式"><List size={14} /></button>
                  <button type="button" className={viewMode === "card" ? "is-active" : ""} onClick={() => setViewMode("card")} aria-label="卡片模式"><LayoutGrid size={14} /></button>
                </span>
                {viewMode === "card" ? (
                  <span className="library-thumb-slider" title="缩略图大小">
                    <SlidersHorizontal size={13} />
                    <input type="range" min={THUMB_MIN} max={THUMB_MAX} step={8} value={thumbSize} onChange={(event) => changeThumbSize(Number(event.target.value))} aria-label="缩略图大小" />
                  </span>
                ) : null}
                <button type="button" className="quiet-button" onClick={scanDuplicates} disabled={!desktopRuntime || loading}><GitCompareArrows size={14} />查找重复</button>
                {tab === "bgm" ? (
                  <button type="button" className="library-accent-button" onClick={() => setExtract((current) => ({ ...current, open: true, saveFolder: currentFolder }))} disabled={!desktopRuntime}><Scissors size={14} />批量拆BGM</button>
                ) : null}
                {tab === "bgm" || tab === "watermark" ? (
                  <button type="button" className="quiet-button" onClick={openJianying} disabled={!desktopRuntime || loading}><Clapperboard size={14} />从剪映导入</button>
                ) : null}
                <button type="button" className="quiet-button" onClick={() => importFiles(tab, currentFolder)} disabled={!desktopRuntime || loading || importingCount > 0}>
                  {importingCount > 0 ? <Loader2 className="is-spinning" size={14} /> : <Upload size={14} />}
                  {importingCount > 0 ? `导入中 ${importingCount} 项…` : "导入"}
                </button>
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
                <button type="button" className="quiet-button" onClick={openBatchRename}><Wand2 size={14} />批量重命名</button>
                <button type="button" className="quiet-button danger-text" onClick={() => requestRemove(tab, Array.from(selected))}><Trash2 size={14} />删除</button>
                <button type="button" className="quiet-button" onClick={() => setSelected(new Set())}><X size={14} />取消选择</button>
              </div>
            ) : null}

            {error ? <div className="library-error"><CircleAlert size={15} />{error}</div> : null}

            {tab === "bgm" ? (
              viewMode === "list" ? (
                <ul className="library-list">
                  {!loading && !visibleItems.length ? (
                    <li className="library-empty">
                      <span>{currentFolder
                        ? <>这个文件夹还是空的。导入音频会保存到当前文件夹，或点击「批量拆BGM」从视频提取。</>
                        : <>BGM 库还是空的。</>}</span>
                      <span className="library-empty-actions">
                        <button type="button" className="library-accent-button" onClick={() => void importFiles("bgm", currentFolder)} disabled={!desktopRuntime || importingCount > 0}>{importingCount > 0 ? <Loader2 className="is-spinning" size={14} /> : <Upload size={14} />}{importingCount > 0 ? "导入中…" : "导入音频"}</button>
                        <button type="button" className="quiet-button" onClick={() => setExtract((current) => ({ ...current, open: true, saveFolder: currentFolder }))} disabled={!desktopRuntime}><Scissors size={14} />批量拆BGM</button>
                      </span>
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
                          <button type="button" className="library-item-name" onClick={() => openDetail(item)} title={item.path}>{item.name}</button>
                          <small>{item.folder ? `${item.folder} · ` : ""}{formatBytes(item.size_bytes)} · {formatDuration(item.duration)}{item.added_at ? ` · 入库于 ${formatAddedAt(item.added_at)}` : ""}</small>
                          <ItemMetaChips item={item} />
                          {isPlaying ? <AudioProgressBar audioRef={audioRef} onSeek={seekAudio} /> : null}
                        </span>
                        <span className="library-row-actions">
                          <StarButton item={item} onToggle={toggleStar} />
                          <button type="button" className="icon-button" onClick={() => void togglePlay(item)} aria-label={isPlaying ? "停止试听" : "试听"}>
                            {isPlaying ? <Pause size={15} /> : <Play size={15} />}
                          </button>
                          <button type="button" className="icon-button" onClick={() => addToBgmFiles([item.path])} aria-label={`选用为BGM ${item.name}`} title="选用为当前工作区BGM"><Plus size={14} /></button>
                          <button type="button" className="icon-button" onClick={() => requestRename("bgm", item)} aria-label={`重命名 ${item.name}`} title="重命名"><Pencil size={14} /></button>
                          <button type="button" className="icon-button" draggable onClick={() => { setSelected(new Set([item.path])); setMoveOpen(true); }} onDragStart={beginItemDrag(item)} onDragEnd={clearItemDrag} aria-label={`移动 ${item.name}`} title="拖到左侧文件夹移动"><Move size={14} /></button>
                          <button type="button" className="icon-button danger" onClick={() => requestRemove("bgm", [item.path])} aria-label={`删除 ${item.name}`}><Trash2 size={15} /></button>
                        </span>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <ul className="library-grid" style={{ "--library-thumb": `${thumbSize}px` } as Record<string, string>}>
                  {!loading && !visibleItems.length ? (
                    <li className="library-empty">
                      <span>{currentFolder
                        ? <>这个文件夹还是空的。导入音频会保存到当前文件夹，或点击「批量拆BGM」从视频提取。</>
                        : <>BGM 库还是空的。</>}</span>
                      <span className="library-empty-actions">
                        <button type="button" className="library-accent-button" onClick={() => void importFiles("bgm", currentFolder)} disabled={!desktopRuntime || importingCount > 0}>{importingCount > 0 ? <Loader2 className="is-spinning" size={14} /> : <Upload size={14} />}{importingCount > 0 ? "导入中…" : "导入音频"}</button>
                        <button type="button" className="quiet-button" onClick={() => setExtract((current) => ({ ...current, open: true, saveFolder: currentFolder }))} disabled={!desktopRuntime}><Scissors size={14} />批量拆BGM</button>
                      </span>
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
                          <button type="button" className="library-item-name" onClick={() => openDetail(item)} title={item.path}>{item.name}</button>
                          <small>{item.folder ? `${item.folder} · ` : ""}{formatBytes(item.size_bytes)}</small>
                          <ItemMetaChips item={item} />
                          {isPlaying ? <AudioProgressBar audioRef={audioRef} onSeek={seekAudio} /> : null}
                        </span>
                        <span className="library-card-actions">
                          <StarButton item={item} onToggle={toggleStar} />
                          <button type="button" className="icon-button" onClick={() => void togglePlay(item)} aria-label={isPlaying ? "停止试听" : "试听"}>
                            {isPlaying ? <Pause size={14} /> : <Play size={14} />}
                          </button>
                          <button type="button" className="icon-button" onClick={() => addToBgmFiles([item.path])} aria-label={`选用为BGM ${item.name}`} title="选用为当前工作区BGM"><Plus size={13} /></button>
                          <button type="button" className="icon-button" onClick={() => requestRename("bgm", item)} aria-label={`重命名 ${item.name}`} title="重命名"><Pencil size={13} /></button>
                          <button type="button" className="icon-button" draggable onClick={() => { setSelected(new Set([item.path])); setMoveOpen(true); }} onDragStart={beginItemDrag(item)} onDragEnd={clearItemDrag} aria-label={`移动 ${item.name}`} title="拖到左侧文件夹移动"><Move size={13} /></button>
                          <button type="button" className="icon-button danger" onClick={() => requestRemove("bgm", [item.path])} aria-label={`删除 ${item.name}`}><Trash2 size={14} /></button>
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
                    <span>{currentFolder
                      ? <>这个文件夹还是空的。导入的图片会保存到当前文件夹。</>
                      : <>水印库还是空的。</>}</span>
                    <span className="library-empty-actions">
                      <button type="button" className="library-accent-button" onClick={() => void importFiles("watermark", currentFolder)} disabled={!desktopRuntime || importingCount > 0}>{importingCount > 0 ? <Loader2 className="is-spinning" size={14} /> : <Upload size={14} />}{importingCount > 0 ? "导入中…" : "导入素材"}</button>
                    </span>
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
                        <button type="button" className="library-thumb-play" onClick={() => openImagePreview(item)} aria-label={`放大预览 ${item.name}`} title="点击放大预览">
                          <span className="library-thumb-play-hint"><Search size={16} /></span>
                          <span className="library-thumb-wrap">
                            <WatermarkThumb path={item.path} size="small" />
                          </span>
                        </button>
                      )}
                      <span className="library-row-main">
                        <button type="button" className="library-item-name" onClick={() => openDetail(item)} title={item.path}>{item.name}</button>
                        <small>{item.folder ? `${item.folder} · ` : ""}{isVideo ? `${formatDuration(item.duration)} · ` : ""}{formatBytes(item.size_bytes)}{item.added_at ? ` · 入库于 ${formatAddedAt(item.added_at)}` : ""}</small>
                        <ItemMetaChips item={item} />
                      </span>
                      <span className="library-row-actions">
                        <StarButton item={item} onToggle={toggleStar} />
                        {isVideo ? <button type="button" className="icon-button" onClick={() => void openVideoPreview(item)} aria-label="放大播放预览" title="放大播放预览"><Play size={14} /></button> : null}
                        {isVideo ? <button type="button" className="quiet-button" onClick={() => useAsVideoWatermark(item)}><Stamp size={13} />用作视频水印</button> : null}
                        <button type="button" className="quiet-button" onClick={() => addWatermarkLayer(item)}><Plus size={13} />加入水印图层</button>
                        <button type="button" className="icon-button" onClick={() => requestRename("watermark", item)} aria-label={`重命名 ${item.name}`} title="重命名"><Pencil size={14} /></button>
                        <button type="button" className="icon-button" draggable onClick={() => { setSelected(new Set([item.path])); setMoveOpen(true); }} onDragStart={beginItemDrag(item)} onDragEnd={clearItemDrag} aria-label={`移动 ${item.name}`} title="拖到左侧文件夹移动"><Move size={14} /></button>
                        <button type="button" className="icon-button danger" onClick={() => requestRemove("watermark", [item.path])} aria-label={`删除 ${item.name}`}><Trash2 size={15} /></button>
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <ul className="library-grid" style={{ "--library-thumb": `${thumbSize}px` } as Record<string, string>}>
                {!loading && !visibleItems.length ? (
                  <li className="library-empty">
                    <span>{currentFolder
                      ? <>这个文件夹还是空的。导入的图片会保存到当前文件夹。</>
                      : <>水印库还是空的。</>}</span>
                    <span className="library-empty-actions">
                      <button type="button" className="library-accent-button" onClick={() => void importFiles("watermark", currentFolder)} disabled={!desktopRuntime || importingCount > 0}>{importingCount > 0 ? <Loader2 className="is-spinning" size={14} /> : <Upload size={14} />}{importingCount > 0 ? "导入中…" : "导入素材"}</button>
                    </span>
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
                        <button type="button" className="library-thumb-play" onClick={() => openImagePreview(item)} aria-label={`放大预览 ${item.name}`} title="点击放大预览">
                          <span className="library-thumb-play-hint"><Search size={16} /></span>
                          <span className="library-thumb-wrap">
                            <WatermarkThumb path={item.path} />
                          </span>
                        </button>
                      )}
                      <span className="library-card-meta">
                        <button type="button" className="library-item-name" onClick={() => openDetail(item)} title={item.path}>{item.name}</button>
                        <small>{item.folder ? `${item.folder} · ` : ""}{isVideo ? `${formatDuration(item.duration)} · ` : ""}{formatBytes(item.size_bytes)}</small>
                        <ItemMetaChips item={item} />
                      </span>
                      <span className="library-card-actions">
                        <StarButton item={item} onToggle={toggleStar} />
                        {isVideo ? <button type="button" className="icon-button" onClick={() => useAsVideoWatermark(item)} aria-label={`用作视频水印 ${item.name}`} title="用作视频水印（设为导出水印）"><Stamp size={14} /></button> : null}
                        <button type="button" className="icon-button" onClick={() => addWatermarkLayer(item)} aria-label={`加入水印图层 ${item.name}`} title="加入水印图层"><Layers size={14} /></button>
                        <button type="button" className="icon-button" onClick={() => requestRename("watermark", item)} aria-label={`重命名 ${item.name}`} title="重命名"><Pencil size={13} /></button>
                        <button type="button" className="icon-button" draggable onClick={() => { setSelected(new Set([item.path])); setMoveOpen(true); }} onDragStart={beginItemDrag(item)} onDragEnd={clearItemDrag} aria-label={`移动 ${item.name}`} title="拖到左侧文件夹移动"><Move size={13} /></button>
                        <button type="button" className="icon-button danger" onClick={() => requestRemove("watermark", [item.path])} aria-label={`删除 ${item.name}`} title="删除"><Trash2 size={14} /></button>
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
        <div className="library-backdrop library-backdrop-inner" role="presentation" onMouseDown={(event) => { event.stopPropagation(); setMoveOpen(false); }}>
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

      {confirm ? (
        <div className="library-backdrop library-backdrop-inner library-confirm-backdrop" role="presentation" onMouseDown={(event) => { event.stopPropagation(); setConfirm(null); }}>
          <section className="library-confirm-dialog" role="dialog" aria-modal="true" aria-label={confirm.title} onMouseDown={(event) => event.stopPropagation()}>
            <header className="library-dialog-heading">
              <span className="library-dialog-icon"><CircleAlert size={20} /></span>
              <span><strong id="library-confirm-title">{confirm.title}</strong></span>
            </header>
            <div className="library-confirm-body">{confirm.message}</div>
            <footer className="library-dialog-footer">
              <span className="library-dialog-footer-hint">删除后可在系统回收站中还原。</span>
              <span className="library-dialog-footer-actions">
                <button type="button" className="quiet-button" onClick={() => setConfirm(null)}>取消</button>
                <button type="button" className="library-accent-button is-danger" onClick={() => { const action = confirm.onConfirm; setConfirm(null); action(); }}>{confirm.confirmLabel}</button>
              </span>
            </footer>
          </section>
        </div>
      ) : null}

      {renameOpen ? (
        <div className="library-backdrop library-backdrop-inner library-confirm-backdrop" role="presentation" onMouseDown={(event) => { event.stopPropagation(); setRenameOpen(null); }}>
          <section className="library-confirm-dialog" role="dialog" aria-modal="true" aria-label="重命名素材" onMouseDown={(event) => event.stopPropagation()}>
            <header className="library-dialog-heading">
              <span className="library-dialog-icon"><Pencil size={20} /></span>
              <span><strong>重命名素材</strong></span>
            </header>
            <div className="library-confirm-body">
              <div className="library-rename-row">
                <input
                  className="library-rename-input"
                  value={renameDraft}
                  onChange={(event) => setRenameDraft(event.target.value)}
                  onKeyDown={(event) => { if (event.key === "Enter") commitRename(); if (event.key === "Escape") setRenameOpen(null); }}
                  placeholder="新名称"
                  autoFocus
                  aria-label="新名称"
                />
                <span className="library-rename-ext">{renameOpen.name.slice(renameOpen.name.lastIndexOf("."))}</span>
              </div>
            </div>
            <footer className="library-dialog-footer">
              <span className="library-dialog-footer-hint">扩展名保持不变。</span>
              <span className="library-dialog-footer-actions">
                <button type="button" className="quiet-button" onClick={() => setRenameOpen(null)}>取消</button>
                <button type="button" className="library-accent-button" onClick={commitRename} disabled={!renameDraft.trim()}>重命名</button>
              </span>
            </footer>
          </section>
        </div>
      ) : null}

      {extract.open ? (
        <div className="library-backdrop library-backdrop-inner" role="presentation" onMouseDown={(event) => { event.stopPropagation(); if (!extract.running) setExtract((current) => ({ ...current, open: false })); }}>
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
        <div className="library-backdrop library-backdrop-inner" role="presentation" onMouseDown={(event) => { event.stopPropagation(); if (!jianying.scanning && !jianying.busy) setJianying((current) => ({ ...current, open: false })); }}>
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

      {imagePreview ? (
        <div className="library-backdrop library-backdrop-inner library-video-backdrop" role="presentation" onMouseDown={(event) => { event.stopPropagation(); setImagePreview(null); setImageFailed(false); }}>
          <section className="library-video-player" role="dialog" aria-modal="true" aria-label={`预览图片 ${imagePreview.name}`} onMouseDown={(event) => event.stopPropagation()}>
            <header className="library-dialog-heading">
              <span className="library-dialog-icon"><ImageIcon size={20} /></span>
              <span>
                <small>图片水印预览</small>
                <strong title={imagePreview.name}>{imagePreview.name}</strong>
              </span>
              <button type="button" className="update-close" onClick={() => { setImagePreview(null); setImageFailed(false); }} aria-label="关闭图片预览"><X size={17} /></button>
            </header>
            <div className="library-image-player-body">
              {imageFailed ? (
                <div className="library-image-player-error">
                  <CircleAlert size={20} />
                  <span>无法预览此格式（如 TIFF 请先转为 PNG / JPG）</span>
                </div>
              ) : (
                <img
                  key={imagePreview.path}
                  className="library-image-player-media"
                  src={engine.toAssetUrl(imagePreview.path)}
                  alt={imagePreview.name}
                  onError={() => setImageFailed(true)}
                />
              )}
            </div>
          </section>
        </div>
      ) : null}

      {videoPreview ? (
        <div className="library-backdrop library-backdrop-inner library-video-backdrop" role="presentation" onMouseDown={(event) => { event.stopPropagation(); closeVideoPreview(); }}>
          <section className={`library-video-player${videoAspect !== null && videoAspect > 1 ? " is-portrait" : ""}`} role="dialog" aria-modal="true" aria-label={`播放预览 ${videoPreview.name}`} onMouseDown={(event) => event.stopPropagation()}>
            <header className="library-dialog-heading">
              <span className="library-dialog-icon"><Clapperboard size={20} /></span>
              <span>
                <small>视频水印预览</small>
                <strong title={videoPreview.name}>{videoPreview.name}</strong>
              </span>
              <button type="button" className="update-close" onClick={closeVideoPreview} aria-label="关闭视频预览"><X size={17} /></button>
            </header>
            <div className="library-video-player-body">
              {videoUrl ? (
                <>
                  <video
                    key={videoUrl}
                    className={`library-video-player-media${videoAspect === null ? " is-pending" : ""}`}
                    src={videoUrl}
                    controls
                    autoPlay
                    playsInline
                    onLoadedMetadata={(event) => {
                      const media = event.currentTarget;
                      if (media.videoWidth && media.videoHeight) {
                        setVideoAspect(media.videoHeight / media.videoWidth);
                        if (videoMetaTimerRef.current !== null) {
                          window.clearTimeout(videoMetaTimerRef.current);
                          videoMetaTimerRef.current = null;
                        }
                      }
                    }}
                    onError={() => {
                      notify("error", "视频预览播放失败（格式不受支持）");
                      closeVideoPreview();
                    }}
                    onEnded={() => setPlayingPath(null)}
                  />
                  {videoAspect === null ? (
                    <div className="library-video-player-loading">
                      <Loader2 className="is-spinning" size={20} />
                      <span>正在准备视频预览…</span>
                    </div>
                  ) : null}
                </>
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

      {detail ? (
        <div className="library-backdrop library-backdrop-inner" role="presentation" onMouseDown={(event) => { event.stopPropagation(); closeDetail(); }}>
          <section className="library-detail-panel" role="dialog" aria-modal="true" aria-label={`素材详情 ${detail.name}`} onMouseDown={(event) => event.stopPropagation()}>
            <header className="library-dialog-heading">
              <span className="library-dialog-icon"><StickyNote size={20} /></span>
              <span>
                <small>素材详情</small>
                <strong className="library-detail-title">{detail.name}</strong>
              </span>
              <button type="button" className="update-close" onClick={closeDetail} aria-label="关闭详情"><X size={17} /></button>
            </header>
            <div className="library-detail-body">
              <div className="library-detail-preview">
                {detail.type === "audio" ? (
                  <BgmCover path={detail.path} />
                ) : detail.type === "video" ? (
                  <button type="button" className="library-detail-preview-media" onClick={() => void openVideoPreview(detail)} aria-label={`放大播放 ${detail.name}`}>
                    <WatermarkThumb path={detail.path} />
                    <span className="library-thumb-badge"><Play size={10} />{formatDuration(detail.duration)}</span>
                    <span className="library-detail-preview-hint">点击放大播放</span>
                  </button>
                ) : (
                  <button type="button" className="library-detail-preview-media" onClick={() => openImagePreview(detail)} aria-label={`放大预览 ${detail.name}`}>
                    <WatermarkThumb path={detail.path} />
                    <span className="library-detail-preview-hint">点击放大预览</span>
                  </button>
                )}
              </div>
              <dl className="library-detail-meta">
                <div><dt>路径</dt><dd title={detail.path}>{detail.path}</dd></div>
                <div><dt>所在文件夹</dt><dd>{detail.folder || "库根目录"}</dd></div>
                <div><dt>类型</dt><dd>{detail.type === "audio" ? "音频" : detail.type === "video" ? "视频" : "图片"}</dd></div>
                <div><dt>大小</dt><dd>{formatBytes(detail.size_bytes)}</dd></div>
                {detail.duration != null ? <div><dt>时长</dt><dd>{formatDuration(detail.duration)}</dd></div> : null}
                <div><dt>入库时间</dt><dd>{detail.added_at ? formatAddedAt(detail.added_at) : "—"}</dd></div>
              </dl>
              <div className="library-detail-section">
                <span className="library-detail-label">收藏</span>
                <button type="button" className={`library-star-toggle${detailDraft.starred ? " is-starred" : ""}`} onClick={() => setDetailDraft((current) => ({ ...current, starred: !current.starred }))} aria-pressed={detailDraft.starred}>
                  <Star size={16} fill={detailDraft.starred ? "currentColor" : "none"} />
                  {detailDraft.starred ? "已收藏" : "点击收藏"}
                </button>
              </div>
              <div className="library-detail-section">
                <span className="library-detail-label">标签</span>
                <div className="library-detail-tags">
                  {detailDraft.tags.map((tag) => (
                    <span key={tag} className="library-chip is-editable"><Tag size={10} />{tag}<button type="button" onClick={() => removeDetailTag(tag)} aria-label={`移除标签 ${tag}`}><X size={10} /></button></span>
                  ))}
                  {!detailDraft.tags.length ? <span className="library-detail-empty">还没有标签</span> : null}
                </div>
                <div className="library-detail-tag-input">
                  <input value={detailTagDraft} onChange={(event) => setDetailTagDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") addDetailTag(); }} placeholder="输入标签后回车" aria-label="新增标签" />
                  <button type="button" className="quiet-button" onClick={addDetailTag} disabled={!detailTagDraft.trim()}><Plus size={13} />添加</button>
                </div>
                {allTags.filter((tag) => !detailDraft.tags.includes(tag.name)).slice(0, 8).length ? (
                  <div className="library-detail-suggest">
                    {allTags.filter((tag) => !detailDraft.tags.includes(tag.name)).slice(0, 8).map((tag) => (
                      <button key={tag.name} type="button" className="library-chip" onClick={() => setDetailDraft((current) => (current.tags.includes(tag.name) ? current : { ...current, tags: [...current.tags, tag.name] }))}>+ {tag.name}</button>
                    ))}
                  </div>
                ) : null}
              </div>
              <div className="library-detail-section">
                <span className="library-detail-label">备注</span>
                <textarea className="library-detail-note" value={detailDraft.note} onChange={(event) => setDetailDraft((current) => ({ ...current, note: event.target.value }))} placeholder="记录用途、来源、注意事项…" rows={4} aria-label="素材备注" />
              </div>
            </div>
            <footer className="library-dialog-footer">
              <span className="library-dialog-footer-hint">标签、收藏与备注保存在素材库索引中，不会修改源文件。</span>
              <span className="library-dialog-footer-actions">
                <button type="button" className="quiet-button" onClick={closeDetail}>取消</button>
                <button type="button" className="library-accent-button" onClick={saveDetail}>保存</button>
              </span>
            </footer>
          </section>
        </div>
      ) : null}

      {dupOpen ? (
        <div className="library-backdrop library-backdrop-inner" role="presentation" onMouseDown={(event) => { event.stopPropagation(); if (!dupState.scanning) setDupOpen(false); }}>
          <section className="library-dup-dialog" role="dialog" aria-modal="true" aria-labelledby="library-dup-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="library-dialog-heading">
              <span className="library-dialog-icon"><GitCompareArrows size={21} /></span>
              <span>
                <small>重复 / 相似素材</small>
                <strong id="library-dup-title">查找重复素材</strong>
              </span>
              <button type="button" className="update-close" onClick={() => setDupOpen(false)} disabled={dupState.scanning} aria-label="关闭查找重复窗口"><X size={17} /></button>
            </header>
            <div className="library-dup-body">
              {dupState.scanning ? (
                <div className="library-dup-empty"><Loader2 className="is-spinning" size={20} />正在扫描素材库…（图片较多时可能需要一些时间）</div>
              ) : !dupState.result ? (
                <div className="library-dup-empty">
                  <span>扫描整个{tab === "bgm" ? "BGM" : "水印"}库，按内容识别重复与相似素材（图片用感知哈希，音频用响度指纹）。</span>
                  <button type="button" className="library-accent-button" onClick={scanDuplicates}><GitCompareArrows size={14} />开始扫描</button>
                </div>
              ) : dupState.result.groups.length === 0 ? (
                <div className="library-dup-empty"><Check size={18} />没有发现重复素材（共扫描 {dupState.result.scanned} 个）</div>
              ) : (
                <>
                  <p className="library-dup-summary">
                    发现 {dupState.result.groups.length} 组重复（共扫描 {dupState.result.scanned} 个素材，可释放 {formatBytes(dupState.result.groups.reduce((sum, group) => sum + group.saved_bytes, 0))}）。默认勾选每组保留一个后的其余素材。
                  </p>
                  <div className="library-dup-groups">
                    {dupState.result.groups.map((group, groupIndex) => {
                      const members = [group.representative, ...group.duplicates];
                      const checkedCount = members.filter((item) => dupState.checked.has(item.path)).length;
                      const allChecked = checkedCount === members.length;
                      return (
                        <div key={groupIndex} className="library-dup-group">
                          <div className="library-dup-group-head">
                            <button type="button" className="quiet-button" onClick={() => toggleDupGroup(group, !allChecked)}>
                              {allChecked ? <Check size={13} /> : <Plus size={13} />}{allChecked ? "全部取消" : "全部选中"}
                            </button>
                            <span>{group.reason} · {group.count} 个素材 · 可释放 {formatBytes(group.saved_bytes)}</span>
                          </div>
                          <ul className="library-dup-list">
                            {members.map((item) => (
                              <li key={item.path} className={dupState.checked.has(item.path) ? "is-checked" : ""}>
                                <input type="checkbox" checked={dupState.checked.has(item.path)} onChange={() => toggleDupChecked(item.path)} aria-label={`选择 ${item.name}`} />
                                <span className="library-dup-thumb">
                                  {item.type === "audio" ? <BgmCover path={item.path} size="small" /> : <WatermarkThumb path={item.path} size="small" />}
                                </span>
                                <span className="library-dup-name">
                                  <strong>{item.name}</strong>
                                  <small>{item.folder ? `${item.folder} · ` : ""}{formatBytes(item.size_bytes)}</small>
                                </span>
                                {item.path === group.representative.path ? <span className="library-chip is-keep">保留</span> : null}
                              </li>
                            ))}
                          </ul>
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
            </div>
            <footer className="library-dialog-footer">
              <span className="library-dialog-footer-hint">删除会移入系统回收站；每组默认至少保留一个素材。</span>
              <span className="library-dialog-footer-actions">
                <button type="button" className="quiet-button" onClick={() => setDupOpen(false)} disabled={dupState.scanning}>关闭</button>
                {dupState.result && !dupState.scanning ? (
                  <button type="button" className="library-accent-button is-danger" onClick={() => void deleteCheckedDuplicates()} disabled={!dupState.checked.size}>
                    <Trash2 size={14} />删除选中（{dupState.checked.size}）
                  </button>
                ) : null}
              </span>
            </footer>
          </section>
        </div>
      ) : null}

      {batchRenameOpen ? (
        <div className="library-backdrop library-backdrop-inner" role="presentation" onMouseDown={(event) => { event.stopPropagation(); if (!batchRename.applying) setBatchRenameOpen(false); }}>
          <section className="library-rename-batch-dialog" role="dialog" aria-modal="true" aria-labelledby="library-rename-batch-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="library-dialog-heading">
              <span className="library-dialog-icon"><Wand2 size={20} /></span>
              <span>
                <small>批量重命名</small>
                <strong id="library-rename-batch-title">批量重命名（{batchRename.items.length} 项）</strong>
              </span>
              <button type="button" className="update-close" onClick={() => setBatchRenameOpen(false)} disabled={batchRename.applying} aria-label="关闭批量重命名窗口"><X size={17} /></button>
            </header>
            <div className="library-rename-batch-body">
              <div className="library-rename-batch-fields">
                <label>
                  <span>模板</span>
                  <input value={batchRename.pattern} onChange={(event) => updateBatchRenameDraft({ pattern: event.target.value })} placeholder="{n}-{name}" aria-label="重命名模板" />
                </label>
                <label>
                  <span>起始序号</span>
                  <input type="number" min={1} value={batchRename.startIndex} onChange={(event) => updateBatchRenameDraft({ startIndex: Math.max(1, Number(event.target.value) || 1) })} aria-label="起始序号" />
                </label>
              </div>
              <p className="library-rename-batch-hint">占位符：{'{n}'}=序号（自动补零）、{'{name}'}=原文件名、{'{date}'}=当天日期。扩展名保持不变。</p>
              <div className="library-rename-batch-list">
                <div className="library-rename-batch-head"><span>原文件名</span><span>新文件名</span></div>
                {batchRename.preview.map((row, index) => (
                  <div key={index} className={`library-rename-batch-row${row.ok ? "" : " is-error"}`}>
                    <span title={batchRename.items[index]?.path}>{row.old}</span>
                    <span><ArrowRight size={12} /><em className={row.ok ? "" : "is-invalid"}>{row.next}</em>{!row.ok ? <small>{row.reason}</small> : null}</span>
                  </div>
                ))}
              </div>
            </div>
            <footer className="library-dialog-footer">
              <span className="library-dialog-footer-hint">{batchRename.preview.filter((row) => row.ok).length} 个可重命名，{batchRename.preview.filter((row) => !row.ok).length} 个不可用。</span>
              <span className="library-dialog-footer-actions">
                <button type="button" className="quiet-button" onClick={() => setBatchRenameOpen(false)} disabled={batchRename.applying}>取消</button>
                <button type="button" className="library-accent-button" onClick={() => void applyBatchRename()} disabled={batchRename.applying || !batchRename.preview.some((row) => row.ok)}>
                  {batchRename.applying ? <Loader2 className="is-spinning" size={14} /> : <Wand2 size={14} />}重命名
                </button>
              </span>
            </footer>
          </section>
        </div>
      ) : null}

      {smartFolderOpen ? (
        <div className="library-backdrop library-backdrop-inner" role="presentation" onMouseDown={(event) => { event.stopPropagation(); setSmartFolderOpen(false); setSmartFolderEdit(null); }}>
          <section className="library-smart-dialog" role="dialog" aria-modal="true" aria-labelledby="library-smart-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="library-dialog-heading">
              <span className="library-dialog-icon"><FolderCog size={20} /></span>
              <span>
                <small>规则虚拟集合</small>
                <strong id="library-smart-title">智能文件夹</strong>
              </span>
              <button type="button" className="update-close" onClick={() => { setSmartFolderOpen(false); setSmartFolderEdit(null); }} aria-label="关闭智能文件夹窗口"><X size={17} /></button>
            </header>
            <div className="library-smart-body">
              {smartFolderEdit ? (
                <SmartFolderEditor folder={smartFolderEdit} onChange={setSmartFolderEdit} onCancel={() => setSmartFolderEdit(null)} onSave={() => void saveSmartFolderEdit()} />
              ) : (
                <>
                  <div className="library-smart-list-rows">
                    {smartFolders.length ? smartFolders.map((folder) => (
                      <div key={folder.id} className="library-smart-row">
                        <span className="library-smart-row-main">
                          <strong>{folder.name}</strong>
                          <small>{folder.kind === "bgm" ? "BGM 库" : "水印库"} · {smartFolderRuleSummary(folder)}</small>
                        </span>
                        <span className="library-smart-row-actions">
                          <button type="button" className="icon-button" onClick={() => setSmartFolderEdit(folder)} aria-label={`编辑 ${folder.name}`} title="编辑"><Pencil size={13} /></button>
                          <button type="button" className="icon-button danger" onClick={() => deleteSmartFolder(folder.id)} aria-label={`删除 ${folder.name}`} title="删除"><Trash2 size={13} /></button>
                        </span>
                      </div>
                    )) : <span className="library-smart-empty">还没有智能文件夹。点击「新建」按规则自动归类素材。</span>}
                  </div>
                  <button type="button" className="library-accent-button" onClick={openSmartFolderCreate}><FolderPlus size={14} />新建智能文件夹</button>
                </>
              )}
            </div>
            <footer className="library-dialog-footer">
              <span className="library-dialog-footer-hint">智能文件夹不移动文件，只按条件实时筛选展示。</span>
              <span className="library-dialog-footer-actions">
                <button type="button" className="library-primary-button" onClick={() => { setSmartFolderOpen(false); setSmartFolderEdit(null); }}>完成</button>
              </span>
            </footer>
          </section>
        </div>
      ) : null}

      <audio ref={audioRef} className="library-audio" />
    </div>
  );

  return createPortal(dialog, document.body);
}

function FolderNode({ nodes, depth, currentFolder, expanded, creatingUnder, renaming, folderDraft, dropTarget, onFolderDraft, onSelect, onToggle, onStartCreate, onStartRename, onDelete, onCommit, onCancelEdit, onFolderDragOver, onFolderDrop, onFolderDragLeave }: {
  nodes: TreeNode[];
  depth: number;
  currentFolder: string;
  expanded: Set<string>;
  creatingUnder: string | null;
  renaming: string | null;
  folderDraft: string;
  dropTarget: string | null;
  onFolderDraft: (value: string) => void;
  onSelect: (folder: string) => void;
  onToggle: (folder: string) => void;
  onStartCreate: (parent: string) => void;
  onStartRename: (folder: string) => void;
  onDelete: (folder: string) => void;
  onCommit: () => void;
  onCancelEdit: () => void;
  onFolderDragOver: (folder: string, event: ReactDragEvent<HTMLElement>) => void;
  onFolderDrop: (folder: string, event: ReactDragEvent<HTMLElement>) => void;
  onFolderDragLeave: (folder: string) => void;
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
              <button
                type="button"
                className={`library-tree-folder${dropTarget === node.relative ? " is-drop-target" : ""}`}
                onClick={() => onSelect(node.relative)}
                onDragOver={(event) => onFolderDragOver(node.relative, event)}
                onDrop={(event) => onFolderDrop(node.relative, event)}
                onDragLeave={() => onFolderDragLeave(node.relative)}
              >
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
                dropTarget={dropTarget}
                onFolderDraft={onFolderDraft}
                onSelect={onSelect}
                onToggle={onToggle}
                onStartCreate={onStartCreate}
                onStartRename={onStartRename}
                onDelete={onDelete}
                onCommit={onCommit}
                onCancelEdit={onCancelEdit}
                onFolderDragOver={onFolderDragOver}
                onFolderDrop={onFolderDrop}
                onFolderDragLeave={onFolderDragLeave}
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

function StarButton({ item, onToggle }: { item: LibraryItem; onToggle: (item: LibraryItem) => void }) {
  return (
    <button
      type="button"
      className={`icon-button library-star-button${item.starred ? " is-starred" : ""}`}
      onClick={(event) => { event.stopPropagation(); onToggle(item); }}
      aria-label={item.starred ? `取消收藏 ${item.name}` : `收藏 ${item.name}`}
      title={item.starred ? "取消收藏" : "收藏"}
    >
      <Star size={14} fill={item.starred ? "currentColor" : "none"} />
    </button>
  );
}

function SmartFolderEditor({ folder, onChange, onCancel, onSave }: {
  folder: LibrarySmartFolder;
  onChange: (folder: LibrarySmartFolder) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  const updateCondition = (index: number, patch: Partial<LibrarySmartFolderCondition>) => {
    onChange({ ...folder, conditions: folder.conditions.map((condition, i) => (i === index ? { ...condition, ...patch } : condition)) });
  };
  const removeCondition = (index: number) => {
    onChange({ ...folder, conditions: folder.conditions.filter((_, i) => i !== index) });
  };
  const addCondition = () => {
    onChange({ ...folder, conditions: [...folder.conditions, { field: "type", op: "eq", value: "image" }] });
  };
  return (
    <div className="library-smart-editor">
      <label className="library-smart-editor-name">
        <span>名称</span>
        <input autoFocus value={folder.name} onChange={(event) => onChange({ ...folder, name: event.target.value })} placeholder="如：长视频水印" aria-label="智能文件夹名称" />
      </label>
      <div className="library-smart-editor-kind">
        <span>应用于</span>
        <select value={folder.kind} onChange={(event) => onChange({ ...folder, kind: event.target.value as LibraryKind })} aria-label="应用于哪个库">
          <option value="bgm">BGM 库</option>
          <option value="watermark">水印库</option>
        </select>
      </div>
      <div className="library-smart-editor-conditions">
        <span>条件（全部满足才显示）</span>
        {folder.conditions.map((condition, index) => (
          <div key={index} className="library-smart-condition">
            <select value={condition.field} onChange={(event) => updateCondition(index, { field: event.target.value as LibrarySmartFolderCondition["field"] })} aria-label="条件字段">
              <option value="type">类型</option>
              <option value="duration">时长（秒）</option>
              <option value="size">大小（字节）</option>
              <option value="folder">文件夹</option>
              <option value="name">文件名</option>
              <option value="tag">标签</option>
              <option value="starred">收藏</option>
            </select>
            <select value={condition.op} onChange={(event) => updateCondition(index, { op: event.target.value as LibrarySmartFolderCondition["op"] })} aria-label="条件操作符">
              <option value="eq">等于</option>
              <option value="ne">不等于</option>
              <option value="gt">大于</option>
              <option value="lt">小于</option>
              <option value="contains">包含</option>
              <option value="exists">存在</option>
            </select>
            {condition.op !== "exists" ? (
              condition.field === "starred" ? (
                <select value={String(condition.value ?? "")} onChange={(event) => updateCondition(index, { value: event.target.value === "true" })} aria-label="收藏条件值">
                  <option value="true">是</option>
                  <option value="false">否</option>
                </select>
              ) : condition.field === "type" ? (
                <select value={String(condition.value ?? "image")} onChange={(event) => updateCondition(index, { value: event.target.value })} aria-label="类型条件值">
                  <option value="image">图片</option>
                  <option value="video">视频</option>
                  <option value="audio">音频</option>
                </select>
              ) : (
                <input value={String(condition.value ?? "")} onChange={(event) => updateCondition(index, { value: event.target.value })} placeholder={condition.field === "duration" ? "秒" : condition.field === "size" ? "字节" : "值"} aria-label="条件值" />
              )
            ) : null}
            <button type="button" className="icon-button danger" onClick={() => removeCondition(index)} aria-label="删除条件"><X size={12} /></button>
          </div>
        ))}
        <button type="button" className="quiet-button" onClick={addCondition}><Plus size={12} />添加条件</button>
      </div>
      <footer className="library-dialog-footer">
        <span className="library-dialog-footer-hint">保存后左侧「智能文件夹」即可按条件筛选。</span>
        <span className="library-dialog-footer-actions">
          <button type="button" className="quiet-button" onClick={onCancel}>取消</button>
          <button type="button" className="library-accent-button" onClick={onSave} disabled={!folder.name.trim()}>保存</button>
        </span>
      </footer>
    </div>
  );
}

function ItemMetaChips({ item }: { item: LibraryItem }) {
  const tags = item.tags ?? [];
  if (!tags.length && !item.note) return null;
  return (
    <span className="library-item-chips">
      {tags.slice(0, 3).map((tag) => (
        <span key={tag} className="library-chip"><Tag size={9} />{tag}</span>
      ))}
      {tags.length > 3 ? <span className="library-chip is-more">+{tags.length - 3}</span> : null}
      {item.note ? <span className="library-chip is-note" title={item.note}><StickyNote size={9} />备注</span> : null}
    </span>
  );
}

// 水印缩略图：按 path 缓存提取结果，避免切换视图/搜索时重复调用引擎（同 BgmCover 的策略）
const watermarkThumbCache = new Map<string, string | null>();

function AudioProgressBar({ audioRef, onSeek }: { audioRef: RefObject<HTMLAudioElement | null>; onSeek: (ratio: number) => void }) {
  const [progress, setProgress] = useState<{ current: number; duration: number } | null>(null);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const update = () => {
      const currentTime = audio.currentTime;
      const duration = audio.duration;
      if (!Number.isFinite(duration) || duration <= 0) return;
      // 仅当整秒变化时更新，避免每个 timeupdate 都触发父级重渲染
      setProgress((prev) => (prev && Math.floor(prev.current) === Math.floor(currentTime) ? prev : { current: currentTime, duration }));
    };
    audio.addEventListener("timeupdate", update);
    audio.addEventListener("loadedmetadata", update);
    audio.addEventListener("durationchange", update);
    update();
    return () => {
      audio.removeEventListener("timeupdate", update);
      audio.removeEventListener("loadedmetadata", update);
      audio.removeEventListener("durationchange", update);
    };
  }, [audioRef]);

  const current = progress?.current ?? 0;
  const duration = progress?.duration ?? 0;
  const ratio = duration > 0 ? Math.min(1, current / duration) : 0;
  return (
    <span className="library-audio-progress">
      <span
        className="library-audio-progress-track"
        onClick={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          onSeek(rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0);
        }}
        aria-label="播放进度，点击可定位"
      >
        <span className="library-audio-progress-fill" style={{ width: `${ratio * 100}%` }} />
      </span>
      <small>{formatClock(current)} / {formatClock(duration)}</small>
    </span>
  );
}

function WatermarkThumb({ path, size = "normal" }: { path: string; size?: "small" | "normal" }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const cached = watermarkThumbCache.get(path);
    if (cached !== undefined) {
      if (cached) setUrl(cached);
      else setFailed(true);
      return;
    }
    void engine.call<{ preview_path: string }>("preview_thumbnail", { path, max_width: 240, max_height: 240 }, 30_000)
      .then((result) => {
        if (cancelled) return;
        const thumbUrl = engine.toAssetUrl(result.preview_path);
        watermarkThumbCache.set(path, thumbUrl || null);
        if (thumbUrl) setUrl(thumbUrl);
        else setFailed(true);
      })
      .catch(() => {
        if (!cancelled) {
          watermarkThumbCache.set(path, null);
          setFailed(true);
        }
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