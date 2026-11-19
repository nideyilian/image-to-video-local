import { convertFileSrc, invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { FALLBACK_CONFIG } from "./constants";
import type { EngineEvent, EngineHealth, ValidationIssue, VideoConfig } from "./types";

/** 已由 Rust 原生接管（不碰像素、纯文件扫描）的接口；其余继续走 Python 引擎。 */
const NATIVE_METHODS = new Set([
  "library_dirs",
  "library_snapshot",
  "library_import",
  "library_remove",
  "library_remove_batch",
  "library_move",
  "library_create_folder",
  "library_rename_folder",
  "library_delete_folder",
  "library_rename",
  "library_set_metadata",
  "library_get_tags",
  "library_smart_folders_list",
  "library_smart_folders_save",
  "library_rename_batch",
  "library_find_duplicates",
  "library_scan_tainted",
  "library_clean_tainted",
  "scan_images",
  "scan_subfolders",
  "scan_subfolder_groups",
  "default_config",
  "normalize_config",
  "validate_config",
  "validate_config_detailed",
  // 任务队列（事件走 Tauri emit，见 attachNativeEvents）
  "start_job",
  "pause_job",
  "resume_job",
  "cancel_job",
  "list_jobs",
  "system_snapshot",
  "optimize_memory",
  // 预览类（缓存键与目录和旧引擎共用，见 engine/preview.rs）
  "preview_thumbnail",
  "preview_bgm",
  "library_preview_audio",
  "library_preview_video",
  "library_audio_cover",
  // 特效演示图资产（渲染类 preview_effect_frame / effect_preview_animation 仍走旧引擎）
  "effect_library_assets",
  "effect_library_set_asset",
  "effect_library_reset_assets",
  // 拆 BGM（后台任务，进度走 engine-event：library.extract.progress / .done）
  "library_extract_bgm",
  "library_extract_cancel",
  // 特效预览：只接管「无两类水印 + 已实现的 9 种转场 / 11 种特效」，
  // 其余由原生侧返回 handled=false 交回旧引擎
  "preview_effect_frame",
  "effect_preview_animation",
]);

/** `handled: false` = Rust 不接这个请求（未迁移 / 需要旧引擎的语义），交给 sidecar。 */
type NativeResponse<T> = { handled: boolean; result?: T; error?: string };

const NOT_NATIVE = Symbol("not-native");

export class EngineBridge {
  private listeners = new Set<(event: EngineEvent) => void>();
  /** 缓存的 health（原生分发一次即可，避免每次 connect 都问一遍）。 */
  private health: EngineHealth | null = null;

  get desktopRuntime() {
    return isTauri();
  }

  /**
   * 「连接引擎」在 Rust 化之后不再是「spawn 一个进程」，而是确认原生分发可用。
   *
   * 保留这个方法是为了不动 App.tsx 的启动流程（它 await connect() 后拿 health 显示状态）。
   * `EngineHealth` 的字段保持原样，`engine` 改成 "rust-native"，`pid` 用本进程占位。
   */
  async connect(): Promise<EngineHealth> {
    if (!this.desktopRuntime) {
      throw new Error("浏览器预览模式未连接本地引擎");
    }
    if (this.health) return this.health;
    const health = await invoke<EngineHealth>("engine_dispatch", {
      method: "native_health",
      params: {},
    }).then((response) => (response as unknown as { result: EngineHealth }).result);
    this.health = health;
    // 前端有地方在等 engine.ready 才关启动屏，这里补一个（幂等）
    this.emit({ type: "event", event: "engine.ready", payload: { protocol: health.protocol } });
    return health;
  }

  async call<T>(method: string, params: Record<string, unknown> = {}, timeoutMs = 15_000): Promise<T> {
    if (!this.desktopRuntime) {
      return this.browserFallback<T>(method, params);
    }
    void timeoutMs;
    const native = await this.callNative<T>(method, params);
    if (native !== NOT_NATIVE) return native;
    // 所有接口都已由原生接管；如果走到这里，说明白名单与 Rust 分发不一致
    throw new Error(`本地引擎不支持 ${method}（原生未接管，且已不再保留旧引擎兜底）`);
  }

  /**
   * 已迁移到 Rust 的接口走 Tauri command，省掉一次 Python 进程往返。
   * 未迁移、或原生侧明确表示「这个请求我不接」（handled=false）时返回 NOT_NATIVE，
   * 由调用方继续走旧引擎；原生实现抛异常也回落，保证迁移期间功能不退化。
   */
  private async callNative<T>(method: string, params: Record<string, unknown>): Promise<T | typeof NOT_NATIVE> {
    if (!NATIVE_METHODS.has(method)) return NOT_NATIVE;
    let response: NativeResponse<T>;
    try {
      response = await invoke<NativeResponse<T>>("engine_dispatch", { method, params });
    } catch (error) {
      console.warn(`[engine] ${method} 的原生实现不可用，回落旧引擎`, error);
      return NOT_NATIVE;
    }
    if (!response.handled) return NOT_NATIVE;
    // 已接管但业务失败（例如「只能删除素材库内的文件」）：与旧引擎抛错语义一致
    if (response.error) throw new Error(response.error);
    return response.result as T;
  }

  subscribe(listener: (event: EngineEvent) => void) {
    this.listeners.add(listener);
    // 第一次有人订阅时，把 Rust 侧的任务事件接进同一个通道。
    // 订阅方（App.tsx / MaterialLibrary.tsx）不需要知道事件来自 sidecar 还是 Rust。
    void this.attachNativeEvents();
    return () => this.listeners.delete(listener);
  }

  /// 把 Rust 通过 `engine-event` 推送的事件桥接到本地订阅者。
  /// 任务队列已由 Rust 接管（start_job / pause_job / ...），事件走 Tauri 而不是 sidecar 的 stdout。
  private nativeEventsReady = false;
  private attachNativeEvents() {
    if (this.nativeEventsReady || !this.desktopRuntime) return;
    this.nativeEventsReady = true;
    void listen<EngineEvent>("engine-event", (event) => {
      const payload = event.payload;
      if (!payload || payload.type !== "event") return;
      this.emit(payload);
    }).catch((error) => {
      console.warn("[engine] 原生事件通道不可用", error);
      this.nativeEventsReady = false;
    });
  }

  toAssetUrl(path: string) {
    return this.desktopRuntime ? convertFileSrc(path) : path;
  }

  private emit(event: EngineEvent) {
    for (const listener of this.listeners) listener(event);
  }

  private async browserFallback<T>(method: string, params: Record<string, unknown>): Promise<T> {
    if (method === "default_config" || method === "normalize_config") {
      return { ...FALLBACK_CONFIG, ...((params.config as object | undefined) ?? {}) } as T;
    }
    if (method === "validate_config") {
      const config = (params.config ?? FALLBACK_CONFIG) as VideoConfig;
      const errors = [
        ...(!config.input_dir ? ["请输入输入目录"] : []),
        ...(!config.output_dir ? ["请输入输出目录"] : []),
      ];
      return { valid: errors.length === 0, errors } as T;
    }
    if (method === "validate_config_detailed") {
      const config = (params.config ?? FALLBACK_CONFIG) as VideoConfig;
      const issues: ValidationIssue[] = [
        ...(!config.input_dir ? [{ field: "input_dir", section: "basic", message: "请输入输入目录" }] : []),
        ...(!config.output_dir ? [{ field: "output_dir", section: "basic", message: "请输入输出目录" }] : []),
      ];
      return { valid: issues.length === 0, issues } as T;
    }
    if (method === "scan_images") return { count: 0, images: [] } as T;
    if (method === "scan_subfolder_groups") {
      return { count: 0, groups: [], images: [], skipped: [], combination_total: 0 } as T;
    }
    if (method === "library_dirs") {
      return { library_root: "", bgm_dir: "", watermark_dir: "" } as T;
    }
    if (method === "library_snapshot") {
      return { library_root: "", bgm_dir: "", watermark_dir: "", bgm: [], bgm_folders: [], watermark: [], watermark_folders: [] } as T;
    }
    if (method === "library_import") return { results: [] } as T;
    if (method === "library_set_metadata") return { path: "", tags: [], starred: false, note: "" } as T;
    if (method === "library_get_tags") return { tags: [] } as T;
    if (method === "library_find_duplicates") return { groups: [], scanned: 0 } as T;
    if (method === "library_rename_batch") return { results: [], pattern: "" } as T;
    if (method === "library_smart_folders_list") return { path: "", folders: [] } as T;
    if (method === "library_smart_folders_save") return { path: "", folders: [] } as T;
    if (method === "library_preview_audio") {
      throw new Error("音频试听需要在 Tauri 桌面窗口中运行");
    }
    if (method === "system_snapshot") {
      return {
        cpu_percent: 0,
        memory_percent: 0,
        memory_available_gb: 0,
        process_memory_mb: 0,
        disk_free_gb: 0,
        ffmpeg_available: false,
        ffmpeg_path: null,
      } as T;
    }
    throw new Error("此操作需要在 Tauri 桌面窗口中运行");
  }
}

export const engine = new EngineBridge();
