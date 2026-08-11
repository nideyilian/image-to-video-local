import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Crosshair, Expand, Pause, Play, SkipBack, SkipForward, X } from "lucide-react";
import type { PreviewFrame, Workspace } from "../types";
import { EFFECT_PRESETS, computeEffectStyle, effectClassNameFor, isEffectEnabled, previewEffectType } from "./previewEffects";
import { CENTER_FOCUS, computeCoverTransform, findFocusRegion, type FocusRegion } from "./previewFocus";
import { useEngineEffectPreview } from "./useEngineEffectPreview";

function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${remainder.toFixed(1).padStart(4, "0")}`;
}

function fileNameOf(frame: PreviewFrame | undefined): string {
  if (!frame) return "";
  const tail = frame.source.split(/[\\/]/).pop() ?? "";
  return tail.replace(/\.[^.]+$/, "") || tail;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

let hintShownOnce = false;

const FOCUS_BASE_ZOOM = 1.5;
const FOCUS_MAX_ZOOM = 4;

type FocusState = "idle" | "loading" | "ready" | "fallback";

export function PreviewLightbox({
  workspace,
  frames,
  initialIndex,
  onClose,
}: {
  workspace: Workspace;
  frames: PreviewFrame[];
  initialIndex: number;
  onClose: () => void;
}) {
  const markerCount = frames.length || Math.max(1, Math.min(7, workspace.config.num_images));
  const frameDuration = Math.max(0.1, workspace.config.duration);
  const automaticTotal = markerCount * frameDuration;
  const total = Math.max(0.1, workspace.config.total_duration > 0 ? workspace.config.total_duration : automaticTotal);

  const [time, setTime] = useState(() => {
    const start = clamp(initialIndex, 0, Math.max(0, markerCount - 1));
    return start * frameDuration;
  });
  const [playing, setPlaying] = useState(false);
  const [uiVisible, setUiVisible] = useState(true);
  const [focusMode, setFocusMode] = useState(false);
  const [focus, setFocus] = useState<FocusRegion>(CENTER_FOCUS);
  const [focusState, setFocusState] = useState<FocusState>("idle");
  const [zoom, setZoom] = useState(FOCUS_BASE_ZOOM);
  const [dragging, setDragging] = useState(false);
  const [hintVisible, setHintVisible] = useState(!hintShownOnce);
  const [stageSize, setStageSize] = useState<{ width: number; height: number } | null>(null);

  const rootRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const idleTimerRef = useRef<number | null>(null);
  const dragRef = useRef<{ startX: number; startY: number; fx: number; fy: number } | null>(null);
  const zoomRef = useRef(FOCUS_BASE_ZOOM);

  const frameIndex = Math.floor(time / frameDuration) % markerCount;
  const frame = frames[frameIndex] ?? frames[0];
  const nextFrame = frames.length > 1 ? frames[(frameIndex + 1) % frames.length] : null;
  const url = frame?.previewUrl;

  const effectEnabled = isEffectEnabled(workspace.config);
  const effectPreset = EFFECT_PRESETS[previewEffectType(workspace.config)] ?? { motion: "breathe" as const };
  const effectClassName = effectClassNameFor(workspace.config);
  const effectStyle = useMemo(
    () => computeEffectStyle(Number(workspace.config.video_effect_intensity), Number(workspace.config.video_effect_speed)),
    [workspace.config.video_effect_intensity, workspace.config.video_effect_speed],
  );
  const engineEffect = useEngineEffectPreview(workspace, frame, time, !focusMode, nextFrame);
  const renderedUrl = engineEffect.url ?? url;
  const renderedByEngine = Boolean(engineEffect.url);

  // 进入全屏：优先浏览器全屏 API，失败时退化为固定覆盖层
  useEffect(() => {
    const element = rootRef.current;
    const handleChange = () => {
      if (document.fullscreenElement !== element) onClose();
    };
    document.addEventListener("fullscreenchange", handleChange);
    const enter = async () => {
      try {
        if (element && !document.fullscreenElement && element.requestFullscreen) {
          await element.requestFullscreen();
        }
      } catch {
        /* 全屏被拒时，固定覆盖层仍提供完整沉浸体验 */
      }
    };
    void enter();
    return () => {
      document.removeEventListener("fullscreenchange", handleChange);
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    };
  }, [onClose]);

  // 控件自动隐藏：鼠标移动唤醒，静止 2.6s 后淡出
  const wakeUi = useCallback(() => {
    setUiVisible(true);
    if (idleTimerRef.current !== null) window.clearTimeout(idleTimerRef.current);
    idleTimerRef.current = window.setTimeout(() => setUiVisible(false), 2600);
  }, []);

  useEffect(() => {
    wakeUi();
    return () => {
      if (idleTimerRef.current !== null) window.clearTimeout(idleTimerRef.current);
    };
  }, [wakeUi]);

  // 首次进入的微提示：3 秒后淡出，仅在本次会话出现一次
  useEffect(() => {
    if (!hintVisible) return;
    hintShownOnce = true;
    const timer = window.setTimeout(() => setHintVisible(false), 3200);
    return () => window.clearTimeout(timer);
  }, [hintVisible]);

  // 监听舞台尺寸，用于聚焦视图的变换计算
  useEffect(() => {
    const element = stageRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setStageSize({ width: entry.contentRect.width, height: entry.contentRect.height });
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // 播放驱动
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setTime((value) => (value + 0.1) % total), 100);
    return () => window.clearInterval(timer);
  }, [playing, total]);

  // 聚焦模式下重新分析当前画面主体
  useEffect(() => {
    if (!focusMode || !url) {
      setFocusState("idle");
      return;
    }
    let cancelled = false;
    setFocusState("loading");
    zoomRef.current = FOCUS_BASE_ZOOM;
    setZoom(FOCUS_BASE_ZOOM);
    findFocusRegion(url).then((region) => {
      if (cancelled) return;
      setFocus(region ?? CENTER_FOCUS);
      setFocusState(region ? "ready" : "fallback");
    });
    return () => {
      cancelled = true;
    };
  }, [focusMode, url]);

  const close = useCallback(() => {
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => onClose());
    } else {
      onClose();
    }
  }, [onClose]);

  const showAdjacent = useCallback(
    (offset: -1 | 1) => {
      const next = (frameIndex + offset + markerCount) % markerCount;
      setTime(Math.min(Math.max(0, total - 0.1), next * frameDuration));
    },
    [frameIndex, markerCount, frameDuration, total],
  );

  const togglePlay = useCallback(() => setPlaying((value) => !value), []);
  const toggleFocus = useCallback(() => setFocusMode((value) => !value), []);

  // 键盘导航
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        showAdjacent(1);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        showAdjacent(-1);
      } else if (event.key === " ") {
        event.preventDefault();
        togglePlay();
      } else if (event.key.toLowerCase() === "f") {
        toggleFocus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close, showAdjacent, togglePlay, toggleFocus]);

  // 聚焦视图变换
  const imgWidth = frame?.width ?? 4;
  const imgHeight = frame?.height ?? 3;
  const focusTransform = useMemo<CSSProperties | null>(() => {
    if (!stageSize || stageSize.width <= 0 || stageSize.height <= 0) return null;
    const { scale, tx, ty } = computeCoverTransform(stageSize.width, stageSize.height, imgWidth, imgHeight, focus.x, focus.y, zoom);
    return {
      width: imgWidth * scale,
      height: imgHeight * scale,
      transform: `translate(${tx.toFixed(2)}px, ${ty.toFixed(2)}px)`,
    };
  }, [stageSize, focus.x, focus.y, imgWidth, imgHeight, zoom]);

  const handleWheel = useCallback(
    (event: WheelEvent) => {
      if (!focusMode) return;
      event.preventDefault();
      if (event.deltaY < 0) {
        const next = Math.min(FOCUS_MAX_ZOOM, zoomRef.current * 1.12);
        zoomRef.current = next;
        setZoom(next);
      } else if (zoomRef.current <= FOCUS_BASE_ZOOM + 0.01) {
        setFocusMode(false);
      } else {
        const next = Math.max(FOCUS_BASE_ZOOM, zoomRef.current / 1.12);
        zoomRef.current = next;
        setZoom(next);
      }
    },
    [focusMode],
  );

  // 以非 passive 方式挂载滚轮监听，确保 preventDefault 生效
  useEffect(() => {
    const element = rootRef.current;
    if (!element) return;
    element.addEventListener("wheel", handleWheel, { passive: false });
    return () => element.removeEventListener("wheel", handleWheel);
  }, [handleWheel]);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!focusMode) return;
      dragRef.current = { startX: event.clientX, startY: event.clientY, fx: focus.x, fy: focus.y };
      setDragging(true);
      event.currentTarget.setPointerCapture?.(event.pointerId);
    },
    [focus.x, focus.y, focusMode],
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      if (!drag || !stageSize) return;
      const scale = Math.max(stageSize.width / imgWidth, stageSize.height / imgHeight) * zoom;
      const dx = (event.clientX - drag.startX) / (imgWidth * scale);
      const dy = (event.clientY - drag.startY) / (imgHeight * scale);
      setFocus({ x: clamp(drag.fx - dx, 0, 1), y: clamp(drag.fy - dy, 0, 1) });
    },
    [stageSize, imgWidth, imgHeight, zoom],
  );

  const endDrag = useCallback(() => {
    dragRef.current = null;
    setDragging(false);
  }, []);

  const outputFit = workspace.config.keep_aspect_ratio ? "contain" : "fill";
  const markers = useMemo(() => Array.from({ length: markerCount }, (_, index) => index), [markerCount]);
  const fileName = fileNameOf(frame);

  return (
    <div ref={rootRef} className="preview-lightbox" onPointerMove={wakeUi} onPointerDown={wakeUi}>
      <div ref={stageRef} className="lightbox-stage">
        {url ? (
          focusMode ? (
            <div
              className={`lightbox-focus-stage${dragging ? " is-dragging" : ""}`}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
            >
              <img className="lightbox-focus-image" src={url} alt="聚焦视图" draggable={false} style={focusTransform ?? undefined} />
            </div>
          ) : (
            <div className="lightbox-fit">
              <div key={`${url}-${workspace.config.video_effect_type}`} className={renderedByEngine ? "preview-media" : effectClassName} style={effectStyle}>
                <img className="effect-frame" src={renderedUrl} alt="全屏预览" style={{ objectFit: renderedByEngine ? "contain" : outputFit }} />
                {!renderedByEngine && effectEnabled && effectPreset.motion === "soul" ? (
                  <img className="preview-ghost" src={url} alt="" aria-hidden="true" style={{ objectFit: outputFit }} />
                ) : null}
              </div>
            </div>
          )
        ) : (
          <div className="lightbox-empty">
            <strong>没有可预览的图片</strong>
            <p>请先在输入目录中读取素材。</p>
          </div>
        )}
      </div>

      <button type="button" className="lightbox-exit" onClick={close} aria-label="退出全屏预览" title="退出全屏 (Esc)">
        <X size={20} />
      </button>

      <div className={`lightbox-chrome ${uiVisible ? "is-visible" : ""}`}>
        <header className="lightbox-topbar">
          <div className="lightbox-meta">
            <strong>{fileName || workspace.name}</strong>
            <span>{frame ? `${frame.width} × ${frame.height}` : ""}</span>
            <span>第 {frameIndex + 1} / {markerCount} 张</span>
          </div>
          <div className="lightbox-facts">
            <span>{workspace.config.resolution_preset}</span>
            <span>{workspace.config.fps} fps</span>
            <span>{formatTime(total)}</span>
          </div>
        </header>

        <footer className="lightbox-toolbar">
          <div className="lightbox-transport">
            <button type="button" className="icon-button" onClick={() => showAdjacent(-1)} disabled={markerCount < 2} aria-label="预览上一张图片" title="上一张图片 (←)">
              <SkipBack size={16} />
            </button>
            <button type="button" className="play-button" onClick={togglePlay} aria-label={playing ? "暂停预览" : "播放预览"} title="播放 / 暂停 (Space)">
              {playing ? <Pause size={18} /> : <Play size={18} />}
            </button>
            <button type="button" className="icon-button" onClick={() => showAdjacent(1)} disabled={markerCount < 2} aria-label="预览下一张图片" title="下一张图片 (→)">
              <SkipForward size={16} />
            </button>
            <span className="timecode">{formatTime(time)} / {formatTime(total)}</span>
            <input
              className="timeline-range"
              type="range"
              min={0}
              max={total}
              step={0.1}
              value={time}
              aria-label="预览时间轴"
              onChange={(event) => setTime(Number(event.target.value))}
            />
          </div>

          <div className="lightbox-filmstrip" aria-label="样片序列">
            {markers.map((marker) => (
              <button
                key={marker}
                type="button"
                className={marker === frameIndex ? "is-current" : ""}
                onClick={() => setTime(Math.min(total, marker * frameDuration))}
                aria-label={`跳到序列 ${marker + 1}`}
                title={`第 ${marker + 1} 张`}
              >
                {frames[marker] ? <img src={frames[marker].previewUrl} alt="" /> : <span />}
              </button>
            ))}
            <span className="playhead" style={{ left: `${Math.min(100, (time / total) * 100)}%` }} />
          </div>

          <div className="lightbox-actions">
            <button
              type="button"
              className={`lightbox-action${focusMode ? " is-active" : ""}`}
              onClick={toggleFocus}
              disabled={!url}
              title="智能识别画面主体并放大铺满 (F)"
            >
              <Crosshair size={14} />
              {focusMode ? "完整视图" : "聚焦视图"}
            </button>
            <button type="button" className="lightbox-action" onClick={close} title="退出全屏 (Esc)">
              <Expand size={14} />
              退出全屏
            </button>
          </div>
        </footer>
      </div>

      {hintVisible ? (
        <div className="lightbox-hint" role="status">鼠标不动时界面更干净哦</div>
      ) : null}
      {focusMode && focusState === "loading" ? (
        <div className="lightbox-focusing" role="status"><Crosshair size={13} className="is-spinning" />正在识别画面焦点…</div>
      ) : null}
      {focusMode && focusState === "fallback" ? (
        <div className="lightbox-focusing" role="status">已切换到中心聚焦</div>
      ) : null}
    </div>
  );
}
