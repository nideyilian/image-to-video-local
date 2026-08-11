import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Image,
  Maximize2,
  Minimize2,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Pause,
  Play,
  RefreshCw,
  ScanLine,
  SkipBack,
  SkipForward,
  Volume2,
} from "lucide-react";
import type { Workspace } from "../types";
import { EFFECT_PRESETS, computeEffectStyle, effectClassNameFor, isEffectEnabled, previewEffectType } from "./previewEffects";
import { useBgmPreview } from "./useBgmPreview";
import { useEngineEffectPreview } from "./useEngineEffectPreview";

function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${remainder.toFixed(1).padStart(4, "0")}`;
}

function resolutionAspectRatio(value: string, fallback: number) {
  const match = value.match(/(\d+)\s*[x×]\s*(\d+)/i);
  if (!match) return fallback;
  const width = Number(match[1]);
  const height = Number(match[2]);
  return width > 0 && height > 0 ? width / height : fallback;
}

export function PreviewStage({
  workspace,
  loading,
  demoMode,
  railCollapsed,
  inspectorCollapsed,
  focused,
  onRefresh,
  onToggleRail,
  onToggleInspector,
  onToggleFocus,
}: {
  workspace: Workspace;
  loading: boolean;
  demoMode: boolean;
  railCollapsed: boolean;
  inspectorCollapsed: boolean;
  focused: boolean;
  onRefresh: () => void;
  onToggleRail: () => void;
  onToggleInspector: () => void;
  onToggleFocus: () => void;
}) {
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [fittedFrame, setFittedFrame] = useState<{ width: number; height: number } | null>(null);
  const [audioPlaybackError, setAudioPlaybackError] = useState("");
  const previewCanvasRef = useRef<HTMLDivElement>(null);
  const bgmAudioRef = useRef<HTMLAudioElement>(null);
  const timeRef = useRef(0);
  const sourceFrames = useMemo(
    () => workspace.preview?.frames?.length ? workspace.preview.frames : workspace.preview ? [workspace.preview] : [],
    [workspace.preview],
  );
  const frameDuration = Math.max(0.1, Number(workspace.config.duration) || 0.1);
  const frames = useMemo(() => {
    if (!sourceFrames.length || workspace.config.total_duration <= 0) return sourceFrames;
    const slotCount = Math.max(1, Math.round(workspace.config.total_duration / frameDuration));
    return Array.from({ length: slotCount }, (_, index) => sourceFrames[index % sourceFrames.length]);
  }, [frameDuration, sourceFrames, workspace.config.total_duration]);
  const markerCount = frames.length;
  const hasFrames = markerCount > 0;
  const automaticTotal = markerCount * frameDuration;
  const total = hasFrames
    ? Math.max(0.1, workspace.config.total_duration > 0 ? workspace.config.total_duration : automaticTotal)
    : 0;
  const frameSourcesKey = useMemo(() => frames.map((frame) => frame.source).join("\u0001"), [frames]);
  const bgmPreview = useBgmPreview(workspace);

  const syncAudioTime = (targetTime: number) => {
    const audio = bgmAudioRef.current;
    if (!audio || !bgmPreview.url) return;
    try {
      const duration = audio.duration;
      if (Number.isFinite(duration) && duration > 0) {
        audio.currentTime = workspace.config.loop_bgm
          ? targetTime % duration
          : Math.min(targetTime, Math.max(0, duration - 0.05));
      } else {
        audio.currentTime = Math.max(0, targetTime);
      }
    } catch {
      setAudioPlaybackError("BGM 时间轴同步失败");
    }
  };

  const playAudio = () => {
    const audio = bgmAudioRef.current;
    if (!audio || !bgmPreview.url) return;
    void audio.play().then(() => setAudioPlaybackError("")).catch(() => {
      setAudioPlaybackError("系统阻止了声音播放，请再次点击播放");
    });
  };

  const seekPreview = (targetTime: number) => {
    const next = Math.max(0, Math.min(Math.max(0, total - 0.1), targetTime));
    timeRef.current = next;
    setTime(next);
    syncAudioTime(next);
  };

  const togglePlayback = () => {
    if (!hasFrames) return;
    const nextPlaying = !playing;
    setPlaying(nextPlaying);
    if (nextPlaying) {
      syncAudioTime(timeRef.current);
      playAudio();
    } else {
      bgmAudioRef.current?.pause();
    }
  };

  useEffect(() => {
    if (!playing || total <= 0) return;
    const timer = window.setInterval(() => {
      const wrapped = timeRef.current + 0.1 >= total;
      const next = wrapped ? 0 : timeRef.current + 0.1;
      timeRef.current = next;
      setTime(next);
      if (wrapped && bgmPreview.url) {
        syncAudioTime(0);
        playAudio();
      }
    }, 100);
    return () => window.clearInterval(timer);
  }, [bgmPreview.url, playing, total, workspace.config.loop_bgm]);

  useEffect(() => {
    setTime(0);
    timeRef.current = 0;
    setPlaying(false);
  }, [frameSourcesKey, workspace.id]);

  useEffect(() => {
    if (!hasFrames) {
      setTime(0);
      timeRef.current = 0;
      setPlaying(false);
      return;
    }
    setTime((value) => {
      const next = Math.min(value, Math.max(0, total - 0.1));
      timeRef.current = next;
      return next;
    });
  }, [hasFrames, total]);

  useEffect(() => {
    const audio = bgmAudioRef.current;
    if (!audio) return;
    audio.volume = Math.max(0, Math.min(1, Number(workspace.config.bgm_volume) || 0));
    audio.loop = Boolean(workspace.config.loop_bgm);
  }, [bgmPreview.url, workspace.config.bgm_volume, workspace.config.loop_bgm]);

  useEffect(() => {
    if (!playing || !bgmPreview.url) bgmAudioRef.current?.pause();
    if (bgmPreview.status !== "error") setAudioPlaybackError("");
  }, [bgmPreview.status, bgmPreview.url, playing]);

  const configuredLayers = workspace.config.use_image_watermark
    ? workspace.config.watermark_layers.filter((layer) => layer.enabled && layer.path).length
    : 0;
  const outputFit = workspace.config.keep_aspect_ratio ? "contain" : "fill";
  const frameIndex = hasFrames ? Math.floor(time / frameDuration) % markerCount : 0;
  const navigableFrameCount = markerCount;
  const currentFrame = frames[frameIndex] ?? null;
  const nextFrame = frames.length > 1 ? frames[(frameIndex + 1) % frames.length] : null;
  const previewUrl = currentFrame?.previewUrl;
  const sourceAspectRatio = currentFrame?.width && currentFrame.height ? currentFrame.width / currentFrame.height : 4 / 3;
  const outputAspectRatio = resolutionAspectRatio(workspace.config.resolution_preset, sourceAspectRatio);
  const previewSpecimenStyle: CSSProperties = {
    width: fittedFrame?.width,
    height: fittedFrame?.height,
    aspectRatio: String(outputAspectRatio),
  };
  const markers = useMemo(() => Array.from({ length: markerCount }, (_, index) => index), [markerCount]);
  const effectEnabled = isEffectEnabled(workspace.config);
  const effectPreset = EFFECT_PRESETS[previewEffectType(workspace.config)] ?? { motion: "breathe" as const };
  const effectStyle = useMemo(
    () => computeEffectStyle(Number(workspace.config.video_effect_intensity), Number(workspace.config.video_effect_speed)),
    [workspace.config.video_effect_intensity, workspace.config.video_effect_speed],
  );
  const effectClassName = effectClassNameFor(workspace.config);
  const engineEffect = useEngineEffectPreview(workspace, currentFrame, time, true, nextFrame);
  const renderedPreviewUrl = engineEffect.url ?? previewUrl;
  const renderedByEngine = Boolean(engineEffect.url);
  const previewTransitionName = workspace.config.random_transition
    ? engineEffect.transitionType || "随机预览"
    : workspace.config.transition_type;
  const previewEffectName = workspace.config.random_video_effect
    ? engineEffect.effectType || "随机预览"
    : workspace.config.video_effect_type;
  const showAdjacentImage = (offset: -1 | 1) => {
    if (!navigableFrameCount) return;
    const nextFrameIndex = (frameIndex + offset + navigableFrameCount) % navigableFrameCount;
    seekPreview(nextFrameIndex * frameDuration);
  };

  useEffect(() => {
    const canvas = previewCanvasRef.current;
    if (!canvas) return;

    const fitFrame = () => {
      const availableWidth = Math.max(1, canvas.clientWidth - 32);
      const availableHeight = Math.max(1, canvas.clientHeight - 32);
      const width = Math.min(availableWidth, availableHeight * outputAspectRatio);
      const height = width / outputAspectRatio;
      setFittedFrame((current) => {
        if (current && Math.abs(current.width - width) < 0.5 && Math.abs(current.height - height) < 0.5) return current;
        return { width, height };
      });
    };

    fitFrame();
    const observer = new ResizeObserver(fitFrame);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [outputAspectRatio]);

  return (
    <section className="preview-stage" aria-label="预览工作台">
      <div className="panel-heading preview-heading">
        <div>
          <span className="panel-kicker">画面预览</span>
          <strong>{workspace.name}</strong>
        </div>
        <div className="preview-facts" aria-label="输出参数">
          <span>{workspace.config.resolution_preset}</span>
          <span>{workspace.config.fps} fps</span>
          <span>{workspace.config.duration}s / 图</span>
          <span>{total}s 总时长</span>
        </div>
        <div className="preview-heading-actions">
          <button type="button" className="icon-button" onClick={onToggleRail} aria-label={railCollapsed ? "展开工作区列表" : "收起工作区列表"} title={railCollapsed ? "展开工作区列表" : "收起工作区列表"}>
            {railCollapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
          </button>
          <button type="button" className="icon-button" onClick={onToggleInspector} aria-label={inspectorCollapsed ? "展开参数检查器" : "收起参数检查器"} title={inspectorCollapsed ? "展开参数检查器" : "收起参数检查器"}>
            {inspectorCollapsed ? <PanelRightOpen size={15} /> : <PanelRightClose size={15} />}
          </button>
          <button type="button" className="icon-button" onClick={onToggleFocus} aria-label={focused ? "退出专注预览" : "进入专注预览"} title={focused ? "退出专注预览" : "进入专注预览"}>
            {focused ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>
          <button type="button" className="quiet-button" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={15} className={loading ? "is-spinning" : ""} />
            {loading ? "正在读取" : "刷新预览"}
          </button>
        </div>
      </div>

      <div className="preview-workspace">
      <div ref={previewCanvasRef} className={`preview-canvas ${previewUrl || demoMode ? "has-preview" : "is-empty"}`}>
        {previewUrl ? (
          <figure className="preview-specimen" style={previewSpecimenStyle}>
            <div key={`${currentFrame?.source}-${workspace.config.video_effect_type}`} className={renderedByEngine ? "preview-media" : effectClassName} style={effectStyle}>
              <img className="effect-frame" src={renderedPreviewUrl} alt="原版流程中的当前预览图片" style={{ objectFit: renderedByEngine ? "fill" : outputFit }} />
              {!renderedByEngine && effectEnabled && effectPreset.motion === "soul" ? <img className="preview-ghost" src={previewUrl} alt="" aria-hidden="true" style={{ objectFit: outputFit }} /> : null}
            </div>
            <figcaption>第 {frameIndex + 1}/{frames.length} 张 · {currentFrame?.width}×{currentFrame?.height}</figcaption>
          </figure>
        ) : demoMode ? (
          <figure className="demo-specimen" style={previewSpecimenStyle}>
            <div key={workspace.config.video_effect_type} className={effectClassName} style={effectStyle}>
              <div className="demo-test-pattern effect-frame" role="img" aria-label="合成的单窗口预览样片">
                <span className="demo-horizon" /><span className="demo-object" />
                <strong>预览窗口</strong><small>合成演示数据 · {workspace.config.resolution_preset}</small>
              </div>
            </div>
            <figcaption>原版单窗口预览 · 演示数据</figcaption>
          </figure>
        ) : (
          <div className="preview-empty">
            <span className="empty-instrument"><ScanLine size={32} /></span>
            <strong>{loading ? "正在同步素材" : "等待本地素材"}</strong>
            <p>{loading ? "读取完成后会自动更新画面和轨道。" : "选择或输入目录后会自动读取。"}</p>
            <button type="button" onClick={onRefresh} disabled={loading}><Image size={16} />读取素材</button>
          </div>
        )}

        <div className="preview-calibration" aria-hidden="true">
          <span className="corner corner-a" /><span className="corner corner-b" />
          <span className="corner corner-c" /><span className="corner corner-d" />
          <span className="stage-ruler ruler-top"><i>00</i><i>25</i><i>50</i><i>75</i><i>100</i></span>
          <span className="stage-ruler ruler-side"><i>00</i><i>50</i><i>100</i></span>
        </div>
        <div className="preview-badges">
          <span>转场：{workspace.config.use_transition ? previewTransitionName : "关闭"}</span>
          <span>特效：{workspace.config.use_video_effect ? previewEffectName : "关闭"}{renderedByEngine ? " · 引擎实时" : effectEnabled && engineEffect.loading ? " · 引擎载入" : effectEnabled ? " · 预览降级" : ""}</span>
          <span>水印：{Number(workspace.config.use_watermark) + configuredLayers} 层</span>
          <span
            className={`preview-audio-status is-${bgmPreview.status}`}
            title={bgmPreview.name || audioPlaybackError || bgmPreview.message}
          >
            <Volume2 size={11} />
            BGM：{audioPlaybackError || (bgmPreview.status === "ready" ? `${bgmPreview.name} · ${Math.round(workspace.config.bgm_volume * 100)}%` : bgmPreview.message)}
          </span>
        </div>
      </div>
      </div>

      <audio
        ref={bgmAudioRef}
        src={bgmPreview.url ?? undefined}
        preload="auto"
        aria-hidden="true"
        onCanPlay={() => {
          setAudioPlaybackError("");
          syncAudioTime(timeRef.current);
          if (playing) playAudio();
        }}
        onError={() => setAudioPlaybackError("当前 BGM 格式无法播放")}
      />

      <div className="transport-row">
        <div className="transport-buttons" aria-label="预览播放控制">
          <button type="button" className="icon-button" onClick={() => showAdjacentImage(-1)} disabled={navigableFrameCount < 2} aria-label="预览上一张图片" title="上一张图片"><SkipBack size={16} /></button>
          <button type="button" className="play-button" onClick={togglePlayback} disabled={!hasFrames} aria-label={playing ? "暂停预览" : "播放预览"}>
            {playing ? <Pause size={18} /> : <Play size={18} />}
          </button>
          <button type="button" className="icon-button" onClick={() => showAdjacentImage(1)} disabled={navigableFrameCount < 2} aria-label="预览下一张图片" title="下一张图片"><SkipForward size={16} /></button>
        </div>
        <span className="timecode">{formatTime(time)} / {formatTime(total)}</span>
        <input
          className="timeline-range"
          type="range"
          min={0}
          max={Math.max(0.1, total)}
          step={0.1}
          value={time}
          disabled={!hasFrames}
          aria-label="预览时间轴"
          onChange={(event) => seekPreview(Number(event.target.value))}
        />
      </div>

      {hasFrames ? (
        <div className="filmstrip-viewport">
          <div
            className="filmstrip"
            aria-label={`视频轨道，共 ${markerCount} 个图片片段`}
            style={{
              gridTemplateColumns: `repeat(${markerCount}, minmax(0, 1fr))`,
              width: markerCount > 7 ? `${(markerCount / 7) * 100}%` : "100%",
            }}
          >
            {markers.map((marker) => (
              <button
                key={marker}
                type="button"
                className={marker === frameIndex ? "is-current" : ""}
                onClick={() => seekPreview(marker * frameDuration)}
                aria-label={`跳到序列 ${marker + 1}`}
              >
                <img src={frames[marker].previewUrl} alt="" />
                <small>{String(marker + 1).padStart(2, "0")}</small>
              </button>
            ))}
            <span className="playhead" style={{ left: `${Math.min(100, (time / total) * 100)}%` }} />
          </div>
        </div>
      ) : (
        <div className="filmstrip-empty" role="status">没有可播放的图片，轨道已停止。</div>
      )}
      <p className="preview-disclaimer">效果仅供预览，成片以导出结果为准。</p>

    </section>
  );
}
