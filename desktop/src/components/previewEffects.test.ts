import { describe, expect, it } from "vitest";
import { VIDEO_EFFECTS } from "../constants";
import { EFFECT_PRESETS } from "../components/previewEffects";

/**
 * 演示模式（没有后端预览）时，画面动效完全由 `EFFECT_PRESETS` 决定。
 * 表里缺一项不会报错，会静默落到 `{ motion: "breathe" }` 兜底 ——
 * 表现就是「选了个抖动特效，预览却在缓慢呼吸」。
 *
 * 2026-11-20 新增「色差分离 / 色调分离 / 半调网点」时就漏了这一处。
 * 这条测试把「下拉里的每个特效都有动效声明」钉死。
 */
describe("EFFECT_PRESETS 覆盖所有特效", () => {
  it("VIDEO_EFFECTS 里的每一个都有动效声明", () => {
    const missing = VIDEO_EFFECTS.filter((name) => !(name in EFFECT_PRESETS));
    expect(missing).toEqual([]);
  });

  it("没有多余的、界面选不到的条目（别名除外）", () => {
    const extra = Object.keys(EFFECT_PRESETS).filter(
      (name) => !VIDEO_EFFECTS.includes(name) && name !== "心跳跃动",
    );
    expect(extra).toEqual([]);
  });
});
