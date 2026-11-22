# 本机实例记录

部署记录日期：2026-10-27；免 sudo 客户端更新：2026-11-12。下文部署参数保留当时记录；新的调用入口见下一节，历史测试不代替实时状态检查。

## 直接调用（2026-11-12 更新）

- 新 agent 优先运行技能内 `scripts/client.py`，不读取 root 所有的服务 `.env`，无需 sudo 或管理登录。
- `ghs` 用户的代理 token 已单独保存在 `~/.config/aistudio2api/client.json`（目录0700、文件0600）；只含 `api_key`，无管理/Google 凭证。脚本自动读取，不输出 token。权限、轮换和完整调用见 [client-usage.md](client-usage.md)。
- 源码技能位于 `/data/ghs/services/ai-toolkit/skill/aistudio2api`；DSH 安装副本位于 `/data/ghs/.dsh/skills/aistudio2api`，需要连同 scripts 与 references 一起同步。
- 2026-11-12 已有一次 `gemini-4-argon` 普通长文生成成功：HTTP200、`finish_reason=stop`，输入两份本地参考笔记。
- 同日通过安装副本的 `scripts/client.py`，以普通 `ghs` 用户、无需 sudo/密码完成 `/v1/models` 查询与 Argon 短生成：HTTP200，17×19 返回323，约3.91秒，`finish_reason=stop`。另完成7项客户端离线检查（私有配置、权限拒绝、缺失配置、文件附加、模型不替换、输出不覆盖、拒绝重定向）。未运行独立新 agent 的端到端测试。
- 上述测试不代表 Argon 工具或流式已验证，也不以响应模型名独立认证上游身份。

## 位置与网络

| 项目 | 已验证配置 |
|---|---|
| 服务器系统 | Ubuntu 22.04、x86_64 |
| 实际服务目录 | `/data/ghs/services/aistudio2api` |
| Compose 文件 | `/data/ghs/services/aistudio2api/docker-compose.yml` |
| 容器 | `aistudio2api` |
| 镜像 | `ghcr.io/mag1cfall/aistudio2api:v0.2.16` |
| 管理页面 | `http://127.0.0.1:2048` |
| OpenAI 兼容 Base URL | `http://127.0.0.1:2048/v1` |
| HTML 预览 | `http://127.0.0.1:2050` |
| Mihomo | `http://127.0.0.1:7894`，仅监听本机 |
| Docker 网络 | `host`；应用的2048和2050都仅监听 `127.0.0.1` |
| 上游通道 | `playground` |
| 生成服务自动启动 | `AUTO_START=true`，已验证应用容器重启后自动恢复 |

技能源码位于 `/data/ghs/services/ai-toolkit/skill/aistudio2api`。这是文档与技能目录，不是运行数据目录。

## 凭证位置

配置文件为 `/data/ghs/services/aistudio2api/data/.env`，不在本仓库中：

- `ADMIN_USERNAME` / `ADMIN_PASSWORD`：用于管理页面和管理 API。
- `PROXY_API_KEY`：用于客户端访问生成 API，与管理密码独立。
- `data/auth/`：Google 登录状态，由运行中的应用管理。

当日已完成一个 Google 账号认证。这里不记录邮箱、密码、API Key 或 Cookie。普通生成使用上方用户私有客户端配置；仅服务维护才涉及原 `.env`，不因普通调用失败而索取 sudo 密码或扩大该文件权限。

Windows 用户应在本地建立 SSH 转发；在服务器上直接访问接口不需要 SSH 转发。具体操作见 [deployment.md](deployment.md)。

## 已验证的模型

| 模型名 | 当日通过的检查 | 边界 |
|---|---|---|
| `gemini-3-flash-preview` | 普通对话、SSE 流式、函数调用、工具结果续接 | 不代表其他模型也通过这些能力测试 |
| `gemini-4-argon` | 普通对话；17×19 正确返回323，约4.25秒 | 未在此次部署中验证该模型的流式与工具调用 |

模型目录当日返回45个条目，不保证每个模型均有调用权限或额度。测试模型时使用目录中的完整名称；其他中转站的 `gemini-3-flash` 短别名不能直接当作本机模型名。

服务目录中保留以下记录，可按任务需要读取，勿整体复制到公开仓库：

- `README.local.md`：本机访问与维护说明。
- `deployment-status.json`：部署状态与分模型验证范围。
- `available-models.json`：带检查日期的模型目录快照。
- `api-smoke-test.json`：Gemini 3 Flash 普通生成结果。
- `api-capability-tests.json`：Gemini 3 Flash 流式与工具调用结果。
- `gemini-4-argon-smoke-test.json`：Argon 普通生成结果。

## 历史问题

- Docker 原代理端口为7890，当时镜像仓库访问失败，已改为7894；终端代理并不会自动替代 Docker 守护进程代理。
- Docker service/socket 曾显示 active，但 `/run/docker.sock` 路径丢失。经用户授权维护后恢复；当时的既有容器进程已核对保留。此记录不构成以后自动重启共享 Docker 的授权。
- 将 `MAX_ACTIVE_WORKERS` 设为1时，需要同时设置 `WARM_STARTUP_CONCURRENCY=1`，否则会因参数约束无法启动。
- 未下载本地模型、未使用 L40 GPU。Camoufox 是浏览器运行时，保存在应用数据目录，不属于模型权重。
