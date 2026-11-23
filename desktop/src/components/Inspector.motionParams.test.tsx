/**
 * 「随机特效」模式下，专属参数控件必须禁用。
 *
 * ## 为什么
 *
 * 专属参数是按**当前特效 id** 存取的（`effect_params[特效id][参数名]`）。
 * 随机模式下配置里那个 `video_effect_type` 根本不参与渲染 —— 抽中的是池里
 * 任意一个。控件还能拖，就是在骗人：拖了半天画面不变，用户判定「功能坏了」。
 *
 * 「当前特效」下拉早就 `disabled={effectMode !== "fixed"}`，但参数控件当时只判
 * `effectMode === "off"`，两处不一致。这里把两者钉在一起。
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FALLBACK_CONFIG } from "../constants";
import type { EffectParamSchema } from "../types";
import { Inspector } from "./Inspector";

let mountedRoot: Root | null = null;
let container: HTMLDivElement | null = null;

/** 「故障抖动」带一个专属参数，用来观察控件是否被禁用。 */
const paramSchema: EffectParamSchema = {
  故障抖动: [
    {
      key: "glitch_amount",
      label: "错位幅度",
      kind: "percent",
      min: 0,
      max: 200,
      default: 50,
      choices: [],
      value: 50,
    },
  ],
};

function renderInspector(overrides: Partial<typeof FALLBACK_CONFIG>) {
  container = document.createElement("div");
  document.body.appendChild(container);
  mountedRoot = createRoot(container);
  act(() => {
    mountedRoot!.render(
      <Inspector
        config={{ ...FALLBACK_CONFIG, use_video_effect: true, video_effect_type: "故障抖动", ...overrides }}
        onChange={vi.fn()}
        onBrowseDirectory={vi.fn()}
        onBrowseFile={vi.fn()}
        activeTab="motion"
        onActiveTabChange={vi.fn()}
        validationIssues={[]}
        onOpenLibraryTab={vi.fn()}
        subfolderScan={null}
        paramSchema={paramSchema}
        onParamChange={vi.fn()}
      />,
    );
  });
  return container;
}

/** 参数控件的 input：包在 label 文本含「错位幅度」的那个 Field 里。 */
function paramInput(host: HTMLDivElement) {
  const field = [...host.querySelectorAll("label")].find((node) =>
    node.textContent?.includes("错位幅度"),
  );
  expect(field, "找不到「错位幅度」这个参数控件 —— schema 没被用上？").toBeTruthy();
  const input = field!.querySelector("input");
  expect(input, "参数控件里应该有 input").toBeTruthy();
  return input!;
}

afterEach(() => {
  act(() => mountedRoot?.unmount());
  mountedRoot = null;
  container?.remove();
  container = null;
});

describe("随机特效模式下的专属参数", () => {
  it("固定模式下可拖动", () => {
    const host = renderInspector({ random_video_effect: false });
    expect(paramInput(host).disabled).toBe(false);
  });

  it("随机模式下禁用（那个 id 不参与渲染，拖了也不生效）", () => {
    const host = renderInspector({ random_video_effect: true });
    expect(paramInput(host).disabled).toBe(true);
  });

  it("关闭特效时也禁用", () => {
    const host = renderInspector({ use_video_effect: false });
    expect(paramInput(host).disabled).toBe(true);
  });
});
