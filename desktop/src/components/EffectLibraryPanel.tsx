import { useEffect, useRef, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { Check, Image as ImageIcon, Loader2, Plus, RotateCcw, Shuffle, Sparkles, Trash2, Upload, X } from "lucide-react";
import { FALLBACK_CONFIG, TRANSITIONS, VIDEO_EFFECTS } from "../constants";
import { engine } from "../engine";
import type { VideoConfig } from "../types";

const ANIMATION_FRAMES = 8;

type EffectLibraryAssets = {
  source_a: string;
  source_b: string;
  custom_a?: boolean;
  custom_b?: boolean;
  user_path_a?: string;
  user_path_b?: string;
};

// 模块级 LRU 缓存：同一效果的动画帧/静态帧只请求一次（引擎侧另有磁盘缓存）
const ANIMATION_CACHE = new Map<string, string[]>();
const STATIC_CACHE = new Map<string, string>();
const CACHE_LIMIT = 120;

function cacheGet<T>(cache: Map<string, T>, key: string): T | undefined {
  const value = cache.get(key);
  if (value !== undefined) {
    cache.delete(key);
    cache.set(key, value);
  }
  return value;
}

function cacheSet<T>(cache: Map<string, T>, key: string, value: T) {
  cache.delete(key);
  cache.set(key, value);
  if (cache.size > CACHE_LIMIT) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) cache.delete(oldest);
  }
}

