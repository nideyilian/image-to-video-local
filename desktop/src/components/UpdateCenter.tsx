/**
 * 软件更新检查：**只提示版本号 + 给下载链接**。
 *
 * ## 为什么是这个形态（2026-11-20 重写）
 *
 * 旧版走 `@tauri-apps/plugin-updater`：4 个镜像端点顺序轮询、minisign 签名链、
 * 应用内下载并安装。实测「经常失败」，三层根因：
 *
 * | 端点 | 拉清单 | 下载 |
 * |---|---|---|
 * | 直连 GitHub | 失败 | 0 字节 |
 * | mirror.ghproxy.com | 失败 | 失败 |
 * | ghproxy.net | 302 | 403 |
 * | gh-proxy.com | 200 | 2.9MB/s |
 *
 * 4 个里 3 个是坏的，而插件按顺序轮询：前面任何一步超时都要等满 20 秒，
 * 看着像卡死；下载阶段命中坏源必然失败。而且 `latest.json` 的下载地址是
 * `api.github.com/.../assets/ID`，要求特定请求头，多数公共镜像直接 403。
 *
 * ## 现在
 *
 * Rust 侧（`engine/updater.rs`）拉一个只含 `{version, url}` 的清单并比版本号；
 * 有新版就把链接交给**系统浏览器**去下载。
 *
 * 代价是少一个「一键更新」，换来：
 * - 失败点从 5 个降到 1 个（只有「拉清单」可能失败）
 * - 浏览器下载有断点续传和进度，比我们自己下更可靠
 * - 不用写临时文件、不用处理安装器退出码、不依赖签名链
 *
 * 失败信息原样展示（Rust 把每个地址的具体原因都拼进去了），
 * 不再一律甩「国内网络受限」——用户能看出是哪个环节断了。
 */
