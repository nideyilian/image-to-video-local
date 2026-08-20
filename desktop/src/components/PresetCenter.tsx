import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, Clock3, Save, Trash2, X } from "lucide-react";
import type { VideoConfig } from "../types";

// 预设不包含工作区目录类字段（输入/输出目录属于工作区专属）。
// 水印图层（watermark_layers）、视频水印路径（watermark_path）、素材库 BGM
// 文件（bgm_files）属于参数配置，随预设一起保存，保证预设完整可复现。
const PATH_KEYS = new Set([
  "input_dir",
  "output_dir",
  "bgm_dir",
  "width",
  "height",
  "_qt_watermark_defaults_v2",
]);

const PRESET_KEY = "image-to-video.presets.v1";

export type ConfigPreset = {
  id: string;
  name: string;
  savedAt: number;
  config: Partial<VideoConfig>;
};

export function extractPresetConfig(config: VideoConfig): Partial<VideoConfig> {
  const preset: Partial<VideoConfig> = {};
  for (const [key, value] of Object.entries(config)) {
    if (!PATH_KEYS.has(key)) preset[key as keyof VideoConfig] = value as never;
  }
  return preset;
}

export function PresetCenter({ open, onClose, config, onApply, notify }: {
  open: boolean;
  onClose: () => void;
  config: VideoConfig;
  onApply: (preset: ConfigPreset) => void;
  notify: (kind: "info" | "success" | "error", message: string) => void;
}) {
  const [presets, setPresets] = useState<ConfigPreset[]>([]);
  const [draftName, setDraftName] = useState("");
  const dialogRef = useRef<HTMLElement>(null);

  useEffect(() => {
    try {
      const raw = JSON.parse(localStorage.getItem(PRESET_KEY) || "[]");
      setPresets(Array.isArray(raw) ? raw as ConfigPreset[] : []);
    } catch {
      setPresets([]);
    }
  }, [open]);

  useEffect(() => {
    try {
      localStorage.setItem(PRESET_KEY, JSON.stringify(presets));
    } catch {
      /* 存储失败不影响使用 */
    }
  }, [presets]);

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

  const saveCurrent = () => {
    const name = draftName.trim();
    if (!name) return;
    const preset: ConfigPreset = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
      name,
      savedAt: Date.now(),
      config: extractPresetConfig(config),
    };
    setPresets((current) => [preset, ...current]);
    setDraftName("");
    notify("success", `已保存参数预设「${name}」`);
  };

  const sorted = useMemo(() => [...presets].sort((a, b) => b.savedAt - a.savedAt), [presets]);

  if (!open) return null;

  const dialog = (
    <div className="library-backdrop library-backdrop-inner" role="presentation" onMouseDown={onClose}>
      <section ref={dialogRef} className="library-picker-dialog" role="dialog" aria-modal="true" aria-labelledby="preset-title" onMouseDown={(event) => event.stopPropagation()}>
        <header className="library-dialog-heading">
          <span className="library-dialog-icon"><Save size={20} /></span>
          <span>
            <small>参数管理</small>
            <strong id="preset-title">参数预设</strong>
          </span>
          <span className="library-heading-hint">{presets.length} 个预设</span>
          <button type="button" className="update-close" onClick={onClose} aria-label="关闭参数预设"><X size={17} /></button>
        </header>

        <div className="library-picker-body">
          <div className="preset-save-row">
            <input
              value={draftName}
              onChange={(event) => setDraftName(event.target.value)}
              placeholder="预设名称，如：抖音竖屏 · 高码率"
              aria-label="预设名称"
              onKeyDown={(event) => {
                if (event.key === "Enter") saveCurrent();
              }}
            />
            <button type="button" className="library-accent-button" onClick={saveCurrent} disabled={!draftName.trim()}>
              <Save size={14} />保存当前参数
            </button>
          </div>
          <p className="preset-hint">预设保存分辨率、帧率、转场特效、BGM 与水印（含图片水印图层）等参数（不含输入/输出目录）。</p>

          {sorted.length ? (
            <ul className="preset-list">
              {sorted.map((preset) => (
                <li key={preset.id} className="preset-row">
                  <span className="preset-row-icon"><Clock3 size={14} /></span>
                  <span className="preset-row-main">
                    <strong>{preset.name}</strong>
                    <small>{new Date(preset.savedAt).toLocaleString("zh-CN")} · {preset.config.resolution_preset ?? "—"} · {preset.config.fps ?? "—"} fps</small>
                  </span>
                  <span className="preset-row-actions">
                    <button type="button" className="quiet-button" onClick={() => { onApply(preset); onClose(); }}><Check size={13} />应用</button>
                    <button type="button" className="icon-button danger" onClick={() => setPresets((current) => current.filter((item) => item.id !== preset.id))} aria-label={`删除预设 ${preset.name}`}><Trash2 size={14} /></button>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <li className="library-empty">还没有参数预设。命名并「保存当前参数」，下次一键应用。</li>
          )}
        </div>

        <footer className="library-dialog-footer">
          <span>预设保存在本机，可随时应用或删除。</span>
          <span className="library-dialog-footer-actions">
            <button type="button" className="quiet-button" onClick={onClose}>关闭</button>
          </span>
        </footer>
      </section>
    </div>
  );

  return createPortal(dialog, document.body);
}
