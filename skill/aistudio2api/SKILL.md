---
name: aistudio2api
description: 部署、使用和维护 Mag1cFall/AIStudio2API，将 Google AI Studio 网页登录状态转换为 Gemini、OpenAI 或 Anthropic 兼容接口。用于该项目的 Docker 部署、Mihomo 代理接入、账号登录、模型调用验证与运行故障排查。
---

# AIStudio2API 使用与维护

本技能中提到的“gemini2api”指 [Mag1cFall/AIStudio2API](https://github.com/Mag1cFall/AIStudio2API)。它使用 AI Studio 的网页认证状态；`PROXY_API_KEY` 是本地代理的访问密钥，不是 Google 官方 Gemini API Key。

## 先确定操作对象

- 使用现有服务器或测试模型时，先读 [references/current-instance.md](references/current-instance.md)，核对现场状态；其中路径、版本与测试结果是带日期的实例记录。
- 新建实例、调整 Mihomo 网络、升级或处理启动故障时，读 [references/deployment.md](references/deployment.md)。不要因为技能被调用就重建已有服务。
- 部署数据应留在独立的服务目录。不要把实际 `.env`、`auth/`、Cookie、Google 登录状态、管理密码或 API 密钥复制到技能仓库、提交到 Git 或打印到日志。

## 日常操作

1. 检查 Compose 文件、应用配置和容器状态。只输出需要排查的非敏感字段，读取配置时不展开密码或密钥。
2. 区分三种状态：容器进程运行、管理网页可访问、生成服务 `RUNNING`。管理首页返回 HTTP 200 不能证明模型调用成功。
3. 如需管理页面，让用户在**自己的电脑**建立 SSH 转发，再用本机浏览器打开页面。Google 登录、手机验证和授权由用户在登录窗口完成；不要要求用户把 Google 密码或 Cookie 发到聊天中。
4. 若需操作管理 API，先用独立的管理凭证认证，保持会话 Cookie 仅在内存中：
   - `POST /api/auth/login`：JSON 包含 `username`、`password`、`remember`。
   - `GET /api/status`：读取 `state`。
   - `GET /api/accounts`：检查账号，不输出邮箱和认证数据。
   - `POST /api/control/start`：仅在账号就绪且服务未运行时启动。
   - 以上路径已在 v0.2.16 验证；升级后如路径不匹配，检查对应版本源码或管理界面请求，不盲猜认证接口。
5. 通过带 `PROXY_API_KEY` 的 `GET /v1/models` 取得模型名。模型出现在目录中只表示已列出，不证明账号有额度或实际请求能成功。
6. 首先验证用户指定模型的一次简短生成请求，记录 HTTP 状态、返回模型名、耗时与实际答案。只在用户需要或接入 Agent 客户端时补测流式、函数调用和工具结果续接。

## 调用生成接口

OpenAI 兼容配置：

```text
Base URL: http://127.0.0.1:2048/v1
API Key: 服务配置中的 PROXY_API_KEY
Model: 从 /v1/models 取得的完整模型名
```

下面的示例在**服务器**执行，从现有服务配置读取密钥，不把密钥放入命令行或输出。换模型时只替换 `model`：

```bash
python3 - <<'PY'
import json
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

env = {}
for line in Path('/data/ghs/services/aistudio2api/data/.env').read_text().splitlines():
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        name, value = line.split('=', 1)
        env[name.strip()] = value.strip()
key = env['PROXY_API_KEY'].split(',')[0].strip()
body = {
    'model': 'gemini-4-argon',
    'messages': [{'role': 'user', 'content': 'Compute 17*19. Reply with just the integer.'}],
    'max_tokens': 2048,
    'stream': False,
}
request = Request(
    'http://127.0.0.1:2048/v1/chat/completions',
    data=json.dumps(body).encode(),
    headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
)
opener = build_opener(ProxyHandler({}), NoRedirect())
with opener.open(request, timeout=120) as response:
    result = json.load(response)
print('model:', result.get('model'))
print('answer:', result['choices'][0]['message']['content'])
print('usage:', result.get('usage'))
PY
```

预期答案为 `323`。此测试只证明该接口当次可以生成回答，不证明模型身份、全部能力或未来的可用额度。示例配置读取器针对本机生成的简单 `KEY=value` 文件；不要用 shell 执行来源不明的 `.env`。

## 实验与排错要点

- 将用户要求的模型、通道、流式方式和并发配置保留在记录中。Playground、Build 和带 `-build` 后缀的模型不能在实验中混为同一条件；`-build` 模型可能附带 Build 代码助手的系统提示词。
- 工具调用后，把原始 assistant 消息连同工具调用元数据完整带回，再追加对应的 tool 结果。不要手动删掉签名等扩展字段。
- `401 invalid_api_key`：检查代理密钥及 Bearer 认证，不用管理密码或 Google 密钥代替。
- `503 service_stopped`：检查生成服务状态和账号是否就绪，不反复重建容器。
- `429`：保留模型、通道和错误原因，按响应要求等待；不要持续重试或静默换到其他模型、账号或 Build 通道来掩盖失败。
- 先定位问题属于 Docker 拉镜像、容器访问 Google、Google 账号认证还是模型调用。详见部署参考，不混改这些层的配置。
- 变更应用配置后优先只重启本项目容器。若必须重启共享 Docker，先检查其他容器和当前会话授权；已有明确授权时直接执行，尚未授权且可能中断其他服务时说明影响并询问。

## 完成时交付

报告实际验证过的模型与能力、生成接口地址、密钥文件位置及仍需用户完成的步骤。更新实例记录时标注验证日期，不把目录中的全部模型记成已测试；不要为了“验证更多”重复消耗账号额度。
