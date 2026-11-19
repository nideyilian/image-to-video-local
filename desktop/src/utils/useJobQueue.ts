/**
 * 渲染任务队列：排队、并发调度、暂停/恢复/取消、事件回填。
 *
 * 从 `App.tsx` 抽出来的第二块。它只依赖 `engine`、当前工作区快照和
 * 一个「校验配置」回调，不碰布局、不碰预览、不碰弹窗。
 *
 * 调度模型（保持原样，这次只是搬家）：
 * - 队列本身是 `jobs` 数组里的 `status === "queued"` 项；
 * - 每次 `pumpQueue` 按并发上限补足「running/paused/cancelling」的数量；
 * - 任务完成（`job.finished`）后立刻再泵一次，所以队列能自己往前推。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { engine } from "../engine";
import { imagesPerVideo } from "./durationLink";
import type { EngineEvent, JobState, SubfolderScan, Workspace } from "../types";

const ACTIVE_STATUSES = ["running", "paused", "cancelling"] as const;
const OCCUPIED_STATUSES = ["queued", "running", "paused", "cancelling"] as const;

function uuid() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function makeQueuedJob(workspace: Workspace, demo = false, perVideoImages?: number): JobState {
  // 子文件夹模式下每视频张数由子文件夹个数决定，摘要不能再用「图片数」
  const imageCount = perVideoImages && perVideoImages > 0 ? perVideoImages : workspace.config.num_images;
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
    configSummary: `${workspace.config.resolution_preset} · ${workspace.config.fps} fps · ${imageCount} 图 · ${workspace.config.total_duration > 0 ? `${workspace.config.total_duration} 秒/条` : "自动时长"} × ${workspace.config.video_count} 条`,
    demo,
  };
}

export function demoJobs(workspace: Workspace): JobState[] {
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

/** 有任务在跑或排队（用于禁用「批量导出」等入口）。 */
export function hasActiveJobs(jobs: JobState[]): boolean {
  return jobs.some((job) => (OCCUPIED_STATUSES as readonly string[]).includes(job.status));
}

/** 某个工作区是否已有任务在队列里（用于禁用「导出当前」）。 */
export function workspaceHasActiveJob(jobs: JobState[], workspaceId: string | undefined): boolean {
  if (!workspaceId) return false;
  return jobs.some((job) => job.workspaceId === workspaceId && (OCCUPIED_STATUSES as readonly string[]).includes(job.status));
}

type UseJobQueueOptions = {
  /** 是否已连上本地引擎；未连接时不调度。 */
  connected: boolean;
  /** 演示模式：只展示假数据，不发请求。 */
  demoMode: boolean;
  /** 子文件夹扫描结果（决定每个视频用几张图，影响任务摘要）。 */
  subfolderScans: Record<string, SubfolderScan>;
  /** 校验一个工作区；返回 valid 才允许入队。 */
  validateWorkspace: (workspace: Workspace) => Promise<{ valid: boolean; errors: string[] }>;
  /** 校验失败时把问题写回工作区。 */
  onValidationFailed: (workspaceId: string, message: string) => void;
  notify: (kind: "info" | "success" | "error", message: string) => void;
  /** 引擎断开时更新连接状态。 */
  onEngineDisconnected: () => void;
  /** 初始任务列表（demo 模式用来铺假数据）。只在挂载时读一次。 */
  initialJobs?: JobState[];
};

