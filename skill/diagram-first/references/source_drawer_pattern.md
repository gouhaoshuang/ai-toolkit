# 可选阶段：克制源码抽屉模式（Restrained Source Drawer）

**启用前提**：仅当静态原理图本身已被用户认可，且用户希望“点击图上模块对照真实源码”时才启用。

---

## 设计铁律（绝不污染主画布）

1. **主画布 100% 视觉无新增噪音**：
   - 禁止在 SVG 节点上贴 `</> 查看代码` 按钮、悬浮角标、红点提示或微型代码框。
   - 仅在整张图的底部边缘放一行极淡提示（`11px`，`#94A3B8`）：`提示：点击图中任意核心模块，可在右侧对照对应源码`。
2. **极轻悬停反馈**：
   - 可点击的 `<g class="inspectable" data-snippet="key">` 仅设置 `cursor: pointer;`；
   - 悬停时仅轻微加深外框描边或加极淡阴影（`filter: drop-shadow(0 2px 6px rgba(15,23,42,0.08))`），不做弹跳放大动画。
3. **浅色右侧滑出抽屉**：
   - 宽度 `420px–460px`，纯白背景 `#FFFFFF`，左边框 `1px solid #E2E8F0`，轻量阴影；
   - 顶部显示：模块名 + 真实文件路径与行号（等宽浅灰胶囊，如 `core_algos.py:L199-L216`）+ 关闭按钮 `×`（同时支持按 `Esc` 或点击遮罩关闭）；
   - 正文结构固定为 2 块，保持极短：
     1. **1 句话直觉对应**（说明这段代码对应图中哪一个视觉变化）；
     2. **≤15 行真实源码片段**（浅灰代码底 `#F8FAFC`，`12.5px` 等宽字体，关键 1–2 行用 `#FFF1F2` 或 `#EFF6FF` 浅色底高亮）。

---

## 极简实现骨架

```html
<style>
  .inspectable { cursor: pointer; transition: opacity 0.15s ease, filter 0.15s ease; }
  .inspectable:hover { filter: drop-shadow(0 2px 6px rgba(15, 23, 42, 0.10)); }
  .inspectable.active rect:first-of-type { stroke-width: 2.2; }

  .drawer-backdrop {
    position: fixed; inset: 0; background: rgba(15, 23, 42, 0.16);
    opacity: 0; pointer-events: none; transition: opacity 0.18s ease; z-index: 40;
  }
  .drawer-backdrop.open { opacity: 1; pointer-events: auto; }

  .source-drawer {
    position: fixed; top: 0; right: 0; height: 100vh; width: 440px; max-width: 92vw;
    background: #FFFFFF; border-left: 1px solid #E2E8F0;
    box-shadow: -8px 0 28px rgba(15, 23, 42, 0.08);
    transform: translateX(100%); transition: transform 0.2s ease;
    z-index: 50; display: flex; flex-direction: column; padding: 22px 24px;
  }
  .source-drawer.open { transform: translateX(0); }
  .drawer-path {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12px; color: #475569; background: #F1F5F9;
    padding: 4px 8px; border-radius: 6px; display: inline-block; margin: 8px 0 12px;
  }
  .drawer-code {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12.5px; line-height: 1.55; color: #0F172A;
    background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px;
    padding: 14px 16px; overflow: auto; white-space: pre;
  }
</style>
```

> **源码纪律**：`SNIPPETS` 字典中的所有代码必须逐行摘自真实文件并标注精确行号，禁止改写或臆造伪代码充当源码。