export function EffectLibraryPanel({ kind, config, onChange, notify }: {
  kind: "effect" | "transition";
  config: VideoConfig;
  onChange: <K extends keyof VideoConfig>(key: K, value: VideoConfig[K]) => void;
  notify: (kind: "info" | "success" | "error", message: string) => void;
}) {
  const isEffect = kind === "effect";
  const names = isEffect ? VIDEO_EFFECTS : TRANSITIONS;
  const current = isEffect ? config.video_effect_type : config.transition_type;
  const enabled = isEffect ? config.use_video_effect : config.use_transition;
  const randomMode = isEffect ? config.random_video_effect : config.random_transition;
  const pool = isEffect ? config.enabled_video_effects : config.enabled_transitions;

  const applySelection = (name: string) => {
    if (isEffect) {
      onChange("use_video_effect", true);
      onChange("video_effect_type", name);
      onChange("random_video_effect", false);
    } else {
      onChange("use_transition", true);
      onChange("transition_type", name);
      onChange("random_transition", false);
    }
    notify("success", `已选用${isEffect ? "特效" : "转场"}：${name}`);
  };

  const togglePool = (name: string) => {
    const inPool = pool.includes(name);
    const next = inPool ? pool.filter((item) => item !== name) : [...pool, name];
    if (isEffect) onChange("enabled_video_effects", next);
    else onChange("enabled_transitions", next);
    notify(inPool ? "info" : "success", inPool ? `已把${isEffect ? "特效" : "转场"}移出随机池：${name}` : `已加入随机池：${name}`);
  };

  const clearPool = () => {
    if (isEffect) onChange("enabled_video_effects", []);
    else onChange("enabled_transitions", []);
    notify("info", `已清空随机池（共 ${pool.length} 项）`);
  };

  // ---------- 自定义演示图 ----------

  const [assets, setAssets] = useState<EffectLibraryAssets | null>(null);
  const [assetVersion, setAssetVersion] = useState(0);
  const [assetBusy, setAssetBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void engine.call<EffectLibraryAssets>("effect_library_assets", {}, 15_000)
      .then((result) => {
        if (!cancelled) setAssets(result);
      })
      .catch(() => {
        /* 演示图信息非关键路径，失败不打扰 */
      });
    return () => { cancelled = true; };
  }, []);

  const applyAssets = (result: EffectLibraryAssets, message: string) => {
    ANIMATION_CACHE.clear();
    STATIC_CACHE.clear();
    setAssets(result);
    setAssetVersion((version) => version + 1);
    notify("success", message);
  };

  const pickCustomAsset = async (which: "a" | "b") => {
    if (!engine.desktopRuntime) return notify("info", "自定义演示图需要在 Tauri 桌面窗口中运行");
    const picked = await openDialog({
      multiple: false,
      directory: false,
      title: `选择演示图${which === "a" ? " A（特效 / 转场首帧）" : " B（转场第二帧）"}`,
      filters: [{ name: "图片", extensions: ["png", "jpg", "jpeg", "webp", "bmp", "gif"] }],
    });
    if (!picked) return;
    setAssetBusy(true);
    try {
      const result = await engine.call<EffectLibraryAssets>("effect_library_set_asset", { which, path: picked }, 30_000);
      applyAssets(result, `已使用自定义演示图${which === "a" ? " A" : " B"}，全部预览已更新`);
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "设置演示图失败");
    } finally {
      setAssetBusy(false);
    }
  };

  const resetAssets = async () => {
    setAssetBusy(true);
    try {
      const result = await engine.call<EffectLibraryAssets>("effect_library_reset_assets", {}, 30_000);
      applyAssets(result, "已恢复内置演示图");
    } catch (err) {
      notify("error", err instanceof Error ? err.message : "恢复演示图失败");
    } finally {
      setAssetBusy(false);
    }
  };

  const customA = Boolean(assets?.custom_a);
  const customB = Boolean(assets?.custom_b);

  return (
    <div className="effect-library">
      <div className="effect-stats-bar">
        <span className="effect-stats-current">
          <Sparkles size={13} />
          {enabled
            ? <>当前：<strong>{current}</strong></>
            : <>尚未启用{isEffect ? "特效" : "转场"}，点击卡片选用</>}
        </span>
        <span className="effect-stats-pool">
          <Shuffle size={13} />
          随机池 {pool.length} / {names.length}
          {randomMode ? <em className="effect-random-on">随机模式已开启</em> : null}
        </span>
      </div>

      <div className="effect-asset-bar">
        <span className="effect-asset-head">
          <span><ImageIcon size={13} /><strong>演示图</strong></span>
          <small>A 图用于特效与转场首帧，B 图用于转场第二帧；自定义后所有卡片预览立即更新。</small>
        </span>
        <span className="effect-asset-slots">
          <span className={`effect-asset-slot${customA ? " is-custom" : ""}`}>
            {assets ? <img src={engine.toAssetUrl(assets.source_a)} alt="演示图 A" /> : <span className="effect-asset-slot-empty"><Loader2 className="is-spinning" size={12} /></span>}
            <button type="button" className="quiet-button" onClick={() => void pickCustomAsset("a")} disabled={!engine.desktopRuntime || assetBusy}>
              <Upload size={12} />{customA ? "更换 A" : "自定义 A"}
            </button>
          </span>
          <span className={`effect-asset-slot${customB ? " is-custom" : ""}`}>
            {assets ? <img src={engine.toAssetUrl(assets.source_b)} alt="演示图 B" /> : <span className="effect-asset-slot-empty"><Loader2 className="is-spinning" size={12} /></span>}
            <button type="button" className="quiet-button" onClick={() => void pickCustomAsset("b")} disabled={!engine.desktopRuntime || assetBusy}>
              <Upload size={12} />{customB ? "更换 B" : "自定义 B"}
            </button>
          </span>
          {customA || customB ? (
            <button type="button" className="quiet-button" onClick={() => void resetAssets()} disabled={assetBusy}>
              <RotateCcw size={12} />恢复默认
            </button>
          ) : null}
        </span>
      </div>

      {pool.length ? (
        <div className="effect-pool-bar">
          <span className="effect-pool-label"><Shuffle size={12} />随机池（{pool.length}/{names.length}）</span>
          <ul className="effect-pool-chips">
            {pool.map((name) => (
              <li key={name}>
                <span title={name}>{name}</span>
                <button type="button" className="icon-button" onClick={() => togglePool(name)} aria-label={`把 ${name} 移出随机池`} title="移出随机池"><X size={11} /></button>
              </li>
            ))}
          </ul>
          <button type="button" className="quiet-button" onClick={clearPool}><Trash2 size={12} />清空</button>
        </div>
      ) : null}

      <ul className="effect-grid">
        {names.map((name) => {
          const isActive = enabled && current === name;
          const inPool = pool.includes(name);
          return (
            <EffectCard
              key={`${name}:${assetVersion}`}
              name={name}
              kind={kind}
              active={isActive}
              inPool={inPool}
              onUse={() => applySelection(name)}
              onTogglePool={() => togglePool(name)}
            />
          );
        })}
      </ul>
    </div>
  );
}

