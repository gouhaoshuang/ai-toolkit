# 本机实例记录

核对日期：2026-10-27。以下是当日部署和测试结果，不代替使用时的状态检查。

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

当日已完成一个 Google 账号认证。这里不记录邮箱、密码、API Key 或 Cookie。权限不足时先检查文件所有者，必要时使用已获授权的管理员方式读取所需字段，不向输出暴露凭证值。

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
