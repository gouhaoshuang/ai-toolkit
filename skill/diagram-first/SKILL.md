---
name: diagram-first
description: >-
  Use this skill when the user asks to create or iterate on technical principle diagrams,
  system/agent architecture comparisons, algorithm data-flow visuals, or code-backed explainers
  (e.g., "画图", "画原理图", "架构对比图", "可视化", "flowchart", "diagram"). Enforces a
  diagram-first ("图自己说话"), light academic visual style, small-step alignment before heavy
  coding, single-file HTML+SVG rendering with local fonts, and an optional restrained
  click-to-inspect source-code drawer after the static diagram is approved.
---

# Diagram-First: “图自己说话” 的静态原理图工作流

本 Skill 专注产出**高质量静态技术原理图 + 可选克制源码抽屉**。核心原则：**图形拓扑与具象微图承载逻辑，文字只做短标签，小步快跑频繁对齐，绝不先堆暗黑文字墙或花哨动画。**

---

## 一、强制四步流程（禁止跳步一把梭）

### Gate 0：先问“到底值不值得画图”
- 如果需求本质只是**参数表、概念名词解释、线性清单**，直接用 Markdown 表格或要点讲清楚，主动劝退画图，**绝不为了交差硬拼“文字卡片 HTML”**。
- 只有存在**空间拓扑、时间/状态流转、多方案结构差异、或数学映射直觉痛点**时，才进入 Step 1。

### Step 1：1 分钟结构对齐（先不写代码）
在写任何 HTML/SVG 之前，用 **5–8 行短文字** 与用户对齐 3 件事：
1. **核心直觉痛点**：这张图最想让人一眼看穿的 1–2 个“啊哈”瞬间是什么？
2. **视觉拓扑形态**：用哪种空间结构最直观？（例如：多行同列纵向泳道对比 / 左右双轨时间轴 / 坐标曲线与阈值翻转 / 状态闭环）
3. **共享具体锚点案例**：全图统一跑哪一个具体样例？（如“点击 Save 按钮 @ `1080×2400`，目标点 `(500, 820)` / 标号 `#12`”，拒绝抽象占位符）

> 若用户明确要求“直接出 v1 草图”，则将上述 3 点压缩为 3 行摘要，随 v1 截图一并交付。

### Step 2：极速静态草图 v1 → 截图自检 → 快速迭代
1. **参考黄金范例与原语**：
   - 视觉标杆：[examples/gold_standard_agents.html](./examples/gold_standard_agents.html)
   - 可复用 SVG 微图形原语：[references/visual_primitives.md](./references/visual_primitives.md)
   - 反面清单与验收标准：[references/anti_patterns.md](./references/anti_patterns.md)
2. **编写单文件自包含 HTML + 内联 SVG**：
   - 纯静态、零外部依赖、**严禁外链 CDN 字体**（Google Fonts 等易在离线/受限环境白屏），统一使用本地系统字体栈：
     `"Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", -apple-system, sans-serif`
   - 默认只画静态图，**禁止在草图阶段添加粒子动画、流光连线、霓虹发光或复杂交互**。
3. **一条命令渲染 PNG 并视觉验收**：
   ```bash
   bash /data/ghs/services/ai-toolkit/skill/diagram-first/scripts/render_png.sh <diagram.html> [diagram.png]
   ```
   - 立刻用读图工具查看生成的 PNG，按 [references/anti_patterns.md](./references/anti_patterns.md) 的 **4 项截图自检表**核对有无重叠、裁切、文字过密或差异不显形。
   - 若有硬伤（重叠/裁切），当轮修好再交付；否则直接发图给用户，并**主动指出 1–2 个你认为最值得继续打磨的视觉点**。

### Step 3：静态图过关后，按需加“克制源码抽屉”（可选）
- 只有当用户明确认可静态图形本身后，才询问或按需升级为**带源码抽屉的交互版 HTML**。
- 严格遵守 [references/source_drawer_pattern.md](./references/source_drawer_pattern.md)：
  - 主画布 100% 保持原貌，**不在图面上贴按钮、角标或代码预览框**；
  - 仅在可点击模块上加极轻悬停高亮 + 画布底部一行安静提示；
  - 点击模块从右侧滑出浅色源码抽屉，展示 **≤15 行真实源码 + 文件路径与行号 + 1 句人话解读**。

---

## 二、视觉语法 5 条硬红线

1. **浅色出版级纸面感**：纯白画布卡片（`#FFFFFF`）配浅灰衬底（`#F6F7F9`），中性灰骨架（`#CBD5E1` / `#64748B` / `#0F172A`），全图**至多 2 个低饱和强调色**：
   - 主焦点色：深红 `#BE123C`（配浅粉底 `#FFF1F2`），专标核心计算 / 模型调用 / 关键翻转；
   - 辅助差异色：克制蓝 `#2563EB`（配浅蓝底 `#EFF6FF`），专标关键结构差异 / 输入与记忆机制；
   - 仅在必要语义（如“通过/绿框”或“反馈回路”）点缀极小面积 `#059669` 或 `#D97706`，禁用深色暗黑后台风与渐变霓虹。
2. **文字减脂 70%**：图内只放短标签（尽量 ≤10 字）、真实数值、缩略字段与具体微型样例；超过 15 字的解释全部留在对话正文。
3. **具象 > 抽象**：绝不用“历史折为文本”“决策输出”这类空洞抽象框应付；必须画成一眼能懂的具象微图（如 `Step 1: 打开录音机`、`[×][×][图7]`、缩略 JSON/XML 块、真实数值刻度）。
4. **差异必须显形**：多方案对比时，若方案差异在输入窗口、输出结构或执行路径，**图形拓扑本身必须长得不一样**，绝不能把不同机制画成外观雷同的方块与横线。
5. **代码与数值 100% 溯源**：凡涉及代码架构、算法公式、超参数或样例数值，必须直接核对真实源码或既定规格，禁止凭印象编造字段名和数字。

---

## 三、提速与工程纪律

- **减少串行工具回合**：写完 HTML 后尽量紧接着跑 `render_png.sh`，不要把“写文件 → 查路径 → 截图 → 再看图”拆成过多低效串行步骤。
- **单 Agent 小步迭代**：在静态草图未对齐前，**禁止并行起多个子 Agent 盲跑多套重型渲染方案**。
- **保持上下文清爽**：多轮迭代时只看最新一版 PNG，不要反复重复读取历史旧图。
