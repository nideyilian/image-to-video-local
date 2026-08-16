import { useEffect, useRef } from "react";
import { Eraser, Terminal, X } from "lucide-react";
import type { LogEntry } from "../types";

function formatTime(ts: number) {
  const date = new Date(ts);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function isErrorLike(entry: LogEntry) {
  if (entry.stream === "stderr") return true;
  return /error|错误|失败|exception|traceback|无法|失败|拒绝/i.test(entry.message);
}

const STREAM_LABELS: Record<string, string> = {
  stdout: "stdout",
  stderr: "stderr",
  worker: "渲染",
  engine: "引擎",
};

export function LogDrawer({ logs, open, onClose, onClear }: {
  logs: LogEntry[];
  open: boolean;
  onClose: () => void;
  onClear: () => void;
}) {
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (open && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [logs, open]);

  if (!open) return null;

  return (
    <div className="log-drawer" role="region" aria-label="运行日志">
      <header className="log-drawer-heading">
        <span className="log-drawer-title"><Terminal size={14} />运行日志<small>{logs.length} 条</small></span>
        <span className="log-drawer-actions">
          <button type="button" className="quiet-button" onClick={onClear} disabled={!logs.length}><Eraser size={13} />清空</button>
          <button type="button" className="icon-button" onClick={onClose} aria-label="关闭日志抽屉"><X size={15} /></button>
        </span>
      </header>
      <div ref={listRef} className="log-drawer-body">
        {!logs.length ? (
          <p className="log-drawer-empty">暂无日志。渲染任务与引擎输出会显示在这里。</p>
        ) : (
          logs.map((entry) => (
            <div key={entry.id} className={`log-line${isErrorLike(entry) ? " is-error" : ""}`}>
              <span className="log-line-time">{formatTime(entry.ts)}</span>
              <span className={`log-line-stream is-${entry.stream}`}>{STREAM_LABELS[entry.stream] ?? entry.stream}</span>
              {entry.jobId ? <span className="log-line-job" title={`任务 ${entry.jobId}`}>{entry.jobId.slice(0, 6)}</span> : null}
              <span className="log-line-message">{entry.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
