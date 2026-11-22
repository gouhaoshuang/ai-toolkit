# 现有服务客户端：免 sudo 使用

## 默认配置与安全边界

- 仅使用本机 OpenAI 兼容接口 `http://127.0.0.1:2048/v1`。
- `scripts/client.py` 按以下顺序取得代理 token：
  1. 环境变量 `AISTUDIO2API_API_KEY`（由安全运行环境注入，不在命令行写明文）。
  2. `AISTUDIO2API_CONFIG` 指定的 JSON 文件，默认 `~/.config/aistudio2api/client.json`，字段为 `api_key`。
- 当前 `ghs` 用户已配置默认客户端文件：目录 `0700`、文件 `0600`，只保存代理生成接口 token。它不是 Google 官方 API Key，也不是管理密码。新 agent 在同一用户、文件系统/网络允许访问时无需 sudo。脚本拒绝其他用户拥有、组/其他人可读或符号链接的凭证文件。
- 不要用 read/cat 打开凭证。让脚本直接读取即可；不要复制到技能、项目仓库、提示词、日志或聊天。
- 原服务 `.env` 仍是 root 私有，不需要改变权限，也不把 sudo 密码保存进技能。客户端私有副本在服务器 token 轮换后需要更新。
- 沙箱访问拒绝按会话权限流程处理，不尝试换路径、sudo 或 Docker 绕过；`no_new_privileges` 等限制也不能靠记录密码解决。服务可能停止、模型可能无额度，因此不承诺永远可用。

## 常见调用

从技能目录运行，或使用 `client.py` 的绝对路径：

```bash
python3 scripts/client.py models
python3 scripts/client.py chat --model gemini-4-argon --prompt '用两句话解释 actor 和 critic。'
python3 scripts/client.py chat --model gemini-4-argon \
  --prompt-file /absolute/path/prompt.txt \
  --context /absolute/path/paper-a.md --context /absolute/path/paper-b.md \
  --max-tokens 16384 --timeout 900 --output /absolute/path/new-explanation.md
```

脚本只读 UTF-8 文本，不解析 PDF/图片。只有路径不会把文件传给模型，使用 `--context` 才会附加文件全文。发送前检查材料是否获授权、大小是否合适；上下文与输出上限随模型而异，不能从一个成功请求推断通用上限。输出目录须存在，文件须不存在；脚本在发送前检查，避免因覆盖路径消耗额度。

stdout 默认是模型文本，stderr 是不含凭证的调用摘要。`finish_reason=length` 表示可能截断；不要把截断文本当完整结果。长请求适合受管理后台任务，跟踪 job 并收集结果，不重复提交。超时只意味着客户端没等到，服务端可能仍在生成并消耗额度；脚本不自动重试、不切模型。

## 完整 messages / 工具续接

对于需要 system 消息、工具调用或多轮记录的任务，把完整请求保存为 JSON，再调用：

```bash
python3 scripts/client.py chat --model gemini-4-argon \
  --request-file /absolute/path/request.json --json \
  --timeout 900 --output /absolute/path/new-response.json
```

请求示例（只示意消息结构）：

```json
{
  "model": "gemini-4-argon",
  "messages": [{"role": "user", "content": "你好"}],
  "max_tokens": 2048,
  "stream": false
}
```

`--model` 必须与请求中的模型一致。脚本保留 messages、tools 等字段；`--json` 保存完整响应。工具结果续接时保留原 assistant 消息及 tool-call ID、签名等扩展字段；不是只摘出文本再拼接。Argon 的工具能力未因普通生成测试而得到验证。脚本不支持 SSE，收到工具调用而未指定 `--json` 会明确报错，不把它伪装成普通文字回答。

客户端禁用环境 HTTP 代理并拒绝重定向，防止代理 token 被带离本机服务。不要给脚本添加任意远端 endpoint 后仍复用本机 token。

## 仅在配置缺失或 token 轮换时初始化

日常 agent 不运行此步骤。若出现 401，先确认是否发生轮换；权限或额度错误不能靠盲目重建服务解决。

由有权限的维护者在自己的安全终端，将当前服务的首个 `PROXY_API_KEY` 写入用户私有 `client.json` 的 `api_key` 字段：

1. 配置目录归客户端运行用户，模式 `0700`。
2. 以该用户创建/更新文件，模式 `0600`，内容为 `{"api_key": "实际代理token"}`。这只是结构示意，实际值不写入技能。
3. 只提取该字段，不复制整个服务 `.env`、管理密码或 Google `auth/`。
4. 再运行 `models` 与一次指定模型的短生成验证。

2026-11-12 的首次初始化仅提取了现有本地服务的代理 token，未改变服务配置、未扩大原 `.env` 权限。拥有 Docker 权限本身接近主机管理员能力，不把 Docker 凭证提取当成受限会话绕过权限的通用办法。
