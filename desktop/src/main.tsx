import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { restoreWindowState, setupWindowStatePersistence } from "./windowState";

// 在 React 渲染前尽早恢复上次关闭时的窗口尺寸，减少启动时的尺寸跳变。
void restoreWindowState().then(() => setupWindowStatePersistence());

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