import { getVersion } from "@tauri-apps/api/app";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import { CircleAlert, Check, Download, ExternalLink, RefreshCw, Rocket, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const AUTO_CHECK_KEY = "image-to-video.auto-check-updates";
const AUTO_CHECK_INTERVAL = 6 * 60 * 60 * 1000;

const RELEASES_PAGE = "https://github.com/nideyilian/image-to-video-local/releases/latest";
/** 镜像站上的发布页：直连 GitHub 打不开时用这个。 */
const RELEASES_PAGE_MIRROR = `https://gh-proxy.com/${RELEASES_PAGE}`;

type Phase = "idle" | "checking" | "current" | "available" | "error";

type CheckResult = {
  ok: boolean;
  current: string;
  available?: boolean;
  version?: string;
  url?: string;
  error?: string;
};

type UpdateInfo = {
  version: string;
  url: string;
};

type UpdateCenterProps = {
  hasActiveJobs: boolean;
};

export function UpdateCenter({ hasActiveJobs }: UpdateCenterProps) {
  const desktopRuntime = isTauri();
  const [open, setOpen] = useState(false);
  const [autoCheck, setAutoCheck] = useState(() => localStorage.getItem(AUTO_CHECK_KEY) !== "false");
  const [currentVersion, setCurrentVersion] = useState("");
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState("");
  const checkingRef = useRef(false);
  const mountedRef = useRef(true);
  const dialogRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const checking = phase === "checking";

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!desktopRuntime) return;
    let cancelled = false;
    void getVersion()
      .then((version) => {
        if (!cancelled) setCurrentVersion(version);
      })
      .catch(() => {
        if (!cancelled) setCurrentVersion("");
      });
    return () => {
      cancelled = true;
    };
  }, [desktopRuntime]);

  const checkForUpdates = useCallback(
    async (interactive: boolean) => {
      if (!desktopRuntime) {
        if (interactive) {
          setOpen(true);
          setPhase("error");
          setMessage("更新功能仅在桌面应用中使用。");
        }
        return;
      }
      if (checkingRef.current) {
        if (interactive) setOpen(true);
        return;
      }
      checkingRef.current = true;
      if (interactive) setOpen(true);
      setPhase("checking");
      setMessage("正在检查更新…");
      try {
        const version = currentVersion || (await getVersion().catch(() => ""));
        const response = await invoke<{ result: CheckResult }>("engine_dispatch", {
          method: "updater_check",
          params: { current_version: version },
        });
        if (!mountedRef.current) return;
        const result = response.result;
        if (!result.ok) {
          // 自动检查失败就静默，不打扰正在干活的人；手动点才把原因摆出来
          if (interactive) {
            setPhase("error");
            setMessage(result.error || "检查更新失败。");
          } else {
            setPhase("idle");
            setMessage("");
          }
          return;
        }
        if (!result.available) {
          setPhase(interactive ? "current" : "idle");
          setMessage(interactive ? "已经是最新版本。" : "");
          return;
        }
        setUpdate({ version: result.version ?? "", url: result.url ?? "" });
        setPhase("available");
        setMessage(`发现新版本 ${result.version}`);
        setOpen(true);
      } catch (error) {
        if (!mountedRef.current) return;
        if (interactive) {
          setPhase("error");
          setMessage(`检查更新失败：${error instanceof Error ? error.message : String(error)}`);
        } else {
          setPhase("idle");
          setMessage("");
        }
      } finally {
        checkingRef.current = false;
      }
    },
    [currentVersion, desktopRuntime],
  );

  useEffect(() => {
    localStorage.setItem(AUTO_CHECK_KEY, String(autoCheck));
    if (!autoCheck || !desktopRuntime || update) return;
    const initial = window.setTimeout(() => void checkForUpdates(false), 1600);
    const interval = window.setInterval(() => void checkForUpdates(false), AUTO_CHECK_INTERVAL);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(interval);
    };
  }, [autoCheck, desktopRuntime, checkForUpdates, update]);

  // 对话框的焦点管理（Esc 关闭、Tab 循环）
  useEffect(() => {
    if (!open) return;
    const previous =
      document.activeElement instanceof HTMLElement ? document.activeElement : triggerRef.current;
    const timer = window.setTimeout(() => {
      dialogRef.current?.querySelector<HTMLElement>("button:not(:disabled)")?.focus();
    }, 0);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const items = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>("button:not(:disabled)"),
      );
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [open]);

  /** 打开安装包直链，由浏览器接管下载。 */
  const openDownload = useCallback(() => {
    if (!update) return;
    void openUrl(update.url);
  }, [update]);

  const openDownloadPage = useCallback(() => {
    void openUrl(RELEASES_PAGE_MIRROR);
  }, []);
  const openGithubPage = useCallback(() => {
    void openUrl(RELEASES_PAGE);
  }, []);

  const dialog = open ? (
    <div className="update-backdrop" role="presentation" onMouseDown={() => setOpen(false)}>
      <section
        ref={dialogRef}
        className="update-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="update-title"
        aria-describedby="update-status"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="update-dialog-heading">
          <span className="update-dialog-icon">
            <Rocket size={21} />
          </span>
          <span>
            <small>软件更新</small>
            <strong id="update-title">图转视频极速版</strong>
          </span>
          <button
            type="button"
            className="update-close"
            onClick={() => setOpen(false)}
            aria-label="关闭更新窗口"
          >
            <X size={17} />
          </button>
        </header>

        <div className="update-dialog-body">
          <div
            id="update-status"
            className={`update-state update-state-${phase}`}
            aria-live="polite"
          >
            {checking ? <RefreshCw className="is-spinning" size={18} /> : null}
            {phase === "available" ? <Download size={18} /> : null}
            {phase === "current" ? <Check size={18} /> : null}
            {phase === "error" ? <CircleAlert size={18} /> : null}
            <span>
              <strong>{message || "可以随时检查新版本。"}</strong>
              {currentVersion ? <small>当前版本 {currentVersion}</small> : null}
            </span>
          </div>

          {update ? (
            <div className="update-release">
              <div>
                <span>可用版本</span>
                <strong>{update.version}</strong>
              </div>
              <div>
                <span>下载来源</span>
                <strong>{hostOf(update.url)}</strong>
              </div>
            </div>
          ) : null}

          {hasActiveJobs && update ? (
            <p className="update-warning">
              <CircleAlert size={15} />
              你还有正在进行的任务。装好新版本后请重开应用，避免导出被中断。
            </p>
          ) : null}

          {phase === "error" ? (
            <p className="update-warning">
              <CircleAlert size={15} />
              自动检查没成功。可以直接去下载页手动获取安装包。
            </p>
          ) : null}

          <div className="update-manual-actions">
            <button type="button" className="quiet-button" onClick={openDownloadPage}>
              <Download size={13} />
              镜像站下载页
            </button>
            <button type="button" className="quiet-button" onClick={openGithubPage}>
              <ExternalLink size={13} />
              GitHub 发布页
            </button>
          </div>

          <label className="update-setting">
            <input
              type="checkbox"
              checked={autoCheck}
              onChange={(event) => setAutoCheck(event.target.checked)}
            />
            <span>
              <strong>启动时自动检查更新</strong>
              <small>发现新版本时提示，不会自动中断正在进行的任务。</small>
            </span>
          </label>
        </div>

        <footer className="update-dialog-actions">
          {update ? (
            <>
              <button type="button" className="quiet-button" onClick={() => setOpen(false)}>
                稍后提醒
              </button>
              <button type="button" className="update-primary" onClick={openDownload}>
                打开下载页
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="quiet-button"
                onClick={() => setOpen(false)}
                disabled={checking}
              >
                关闭
              </button>
              <button
                type="button"
                className="update-primary"
                onClick={() => void checkForUpdates(true)}
                disabled={checking}
              >
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
      <button
        ref={triggerRef}
        type="button"
        className={`update-button${update ? " has-update" : ""}`}
        onClick={() => void checkForUpdates(true)}
        aria-label={update ? `发现新版本 ${update.version}，打开更新窗口` : "检查软件更新"}
      >
        {checking ? (
          <RefreshCw className="is-spinning" size={15} />
        ) : update ? (
          <Download size={15} />
        ) : (
          <RefreshCw size={15} />
        )}
        {update ? `更新 ${update.version}` : "检查更新"}
      </button>
      {dialog ? createPortal(dialog, document.body) : null}
    </>
  );
}

/** 取链接的域名用于展示；解析失败不抛异常（清单已校验过是 https）。 */
function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return "GitHub";
  }
}
