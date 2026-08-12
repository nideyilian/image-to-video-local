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
  video_watermark_name?: string;
};

type PreviewRequest = {
  identity: string;
  path: string;
  nextPath: string;
  config: Workspace["config"];
  timeSec: number;
  previewSequence: number;
};

export function quantizeEffectPreviewTime(time: number, duration: number, fps: number) {
  const safeDuration = Math.max(0.1, Number(duration) || 0.1);
  const safeFps = Math.max(1, Math.floor(Number(fps) || 1));
  const wrapped = ((Number(time) % safeDuration) + safeDuration) % safeDuration;
  const totalFrames = Math.max(1, Math.floor(safeDuration * safeFps));
  const frameIndex = Math.min(totalFrames - 1, Math.floor(wrapped * safeFps + 1e-7));
  return Number((frameIndex / safeFps).toFixed(6));
}

export function useEngineEffectPreview(
  workspace: Workspace,
  frame: PreviewFrame | null | undefined,
  time: number,
  active = true,
  nextFrame?: PreviewFrame | null,
  previewSequence = 0,
) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [effectType, setEffectType] = useState("");
  const [transitionType, setTransitionType] = useState("");
  const [videoWatermarkName, setVideoWatermarkName] = useState("");
  const pendingRef = useRef<PreviewRequest | null>(null);
  const runningRef = useRef(false);
  const mountedRef = useRef(true);
  const latestIdentityRef = useRef("");

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
      if (latestIdentityRef.current === request.identity) setLoading(true);
      try {
        const result = await engine.call<EffectPreviewResponse>(
          "preview_effect_frame",
          {
            path: request.path,
            next_path: request.nextPath,
            config: request.config,
            time_sec: request.timeSec,
            preview_sequence: request.previewSequence,
            max_width: 640,
            max_height: 360,
          },
          30_000,
        );
        if (mountedRef.current && latestIdentityRef.current === request.identity) {
          setUrl(engine.toAssetUrl(result.preview_path));
          setEffectType(result.effect_type);
          setTransitionType(result.transition_type);
          setVideoWatermarkName(result.video_watermark_name || "");
          setError("");
        }
      } catch (requestError) {
        if (mountedRef.current && latestIdentityRef.current === request.identity) {
          setUrl(null);
          setEffectType("");
          setTransitionType("");
          setVideoWatermarkName("");
          setError(requestError instanceof Error ? requestError.message : "特效预览失败");
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
    previewSequence,
  }), [
    frame?.source,
    nextFrame?.source,
    workspace.config,
    previewSequence,
  ]);

  useEffect(() => {
    setUrl(null);
    setEffectType("");
    setTransitionType("");
    setVideoWatermarkName("");
    setError("");
  }, [identity]);

  useEffect(() => {
    const hasImageWatermark = Boolean(
      workspace.config.use_image_watermark
      && workspace.config.watermark_layers.some((layer) => layer.enabled && layer.path),
    );
    const hasVideoWatermark = Boolean(workspace.config.use_watermark && workspace.config.watermark_path);
    const hasTransition = Boolean(workspace.config.use_transition && nextFrame?.source);
    if (!active || !frame?.source || (!isEffectEnabled(workspace.config) && !hasImageWatermark && !hasVideoWatermark && !hasTransition)) {
      latestIdentityRef.current = "";
      pendingRef.current = null;
      setUrl(null);
      setLoading(false);
      setEffectType("");
      setTransitionType("");
      setVideoWatermarkName("");
      setError("");
      return;
    }
    const duration = Math.max(0.1, Number(workspace.config.duration) || 0.1);
    const localTime = quantizeEffectPreviewTime(time, duration, workspace.config.fps);
    latestIdentityRef.current = identity;
    pendingRef.current = {
      identity,
      path: frame.source,
      nextPath: nextFrame?.source ?? "",
      config: workspace.config,
      timeSec: localTime,
      previewSequence,
    };
    void pump();
  }, [active, frame?.source, identity, nextFrame?.source, previewSequence, pump, time, workspace.config]);

  return { url, loading, error, effectType, transitionType, videoWatermarkName };
}
