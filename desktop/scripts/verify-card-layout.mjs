// 验证素材卡片操作行：4 个图标按钮必须排成一行（真实浏览器布局检查）
// 用法：node scripts/verify-card-layout.mjs
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const puppeteer = require("puppeteer-core");
const root = join(dirname(fileURLToPath(import.meta.url)), "..");

// 从 App.css 提取本次相关规则（含修复）
const css = readFileSync(join(root, "src", "App.css"), "utf-8");
const grab = (selector) => {
  const start = css.indexOf(selector);
  if (start < 0) throw new Error(`CSS 规则未找到: ${selector}`);
  const brace = css.indexOf("{", start);
  let depth = 1;
  let end = brace + 1;
  while (depth > 0 && end < css.length) {
    if (css[end] === "{") depth += 1;
    if (css[end] === "}") depth -= 1;
    end += 1;
  }
  return css.slice(start, end);
};
const relevant = [
  ".library-card-actions",
  ".library-card-actions .icon-button",
  ".library-grid",
  ".library-card",
  ".library-card-meta",
  ".icon-button",
].map((s) => grab(s)).join("\n");

const html = `<!doctype html><html><head><meta charset="utf-8"><style>
${relevant}
body { background: #222; }
</style></head><body>
<ul class="library-grid" style="width: 300px">
  <li class="library-card">
    <span class="library-card-meta"><strong title="x">测试水印.mp4</strong><small>128 KB</small></span>
    <span class="library-card-actions">
      <button type="button" class="icon-button"><svg width="14" height="14"></svg></button>
      <button type="button" class="icon-button"><svg width="14" height="14"></svg></button>
      <button type="button" class="icon-button"><svg width="13" height="13"></svg></button>
      <button type="button" class="icon-button"><svg width="14" height="14"></svg></button>
    </span>
  </li>
</ul>
</body></html>`;

const browser = await puppeteer.launch({
  headless: "new",
  executablePath: "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  args: ["--no-sandbox"],
});
try {
  const page = await browser.newPage();
  await page.setContent(html, { waitUntil: "load" });
  const result = await page.evaluate(() => {
    const card = document.querySelector(".library-card");
    const actions = document.querySelector(".library-card-actions");
    const buttons = Array.from(document.querySelectorAll(".library-card-actions button"));
    const rects = buttons.map((b) => b.getBoundingClientRect());
    const actionRect = actions.getBoundingClientRect();
    return {
      cardWidth: Math.round(card.getBoundingClientRect().width),
      actionRowHeight: Math.round(actionRect.height),
      count: buttons.length,
      tops: rects.map((r) => Math.round(r.top)),
      rightEdge: Math.round(Math.max(...rects.map((r) => r.right))),
      rowRight: Math.round(actionRect.right),
      widths: rects.map((r) => Math.round(r.width)),
    };
  });
  console.log(JSON.stringify(result, null, 2));
  const sameRow = result.tops.every((top) => Math.abs(top - result.tops[0]) <= 1);
  const fits = result.rightEdge <= result.rowRight + 1;
  const singleLine = result.actionRowHeight <= 26;
  if (result.count !== 4 || !sameRow || !fits || !singleLine) {
    console.error("FAIL: 4 个按钮未能在同一行放下");
    process.exit(1);
  }
  console.log(`PASS: ${result.count} 个图标按钮同一行（行高 ${result.actionRowHeight}px，宽度 ${result.cardWidth}px 卡片内放得下）`);
} finally {
  await browser.close();
}
