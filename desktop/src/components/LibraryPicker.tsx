import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, CircleAlert, Image as ImageIcon, Layers, Loader2, Music, Play, Search, X } from "lucide-react";
import { engine } from "../engine";
import type { LibraryDirs, LibraryItem } from "../types";

const LIBRARY_KEY = "image-to-video.library.v1";

function loadStoredDirs(): Partial<LibraryDirs> {
  try {
    const raw = JSON.parse(localStorage.getItem(LIBRARY_KEY) || "{}") as Partial<LibraryDirs>;
    return raw && typeof raw === "object" ? raw : {};
  } catch {
    return {};
  }
}

function formatDuration(seconds: number | null | undefined) {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return "";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes > 0 ? `${minutes}:${String(rest).padStart(2, "0")}` : `${rest}s`;
}

function formatBytes(bytes: number) {
  if (!bytes || bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function LibraryPicker({ open, onClose, kind, selected, onConfirmBgm, onUseAsVideo, onAddWatermarkLayers }: {
  open: boolean;
  onClose: () => void;
  kind: "bgm" | "watermark";
  selected?: string[];
  onConfirmBgm?: (paths: string[]) => void;
  onUseAsVideo?: (item: LibraryItem) => void;
  onAddWatermarkLayers?: (items: LibraryItem[]) => void;
}) {
  const isBgm = kind === "bgm";
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set(selected ?? []));
  const dialogRef = useRef<HTMLElement>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    if (!open) return;
    setPicked(new Set(selected ?? []));
    setQuery("");
    void (async () => {
      if (!engine.desktopRuntime) return;
      setLoading(true);
      setError(null);
      try {
        const stored = loadStoredDirs();
        const defaults = await engine.call<LibraryDirs>("library_dirs", {}, 15_000);
        const dirs = {
          bgm_dir: stored.bgm_dir || defaults.bgm_dir,
          watermark_dir: stored.watermark_dir || defaults.watermark_dir,
        };
        const snapshot = await engine.call<{ bgm: LibraryItem[]; watermark: LibraryItem[] }>("library_snapshot", dirs, 60_000);
        if (!mountedRef.current) return;
        setItems(isBgm ? snapshot.bgm : snapshot.watermark);
      } catch (err) {
        if (!mountedRef.current) return;
        setError(err instanceof Error ? err.message : "读取素材库失败");
      } finally {
        if (mountedRef.current) setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, open]);

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusTimer = window.setTimeout(() => dialogRef.current?.querySelector<HTMLElement>("button:not(:disabled), input:not(:disabled)")?.focus(), 0);
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
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
    document.body.classList.add("is-modal-open");
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("keydown", handleKeyDown);
      document.body.classList.remove("is-modal-open");
      previousFocus?.focus();
    };
  }, [open, onClose]);

  const toggle = useCallback((path: string) => {
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q ? items.filter((item) => item.name.toLowerCase().includes(q)) : items;
    return [...list].sort((a, b) => a.name.localeCompare(b.name, "zh-Hans-CN"));
  }, [items, query]);

  const confirmBgm = useCallback(() => {
    const paths = Array.from(picked);
    if (paths.length && onConfirmBgm) onConfirmBgm(paths);
    onClose();
  }, [onClose, onConfirmBgm, picked]);

  const confirmWatermarkLayers = useCallback(() => {
    const chosen = items.filter((item) => picked.has(item.path));
    if (chosen.length && onAddWatermarkLayers) onAddWatermarkLayers(chosen);
    onClose();
  }, [items, onAddWatermarkLayers, onClose, picked]);

  if (!open) return null;

  const dialog = (
    <div className="library-backdrop library-backdrop-inner" role="presentation" onMouseDown={onClose}>
      <section ref={dialogRef} className="library-picker-dialog" role="dialog" aria-modal="true" aria-labelledby="library-picker-title" onMouseDown={(event) => event.stopPropagation()}>
        <header className="library-dialog-heading">
          <span className="library-dialog-icon">{isBgm ? <Music size={20} /> : <ImageIcon size={20} />}</span>
          <span>
            <small>从素材库选择</small>
            <strong id="library-picker-title">{isBgm ? "选择 BGM 素材" : "选择水印素材"}</strong>
          </span>
          <span className="library-heading-hint">已选 {picked.size} 项</span>
          <button type="button" className="update-close" onClick={onClose} aria-label="关闭素材选择器"><X size={17} /></button>
        </header>

        <div className="library-picker-body">
          {!engine.desktopRuntime ? (
            <div className="library-desktop-only"><CircleAlert size={16} />从素材库选择素材需要在 Tauri 桌面窗口中运行。</div>
          ) : null}
          <div className="library-picker-toolbar">
            <span className="library-search">
              <Search size={13} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={isBgm ? "搜索 BGM" : "搜索水印素材"} aria-label={isBgm ? "搜索 BGM" : "搜索水印素材"} />
              {query ? <button type="button" className="icon-button" onClick={() => setQuery("")} aria-label="清除搜索"><X size={12} /></button> : null}
            </span>
            <span className="library-picker-toolbar-hint">
              {isBgm
                ? "可多选；导出按「随机 / 顺序」模式从已选素材中选取，留空则从音频目录选取。"
                : "图片与视频都可加入水印图层；视频还可直接用作单文件视频水印。"}
            </span>
          </div>

          {error ? <div className="library-error"><CircleAlert size={15} />{error}</div> : null}

          <ul className="library-picker-list">
            {!loading && !visible.length ? (
              <li className="library-empty">
                {query ? "没有匹配的素材。" : isBgm ? "BGM 库还是空的：请先打开「素材库」导入音频或批量拆 BGM。" : "水印库还是空的：请先打开「素材库」导入图片或视频。"}
              </li>
            ) : null}
            {visible.map((item) => {
              const isPicked = picked.has(item.path);
              const isVideo = !isBgm && item.type === "video";
              return (
                <li key={item.path} className={`library-picker-row${isPicked ? " is-picked" : ""}`}>
                  <input type="checkbox" className="library-checkbox" checked={isPicked} onChange={() => toggle(item.path)} aria-label={`选择 ${item.name}`} />
                  {isBgm ? (
                    <span className="library-file-icon"><Music size={15} /></span>
                  ) : (
                    <span className="library-thumb-wrap">
                      <PickerThumb path={item.path} />
                      {isVideo ? <span className="library-thumb-badge"><Play size={9} />{formatDuration(item.duration)}</span> : null}
                    </span>
                  )}
                  <span className="library-row-main">
                    <strong title={item.path}>{item.name}</strong>
                    <small>
                      {item.folder ? `${item.folder} · ` : ""}
                      {isBgm ? formatDuration(item.duration) : isVideo ? `${formatDuration(item.duration)} · ` : ""}
                      {formatBytes(item.size_bytes)}
                    </small>
                  </span>
                  <span className="library-row-actions">
                    {!isBgm && isVideo && onUseAsVideo ? (
                      <button type="button" className="quiet-button" onClick={() => onUseAsVideo(item)}><Play size={13} />用作视频水印</button>
                    ) : null}
                    {!isBgm && onAddWatermarkLayers ? (
                      <button type="button" className="icon-button" onClick={() => onAddWatermarkLayers([item])} aria-label={`加入水印图层 ${item.name}`} title="加入水印图层"><Layers size={14} /></button>
                    ) : null}
                    {isPicked ? <Check size={15} className="library-picker-check" /> : null}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>

        <footer className="library-dialog-footer">
          <span>{isBgm ? "「确定」后作为当前工作区 BGM 素材。" : "「加入图层」会添加到图片水印图层（图片与视频均支持）。"}</span>
          <span className="library-dialog-footer-actions">
            <button type="button" className="quiet-button" onClick={onClose}>取消</button>
            {isBgm ? (
              <button type="button" className="library-accent-button" onClick={confirmBgm} disabled={!picked.size}>
                <Check size={14} />确定（{picked.size}）
              </button>
            ) : (
              <button type="button" className="library-accent-button" onClick={confirmWatermarkLayers} disabled={!picked.size}>
                <Layers size={14} />加入图层（{picked.size}）
              </button>
            )}
          </span>
        </footer>
      </section>
    </div>
  );

  return createPortal(dialog, document.body);
}

function PickerThumb({ path }: { path: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void engine.call<{ preview_path: string }>("preview_thumbnail", { path, max_width: 240, max_height: 240 }, 60_000)
      .then((result) => {
        if (!cancelled) setUrl(engine.toAssetUrl(result.preview_path));
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => { cancelled = true; };
  }, [path]);

  if (url) return <img className="library-thumb is-small" src={url} alt="" />;
  return (
    <span className="library-thumb-placeholder is-small">
      {failed ? <CircleAlert size={18} /> : <Loader2 className="is-spinning" size={18} />}
    </span>
  );
}
