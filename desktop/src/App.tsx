import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open as openDialog, save as saveDialog } from "@tauri-apps/plugin-dialog";
import {
  Aperture,
  ArchiveRestore,
  BrainCircuit,
  Check,
  CircleAlert,
  FolderOpen,
  Gauge,
  HardDrive,
  Moon,
  Play,
  Save,
  Sun,
} from "lucide-react";
import { FALLBACK_CONFIG } from "./constants";
import { engine } from "./engine";
import { Inspector, type InspectorTabId } from "./components/Inspector";
import { JobManifest } from "./components/JobManifest";
import { PreviewStage } from "./components/PreviewStage";
import { UpdateCenter } from "./components/UpdateCenter";
import { WorkspaceRail } from "./components/WorkspaceRail";
import type {
  EngineEvent,
  EngineState,
  JobState,
  PreviewAsset,
  SystemSnapshot,
  ValidationIssue,
  VideoConfig,
  Workspace,
} from "./types";
import "./App.css";

const STORAGE_KEY = "image-to-video.workspaces.v1";
const THEME_KEY = "image-to-video.theme";
const LAYOUT_KEY = "image-to-video.layout.v3";

type LayoutState = {
  railWidth: number;
  inspectorWidth: number;
  manifestHeight: number;
  railCollapsed: boolean;
  inspectorCollapsed: boolean;
};

type LayoutSizeKey = "railWidth" | "inspectorWidth" | "manifestHeight";

const DEFAULT_LAYOUT: LayoutState = {
  railWidth: 216,
  inspectorWidth: 440,
  manifestHeight: 267,
  railCollapsed: false,
  inspectorCollapsed: false,
};

const INSPECTOR_SECTION_LABELS: Record<string, string> = {
  basic: "基础参数",
  motion: "转场与特效",
  watermark: "视频水印",
};
const GENERAL_SECTION_LABEL = "通用";

