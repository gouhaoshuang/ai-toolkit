# 视频链接摄取与动态关键帧（YouTube / Bilibili）

当用户输入 YouTube 或 Bilibili 视频链接时，使用 `scripts/video_ingest.py` 将视频转成可供 `course_notes.py` 消费的标准素材目录。视频产物一律写入用户指定的课程工作目录，不写入本 skill 仓库。

## 运行环境

统一使用本地 `agent` conda 环境（Python 3.11 + 最新版 `yt-dlp` + `faster-whisper` + `opencv` + 系统 `ffmpeg`）：

```bash
/data/ghs/miniconda3/envs/agent/bin/python scripts/video_ingest.py --help
```

更新 `yt-dlp`（避免系统 apt 老旧源）：

```bash
/data/ghs/miniconda3/envs/agent/bin/pip install -U "yt-dlp[default]"
```

## 1. 拉取元信息与逐字稿（`fetch`）

```bash
/data/ghs/miniconda3/envs/agent/bin/python scripts/video_ingest.py fetch \
  "https://www.youtube.com/watch?v=..." \
  --out /work/course/sources/video
```

行为规则：
- **字幕优先**：优先下载人工字幕，其次原语言自动字幕（不选用平台机器翻译字幕）。可用 `--no-auto-subs` 或 `--force-asr` 强制走本地转写。
- **本地 GPU ASR 兜底**：无可用字幕时只下载音频流，默认使用 `faster-whisper` 的 `large-v3-turbo`（FP16 + VAD，中英双语口碑与速度最佳平衡）。
- **空闲 GPU 自动选择与占满停机**：通过 `nvidia-smi` 自动选空闲显存最多且 ≥ `6144 MiB`（`--min-free-vram-mb`）的卡；若全部 GPU 已占满，脚本以退出码 `3` 中止并打印各卡占用，不强行挤占，也不静默降级 CPU——此时应停下来向用户反馈。
- **产物**：
  - `meta.json`：标题、时长、章节 `chapters`、简介与提取出的外链、字幕来源与 GPU 信息。
  - `transcript_raw.txt`：纯文本逐字稿（直接对接 `course.json`）。
  - `transcript_timed.jsonl`：与 `transcript_raw.txt` 逐行 1:1 对应的 `[start, end]` 时间戳索引。
  - `transcript_timed.txt`：便于审阅的 `[MM:SS] 文本`。

## 2. 按需动态抽帧（`frames`）

不是每个视频都需要抽帧。Agent 阅读 `meta.json` 和逐字稿后动态判断：
- **建议触发**：没有原始 PDF/PPT，且讲师高频口述“看图 / 屏幕上的公式 / 架构图 / 表格对比 / 代码界面 / PPT 这里”。
- **无需触发**：播客、访谈、纯口播，或已拿到完整 PDF 课件与源码。

按需运行（支持 `--line-ranges` 或 `--ranges` 只抽取需要看画面的片段）：

```bash
/data/ghs/miniconda3/envs/agent/bin/python scripts/video_ingest.py frames \
  /work/course/sources/video \
  --line-ranges 1-80,140-220 \
  --max-frames 20
```

产出 `frames/frame_*.png` 和 `frames/manifest.json`（含 `timestamp` 与最近逐字稿行号 `line`），可直接按分段行号归类挂载到 `course.json` 的 `parts[i].files`。

## 3. 代理与 Cookies 约定

- **代理**：YouTube 等海外站点默认继承终端环境变量（`HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`）；Bilibili 默认直连（自动传 `--proxy ""` 绕过海外代理以免超时），若确实需要代理可显式传 `--proxy`。
- **Cookies**：绝不写入仓库或课程目录。默认无 cookies 运行；若遇到需要登录态的视频（脚本以退出码 `2` 报错），提示用户将 Netscape 格式的 cookies 放到本机私有目录：
  - `~/.config/gemini-course-notes/youtube.txt`（YouTube 专用）
  - `~/.config/gemini-course-notes/bilibili.txt`（B 站专用）
  - `~/.config/gemini-course-notes/cookies.txt`（通用兜底）

  检测到非空文件后自动加载，不打印内容。
