import { getVersion } from "@tauri-apps/api/app";
import { isTauri } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import { relaunch } from "@tauri-apps/plugin-process";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { Check, CircleAlert, Download, ExternalLink, RefreshCw, Rocket, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { formatBytes } from "../utils/workspaceOps";

const AUTO_CHECK_KEY = "image-to-video.auto-check-updates";
const PROXY_KEY = "image-to-video.update-proxy";
const AUTO_CHECK_INTERVAL = 6 * 60 * 60 * 1000;
const CHECK_TIMEOUT = 20_000;
const DOWNLOAD_TIMEOUT = 10 * 60 * 1000; // 下载可能很慢，放宽到 10 分钟

const RELEASE_PAGE = "https://github.com/nideyilian/image-to-video-local/releases/latest";
const MIRROR_PREFIX = "https://mirror.ghproxy.com/";
const RELEASE_PAGE_MIRROR = `${MIRROR_PREFIX}${RELEASE_PAGE}`;

type UpdatePhase = "idle" | "checking" | "available" | "downloading" | "installing" | "current" | "error";
type ErrorKind = "network" | "signature" | "format" | "other";

type UpdateCenterProps = {
  hasActiveJobs: boolean;
};

function classifyError(error: unknown): { kind: ErrorKind; message: string } {
  const detail = error instanceof Error ? error.message : String(error);
  if (/signature|digest|hash|public key|密钥|签名/i.test(detail)) {
    return { kind: "signature", message: "安装包签名校验失败：下载内容可能不完整或发布文件异常，请稍后重试。" };
  }
  if (/json|schema|malformed|invalid version|parse/i.test(detail)) {
    return { kind: "format", message: "更新信息解析失败：服务器返回的数据格式异常，请稍后重试。" };
  }
  if (/fetch|network|connect|timed? ?out|ECONN|refused|proxy|reqwest|hyper|dns|lookup/i.test(detail)) {
    return {
      kind: "network",
      message:
        "无法连接更新服务器（国内网络访问 GitHub 可能受限）。已自动按顺序尝试 GitHub 与多个国内镜像源，仍然失败时，请稍后重试，或使用下方「手动下载」入口从镜像站获取安装包。",
    };
  }
  return { kind: "other", message: detail || "检查更新失败，请稍后重试。" };
}

export function UpdateCenter({ hasActiveJobs }: UpdateCenterProps) {
  const desktopRuntime = isTauri();
  const [open, setOpen] = useState(false);
  const [autoCheck, setAutoCheck] = useState(() => localStorage.getItem(AUTO_CHECK_KEY) !== "false");
  const [proxyUrl, setProxyUrl] = useState(() => localStorage.getItem(PROXY_KEY) ?? "");
  const [currentVersion, setCurrentVersion] = useState("");
  const [availableUpdate, setAvailableUpdate] = useState<Update | null>(null);
  const [phase, setPhase] = useState<UpdatePhase>("idle");
  const [errorKind, setErrorKind] = useState<ErrorKind | null>(null);
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

  const packageSize = (() => {
    const size = availableUpdate?.rawJson?.size;
    return typeof size === "number" && Number.isFinite(size) && size > 0 ? formatBytes(size) : null;
  })();

  const installerUrl = (() => {
    const url = availableUpdate?.rawJson?.url;
    return typeof url === "string" && url.startsWith("https://") ? url : null;
  })();

  const checkForUpdates = useCallback(async (interactive: boolean) => {
    if (!desktopRuntime) {
      if (interactive) {
        setOpen(true);
        setPhase("error");
        setErrorKind("other");
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
    setErrorKind(null);
    setMessage("正在检查更新（自动依次连接 GitHub 与国内镜像源）…");
    try {
      const update = await check({ timeout: CHECK_TIMEOUT, proxy: proxyUrl || undefined });
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
        const classified = classifyError(error);
        setErrorKind(classified.kind);
        setPhase("error");
        setMessage(classified.message);
      } else {
        setPhase("idle");
        setMessage("");
      }
    } finally {
      checkingRef.current = false;
    }
  }, [availableUpdate, desktopRuntime, proxyUrl]);

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
    localStorage.setItem(PROXY_KEY, proxyUrl);
  }, [proxyUrl]);

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
    setMessage("正在安全下载更新包，请耐心等待…");
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
      }, { timeout: DOWNLOAD_TIMEOUT });
      await relaunch();
    } catch (error) {
      const classified = classifyError(error);
      setErrorKind(classified.kind);
      setPhase("error");
      setMessage(`更新失败：${classified.message}`);
    }
  }, [availableUpdate, hasActiveJobs]);

  const openManualDownload = useCallback(() => {
    // 优先直接下载安装包（走镜像加速）；失败时打开下载页兜底
    if (installerUrl) {
      void openUrl(`${MIRROR_PREFIX}${installerUrl}`);
    } else {
      void openUrl(RELEASE_PAGE_MIRROR);
    }
  }, [installerUrl]);

  const openReleasePage = useCallback(() => {
    void openUrl(RELEASE_PAGE);
  }, []);

  const showManualRow = phase === "error" && errorKind === "network";
  const downloading = phase === "downloading";

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
            {checking || downloading || phase === "installing" ? <RefreshCw className="is-spinning" size={18} /> : null}
            {phase === "available" ? <Download size={18} /> : null}
            {phase === "current" ? <Check size={18} /> : null}
            {phase === "error" ? <CircleAlert size={18} /> : null}
            <span><strong>{message || "可以随时检查 GitHub 上的最新版本。"}</strong>{currentVersion ? <small>当前版本 {currentVersion}</small> : null}</span>
          </div>

          {availableUpdate ? (
            <div className="update-release">
              <div><span>可用版本</span><strong>{availableUpdate.version}</strong></div>
              <div><span>安装包大小</span><strong>{packageSize ?? "未知"}</strong></div>
              {availableUpdate.date ? <div><span>发布时间</span><strong>{new Date(availableUpdate.date).toLocaleDateString("zh-CN")}</strong></div> : null}
              <p>{availableUpdate.body?.trim() || "此版本包含功能改进与问题修复。"}</p>
            </div>
          ) : null}

          {downloading ? (
            <div className="update-progress" aria-label={`更新下载进度 ${progress}%`}>
              <span style={{ transform: `scaleX(${progress / 100})` }} />
              <small>{contentLength > 0 ? `已下载 ${progress}%` : "正在准备下载…"}</small>
            </div>
          ) : null}

          {availableUpdate && hasActiveJobs ? <p className="update-warning"><CircleAlert size={15} />请先等待当前渲染 / 拆解任务结束或取消任务，避免更新时中断导出。</p> : null}

          {showManualRow ? (
            <div className="update-manual">
              <p><ExternalLink size={14} />自动检查连接失败，可手动下载安装包（运行后覆盖安装，效果与自动更新一致）：</p>
              <div className="update-manual-actions">
                <button type="button" className="quiet-button" onClick={openManualDownload}><Download size={13} />镜像站加速下载</button>
                <button type="button" className="quiet-button" onClick={openReleasePage}><ExternalLink size={13} />打开 GitHub 下载页</button>
              </div>
            </div>
          ) : null}

          {availableUpdate && !updating ? (
            <div className="update-manual">
              <p><ExternalLink size={14} />自动下载较慢时，可手动下载安装包（覆盖安装后即为新版本）：</p>
              <div className="update-manual-actions">
                <button type="button" className="quiet-button" onClick={openManualDownload}><Download size={13} />镜像站加速下载</button>
                <button type="button" className="quiet-button" onClick={openReleasePage}><ExternalLink size={13} />打开 GitHub 下载页</button>
              </div>
            </div>
          ) : null}

          <details className="update-proxy">
            <summary>网络代理设置（可选，仅当需要走代理访问 GitHub 时填写）</summary>
            <div className="update-proxy-row">
              <input
                type="text"
                value={proxyUrl}
                onChange={(event) => setProxyUrl(event.target.value.trim())}
                placeholder="例如 http://127.0.0.1:7890"
                aria-label="代理地址"
              />
              <small>代理地址会同时用于检查与下载更新，仅保存在本机。</small>
            </div>
          </details>

          <label className="update-setting">
            <input type="checkbox" checked={autoCheck} onChange={(event) => setAutoCheck(event.target.checked)} />
            <span><strong>启动时自动检查更新</strong><small>自动依次连接 GitHub 与国内镜像源；发现新版本后立即提醒，不会自动中断任务。</small></span>
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