const LAYOUT_LIMITS: Record<LayoutSizeKey, [number, number]> = {
  railWidth: [168, 360],
  inspectorWidth: [400, 580],
  manifestHeight: [267, 420],
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function loadLayout(): LayoutState {
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

function uuid() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function makeDemoPreview(): PreviewAsset {
  const scenes: Array<{ subject: string; x: number; y: number; r: number; hue: string }> = [
    { subject: "樱花树", x: 0.26, y: 0.4, r: 0.3, hue: "#d98c9a" },
    { subject: "古城塔", x: 0.74, y: 0.34, r: 0.24, hue: "#8faece" },
    { subject: "花海", x: 0.5, y: 0.62, r: 0.28, hue: "#c9a86a" },
    { subject: "远山", x: 0.38, y: 0.28, r: 0.32, hue: "#7d9b8f" },
    { subject: "湖面", x: 0.64, y: 0.46, r: 0.26, hue: "#6f86b8" },
  ];
  const frames = scenes.map((scene, index) => {
    const canvas = document.createElement("canvas");
    canvas.width = 1280;
    canvas.height = 720;
    const context = canvas.getContext("2d");
    if (!context) {
      return {
        source: `demo://${scene.subject}.png`,
        previewPath: "",
        previewUrl: "",
        width: 1280,
        height: 720,
      };
    }
    const gradient = context.createLinearGradient(0, 0, 0, 720);
    gradient.addColorStop(0, "#2b3440");
    gradient.addColorStop(1, "#12161c");
    context.fillStyle = gradient;
    context.fillRect(0, 0, 1280, 720);
    context.fillStyle = "rgba(255,255,255,.08)";
    context.fillRect(0, 400, 1280, 1);
    const cx = scene.x * 1280;
    const cy = scene.y * 720;
    const radius = scene.r * 720;
    context.beginPath();
    context.arc(cx, cy, radius, 0, Math.PI * 2);
    context.fillStyle = "rgba(255,255,255,.05)";
    context.fill();
    context.beginPath();
    context.arc(cx, cy, radius * 0.62, 0, Math.PI * 2);
    context.fillStyle = scene.hue;
    context.fill();
    context.beginPath();
    context.arc(cx, cy, radius * 0.28, 0, Math.PI * 2);
    context.fillStyle = "rgba(255,255,255,.5)";
    context.fill();
    context.font = "16px 'Microsoft YaHei', sans-serif";
    context.fillStyle = "rgba(255,255,255,.42)";
    context.textAlign = "left";
    context.fillText(`演示素材 · ${scene.subject}`, 18, 28);
    context.textAlign = "right";
    context.fillText(`第 ${index + 1} / ${scenes.length} 张`, 1262, 28);
    return {
      source: `demo://${scene.subject}.png`,
      previewPath: "",
      previewUrl: canvas.toDataURL("image/png"),
      width: 1280,
      height: 720,
    };
  });
  return { ...frames[0], frames };
}

function makeWorkspace(config: VideoConfig, name = "新建工作区"): Workspace {
  return {
    id: uuid(),
    name,
    config: structuredClone(config),
    imageCount: null,
    preview: null,
    validationErrors: [],
    validationIssues: [],
    dirty: false,
  };
}

function previewSyncKey(workspace: Workspace, previewSequence = 0) {
  return JSON.stringify([
    workspace.id,
    workspace.config.input_dir.trim(),
    Math.max(0, Math.trunc(Number(workspace.config.num_images) || 0)),
    workspace.config.image_selection_mode,
    previewSequence,
  ]);
}

function makeQueuedJob(workspace: Workspace, demo = false): JobState {
  return {
    job_id: uuid(),
    workspaceId: workspace.id,
    workspaceName: workspace.name,
    status: "queued",
    paused: false,
    cancel_requested: false,
    progress: 0,
    overall: 0,
    speed: null,
    message: "等待调度",
    started_at: null,
    finished_at: null,
    return_code: null,
    outputPath: workspace.config.output_dir,
    configSummary: `${workspace.config.resolution_preset} · ${workspace.config.fps} fps · ${workspace.config.num_images} 图 · ${workspace.config.total_duration > 0 ? `${workspace.config.total_duration} 秒/条` : "自动时长"} × ${workspace.config.video_count} 条`,
    demo,
  };
}

function mergeStoredWorkspaces(raw: unknown, defaults: VideoConfig): Workspace[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((value) => {
    if (!value || typeof value !== "object") return [];
    const item = value as Partial<Workspace>;
    return [{
      id: typeof item.id === "string" ? item.id : uuid(),
      name: typeof item.name === "string" ? item.name : "恢复的工作区",
      config: { ...structuredClone(defaults), ...(item.config ?? {}) } as VideoConfig,
      imageCount: null,
      preview: null,
      validationErrors: [],
      validationIssues: [],
      dirty: false,
    }];
  });
}

function demoJobs(workspace: Workspace): JobState[] {
  const base = makeQueuedJob(workspace, true);
  return [
    { ...base, job_id: "demo-1", workspaceName: "樱花·序章", status: "running", progress: 55, overall: 55, speed: "1.8 张/秒", message: "渲染中", started_at: Date.now() / 1000 },
    { ...base, job_id: "demo-2", workspaceName: "樱花·花海", status: "queued", progress: 0, overall: 0, message: "等待调度" },
    { ...base, job_id: "demo-3", workspaceName: "樱花·古城", status: "completed", progress: 100, overall: 100, message: "处理完成", finished_at: Date.now() / 1000 },
    { ...base, job_id: "demo-4", workspaceName: "樱花·夜游", status: "completed", progress: 100, overall: 100, message: "处理完成", finished_at: Date.now() / 1000 },
    { ...base, job_id: "demo-5", workspaceName: "樱花·雨后", status: "failed", progress: 34, overall: 34, message: "素材读取失败", finished_at: Date.now() / 1000 },
    { ...base, job_id: "demo-6", workspaceName: "樱花·终章", status: "cancelled", progress: 12, overall: 12, message: "任务已取消", finished_at: Date.now() / 1000 },
  ];
}

type Notice = { kind: "info" | "success" | "error"; message: string } | null;

export default function App() {
  const demoMode = new URLSearchParams(window.location.search).has("demo");
  const initialWorkspace = useMemo(() => {
    const workspace = makeWorkspace(FALLBACK_CONFIG, demoMode ? "春日樱花图集转视频" : "工作区 1");
    if (demoMode) {
      workspace.config = {
        ...workspace.config,
        input_dir: "D:\\素材\\春日樱花",
        output_dir: "D:\\输出\\樱花系列",
        num_images: 50,
        video_count: 5,
        duration: 2,
        resolution_preset: "1920x1080",
        use_video_effect: true,
        video_effect_type: "镜头呼吸",
        use_bgm: true,
        bgm_dir: "D:\\素材\\BGM",
      };
      workspace.imageCount = 120;
      workspace.preview = makeDemoPreview();
    }
    return workspace;
  }, [demoMode]);

  const [workspaces, setWorkspaces] = useState<Workspace[]>([initialWorkspace]);
  const [activeId, setActiveId] = useState(initialWorkspace.id);
  const [jobs, setJobs] = useState<JobState[]>(demoMode ? demoJobs(initialWorkspace) : []);
  const [concurrency, setConcurrency] = useState(2);
  const [engineState, setEngineState] = useState<EngineState>({
    connected: false,
    connecting: true,
    previewOnly: !engine.desktopRuntime,
    message: engine.desktopRuntime ? "正在连接本地引擎" : "界面预览模式",
    health: null,
  });
  const [system, setSystem] = useState<SystemSnapshot | null>(null);
  const [ready, setReady] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [theme, setTheme] = useState<"light" | "dark">(() => localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light");
  const [layout, setLayout] = useState<LayoutState>(loadLayout);
  const [previewFocused, setPreviewFocused] = useState(false);
  const [previewSequences, setPreviewSequences] = useState<Record<string, number>>({});
  const [previewReadySequences, setPreviewReadySequences] = useState<Record<string, number>>({});
  const [inspectorTab, setInspectorTab] = useState<InspectorTabId>("basic");

  const jobsRef = useRef(jobs);
  const queuedWorkspaces = useRef(new Map<string, Workspace>());
  const pumpQueueRef = useRef<() => void>(() => undefined);
  const latestPreviewKey = useRef("");
  const validationTokens = useRef<Record<string, number>>({});
  const activeWorkspace = workspaces.find((workspace) => workspace.id === activeId) ?? workspaces[0];
  const activePreviewSequence = activeWorkspace ? previewSequences[activeWorkspace.id] ?? 0 : 0;
  const activePreviewReadySequence = activeWorkspace ? previewReadySequences[activeWorkspace.id] ?? 0 : 0;

  useEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);

  const showNotice = useCallback((kind: Notice extends infer _ ? "info" | "success" | "error" : never, message: string) => {
    setNotice({ kind, message });
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
  }, [layout]);

  useEffect(() => {
    if (!previewFocused) return;
    const exitFocus = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreviewFocused(false);
    };
    window.addEventListener("keydown", exitFocus);
    return () => window.removeEventListener("keydown", exitFocus);
  }, [previewFocused]);

  const nudgeLayout = useCallback((key: LayoutSizeKey, delta: number) => {
    const [min, max] = LAYOUT_LIMITS[key];
    setLayout((current) => ({ ...current, [key]: clamp(current[key] + delta, min, max) }));
  }, []);

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

  const updateJobFromEvent = useCallback((event: EngineEvent) => {
    if (event.event === "engine.closed" || event.event === "engine.error") {
      setEngineState((state) => ({ ...state, connected: false, connecting: false, message: "本地引擎连接已中断" }));
      return;
    }
    const jobId = String(event.payload.job_id ?? "");
    if (!jobId) return;
    setJobs((current) => {
      const next = current.map((job) => {
        if (job.job_id !== jobId) return job;
        const payload = event.payload as Partial<JobState>;
        return {
          ...job,
          ...payload,
          job_id: job.job_id,
          workspaceId: job.workspaceId,
          workspaceName: job.workspaceName,
          outputPath: job.outputPath,
        };
      });
      jobsRef.current = next;
      return next;
    });
    if (event.event === "job.finished") {
      queuedWorkspaces.current.delete(jobId);
      window.setTimeout(() => pumpQueueRef.current(), 0);
    }
  }, []);

  const refreshSystem = useCallback(async (outputDir = "") => {
    if (!engine.desktopRuntime) return;
    try {
      setSystem(await engine.call<SystemSnapshot>("system_snapshot", { output_dir: outputDir }));
    } catch {
      setSystem(null);
    }
  }, []);

  useEffect(() => {
    const unsubscribe = engine.subscribe(updateJobFromEvent);
    const unsubscribeReady = engine.subscribe((event) => {
      if (event.type === "event" && event.event === "engine.ready" && !cancelled) setReady(true);
    });
    let cancelled = false;
    const initialize = async () => {
      let defaults = structuredClone(FALLBACK_CONFIG);
      try {
        if (engine.desktopRuntime) {
          const health = await engine.connect();
          defaults = await engine.call<VideoConfig>("default_config");
          if (!cancelled) setEngineState({ connected: true, connecting: false, previewOnly: false, message: "本地引擎正常", health });
          await refreshSystem();
        } else if (!cancelled) {
          setEngineState({ connected: false, connecting: false, previewOnly: true, message: "界面预览模式", health: null });
        }
      } catch (error) {
        if (!cancelled) setEngineState({ connected: false, connecting: false, previewOnly: false, message: error instanceof Error ? error.message : "本地引擎连接失败", health: null });
      }

      if (!demoMode) {
        let restored: Workspace[] = [];
        try {
          restored = mergeStoredWorkspaces(JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"), defaults);
        } catch {
          restored = [];
        }
        if (!cancelled) {
          const next = restored.length ? restored : [makeWorkspace(defaults, "工作区 1")];
          setWorkspaces(next);
          setActiveId(next[0].id);
        }
      }
      if (!cancelled) setReady(true);
    };
    void initialize();
    return () => {
      cancelled = true;
      unsubscribe();
      unsubscribeReady();
    };
  }, [demoMode, refreshSystem, updateJobFromEvent]);

  useEffect(() => {
    if (!ready || demoMode) return;
    const serializable = workspaces.map(({ preview: _preview, validationErrors: _errors, validationIssues: _issues, ...workspace }) => workspace);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(serializable));
  }, [demoMode, ready, workspaces]);

  useEffect(() => {
    if (!engineState.connected) return;
    const timer = window.setInterval(() => void refreshSystem(activeWorkspace?.config.output_dir ?? ""), 10_000);
    return () => window.clearInterval(timer);
  }, [activeWorkspace?.config.output_dir, engineState.connected, refreshSystem]);

  const patchWorkspace = useCallback((id: string, patch: Partial<Workspace>) => {
    setWorkspaces((current) => current.map((workspace) => workspace.id === id ? { ...workspace, ...patch } : workspace));
  }, []);

  const updateConfig = useCallback(<K extends keyof VideoConfig>(key: K, value: VideoConfig[K]) => {
    if (key === "input_dir") {
      setPreviewSequences((current) => ({ ...current, [activeId]: 0 }));
      setPreviewReadySequences((current) => ({ ...current, [activeId]: 0 }));
    }
    setWorkspaces((current) => current.map((workspace) => {
      if (workspace.id !== activeId) return workspace;
      let preview = workspace.preview;
      if (key === "input_dir" || key === "image_selection_mode") {
        preview = null;
      } else if (key === "num_images" && workspace.preview) {
        const limit = Math.max(0, Math.trunc(Number(value) || 0));
        const frames = workspace.preview.frames.slice(0, limit);
        preview = frames.length ? { ...frames[0], frames } : null;
      }
      return {
        ...workspace,
        config: { ...workspace.config, [key]: value },
        preview,
        imageCount: key === "input_dir" ? null : workspace.imageCount,
        validationErrors: [],
        validationIssues: [],
        dirty: true,
      };
    }));
  }, [activeId]);

  const refreshPreview = useCallback(async (workspace: Workspace, announce = true, previewSequence = 0) => {
    const requestKey = previewSyncKey(workspace, previewSequence);
    latestPreviewKey.current = requestKey;
    if (!workspace.config.input_dir) {
      patchWorkspace(workspace.id, { validationErrors: ["请输入输入目录"], validationIssues: [{ field: "input_dir", section: "basic", message: "请输入输入目录" }] });
      if (announce) showNotice("error", "请输入输入目录");
      return;
    }
    const previewLimit = Math.max(0, Math.trunc(Number(workspace.config.num_images) || 0));
    if (!previewLimit) {
      patchWorkspace(workspace.id, { preview: null, validationErrors: ["每个视频图片数必须大于 0"], validationIssues: [{ field: "num_images", section: "basic", message: "每个视频图片数必须大于 0" }] });
      if (announce) showNotice("error", "每个视频图片数必须大于 0");
      return;
    }
    setPreviewLoading(true);
    try {
      const scan = await engine.call<{ count: number; images: Array<{ path: string; name: string }> }>("scan_images", {
        input_dir: workspace.config.input_dir,
        limit: previewLimit,
        preview_sequence: previewSequence,
      }, 30_000);
      let preview: Workspace["preview"] = null;
      if (scan.count > 0) {
        const results = await Promise.all(scan.images.map(({ path }) => engine.call<{ source: string; preview_path: string; width: number; height: number }>("preview_thumbnail", { path }, 30_000)));
        const frames = results.map((result) => ({
          source: result.source,
          previewPath: result.preview_path,
          previewUrl: engine.toAssetUrl(result.preview_path),
          width: result.width,
          height: result.height,
        }));
        preview = frames.length ? { ...frames[0], frames } : null;
      }
      if (latestPreviewKey.current !== requestKey) return;
      patchWorkspace(workspace.id, { imageCount: scan.count, preview, validationErrors: scan.count ? [] : ["输入目录里没有可用图片"], validationIssues: scan.count ? [] : [{ field: "input_dir", section: "basic", message: "输入目录里没有可用图片" }] });
      if (scan.count > 0) {
        setPreviewReadySequences((current) => ({ ...current, [workspace.id]: previewSequence }));
      }
      if (announce) showNotice(scan.count ? "success" : "error", scan.count ? `已读取 ${scan.count} 张图片` : "目录中没有可用图片");
    } catch (error) {
      if (latestPreviewKey.current !== requestKey) return;
      const message = error instanceof Error ? error.message : "读取预览失败";
      patchWorkspace(workspace.id, { validationErrors: [message], validationIssues: [{ field: "", section: "", message }] });
      if (announce) showNotice("error", message);
    } finally {
      if (latestPreviewKey.current === requestKey) setPreviewLoading(false);
    }
  }, [patchWorkspace, showNotice]);

  useEffect(() => {
    if (!activeWorkspace) return;
    const requestKey = previewSyncKey(activeWorkspace, activePreviewSequence);
    latestPreviewKey.current = requestKey;
    if (!ready || demoMode || !engineState.connected || !activeWorkspace.config.input_dir || activeWorkspace.config.num_images <= 0) {
      setPreviewLoading(false);
      return;
    }
    const workspace = activeWorkspace;
    const timer = window.setTimeout(() => void refreshPreview(workspace, false, activePreviewSequence), 280);
    return () => window.clearTimeout(timer);
  }, [
    activeWorkspace?.id,
    activeWorkspace?.config.input_dir,
    activeWorkspace?.config.num_images,
    activeWorkspace?.config.image_selection_mode,
    activePreviewSequence,
    demoMode,
    engineState.connected,
    ready,
    refreshPreview,
  ]);

  useEffect(() => {
    if (!activeWorkspace || demoMode || !engineState.connected) return;
    const token = (validationTokens.current[activeWorkspace.id] ?? 0) + 1;
    validationTokens.current[activeWorkspace.id] = token;
    const { id, config } = activeWorkspace;
    const timer = window.setTimeout(async () => {
      try {
        const result = await engine.call<{ valid: boolean; issues: ValidationIssue[] }>(
          "validate_config_detailed",
          { config, check_files: true },
          30_000,
        );
        if (validationTokens.current[id] !== token) return;
        patchWorkspace(id, {
          validationIssues: result.issues,
          validationErrors: result.issues.map((issue) => issue.message),
        });
      } catch {
        /* 校验失败不阻塞编辑，等待下次重试用 */
      }
    }, 400);
    return () => window.clearTimeout(timer);
  }, [
    activeWorkspace?.id,
    activeWorkspace?.config.input_dir,
    activeWorkspace?.config.output_dir,
    activeWorkspace?.config.num_images,
    activeWorkspace?.config.video_count,
    activeWorkspace?.config.duration,
    activeWorkspace?.config.total_duration,
    activeWorkspace?.config.use_bgm,
    activeWorkspace?.config.bgm_dir,
    activeWorkspace?.config.watermark_audio,
    activeWorkspace?.config.image_selection_mode,
    demoMode,
    engineState.connected,
    patchWorkspace,
  ]);

  const browseDirectory = useCallback(async (key: keyof VideoConfig) => {
    if (!engine.desktopRuntime) return showNotice("info", "目录选择需要在 Tauri 桌面窗口中运行");
    const selected = await openDialog({ directory: true, multiple: false, title: "选择目录" });
    if (typeof selected !== "string") return;
    updateConfig(key, selected as VideoConfig[typeof key]);
  }, [showNotice, updateConfig]);

  const browseFile = useCallback(async (key: keyof VideoConfig, layerIndex?: number) => {
    if (!engine.desktopRuntime) return showNotice("info", "文件选择需要在 Tauri 桌面窗口中运行");
    const selected = await openDialog({
      directory: false,
      multiple: false,
      title: "选择本地素材",
      filters: [{ name: "媒体文件", extensions: ["png", "jpg", "jpeg", "webp", "bmp", "mp4", "mov", "avi", "mp3", "wav", "m4a"] }],
    });
    if (typeof selected !== "string") return;
    if (key === "watermark_layers" && typeof layerIndex === "number") {
      const layers = activeWorkspace.config.watermark_layers.map((layer, index) => index === layerIndex ? { ...layer, path: selected } : layer);
      updateConfig("watermark_layers", layers);
    } else {
      updateConfig(key, selected as VideoConfig[typeof key]);
    }
  }, [activeWorkspace, showNotice, updateConfig]);

  const validateWorkspace = useCallback(async (workspace: Workspace) => {
    const result = await engine.call<{ valid: boolean; issues: ValidationIssue[] }>("validate_config_detailed", { config: workspace.config, check_files: true }, 30_000);
    patchWorkspace(workspace.id, { validationIssues: result.issues, validationErrors: result.issues.map((issue) => issue.message) });
    return { valid: result.valid, errors: result.issues.map((issue) => issue.message) };
  }, [patchWorkspace]);

  const pumpQueue = useCallback(() => {
    if (!engineState.connected) return;
    const currentJobs = jobsRef.current;
    const activeCount = currentJobs.filter((job) => ["running", "paused", "cancelling"].includes(job.status)).length;
    const nextJobs = currentJobs.filter((job) => job.status === "queued").slice(0, Math.max(0, concurrency - activeCount));
    for (const job of nextJobs) {
      const workspace = queuedWorkspaces.current.get(job.job_id);
      if (!workspace) continue;
      setJobs((current) => {
        const next = current.map((item) => item.job_id === job.job_id ? { ...item, status: "running" as const, message: "正在启动本地渲染" } : item);
        jobsRef.current = next;
        return next;
      });
      void engine.call<JobState>("start_job", { config: workspace.config, job_id: job.job_id }, 30_000).catch((error) => {
        queuedWorkspaces.current.delete(job.job_id);
        setJobs((current) => {
          const next = current.map((item) => item.job_id === job.job_id ? { ...item, status: "failed" as const, message: error instanceof Error ? error.message : "任务启动失败" } : item);
          jobsRef.current = next;
          return next;
        });
        showNotice("error", error instanceof Error ? error.message : "任务启动失败");
        window.setTimeout(() => pumpQueueRef.current(), 0);
      });
    }
  }, [concurrency, engineState.connected, showNotice]);

  useEffect(() => {
    pumpQueueRef.current = pumpQueue;
    pumpQueue();
  }, [pumpQueue]);

  const queueWorkspaces = useCallback(async (targets: Workspace[]) => {
    if (!engineState.connected) return showNotice("error", "本地引擎未连接，无法开始导出");
    const accepted: Array<{ workspace: Workspace; job: JobState }> = [];
    for (const workspace of targets) {
      try {
        const validation = await validateWorkspace(workspace);
        if (validation.valid) {
          const job = makeQueuedJob(workspace);
          accepted.push({ workspace, job });
          queuedWorkspaces.current.set(job.job_id, workspace);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : "配置校验失败";
        patchWorkspace(workspace.id, { validationErrors: [message], validationIssues: [{ field: "", section: "", message }] });
      }
    }
    if (!accepted.length) return showNotice("error", "没有可执行的工作区，请先处理参数提示");
    setJobs((current) => {
      const next = [...accepted.map(({ job }) => job), ...current];
      jobsRef.current = next;
      return next;
    });
    showNotice("success", `已加入 ${accepted.length} 个渲染任务`);
    window.setTimeout(() => pumpQueueRef.current(), 0);
  }, [engineState.connected, patchWorkspace, showNotice, validateWorkspace]);

  const controlJob = useCallback(async (method: "pause_job" | "resume_job" | "cancel_job", id: string) => {
    const local = jobsRef.current.find((job) => job.job_id === id);
    if (local?.status === "queued" && method === "cancel_job") {
      queuedWorkspaces.current.delete(id);
      setJobs((current) => {
        const next = current.map((job) => job.job_id === id ? { ...job, status: "cancelled" as const, message: "任务已取消" } : job);
        jobsRef.current = next;
        return next;
      });
      return;
    }
    try {
      await engine.call(method, { job_id: id });
    } catch (error) {
      showNotice("error", error instanceof Error ? error.message : "任务控制失败");
    }
  }, [showNotice]);

  const addWorkspace = useCallback(async () => {
    const defaults = await engine.call<VideoConfig>("default_config");
    const next = makeWorkspace(defaults, `工作区 ${workspaces.length + 1}`);
    setWorkspaces((current) => [...current, next]);
    setActiveId(next.id);
  }, [workspaces.length]);

  const duplicateWorkspace = useCallback(() => {
    if (!activeWorkspace) return;
    const next = makeWorkspace(activeWorkspace.config, `${activeWorkspace.name} 副本`);
    setWorkspaces((current) => [...current, next]);
    setActiveId(next.id);
  }, [activeWorkspace]);

  const removeWorkspace = useCallback(() => {
    if (workspaces.length <= 1) return;
    const next = workspaces.filter((workspace) => workspace.id !== activeId);
    setWorkspaces(next);
    setActiveId(next[0].id);
  }, [activeId, workspaces]);

  const saveConfig = useCallback(async () => {
    if (!activeWorkspace) return;
    if (!engine.desktopRuntime) return showNotice("info", "保存配置需要在 Tauri 桌面窗口中运行");
    const path = await saveDialog({ title: "保存工作区配置", defaultPath: `${activeWorkspace.name}.json`, filters: [{ name: "JSON 配置", extensions: ["json"] }] });
    if (!path) return;
    const normalized = await engine.call<VideoConfig>("normalize_config", { config: activeWorkspace.config });
    await invoke("write_text_file", { path, contents: JSON.stringify(normalized, null, 2) });
    patchWorkspace(activeWorkspace.id, { config: normalized, dirty: false });
    showNotice("success", "配置已保存");
  }, [activeWorkspace, patchWorkspace, showNotice]);

  const loadConfig = useCallback(async () => {
    if (!engine.desktopRuntime) return showNotice("info", "加载配置需要在 Tauri 桌面窗口中运行");
    const path = await openDialog({ title: "加载工作区配置", multiple: false, filters: [{ name: "JSON 配置", extensions: ["json"] }] });
    if (typeof path !== "string") return;
    try {
      const contents = await invoke<string>("read_text_file", { path });
      const normalized = await engine.call<VideoConfig>("normalize_config", { config: JSON.parse(contents) });
      const name = path.split(/[\\/]/).pop()?.replace(/\.json$/i, "") || "加载的工作区";
      setPreviewSequences((current) => ({ ...current, [activeId]: 0 }));
      setPreviewReadySequences((current) => ({ ...current, [activeId]: 0 }));
      patchWorkspace(activeId, { name, config: normalized, imageCount: null, preview: null, validationErrors: [], validationIssues: [], dirty: false });
      showNotice("success", "配置已加载");
    } catch (error) {
      showNotice("error", error instanceof Error ? error.message : "配置加载失败");
    }
  }, [activeId, patchWorkspace, showNotice]);

  const optimizeMemory = useCallback(async () => {
    try {
      const result = await engine.call<{ before_mb: number; after_mb: number; collected: number }>("optimize_memory");
      showNotice("success", `内存整理完成：${result.before_mb} → ${result.after_mb} MB`);
      await refreshSystem(activeWorkspace.config.output_dir);
    } catch (error) {
      showNotice("error", error instanceof Error ? error.message : "内存整理失败");
    }
  }, [activeWorkspace.config.output_dir, refreshSystem, showNotice]);

  const revealPath = useCallback(async (path: string) => {
    if (!engine.desktopRuntime) return showNotice("info", "打开目录需要在 Tauri 桌面窗口中运行");
    try {
      await invoke("reveal_path", { path });
    } catch (error) {
      showNotice("error", error instanceof Error ? error.message : "无法打开路径");
    }
  }, [showNotice]);

  const activeHasRunningJob = jobs.some((job) => job.workspaceId === activeWorkspace?.id && ["queued", "running", "paused", "cancelling"].includes(job.status));
  const hasRunningJobs = jobs.some((job) => ["queued", "running", "paused", "cancelling"].includes(job.status));
  const canRun = engineState.connected || demoMode;
  const randomPreview = () => {
    setPreviewSequences((current) => ({
      ...current,
      [activeWorkspace.id]: (current[activeWorkspace.id] ?? 0) + 1,
    }));
    showNotice("info", "已换一组临时预览，不会修改保存配置或导出参数");
  };
  const runCurrent = () => demoMode
    ? showNotice("info", "这是标注过的界面演示数据；请在 Tauri 桌面窗口中选择真实素材后导出。")
    : void queueWorkspaces([activeWorkspace]);
  const runBatch = () => demoMode
    ? showNotice("info", "演示模式不会写入文件；桌面窗口会在配置校验后启动本地批量任务。")
    : void queueWorkspaces(workspaces);

  if (!activeWorkspace) return null;

  const appClassName = [
    "app-shell",
    layout.railCollapsed ? "is-rail-collapsed" : "",
    layout.inspectorCollapsed ? "is-inspector-collapsed" : "",
    previewFocused ? "is-preview-focused" : "",
  ].filter(Boolean).join(" ");
  const appStyle = {
    "--rail-width": `${layout.railCollapsed ? 0 : layout.railWidth}px`,
    "--inspector-width": `${layout.inspectorCollapsed ? 0 : layout.inspectorWidth}px`,
    "--manifest-height": `${layout.manifestHeight}px`,
  } as CSSProperties;

  return (
    <div className={appClassName} style={appStyle}>
      <header className="command-strip">
        <div className="brand-block">
          <span className="brand-mark"><Aperture size={20} /></span>
          <span><strong>图转视频极速版</strong><small>本地版</small></span>
        </div>

        <label className="project-name">
          <span>项目</span>
          <input value={activeWorkspace.name} onChange={(event) => patchWorkspace(activeWorkspace.id, { name: event.target.value, dirty: true })} />
        </label>

        <div className="instrument-status" aria-label="本地系统状态">
          <span className={engineState.connected ? "is-ok" : engineState.connecting ? "is-busy" : "is-error"}>
            {engineState.connected ? <Check size={14} /> : engineState.connecting ? <Gauge size={14} /> : <CircleAlert size={14} />}
            {engineState.message}
          </span>
          <span className={system?.ffmpeg_available ? "is-ok" : "is-error"}>
            <HardDrive size={14} />{system ? (system.ffmpeg_available ? "FFmpeg 已连接" : "FFmpeg 未找到") : "FFmpeg 待检测"}
          </span>
          {system ? <span title="系统 CPU、内存与输出盘余量"><BrainCircuit size={14} />CPU {Math.round(system.cpu_percent)}% · 内存 {system.memory_percent}% · 空闲 {system.disk_free_gb} GB</span> : null}
        </div>

        <nav className="command-actions" aria-label="项目命令">
          <button type="button" onClick={loadConfig}><ArchiveRestore size={15} />加载</button>
          <button type="button" onClick={saveConfig}><Save size={15} />保存</button>
          <button type="button" onClick={() => revealPath(activeWorkspace.config.output_dir)} disabled={!activeWorkspace.config.output_dir}><FolderOpen size={15} />输出</button>
          <button type="button" onClick={optimizeMemory} disabled={!engineState.connected}><Gauge size={15} />整理</button>
          <UpdateCenter hasActiveJobs={hasRunningJobs} />
          <button type="button" className="theme-button" onClick={() => setTheme((value) => value === "light" ? "dark" : "light")} aria-label={theme === "light" ? "切换深色主题" : "切换浅色主题"}>
            {theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
          </button>
          <button type="button" className="current-run-button" disabled={!canRun || (activeHasRunningJob && !demoMode)} onClick={runCurrent}><Play size={15} />导出当前</button>
        </nav>
      </header>

      {activeWorkspace.validationIssues.length ? (() => {
        const grouped = new Map<string, string[]>();
        for (const issue of activeWorkspace.validationIssues) {
          const key = issue.section || "general";
          if (!grouped.has(key)) grouped.set(key, []);
          grouped.get(key)!.push(issue.message);
        }
        const jumpToSection = (section: string) => {
          if (section && section !== "general") setInspectorTab(section as InspectorTabId);
          if (layout.inspectorCollapsed) setLayout((current) => ({ ...current, inspectorCollapsed: false }));
        };
        return (
          <div className="validation-banner" role="alert">
            <CircleAlert size={16} />
            <div className="validation-banner-body">
              <strong>当前工作区需要处理（{activeWorkspace.validationIssues.length} 项）：</strong>
              {Array.from(grouped.entries()).map(([section, messages]) => (
                <button type="button" key={section} className="validation-group" onClick={() => jumpToSection(section)} title="点击跳转到对应配置项">
                  <span className="validation-group-label">{INSPECTOR_SECTION_LABELS[section] ?? GENERAL_SECTION_LABEL}</span>
                  <span className="validation-group-items">{messages.join("；")}</span>
                </button>
              ))}
            </div>
          </div>
        );
      })() : <div className="validation-spacer" aria-hidden="true" />}

      <main className="production-grid">
        <WorkspaceRail
          workspaces={workspaces}
          jobs={jobs}
          activeId={activeWorkspace.id}
          onSelect={setActiveId}
          onAdd={() => void addWorkspace()}
          onDuplicate={duplicateWorkspace}
          onRemove={removeWorkspace}
        />
        <div
          className="layout-divider layout-divider-rail"
          role="separator"
          aria-label="调整工作区列表宽度"
          aria-orientation="vertical"
          aria-valuemin={LAYOUT_LIMITS.railWidth[0]}
          aria-valuemax={LAYOUT_LIMITS.railWidth[1]}
          aria-valuenow={layout.railWidth}
          tabIndex={0}
          onDoubleClick={() => setLayout((current) => ({ ...current, railWidth: DEFAULT_LAYOUT.railWidth }))}
          onPointerDown={(event) => beginLayoutResize("railWidth", event)}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") nudgeLayout("railWidth", -8);
            if (event.key === "ArrowRight") nudgeLayout("railWidth", 8);
          }}
        />
        <PreviewStage
          workspace={activeWorkspace}
          loading={previewLoading}
          demoMode={demoMode}
          railCollapsed={layout.railCollapsed}
          inspectorCollapsed={layout.inspectorCollapsed}
          focused={previewFocused}
          onRefresh={() => void refreshPreview(activeWorkspace, true, activePreviewSequence)}
          onRandomPreview={randomPreview}
          previewSequence={activePreviewSequence}
          previewReadySequence={activePreviewReadySequence}
          onToggleRail={() => setLayout((current) => ({ ...current, railCollapsed: !current.railCollapsed }))}
          onToggleInspector={() => setLayout((current) => ({ ...current, inspectorCollapsed: !current.inspectorCollapsed }))}
          onToggleFocus={() => setPreviewFocused((current) => !current)}
        />
        <div
          className="layout-divider layout-divider-inspector"
          role="separator"
          aria-label="调整参数检查器宽度"
          aria-orientation="vertical"
          aria-valuemin={LAYOUT_LIMITS.inspectorWidth[0]}
          aria-valuemax={LAYOUT_LIMITS.inspectorWidth[1]}
          aria-valuenow={layout.inspectorWidth}
          tabIndex={0}
          onDoubleClick={() => setLayout((current) => ({ ...current, inspectorWidth: DEFAULT_LAYOUT.inspectorWidth }))}
          onPointerDown={(event) => beginLayoutResize("inspectorWidth", event)}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") nudgeLayout("inspectorWidth", 8);
            if (event.key === "ArrowRight") nudgeLayout("inspectorWidth", -8);
          }}
        />
        <Inspector
          config={activeWorkspace.config}
          onChange={updateConfig}
          onBrowseDirectory={(key) => void browseDirectory(key)}
          onBrowseFile={(key, layerIndex) => void browseFile(key, layerIndex)}
          activeTab={inspectorTab}
          onActiveTabChange={setInspectorTab}
          validationIssues={activeWorkspace.validationIssues}
        />
      </main>

      <div
        className="layout-divider layout-divider-manifest"
        role="separator"
        aria-label="调整渲染任务区域高度"
        aria-orientation="horizontal"
        aria-valuemin={LAYOUT_LIMITS.manifestHeight[0]}
        aria-valuemax={LAYOUT_LIMITS.manifestHeight[1]}
        aria-valuenow={layout.manifestHeight}
        tabIndex={0}
        onDoubleClick={() => setLayout((current) => ({ ...current, manifestHeight: DEFAULT_LAYOUT.manifestHeight }))}
        onPointerDown={(event) => beginLayoutResize("manifestHeight", event)}
        onKeyDown={(event) => {
          if (event.key === "ArrowUp") nudgeLayout("manifestHeight", 8);
          if (event.key === "ArrowDown") nudgeLayout("manifestHeight", -8);
        }}
      />

      <JobManifest
        jobs={jobs}
        concurrency={concurrency}
        canRun={canRun && workspaces.length > 0}
        onConcurrencyChange={setConcurrency}
        onStartBatch={runBatch}
        onPause={(id) => void controlJob("pause_job", id)}
        onResume={(id) => void controlJob("resume_job", id)}
        onCancel={(id) => void controlJob("cancel_job", id)}
        onReveal={revealPath}
        onClearCompleted={() => setJobs((current) => {
          const next = current.filter((job) => !["completed", "failed", "cancelled"].includes(job.status));
          jobsRef.current = next;
          return next;
        })}
      />

      {!ready ? <div className="boot-status" role="status"><Gauge className="is-spinning" size={18} />正在校准本地工作台…</div> : null}
      {notice ? <div className={`toast toast-${notice.kind}`} role="status">{notice.kind === "success" ? <Check size={16} /> : notice.kind === "error" ? <CircleAlert size={16} /> : <Gauge size={16} />}{notice.message}</div> : null}
    </div>
  );
}
