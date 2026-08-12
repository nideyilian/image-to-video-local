import {
  availableMonitors,
  getCurrentWindow,
  PhysicalPosition,
  PhysicalSize,
  primaryMonitor,
} from "@tauri-apps/api/window";

const WINDOW_STATE_KEY = "image-to-video.window.v1";

// 与 src-tauri/tauri.conf.json 中窗口的 minWidth / minHeight 保持一致（逻辑像素）。
const MIN_WIDTH = 1120;
const MIN_HEIGHT = 700;

type WindowState = {
  width: number;
  height: number;
  x: number;
  y: number;
};

function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

function clampToMinimum(width: number, height: number): { width: number; height: number } {
  const scale = window.devicePixelRatio || 1;
  return {
    width: Math.max(width, Math.round(MIN_WIDTH * scale)),
    height: Math.max(height, Math.round(MIN_HEIGHT * scale)),
  };
}

async function isOnScreen(x: number, y: number): Promise<boolean> {
  try {
    const monitors = await availableMonitors();
    const primary = await primaryMonitor();
    const all = primary ? [primary, ...monitors] : monitors;
    return all.some((monitor) => {
      const position = monitor.position;
      const size = monitor.size;
      return x >= position.x && y >= position.y && x < position.x + size.width && y < position.y + size.height;
    });
  } catch {
    return false;
  }
}

export async function restoreWindowState(): Promise<void> {
  if (!isTauriRuntime()) return;
  const raw = localStorage.getItem(WINDOW_STATE_KEY);
  if (!raw) return;
  try {
    const saved = JSON.parse(raw) as Partial<WindowState>;
    if (!saved.width || !saved.height) return;
    const win = getCurrentWindow();
    const { width, height } = clampToMinimum(saved.width, saved.height);
    await win.setSize(new PhysicalSize(width, height));
    if (typeof saved.x === "number" && typeof saved.y === "number" && (await isOnScreen(saved.x, saved.y))) {
      await win.setPosition(new PhysicalPosition(saved.x, saved.y));
    }
  } catch {
    /* 恢复失败不影响启动，使用 tauri.conf.json 的默认尺寸 */
  }
}

async function saveWindowState(): Promise<void> {
  if (!isTauriRuntime()) return;
  try {
    const win = getCurrentWindow();
    const size = await win.outerSize();
    const position = await win.outerPosition();
    const state: WindowState = {
      width: Math.round(size.width),
      height: Math.round(size.height),
      x: Math.round(position.x),
      y: Math.round(position.y),
    };
    localStorage.setItem(WINDOW_STATE_KEY, JSON.stringify(state));
  } catch {
    /* 忽略保存失败 */
  }
}

export function setupWindowStatePersistence(): void {
  if (!isTauriRuntime()) return;
  const win = getCurrentWindow();
  const handler = () => void saveWindowState();
  win.onResized(handler).catch(() => {});
  win.onMoved(handler).catch(() => {});
  window.addEventListener("beforeunload", handler);
}