export function useJobQueue({
  connected,
  demoMode,
  subfolderScans,
  validateWorkspace,
  onValidationFailed,
  notify,
  onEngineDisconnected,
  initialJobs,
}: UseJobQueueOptions) {
  const [jobs, setJobs] = useState<JobState[]>(initialJobs ?? []);
  const [concurrency, setConcurrency] = useState(2);
  const jobsRef = useRef(jobs);
  const queuedWorkspaces = useRef(new Map<string, Workspace>());
  const pumpQueueRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);

  /** 统一更新 jobs 并同步 ref（ref 是给同步逻辑读的，避免闭包拿到旧值）。 */
  const applyJobs = useCallback((updater: (current: JobState[]) => JobState[]) => {
    setJobs((current) => {
      const next = updater(current);
      jobsRef.current = next;
      return next;
    });
  }, []);

  /** 引擎推送的任务事件回填到队列。 */
  const updateJobFromEvent = useCallback((event: EngineEvent) => {
    if (event.event === "engine.closed" || event.event === "engine.error") {
      onEngineDisconnected();
      return;
    }
    const jobId = String(event.payload.job_id ?? "");
    if (!jobId) return;
    applyJobs((current) => current.map((job) => {
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
    }));
    if (event.event === "job.finished") {
      queuedWorkspaces.current.delete(jobId);
      window.setTimeout(() => pumpQueueRef.current(), 0);
    }
  }, [applyJobs, onEngineDisconnected]);

  /** 按并发上限从队列里补任务。 */
  const pumpQueue = useCallback(() => {
    if (!connected) return;
    const currentJobs = jobsRef.current;
    const activeCount = currentJobs.filter((job) => (ACTIVE_STATUSES as readonly string[]).includes(job.status)).length;
    const nextJobs = currentJobs.filter((job) => job.status === "queued").slice(0, Math.max(0, concurrency - activeCount));
    for (const job of nextJobs) {
      const workspace = queuedWorkspaces.current.get(job.job_id);
      if (!workspace) continue;
      applyJobs((current) => current.map((item) => item.job_id === job.job_id ? { ...item, status: "running" as const, message: "正在启动本地渲染" } : item));
      void engine.call<JobState>("start_job", { config: workspace.config, job_id: job.job_id }, 30_000).catch((error) => {
        queuedWorkspaces.current.delete(job.job_id);
        applyJobs((current) => current.map((item) => item.job_id === job.job_id ? { ...item, status: "failed" as const, message: error instanceof Error ? error.message : "任务启动失败" } : item));
        notify("error", error instanceof Error ? error.message : "任务启动失败");
        window.setTimeout(() => pumpQueueRef.current(), 0);
      });
    }
  }, [applyJobs, concurrency, connected, notify]);

  useEffect(() => {
    pumpQueueRef.current = pumpQueue;
    pumpQueue();
  }, [pumpQueue]);

  /** 把若干工作区校验后入队。 */
  const queueWorkspaces = useCallback(async (targets: Workspace[]) => {
    if (!connected) return notify("error", "本地引擎未连接，无法开始导出");
    const accepted: Array<{ workspace: Workspace; job: JobState }> = [];
    for (const workspace of targets) {
      try {
        const validation = await validateWorkspace(workspace);
        if (validation.valid) {
          const job = makeQueuedJob(workspace, false, imagesPerVideo(workspace.config, subfolderScans[workspace.id]));
          accepted.push({ workspace, job });
          queuedWorkspaces.current.set(job.job_id, workspace);
        }
      } catch (error) {
        onValidationFailed(workspace.id, error instanceof Error ? error.message : "配置校验失败");
      }
    }
    if (!accepted.length) return notify("error", "没有可执行的工作区，请先处理参数提示");
    applyJobs((current) => [...accepted.map(({ job }) => job), ...current]);
    notify("success", `已加入 ${accepted.length} 个渲染任务`);
    window.setTimeout(() => pumpQueueRef.current(), 0);
  }, [applyJobs, connected, notify, onValidationFailed, subfolderScans, validateWorkspace]);

  /** 暂停 / 恢复 / 取消。排队中的任务直接本地取消，不发请求。 */
  const controlJob = useCallback(async (method: "pause_job" | "resume_job" | "cancel_job", id: string) => {
    const local = jobsRef.current.find((job) => job.job_id === id);
    if (local?.status === "queued" && method === "cancel_job") {
      queuedWorkspaces.current.delete(id);
      applyJobs((current) => current.map((job) => job.job_id === id ? { ...job, status: "cancelled" as const, message: "任务已取消" } : job));
      return;
    }
    try {
      await engine.call(method, { job_id: id });
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "任务控制失败");
    }
  }, [applyJobs, notify]);

  /** 清除已完成/失败/取消的条目。 */
  const clearFinished = useCallback(() => {
    applyJobs((current) => current.filter((job) => (ACTIVE_STATUSES as readonly string[]).includes(job.status) || job.status === "queued"));
  }, [applyJobs]);

  return {
    jobs,
    setJobs,
    jobsRef,
    concurrency,
    setConcurrency,
    pumpQueue,
    queueWorkspaces,
    controlJob,
    clearFinished,
    updateJobFromEvent,
    demoMode,
  };
}

export type JobQueue = ReturnType<typeof useJobQueue>;
