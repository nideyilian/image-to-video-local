import { convertFileSrc, invoke, isTauri } from "@tauri-apps/api/core";
import { Command, type Child } from "@tauri-apps/plugin-shell";
import { FALLBACK_CONFIG } from "./constants";
import type { EngineEvent, EngineHealth, VideoConfig } from "./types";

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  timer: number;
};

type ResponsePayload = {
  type: "response";
  id: string | null;
  ok: boolean;
  result?: unknown;
  error?: string;
};

export class EngineBridge {
  private child: Child | null = null;
  private pending = new Map<string, PendingRequest>();
  private listeners = new Set<(event: EngineEvent) => void>();
  private stdoutBuffer = "";
  private sequence = 0;
  private connecting: Promise<EngineHealth> | null = null;

  get desktopRuntime() {
    return isTauri();
  }

  async connect(): Promise<EngineHealth> {
    if (!this.desktopRuntime) {
      throw new Error("浏览器预览模式未连接本地引擎");
    }
    if (this.child) {
      return this.call<EngineHealth>("health");
    }
    if (this.connecting) return this.connecting;

    this.connecting = (async () => {
      const command = import.meta.env.DEV
        ? await (async () => {
            const root = await invoke<string>("project_root");
            return Command.create(
            "python-engine",
            ["-m", "src.engine.server", "--project-root", root],
            {
              cwd: root,
              env: { PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
              encoding: "utf-8",
            },
            );
          })()
        : Command.sidecar("binaries/image-to-video-engine", [], { encoding: "utf-8" });
      command.stdout.on("data", (chunk) => this.consumeStdout(String(chunk)));
      command.stderr.on("data", (chunk) => {
        this.emit({
          type: "event",
          event: "engine.log",
          payload: { stream: "stderr", message: String(chunk) },
        });
      });
      command.on("close", ({ code }) => {
        this.child = null;
        this.rejectPending(new Error(`本地引擎已退出（${code ?? "未知"}）`));
        this.emit({ type: "event", event: "engine.closed", payload: { code } });
      });
      command.on("error", (message) => {
        this.emit({ type: "event", event: "engine.error", payload: { message } });
      });
      this.child = await command.spawn();
      return this.call<EngineHealth>("health");
    })();

    try {
      return await this.connecting;
    } finally {
      this.connecting = null;
    }
  }

  async call<T>(method: string, params: Record<string, unknown> = {}, timeoutMs = 15_000): Promise<T> {
    if (!this.desktopRuntime) {
      return this.browserFallback<T>(method, params);
    }
    if (!this.child && method !== "health") await this.connect();
    if (!this.child) throw new Error("本地引擎未连接");

    const id = `request-${Date.now()}-${this.sequence++}`;
    const payload = `${JSON.stringify({ id, method, params })}\n`;
    const response = new Promise<T>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} 请求超时`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: resolve as (value: unknown) => void,
        reject,
        timer,
      });
    });
    await this.child.write(payload);
    return response;
  }

  subscribe(listener: (event: EngineEvent) => void) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  toAssetUrl(path: string) {
    return this.desktopRuntime ? convertFileSrc(path) : path;
  }

  private consumeStdout(chunk: string) {
    this.stdoutBuffer += chunk;
    const lines = this.stdoutBuffer.split(/\r?\n/);
    this.stdoutBuffer = lines.pop() ?? "";
    for (const line of lines) this.consumeLine(line);
    if (this.stdoutBuffer.trim().startsWith("{") && this.stdoutBuffer.trim().endsWith("}")) {
      const candidate = this.stdoutBuffer;
      this.stdoutBuffer = "";
      this.consumeLine(candidate);
    }
  }

  private consumeLine(line: string) {
    if (!line.trim()) return;
    let payload: ResponsePayload | EngineEvent;
    try {
      payload = JSON.parse(line) as ResponsePayload | EngineEvent;
    } catch {
      this.emit({ type: "event", event: "engine.log", payload: { stream: "stdout", message: line } });
      return;
    }
    if (payload.type === "event") {
      this.emit(payload);
      return;
    }
    if (!payload.id) return;
    const pending = this.pending.get(payload.id);
    if (!pending) return;
    window.clearTimeout(pending.timer);
    this.pending.delete(payload.id);
    if (payload.ok) pending.resolve(payload.result);
    else pending.reject(new Error(payload.error || "本地引擎请求失败"));
  }

  private emit(event: EngineEvent) {
    for (const listener of this.listeners) listener(event);
  }

  private rejectPending(error: Error) {
    for (const pending of this.pending.values()) {
      window.clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pending.clear();
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
    if (method === "scan_images") return { count: 0, images: [] } as T;
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
