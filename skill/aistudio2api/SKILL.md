---
name: aistudio2api
description: 调用、部署和维护 Mag1cFall/AIStudio2API（gemini2api）。当用户要求使用本机 Gemini/Argon API 生成、分析文件、查询模型，或处理该服务的部署、登录与故障时使用；提供自动读取私有代理 token 的免 sudo 客户端。
---

# AIStudio2API

## 直接调用现有服务

在技能目录执行下列命令；从其他目录执行时，将 `scripts/client.py` 替换为本技能目录下的绝对路径。无需 sudo、管理登录或重复部署。

```bash
# 查询完整模型 ID（列出不代表有额度）
python3 scripts/client.py models

# 用户指定 Argon 时使用这个精确 ID，不换成 -build
python3 scripts/client.py chat --model gemini-4-argon --prompt 'Compute 17*19. Reply with just the integer.'

# 文件分析/长文：发送实际内容，不是仅发送本地路径；输出文件须不存在
python3 scripts/client.py chat --model gemini-4-argon \
  --prompt-file /absolute/path/prompt.txt \
  --context /absolute/path/reference.md \
  --max-tokens 16384 --timeout 900 --output /absolute/path/new-result.md
```

- 本机 Base URL：`http://127.0.0.1:2048/v1`；脚本自动读取 `~/.config/aistudio2api/client.json` 的 `api_key`，也支持环境变量注入。**不要读取或展示该文件内容，不要索取 sudo 密码**。凭证权限、轮换、完整 JSON 请求及限制见 [client-usage](references/client-usage.md)。
- 普通调用优先使用脚本，不先检查 Docker/管理后台。首次核验用指定模型做一次简短生成；已有当次成功请求时，不再额外消耗额度。stderr 返回 HTTP、模型、耗时和 usage；stdout 是回答。返回模型名不构成上游身份认证。
- 请求只发送用户授权的材料。多份参考可重复 `--context`；长调用使用受管理后台任务并收集结果。若超时或输出截断，先检查记录，不直接重发。

## 只在需要时展开

- 本机部署位置、历史验证范围：[current-instance](references/current-instance.md)。
- 新建/升级、代理网络、管理 API 与账号登录：[deployment](references/deployment.md)。已有服务不要重建；Google 登录和验证交给用户，容器运行/网页200不等于生成可用。
- 凭证不写入技能、仓库、命令行或日志；私有客户端只持有代理 `PROXY_API_KEY`，不持有管理密码、Cookie 或 Google 登录数据。不递归放宽服务目录权限。
- 保留用户指定的模型、通道、流式和工具条件；不静默换模型/账号/Build。工具调用用完整 JSON 保留原始 assistant 消息及签名等元数据；脚本仅支持非流式，其他协议按对应版本文档处理。
- `401` 检查客户端 token 是否过期/轮换；`503 service_stopped` 检查生成服务；`429` 遵守返回限制，不连续重试。维护只影响本项目，共享 Docker 重启需另外确认影响与授权。
