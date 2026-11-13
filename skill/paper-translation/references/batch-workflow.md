# 批量清单与复用流程

清单保存在论文输出目录，不保存在 skill 仓库。`source_pdf` 使用实际文件路径。`main_end_page`、图号和裁切位置由 Codex 对照原页核实；坐标归一化为 `[x0, y0, x1, y1]`，原点在左上角。

```json
{
  "output_root": "/work/translations",
  "appendix": false,
  "papers": [{
    "slug": "paper-name",
    "title": "Original paper title",
    "source_pdf": "/work/original.pdf",
    "main_end_page": 8,
    "single_column": false,
    "references_start_page": 8,
    "references_end_page": 10,
    "max_pages_per_part": 3,
    "figures": [{
      "number": 1,
      "page": 2,
      "rect_normalized": [0.1, 0.08, 0.9, 0.35],
      "path": "medias/figure-01.png"
    }]
  }],
  "generation": {"model": "gemini-4-argon", "workers": 2, "max_tokens": 32768, "timeout": 900}
}
```

## 准备

```bash
python scripts/paper_bundle.py prepare /work/translations/batch-manifest.json
```

提取全文与逐页文本，复制源 PDF，为每幅图导出裁图，并生成正文 PDF、分段 PDF、提示词和哈希清单。正文最后一页若含 `References`，将该标题及其后的同栏内容遮除；参考文献从左栏开始时，同时遮除右栏。使用前检查这一处理是否适合原稿，尤其是跨栏和单栏排版。`references_heading` 可显式指定原 PDF 点坐标，避免自动检测歧义；坐标仅用于 `references_heading_page`（默认 `references_start_page`，未指定则为正文末页）与正文末页相同的情况。

普通重复执行跳过已准备的论文；不通过重复准备覆盖已有输入。范围或裁图需要修改时，先确认旧响应是否依赖旧输入，保留历史记录，准备新的分段。

注意正文图表可能浮动到参考文献已开始的后续页面。应继续盘点直到附录边界，而不是看到 References 就结束；例如正文表 7 可以出现在第 10 页参考文献之前。此时延长 `main_end_page`，通过 `body_bottom_points`（页码字符串到 PDF 点坐标的映射）遮除每页参考文献，保留浮动表格。单栏稿件设置 `single_column: true`，避免删除参考文献上方正文的右半边。

参考文献按 `references_start_page` / `references_end_page` 提取英文原文。`reference_page_min_y` 可排除参考文献续页上方的浮动表格；若最后一页仅左栏属于参考文献，设置 `references_last_left_only: true`。这些边界必须对照原页确认。未登记参考文献范围时，脚本不猜测。

## 可选 Gemini 生成

仅在用户已授权后：

```bash
python scripts/paper_bundle.py generate /work/translations/batch-manifest.json \
  --client /path/to/ai-toolkit/skill/aistudio2api/scripts/client.py --authorized
```

复用客户端的 `load_key` 与 `request_json`，保持其本机接口、私有凭证权限和禁止重定向约束。传送的是分段 PDF 文件内容，图片和复杂表格可被模型实际查看。响应持久化在每篇 `source/parts/` 中，不把本地文件路径当成已上传材料。

`--client` 指向本地已配置的 Python 客户端，须提供 `load_key()` 与 `request_json(path, key, body, timeout)`，后者返回 `(response_dict, http_status, elapsed_seconds)`，并对 HTTP 错误抛出异常。客户端应禁止在日志中输出凭证。该文件及服务凭证不是本 skill 的内置依赖；不用外部模型时不需要它。

默认请求不自动重试，成功段按哈希跳过。`--only paper-name` 可限制论文，`--part 2` 可限制单段。失败原因核实后可用 `--retry-failed` 显式补试一次；超时不代表上游未执行。

## 合并与检查

```bash
python scripts/paper_bundle.py assemble /work/translations/batch-manifest.json
python scripts/paper_bundle.py validate /work/translations/batch-manifest.json
```

合并稿保留 source-page HTML 注释，供检查连续覆盖但不干扰阅读。表编号、公式和作者信息仍需人工复核。`source/validation.json` 会列出具体问题，不擅自修正模型漏译。

逐个检查 source-page 两侧的句子。脚注、跨页的代码词、算法和多层子表可能打断正文，不能仅按标点自动拼接。合并脚本只处理有限的简单浮动图表，复杂情形需要对照原页调整顺序。

完成 Codex 复核后，在 `review-notes.md` 记录实际视觉检查、数值核对和语义复核范围，再更新批次索引。保留接口原始响应，人工修正只改交付译文并记录修订，不覆盖原响应。最终稿复核后不要再次执行 `assemble` 覆盖人工修订。

同版本 LaTeX 的小数值覆盖检查：

```bash
python scripts/audit_latex_tables.py --tex /work/source/experiments.tex \
  --markdown /work/translations/paper-name/paper-name_zh.md \
  --output /work/translations/paper-name/source/table-decimal-audit.json
```

多个正文源文件可重复 `--tex`。这项检查保留负号、忽略正号，排除 TeX 注释中的旧结果；仍需人工确认行列对应关系和整数。

离线脚本验收（不访问模型、不读取凭证）：

```bash
python -m unittest discover -s scripts -p 'test_*.py' -v
```
