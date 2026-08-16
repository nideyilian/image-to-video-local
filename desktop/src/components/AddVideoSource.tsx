import { useEffect, useState, type KeyboardEvent } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { FolderOpen, Upload } from "lucide-react";
import { engine } from "../engine";

const VIDEO_FILTERS = [{ name: "视频文件", extensions: ["mp4", "mov", "avi", "mkv", "flv", "wmv", "webm", "m4v", "ts", "mpg", "mpeg", "3gp"] }];

const VIDEO_EXTS = new Set(["mp4", "mov", "avi", "mkv", "flv", "wmv", "webm", "m4v", "ts", "mpg", "mpeg", "3gp"]);

function isVideoPath(path: string) {
  const suffix = path.split(".").pop()?.toLowerCase() ?? "";
  return VIDEO_EXTS.has(suffix);
}

/** 批量拆 BGM 的统一添加入口：点击选文件、拖拽添加、文件夹选择三合一。 */
export function AddVideoSource({ running, onAddFiles, onSetFolder, notify }: {
  running: boolean;
  onAddFiles: (paths: string[]) => void;
  onSetFolder: (folder: string) => void;
  notify: (kind: "info" | "success" | "error", message: string) => void;
}) {
  const [dragOver, setDragOver] = useState(false);
  const desktopRuntime = engine.desktopRuntime;

  // 窗口级拖放：拖入视频即加入待拆列表（弹窗打开时组件挂载，卸载即清理）
  useEffect(() => {
    if (!desktopRuntime) return;
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    void getCurrentWebview().onDragDropEvent((event) => {
      const payload = event.payload;
      if (payload.type === "drop") {
        setDragOver(false);
        const dropped = payload.paths ?? [];
        const paths = dropped.filter(isVideoPath);
        if (paths.length) {
          onAddFiles(paths);
          notify("success", `已添加 ${paths.length} 个视频文件${paths.length !== dropped.length ? "，已忽略非视频文件" : ""}`);
        } else {
          notify("error", "拖入的文件不是支持的视频格式（mp4 / mov / avi / mkv 等）");
        }
      } else if (payload.type === "leave") {
        setDragOver(false);
      } else {
        setDragOver(true);
      }
    }).then((fn) => {
      if (cancelled) fn();
      else unlisten = fn;
    });
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [desktopRuntime, notify, onAddFiles]);

  const pickFiles = async () => {
    if (!desktopRuntime) return notify("info", "选择文件需要在 Tauri 桌面窗口中运行");
    const picked = await openDialog({ multiple: true, directory: false, title: "选择要拆 BGM 的视频", filters: VIDEO_FILTERS });
    if (picked && picked.length) onAddFiles(picked as string[]);
  };

  const pickFolder = async () => {
    if (!desktopRuntime) return notify("info", "选择文件夹需要在 Tauri 桌面窗口中运行");
    const picked = await openDialog({ directory: true, multiple: false, title: "选择包含视频的文件夹" });
    if (typeof picked === "string") onSetFolder(picked);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      void pickFiles();
    }
  };

  return (
    <div
      className={`add-video-source${dragOver ? " is-drag-over" : ""}${running ? " is-disabled" : ""}`}
      role="button"
      tabIndex={0}
      aria-label="添加视频素材：点击选择文件，拖拽添加，或选择文件夹"
      onClick={() => void pickFiles()}
      onKeyDown={handleKeyDown}
    >
      <span className="add-video-source-icon"><Upload size={18} /></span>
      <span className="add-video-source-copy">
        <strong>{dragOver ? "松开添加视频文件" : "点击选择视频文件，或拖拽视频到此处"}</strong>
        <small>支持 mp4 / mov / avi / mkv / webm 等，可一次选择多个</small>
      </span>
      <button type="button" className="quiet-button" disabled={running} onClick={(event) => { event.stopPropagation(); void pickFolder(); }}>
        <FolderOpen size={13} />选择文件夹
      </button>
    </div>
  );
}
