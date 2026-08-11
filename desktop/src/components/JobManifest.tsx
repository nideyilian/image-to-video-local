import { useEffect, useState } from "react";
import {
  Ban,
  Check,
  CircleAlert,
  Clock3,
  FolderOpen,
  LoaderCircle,
  Pause,
  Play,
  Rows3,
  X,
} from "lucide-react";
import type { JobState } from "../types";

const SUMMARY_LIMIT = 4;

const STATUS_COPY: Record<JobState["status"], string> = {
  queued: "等待",
  running: "渲染中",
  paused: "已暂停",
  cancelling: "取消中",
  cancelled: "已取消",
  completed: "完成",
  failed: "失败",
};

function StatusIcon({ status }: { status: JobState["status"] }) {
  if (status === "completed") return <Check size={14} />;
  if (status === "failed") return <CircleAlert size={14} />;
  if (status === "cancelled" || status === "cancelling") return <Ban size={14} />;
  if (status === "paused") return <Pause size={14} />;
  if (status === "queued") return <Clock3 size={14} />;
  return <LoaderCircle className="is-spinning" size={14} />;
}

function JobTable({
  jobs,
  onPause,
  onResume,
  onCancel,
  onReveal,
}: {
  jobs: JobState[];
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onCancel: (id: string) => void;
  onReveal: (path: string) => void;
}) {
  return (
    <table>
      <thead>
        <tr>
          <th>任务</th><th>输出</th><th>状态</th><th>进度</th><th>速度</th><th>说明</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        {jobs.length ? jobs.map((job, index) => (
          <tr key={job.job_id} className={`job-row status-${job.status}`}>
            <td><span className="job-index">{String(index + 1).padStart(2, "0")}</span><span className="job-name"><strong>{job.workspaceName}</strong><small>{job.demo ? `演示数据 · ${job.configSummary}` : job.configSummary}</small></span></td>
            <td className="output-cell" title={job.outputPath}>{job.outputPath || "—"}</td>
            <td><span className="status-label"><StatusIcon status={job.status} />{STATUS_COPY[job.status]}</span></td>
            <td><span className="progress-cell"><span className="progress-track" aria-label={`任务进度 ${job.progress}%`}><span style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }} /></span><span>{job.progress}%</span></span></td>
            <td>{job.speed || "—"}</td>
            <td className="message-cell" title={job.message}>{job.message}</td>
            <td>
              <span className="row-actions">
                {job.status === "running" ? <button type="button" className="icon-button" onClick={() => onPause(job.job_id)} aria-label="暂停任务"><Pause size={14} /></button> : null}
                {job.status === "paused" ? <button type="button" className="icon-button" onClick={() => onResume(job.job_id)} aria-label="继续任务"><Play size={14} /></button> : null}
                {job.outputPath ? <button type="button" className="icon-button" onClick={() => onReveal(job.outputPath)} aria-label="打开输出目录"><FolderOpen size={14} /></button> : null}
                {["queued", "running", "paused", "cancelling"].includes(job.status) ? <button type="button" className="icon-button danger" onClick={() => onCancel(job.job_id)} disabled={job.status === "cancelling"} aria-label="取消任务"><X size={14} /></button> : null}
              </span>
            </td>
          </tr>
        )) : (
          <tr className="manifest-empty"><td colSpan={7}><Rows3 size={20} /><span><strong>尚无渲染任务</strong><small>检查当前工作区后，可单独或批量开始导出。</small></span></td></tr>
        )}
      </tbody>
    </table>
  );
}

export function JobManifest({
  jobs,
  concurrency,
  canRun,
  onConcurrencyChange,
  onStartBatch,
  onPause,
  onResume,
  onCancel,
  onReveal,
  onClearCompleted,
}: {
  jobs: JobState[];
  concurrency: number;
  canRun: boolean;
  onConcurrencyChange: (value: number) => void;
  onStartBatch: () => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onCancel: (id: string) => void;
  onReveal: (path: string) => void;
  onClearCompleted: () => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const summaryJobs = jobs.slice(0, SUMMARY_LIMIT);

  useEffect(() => {
    if (!showAll) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setShowAll(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [showAll]);

  return (
    <>
      <section className="job-manifest" aria-label="渲染任务清单">
        <div className="manifest-heading">
          <div>
            <span className="panel-kicker">生产台账</span>
            <strong>渲染任务清单</strong>
            <span className="manifest-count">{jobs.length}</span>
          </div>
          <div className="manifest-heading-actions">
            <button type="button" className="quiet-button" onClick={() => setShowAll(true)} disabled={!jobs.length}>
              <Rows3 size={14} />查看全部任务
            </button>
            <button type="button" className="quiet-button" onClick={onClearCompleted} disabled={!jobs.some((job) => ["completed", "failed", "cancelled"].includes(job.status))}>
              清理已结束
            </button>
          </div>
        </div>

        <div className="manifest-table-wrap">
          <JobTable jobs={summaryJobs} onPause={onPause} onResume={onResume} onCancel={onCancel} onReveal={onReveal} />
        </div>

        <div className="manifest-command-bar">
          <label>并行任务数<select value={concurrency} onChange={(event) => onConcurrencyChange(Number(event.target.value))}><option value={1}>1</option><option value={2}>2</option><option value={3}>3</option></select></label>
          <span className="command-note">默认显示最近 4 条任务；批量导出按工作区顺序执行。</span>
          <button className="batch-button" type="button" onClick={onStartBatch} disabled={!canRun}><Play size={17} />开始批量导出</button>
        </div>
      </section>

      {showAll ? (
        <div className="manifest-history-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setShowAll(false);
        }}>
          <section className="manifest-history-dialog" role="dialog" aria-modal="true" aria-labelledby="manifest-history-title">
            <header className="manifest-history-heading">
              <div>
                <span className="panel-kicker">完整记录</span>
                <strong id="manifest-history-title">全部任务</strong>
                <span className="manifest-count">{jobs.length}</span>
              </div>
              <button type="button" className="icon-button" onClick={() => setShowAll(false)} aria-label="关闭全部任务列表" autoFocus><X size={16} /></button>
            </header>
            <div className="manifest-table-wrap manifest-history-table-wrap">
              <JobTable jobs={jobs} onPause={onPause} onResume={onResume} onCancel={onCancel} onReveal={onReveal} />
            </div>
            <footer className="manifest-history-footer">
              <span>共 {jobs.length} 条任务记录</span>
              <button type="button" className="quiet-button" onClick={() => setShowAll(false)}>关闭</button>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}
