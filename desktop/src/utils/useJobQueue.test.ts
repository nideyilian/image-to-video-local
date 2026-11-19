/**
 * 任务队列的纯逻辑回归测试：状态判定、摘要格式、调度上限。
 *
 * 拆分 hook 前先钉住行为，拆完再跑一遍必须仍然全绿。
 */
import { describe, expect, it } from "vitest";
import { FALLBACK_CONFIG } from "../constants";
import type { JobState, Workspace } from "../types";
import { demoJobs, hasActiveJobs, makeQueuedJob, workspaceHasActiveJob } from "./useJobQueue";

function makeWorkspace(overrides: Partial<Workspace> = {}): Workspace {
  return {
    id: "w1",
    name: "工作区 1",
    config: structuredClone(FALLBACK_CONFIG),
    imageCount: null,
    preview: null,
    validationErrors: [],
    validationIssues: [],
    dirty: false,
    ...overrides,
  };
}

function makeJob(status: JobState["status"], workspaceId = "w1", jobId = "j1"): JobState {
  return {
    ...makeQueuedJob(makeWorkspace({ id: workspaceId })),
    job_id: jobId,
    workspaceId,
    status,
  };
}

describe("hasActiveJobs", () => {
  it("空队列视为没有任务", () => {
    expect(hasActiveJobs([])).toBe(false);
  });

  it("排队、运行、暂停、取消中 都算占用", () => {
    for (const status of ["queued", "running", "paused", "cancelling"] as const) {
      expect(hasActiveJobs([makeJob(status)])).toBe(true);
    }
  });

  it("已完成/失败/取消 不算占用", () => {
    for (const status of ["completed", "failed", "cancelled"] as const) {
      expect(hasActiveJobs([makeJob(status)])).toBe(false);
    }
  });
});

describe("workspaceHasActiveJob", () => {
  it("只看指定工作区", () => {
    const jobs = [makeJob("running", "w2")];
    expect(workspaceHasActiveJob(jobs, "w1")).toBe(false);
    expect(workspaceHasActiveJob(jobs, "w2")).toBe(true);
  });

  it("没有活动工作区时返回 false", () => {
    expect(workspaceHasActiveJob([makeJob("running", "w1")], undefined)).toBe(false);
  });
});

describe("makeQueuedJob", () => {
  it("新任务初始为排队态、进度零", () => {
    const job = makeQueuedJob(makeWorkspace());
    expect(job.status).toBe("queued");
    expect(job.progress).toBe(0);
    expect(job.overall).toBe(0);
    expect(job.message).toBe("等待调度");
    expect(job.demo).toBe(false);
  });

  it("摘要带上分辨率、帧率、图片数、条数", () => {
    const workspace = makeWorkspace();
    workspace.config.num_images = 7;
    workspace.config.video_count = 3;
    const job = makeQueuedJob(workspace);
    expect(job.configSummary).toContain(String(workspace.config.resolution_preset));
    expect(job.configSummary).toContain(`${workspace.config.fps} fps`);
    expect(job.configSummary).toContain("7 图");
    expect(job.configSummary).toContain("3 条");
    // 分隔符是界面文案的一部分，别在重构时手滑改掉
    expect(job.configSummary).toBe(
      `${workspace.config.resolution_preset} · ${workspace.config.fps} fps · 7 图 · 自动时长 × 3 条`,
    );
  });

  it("子文件夹模式下用传入的每组张数，不用「图片数」", () => {
    const workspace = makeWorkspace();
    workspace.config.num_images = 9;
    const job = makeQueuedJob(workspace, false, 4);
    expect(job.configSummary).toContain("4 图");
    expect(job.configSummary).not.toContain("9 图");
  });

  it("perVideoImages 为 0 时回落到「图片数」", () => {
    const workspace = makeWorkspace();
    workspace.config.num_images = 5;
    expect(makeQueuedJob(workspace, false, 0).configSummary).toContain("5 图");
  });

  it("总时长大于 0 时摘要写在「秒/条」里", () => {
    const workspace = makeWorkspace();
    workspace.config.total_duration = 12;
    expect(makeQueuedJob(workspace).configSummary).toContain("12 秒/条");
    workspace.config.total_duration = 0;
    expect(makeQueuedJob(workspace).configSummary).toContain("自动时长");
  });

  it("每个任务拿到唯一 id", () => {
    const a = makeQueuedJob(makeWorkspace());
    const b = makeQueuedJob(makeWorkspace());
    expect(a.job_id).not.toBe(b.job_id);
  });
});

describe("demoJobs", () => {
  it("给出覆盖各种状态的一组演示任务", () => {
    const jobs = demoJobs(makeWorkspace());
    expect(jobs).toHaveLength(6);
    const statuses = jobs.map((job) => job.status);
    expect(statuses).toContain("running");
    expect(statuses).toContain("queued");
    expect(statuses).toContain("completed");
    expect(statuses).toContain("failed");
    expect(statuses).toContain("cancelled");
  });

  it("演示任务都标记为 demo", () => {
    expect(demoJobs(makeWorkspace()).every((job) => job.demo)).toBe(true);
  });
});
