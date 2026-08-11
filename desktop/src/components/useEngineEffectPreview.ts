import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { engine } from "../engine";
import type { PreviewFrame, Workspace } from "../types";
import { isEffectEnabled } from "./previewEffects";

type EffectPreviewResponse = {
  preview_path: string;
  width: number;
  height: number;
  effect_type: string;
  transition_type: string;
};

type PreviewRequest = {
  key: string;
  path: string;
  nextPath: string;
  config: Workspace["config"];
  timeSec: number;
};

export function useEngineEffectPreview(
  workspace: Workspace,
  frame: PreviewFrame | null | undefined,
  time: number,
  active = true,
  nextFrame?: PreviewFrame | null,
) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [effectType, setEffectType] = useState("");
  const [transitionType, setTransitionType] = useState("");
  const pendingRef = useRef<PreviewRequest | null>(null);
  const runningRef = useRef(false);
  const mountedRef = useRef(true);
  const latestKeyRef = useRef("");

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const pump = useCallback(async () => {
    if (runningRef.current) return;
    runningRef.current = true;
    while (mountedRef.current && pendingRef.current) {
      const request = pendingRef.current;
      pendingRef.current = null;
      if (latestKeyRef.current === request.key) setLoading(true);
      try {
        const result = await engine.call<EffectPreviewResponse>(
          "preview_effect_frame",
          {
            path: request.path,
            next_path: request.nextPath,
            config: request.config,
            time_sec: request.timeSec,
            max_width: 960,
            max_height: 540,
          },
          30_000,
        );
        if (mountedRef.current && latestKeyRef.current === request.key) {
          setUrl(engine.toAssetUrl(result.preview_path));
          setEffectType(result.effect_type);
          setTransitionType(result.transition_type);
        }
      } catch {
        if (mountedRef.current && latestKeyRef.current === request.key) {
          setUrl(null);
          setEffectType("");
          setTransitionType("");
        }
      }
    }
    runningRef.current = false;
    if (mountedRef.current) setLoading(false);
  }, []);

  const identity = useMemo(() => JSON.stringify({
    source: frame?.source ?? "",
    nextSource: nextFrame?.source ?? "",
    config: workspace.config,
  }), [
    frame?.source,
    nextFrame?.source,
    workspace.config,
  ]);

  useEffect(() => {
    setUrl(null);
    setEffectType("");
    setTransitionType("");
  }, [identity]);

  useEffect(() => {
    const hasImageWatermark = Boolean(
      workspace.config.use_image_watermark
      && workspace.config.watermark_layers.some((layer) => layer.enabled && layer.path),
    );
    const hasVideoWatermark = Boolean(workspace.config.use_watermark && workspace.config.watermark_path);
    const hasTransition = Boolean(workspace.config.use_transition && nextFrame?.source);
    if (!active || !frame?.source || (!isEffectEnabled(workspace.config) && !hasImageWatermark && !hasVideoWatermark && !hasTransition)) {
      latestKeyRef.current = "";
      pendingRef.current = null;
      setUrl(null);
      setLoading(false);
      setEffectType("");
      setTransitionType("");
      return;
    }
    const duration = Math.max(0.1, Number(workspace.config.duration) || 0.1);
    const localTime = Number((((time % duration) + duration) % duration).toFixed(3));
    const key = `${identity}:${localTime}`;
    latestKeyRef.current = key;
    pendingRef.current = {
      key,
      path: frame.source,
      nextPath: nextFrame?.source ?? "",
      config: workspace.config,
      timeSec: localTime,
    };
    void pump();
  }, [active, frame?.source, identity, nextFrame?.source, pump, time, workspace.config]);

  return { url, loading, effectType, transitionType };
}
