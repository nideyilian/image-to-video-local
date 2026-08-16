import { useEffect, useMemo, useState } from "react";
import { engine } from "../engine";
import type { Workspace } from "../types";

type BgmPreviewResponse = {
  enabled: boolean;
  preview_path?: string;
  name?: string;
  reason?: string;
};

export type BgmPreviewState = {
  status: "off" | "loading" | "ready" | "error";
  url: string | null;
  name: string;
  message: string;
};

const OFF_STATE: BgmPreviewState = { status: "off", url: null, name: "", message: "BGM 已关闭" };

export function useBgmPreview(workspace: Workspace, previewSequence = 0): BgmPreviewState {
  const [state, setState] = useState<BgmPreviewState>(OFF_STATE);
  const bgmFiles = workspace.config.bgm_files ?? [];
  const identity = useMemo(() => JSON.stringify({
    enabled: workspace.config.use_bgm,
    directory: workspace.config.bgm_dir,
    files: bgmFiles,
    random: workspace.config.random_bgm,
    strategy: workspace.config.watermark_audio,
    previewSequence,
  }), [
    workspace.config.bgm_dir,
    workspace.config.bgm_files,
    workspace.config.random_bgm,
    workspace.config.use_bgm,
    workspace.config.watermark_audio,
    previewSequence,
  ]);
  const requestConfig = useMemo(() => workspace.config, [identity]);

  useEffect(() => {
    if (!workspace.config.use_bgm) {
      setState(OFF_STATE);
      return;
    }
    if (!["使用BGM", "两者混合"].includes(workspace.config.watermark_audio)) {
      setState({ status: "off", url: null, name: "", message: `声音策略：${workspace.config.watermark_audio}` });
      return;
    }
    const hasExplicitBgm = bgmFiles.some((path) => path.trim().length > 0);
    if (!hasExplicitBgm && !workspace.config.bgm_dir.trim()) {
      setState({ status: "error", url: null, name: "", message: "请在素材库选择 BGM，或设置音频目录" });
      return;
    }
    if (!engine.desktopRuntime) {
      setState({ status: "off", url: null, name: "", message: "桌面版可播放 BGM" });
      return;
    }

    let cancelled = false;
    setState({ status: "loading", url: null, name: "", message: "正在读取 BGM" });
    const timer = window.setTimeout(() => {
      void engine.call<BgmPreviewResponse>("preview_bgm", {
        config: requestConfig,
        preview_sequence: previewSequence,
      }, 130_000).then((result) => {
        if (cancelled) return;
        if (!result.enabled || !result.preview_path) {
          setState({ status: "off", url: null, name: "", message: result.reason || "BGM 未启用" });
          return;
        }
        setState({
          status: "ready",
          url: engine.toAssetUrl(result.preview_path),
          name: result.name || "BGM",
          message: "BGM 已同步",
        });
      }).catch((error) => {
        if (cancelled) return;
        setState({
          status: "error",
          url: null,
          name: "",
          message: error instanceof Error ? error.message : "BGM 读取失败",
        });
      });
    }, 280);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [identity, previewSequence, requestConfig]);

  return state;
}