function EffectCard({ name, kind, active, inPool, onUse, onTogglePool }: {
  name: string;
  kind: "effect" | "transition";
  active: boolean;
  inPool: boolean;
  onUse: () => void;
  onTogglePool: () => void;
}) {
  const [staticUrl, setStaticUrl] = useState<string | null>(null);
  const [frames, setFrames] = useState<string[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [frameError, setFrameError] = useState("");
  const [frameIndex, setFrameIndex] = useState(0);
  const [hover, setHover] = useState(false);
  const [visible, setVisible] = useState(false);
  const cardRef = useRef<HTMLLIElement>(null);
  const requestedStaticRef = useRef(false);
  const requestedFramesRef = useRef("");

  useEffect(() => {
    const element = cardRef.current;
    if (!element) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) setVisible(true);
      },
      { rootMargin: "120px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // 可见即加载静态代表帧（前端 LRU + 引擎磁盘缓存）
  useEffect(() => {
    if (!visible || staticUrl || requestedStaticRef.current) return;
    requestedStaticRef.current = true;
    const cacheKey = `${kind}:${name}`;
    const cached = cacheGet(STATIC_CACHE, cacheKey);
    if (cached) {
      setStaticUrl(cached);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const assets = await engine.call<{ source_a: string; source_b: string }>("effect_library_assets", {}, 15_000);
        const config = buildPreviewConfig(kind, name);
        const frame = await engine.call<{ preview_path: string }>("preview_effect_frame", {
          path: assets.source_a,
          next_path: kind === "transition" ? assets.source_b : "",
          config,
          time_sec: 0.4,
          max_width: 192,
          max_height: 108,
        }, 30_000);
        if (!cancelled) {
          const url = engine.toAssetUrl(frame.preview_path);
          cacheSet(STATIC_CACHE, cacheKey, url);
          setStaticUrl(url);
        }
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => { cancelled = true; };
  }, [kind, name, staticUrl, visible]);

  // 悬停时才请求完整动画帧
  useEffect(() => {
    if (!hover || frames || requestedFramesRef.current) return;
    const key = `${kind}:${name}`;
    requestedFramesRef.current = key;
    const cached = cacheGet(ANIMATION_CACHE, key);
    if (cached) {
      setFrames(cached);
      return;
    }
    let cancelled = false;
    void engine.call<{ frames: string[] }>("effect_preview_animation", { kind, name, frames: ANIMATION_FRAMES }, 60_000)
      .then((result) => {
        if (cancelled) return;
        const urls = result.frames.map((path) => engine.toAssetUrl(path));
        cacheSet(ANIMATION_CACHE, key, urls);
        setFrames(urls);
      })
      .catch((requestError) => {
        if (!cancelled) setFrameError(requestError instanceof Error ? requestError.message : "动画加载失败");
      });
    return () => { cancelled = true; };
  }, [frames, hover, kind, name]);

  useEffect(() => {
    if (!hover || !frames?.length) return;
    setFrameIndex(0);
    const timer = window.setInterval(() => {
      setFrameIndex((index) => (index + 1) % frames.length);
    }, 90);
    return () => window.clearInterval(timer);
  }, [frames, hover]);

  useEffect(() => {
    if (!hover) {
      setFrameIndex(0);
    }
  }, [hover]);

  const frameUrl = frames && frames.length ? frames[frameIndex % frames.length] : staticUrl;

  return (
    <li
      ref={cardRef}
      className={`effect-card${active ? " is-active" : ""}${inPool ? " is-in-pool" : ""}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      title={hover ? `正在播放${kind === "effect" ? "特效" : "转场"}动画预览` : name}
    >
      <span className="effect-preview">
        {frameUrl ? <img src={frameUrl} alt={`${name} 预览`} /> : (
          <span className="effect-preview-placeholder">
            {failed ? "预览失败" : <Loader2 className="is-spinning" size={16} />}
          </span>
        )}
        {hover && frameUrl ? <span className="effect-preview-playing" aria-hidden="true" /> : null}
        {hover && frameError ? <span className="effect-frame-count">{frameError}</span> : null}
      </span>
      <span className="effect-card-name" title={name}>{name}</span>
      <span className="effect-card-badges">
        {active ? <span className="effect-badge is-active">当前{kind === "effect" ? "特效" : "转场"}</span> : null}
        {inPool ? <span className="effect-badge is-pool">随机池</span> : null}
      </span>
      <span className="effect-card-actions">
        <button type="button" className={`quiet-button${active ? " is-active" : ""}`} onClick={onUse}>
          <Check size={13} />{active ? "已选用" : "选用"}
        </button>
        <button type="button" className={`icon-button${inPool ? " is-in-pool" : ""}`} onClick={onTogglePool} aria-label={inPool ? `把 ${name} 移出随机池` : `把 ${name} 加入随机池`} title={inPool ? "移出随机池" : "加入随机池"}>
          <Plus size={13} />
        </button>
      </span>
    </li>
  );
}

function buildPreviewConfig(kind: "effect" | "transition", name: string): VideoConfig {
  return {
    ...FALLBACK_CONFIG,
    duration: 1,
    fps: 30,
    resolution_preset: "192x108",
    use_transition: kind === "transition",
    transition_type: kind === "transition" ? name : "淡入淡出",
    random_transition: false,
    use_video_effect: kind === "effect",
    video_effect_type: kind === "effect" ? name : "无特效",
    random_video_effect: false,
    use_watermark: false,
    use_image_watermark: false,
    use_bgm: false,
  };
}
