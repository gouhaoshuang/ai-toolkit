# 本地调用器与课程配置

调用器使用 Python 3.9+ 标准库，不需要安装 OpenAI SDK 或其他运行依赖。

## 当前实例约定

截至 2026-11-05，已使用的服务为 AIStudio2API：

- OpenAI 兼容地址：`http://127.0.0.1:2048/v1`
- 模型：`gemini-4-argon`
- 代理密钥：`/data/ghs/services/aistudio2api/data/.env` 的 `PROXY_API_KEY`
- 容器：`aistudio2api`，容器内配置 `/data/.env`

这些是可覆盖的本机默认值，不是凭据本身。调用器优先使用 `COURSE_NOTES_API_KEY` 进程环境变量，然后读取配置文件；文件权限不允许时可从已有容器读取配置到内存。不会打印密钥，也不执行 `.env`。服务迁移时更新课程配置，不猜测账号或改动服务设置。

当前请求格式已验证支持：代码/录音文本、`image_url` 内联 PNG，以及 `type=file` 的内联 PDF。其他服务是否支持同样字段需另行确认。PPT/PPTX 不直接作为 PDF 发送，应先转换。

## 课程配置

在课程工作目录创建 `course.json`。所有输入路径相对于这个 JSON 文件；输出目录必须单独指定且尚不存在。`transcript` 是 Codex 已准备好的校正版，`original_transcript` 可选。行号从 1 开始，包含边界；各部分必须连续、无重叠并覆盖全部录音行。

下面是格式示例，实际路径、范围和段数由本次课程决定：

```json
{
  "title": "GRPO 课程笔记",
  "original_transcript": "sources/录音稿_原始.txt",
  "transcript": "录音稿_术语校正版.txt",
  "api": {
    "base_url": "http://127.0.0.1:2048/v1",
    "model": "gemini-4-argon",
    "concurrency": 2,
    "max_tokens": 32768,
    "timeout": 600,
    "key_env": "COURSE_NOTES_API_KEY",
    "env_file": "/data/ghs/services/aistudio2api/data/.env",
    "key_name": "PROXY_API_KEY",
    "container": "aistudio2api",
    "container_env_file": "/data/.env"
  },
  "parts": [
    {
      "title": "原理与采样",
      "lines": [1, 30],
      "code": [
        {"path": "sources/train.py", "lines": [[48, 63], [138, 186]]}
      ],
      "files": ["sources/原理课件.pdf"]
    },
    {
      "title": "损失与训练",
      "lines": [31, 60],
      "code": ["sources/reward_func.py"],
      "files": ["sources/grpo_loss.png"]
    }
  ]
}
```

`code` 的字符串项发送整个文件，字典项发送指定行段；`text` 可提供其他 UTF-8 文本文件，使用与 `code` 相同的格式。`files` 支持本地 PDF、PNG、JPEG 和 WebP。只把相关材料分配给每一段，避免重复发送整门课。

`api` 可省略并采用上述默认值。非本机服务使用 HTTPS；不要让本机服务的凭据被默认发送到其他地址：更换地址时还必须显式配置该地址使用的 `key_env`，并关闭无关的 `env_file` / `container` 回退。

`concurrency` 是本次最多发出的请求数，不代表服务真实容量；可设 1–4。调用器不修改服务配置。配置中禁止放原始 `api_key` 或密码值。

## 离线准备

从 skill 目录执行，替换路径即可：

```bash
python3 scripts/course_notes.py prepare /work/course/course.json --out /work/course/run
```

生成内容：

- `plan.json`：冻结的模型、提示词哈希、分段行号和附件信息。
- `prompts/`：每段实际要发送的完整提示词，包含录音与代码。
- `materials/`：附件快照；校正版和可选原稿也存入运行目录。

`prepare` 不联网、不读密钥，也不调用模型。先让用户审阅分段；如果调整方案，在新的运行目录重新准备，避免让已确认的计划与实际材料不一致。

## 确认后调用

```bash
python3 scripts/course_notes.py generate /work/course/run/plan.json --confirmed
```

`--confirmed` 是执行入口，只有当前对话已获得分段确认才使用，不能用脚本参数替代用户确认。调用器先验证提示词与附件哈希，不允许悄悄更改已准备的材料；密钥只在实际需要发送请求时读取。

成功段落重复运行会跳过，不再消耗调用。已有失败不会自动重试。检查错误后，可对失败或截断段落显式补试一次：

```bash
python3 scripts/course_notes.py generate /work/course/run/plan.json --confirmed --retry-failed
```

每段最多两次尝试。认证错误、额度用尽或第二次失败后停止并报告，不循环补试。客户端超时可能无法确定上游是否已经执行，补试前需考虑这一点。调整材料或分段用新的计划，而非修改已运行的计划文件。

`run.json` 保留每次尝试、用量和状态；`responses/` 保存原始响应；`generated/` 保存每次得到的正文。`reasoning_content` 不混入笔记。

## 离线合并

```bash
python3 scripts/course_notes.py merge /work/course/run/plan.json
```

只有每一段均完整返回、正文哈希正确、代码围栏闭合时才合并。生成 `课程笔记.md` 和 `运行记录.md`；合并只整理标题层级，不自动删改技术内容。已有文件不会被无提示覆盖。内容去重、章节衔接、公式与链接检查由 Codex 完成，保留修订说明。

## 本地验收

```bash
python3 -m unittest discover -s scripts -p 'test_course_notes.py' -v
```

测试使用临时材料和替代传输函数，并封锁网络，不读取真实配置、不调用 Gemini。覆盖分段完整性、材料快照、文件请求格式、已完成段落不重发、重试次数限制、截断不合并，以及原始正文保护。
