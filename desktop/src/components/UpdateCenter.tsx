import { getVersion } from "@tauri-apps/api/app";
import { isTauri } from "@tauri-apps/api/core";
import { relaunch } from "@tauri-apps/plugin-process";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { Check, CircleAlert, Download, RefreshCw, Rocket, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const AUTO_CHECK_KEY = "image-to-video.auto-check-updates";
const AUTO_CHECK_INTERVAL = 6 * 60 * 60 * 1000;

type UpdatePhase = "idle" | "checking" | "available" | "downloading" | "installing" | "current" | "error";

type UpdateCenterProps = {
  hasActiveJobs: boolean;
};

function errorMessage(error: unknown) {
  const detail = error instanceof Error ? error.message : String(error);
  if (/release json|fetch|network|connect|timed? out/i.test(detail)) {
    return "暂时无法读取 GitHub 最新版本，请检查网络或稍后重试。";
  }
  return detail || "检查更新失败，请稍后重试。";
}

export function UpdateCenter({ hasActiveJobs }: UpdateCenterProps) {
  const desktopRuntime = isTauri();
  const [open, setOpen] = useState(false);
  const [autoCheck, setAutoCheck] = useState(() => localStorage.getItem(AUTO_CHECK_KEY) !== "false");
  const [currentVersion, setCurrentVersion] = useState("");
  const [availableUpdate, setAvailableUpdate] = useState<Update | null>(null);
  const [phase, setPhase] = useState<UpdatePhase>("idle");
  const [message, setMessage] = useState("");
  const [downloaded, setDownloaded] = useState(0);
  const [contentLength, setContentLength] = useState(0);
  const checking = phase === "checking";
  const updating = phase === "downloading" || phase === "installing";
  const progress = contentLength > 0 ? Math.min(100, Math.round((downloaded / contentLength) * 100)) : 0;
  const checkingRef = useRef(false);
  const mountedRef = useRef(true);
  const updatingRef = useRef(updating);
  const dialogRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const checkForUpdates = useCallback(async (interactive: boolean) => {
    if (!desktopRuntime) {
      if (interactive) {
        setOpen(true);
        setPhase("error");
        setMessage("更新功能仅在安装后的桌面应用中可用。");
      }
      return;
    }
    if (availableUpdate) {
      if (interactive) setOpen(true);
      return;
    }
    if (checkingRef.current) {
      if (interactive) setOpen(true);
      return;
    }

    checkingRef.current = true;
    if (interactive) setOpen(true);
    setPhase("checking");
    setMessage("正在连接 GitHub 检查最新版本…");
    try {
      const update = await check({ timeout: 20_000 });
      if (!mountedRef.current) {
        if (update) void update.close();
        return;
      }
      if (update) {
        setAvailableUpdate(update);
        setPhase("available");
        setMessage(`发现新版本 ${update.version}`);
        setOpen(true);
      } else if (interactive) {
        setPhase("current");
        setMessage("当前已经是最新版本。");
      } else {
        setPhase("idle");
        setMessage("");
      }
    } catch (error) {
      console.warn("自动更新检查失败", error);
      if (interactive) {
        setPhase("error");
        setMessage(errorMessage(error));
      } else {
        setPhase("idle");
        setMessage("");
      }
    } finally {
      checkingRef.current = false;
    }
  }, [availableUpdate, desktopRuntime]);

  useEffect(() => {
    if (!desktopRuntime) return;
    let cancelled = false;
    void getVersion().then((version) => {
      if (!cancelled) setCurrentVersion(version);
    }).catch(() => {
      if (!cancelled) setCurrentVersion("");
    });
    return () => { cancelled = true; };
  }, [desktopRuntime]);

  useEffect(() => {
    localStorage.setItem(AUTO_CHECK_KEY, String(autoCheck));
    if (!autoCheck || !desktopRuntime || availableUpdate) return;
    const initialTimer = window.setTimeout(() => void checkForUpdates(false), 1600);
    const interval = window.setInterval(() => void checkForUpdates(false), AUTO_CHECK_INTERVAL);
    return () => {
      window.clearTimeout(initialTimer);
      window.clearInterval(interval);
    };
  }, [autoCheck, availableUpdate, checkForUpdates, desktopRuntime]);

  useEffect(() => {
    updatingRef.current = updating;
  }, [updating]);

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : triggerRef.current;
    const focusTimer = window.setTimeout(() => dialogRef.current?.querySelector<HTMLElement>("button:not(:disabled), input:not(:disabled)")?.focus(), 0);
    const handleDialogKeys = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !updatingRef.current) {
        setOpen(false);
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
    window.addEventListener("keydown", handleDialogKeys);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("keydown", handleDialogKeys);
      previousFocus?.focus();
    };
  }, [open]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => () => { if (availableUpdate) void availableUpdate.close(); }, [availableUpdate]);

  const installUpdate = useCallback(async () => {
    if (!availableUpdate || hasActiveJobs) return;
    setPhase("downloading");
    setMessage("正在安全下载更新包…");
    setDownloaded(0);
    setContentLength(0);
    try {
      await availableUpdate.downloadAndInstall((event) => {
        if (event.event === "Started") {
          setContentLength(event.data.contentLength ?? 0);
          return;
        }
        if (event.event === "Progress") {
          setDownloaded((value) => value + event.data.chunkLength);
          return;
        }
        setPhase("installing");
        setMessage("下载完成，正在安装并重新启动…");
      });
      await relaunch();
    } catch (error) {
      setPhase("error");
      setMessage(`更新失败：${errorMessage(error)}`);
    }
  }, [availableUpdate, hasActiveJobs]);

  const dialog = open ? (
    <div className="update-backdrop" role="presentation" onMouseDown={() => { if (!updating) setOpen(false); }}>
      <section ref={dialogRef} className="update-dialog" role="dialog" aria-modal="true" aria-labelledby="update-title" aria-describedby="update-status" onMouseDown={(event) => event.stopPropagation()}>
        <header className="update-dialog-heading">
          <span className="update-dialog-icon"><Rocket size={21} /></span>
          <span>
            <small>软件更新</small>
            <strong id="update-title">图转视频极速版</strong>
          </span>
          <button type="button" className="update-close" onClick={() => setOpen(false)} disabled={updating} aria-label="关闭更新窗口"><X size={17} /></button>
        </header>

        <div className="update-dialog-body">
          <div id="update-status" className={`update-state update-state-${phase}`} aria-live="polite">
            {phase === "checking" || phase === "downloading" || phase === "installing" ? <RefreshCw className="is-spinning" size={18} /> : null}
            {phase === "available" ? <Download size={18} /> : null}
            {phase === "current" ? <Check size={18} /> : null}
            {phase === "error" ? <CircleAlert size={18} /> : null}
            <span><strong>{message || "可以随时检查 GitHub 上的最新版本。"}</strong>{currentVersion ? <small>当前版本 {currentVersion}</small> : null}</span>
          </div>

          {availableUpdate ? (
            <div className="update-release">
              <div><span>可用版本</span><strong>{availableUpdate.version}</strong></div>
              {availableUpdate.date ? <div><span>发布时间</span><strong>{new Date(availableUpdate.date).toLocaleDateString("zh-CN")}</strong></div> : null}
              <p>{availableUpdate.body?.trim() || "此版本包含功能改进与问题修复。"}</p>
            </div>
          ) : null}

          {phase === "downloading" ? (
            <div className="update-progress" aria-label={`更新下载进度 ${progress}%`}>
              <span style={{ transform: `scaleX(${progress / 100})` }} />
              <small>{contentLength > 0 ? `已下载 ${progress}%` : "正在准备下载…"}</small>
            </div>
          ) : null}

          {availableUpdate && hasActiveJobs ? <p className="update-warning"><CircleAlert size={15} />请先等待当前渲染任务结束或取消任务，避免更新时中断导出。</p> : null}

          <label className="update-setting">
            <input type="checkbox" checked={autoCheck} onChange={(event) => setAutoCheck(event.target.checked)} />
            <span><strong>启动时自动检查更新</strong><small>发现 GitHub 新版本后立即提醒；不会自动中断任务。</small></span>
          </label>
        </div>

        <footer className="update-dialog-actions">
          {availableUpdate ? (
            <>
              <button type="button" className="quiet-button" onClick={() => setOpen(false)} disabled={updating}>稍后提醒</button>
              <button type="button" className="update-primary" onClick={() => void installUpdate()} disabled={updating || hasActiveJobs}>
                {phase === "downloading" ? `下载中 ${progress}%` : phase === "installing" ? "正在安装" : "立即下载并更新"}
              </button>
            </>
          ) : (
            <>
              <button type="button" className="quiet-button" onClick={() => setOpen(false)} disabled={checking}>关闭</button>
              <button type="button" className="update-primary" onClick={() => void checkForUpdates(true)} disabled={checking}>
                {checking ? "正在检查" : "重新检查"}
              </button>
            </>
          )}
        </footer>
      </section>
    </div>
  ) : null;

  return (
    <>
      <button ref={triggerRef} type="button" className={`update-button${availableUpdate ? " has-update" : ""}`} onClick={() => void checkForUpdates(true)} aria-label={availableUpdate ? `发现新版本 ${availableUpdate.version}，打开更新窗口` : "检查软件更新"}>
        {checking ? <RefreshCw className="is-spinning" size={15} /> : availableUpdate ? <Download size={15} /> : <RefreshCw size={15} />}
        {availableUpdate ? `更新 ${availableUpdate.version}` : "检查更新"}
      </button>
      {dialog ? createPortal(dialog, document.body) : null}
    </>
  );
}
