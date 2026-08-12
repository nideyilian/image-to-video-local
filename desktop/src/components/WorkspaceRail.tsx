import { Copy, Files, FolderInput, Plus, Trash2 } from "lucide-react";
import type { JobState, Workspace } from "../types";

export function WorkspaceRail({
  workspaces,
  jobs,
  activeId,
  onSelect,
  onAdd,
  onDuplicate,
  onRemove,
}: {
  workspaces: Workspace[];
  jobs: JobState[];
  activeId: string;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onDuplicate: () => void;
  onRemove: () => void;
}) {
  return (
    <aside className="workspace-rail" aria-label="工作区">
      <div className="rail-heading">
        <div>
          <span className="rail-kicker">工作区</span>
          <strong>{workspaces.length} 个配置</strong>
        </div>
        <button className="icon-button" type="button" onClick={onAdd} aria-label="新建工作区" title="新建工作区">
          <Plus size={17} aria-hidden="true" />
        </button>
      </div>

      <div className="workspace-list">
        {workspaces.map((workspace, index) => {
          const selected = workspace.id === activeId;
          const firstError = workspace.validationIssues[0]?.message ?? workspace.validationErrors[0] ?? "";
          const state = workspace.validationErrors.length
            ? firstError
            : workspace.imageCount === null
              ? "尚未扫描"
              : `${workspace.imageCount} 张图片`;
          return (
            <button
              type="button"
              key={workspace.id}
              className={`workspace-item ${selected ? "is-selected" : ""}`}
              onClick={() => onSelect(workspace.id)}
              aria-current={selected ? "page" : undefined}
            >
              <span className="workspace-index">{String(index + 1).padStart(2, "0")}</span>
              <span className="workspace-copy">
                <strong>{workspace.name}</strong>
                <small>{workspace.config.resolution_preset} · {workspace.config.fps} fps</small>
                <span className={`workspace-state ${workspace.validationErrors.length ? "is-warning" : ""}`}>
                  {workspace.validationErrors.length ? <FolderInput size={13} /> : <Files size={13} />}
                  {state}
                </span>
              </span>
              {workspace.dirty ? <span className="dirty-mark" aria-label="有未保存更改" title="有未保存更改" /> : null}
            </button>
          );
        })}
      </div>

      <div className="rail-queue" aria-label="活动队列">
        <div className="rail-queue-heading"><span>活动队列</span><strong>{jobs.filter((job) => ["queued", "running", "paused", "cancelling"].includes(job.status)).length}</strong></div>
        {jobs.filter((job) => ["queued", "running", "paused", "cancelling"].includes(job.status)).slice(0, 3).map((job) => (
          <div className={`rail-job status-${job.status}`} key={job.job_id}>
            <span className="rail-job-signal" />
            <span><strong>{job.workspaceName}</strong><small>{job.status === "running" ? `渲染中 ${job.progress}%` : job.status === "paused" ? "已暂停" : job.status === "cancelling" ? "取消中" : "等待调度"}</small></span>
          </div>
        ))}
        {!jobs.some((job) => ["queued", "running", "paused", "cancelling"].includes(job.status)) ? <p>暂无活动任务</p> : null}
      </div>

      <div className="rail-actions">
        <button type="button" onClick={onDuplicate}><Copy size={15} />复制</button>
        <button type="button" onClick={onRemove} disabled={workspaces.length <= 1}><Trash2 size={15} />移除</button>
      </div>
      <div className="rail-note">
        每个工作区保存一套独立参数。批量导出会跳过无效配置。
      </div>
    </aside>
  );
}
