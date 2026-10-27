# Docker 部署、登录和维护

## 使用范围

以下是 2026-10-27 在 Linux 服务器上验证过的部署方式，镜像版本为 `v0.2.16`。新部署前核对 [项目文档](https://github.com/Mag1cFall/AIStudio2API)、[发布版本](https://github.com/Mag1cFall/AIStudio2API/releases) 和对应版本配置；不要将此版本长期当作“最新版”。

需要能够使用 AI Studio 的 Google 账号、可运行的 Docker 与 Compose，以及能访问 Google 和镜像/浏览器下载站点的网络。无需本地 GPU、模型权重、Go 或 Node.js。默认 Camoufox 后端首次启动会下载浏览器组件，管理页面可能要等下载和初始化完成才会监听。

## 两层代理

1. **Docker 守护进程代理**决定镜像能否拉取，通常不继承当前终端的代理环境变量。
2. **应用的 `PROXY`**决定 AIStudio2API 和其浏览器运行时如何访问 Google。

本机使用 Mihomo `http://127.0.0.1:7894`，且 Mihomo 只监听本机。采用 `network_mode: host`，让 Linux 容器直接访问这个地址，同时把应用的管理和预览端口显式绑定到 `127.0.0.1`。

桥接网络容器中的 `127.0.0.1` 指容器自己，不能直接用来访问宿主机的 Mihomo。若用户选择桥接网络，需另行配置可达的宿主机代理地址，不能照搬本例的地址。

检查 Docker 当前代理时只查看相关字段，代理 URL 若含账号密码要隐藏凭证：

```bash
docker info --format '{{.HttpProxy}} {{.HttpsProxy}} {{.NoProxy}}'
```

若确需配置守护进程代理，可在 `/etc/systemd/system/docker.service.d/http-proxy.conf` 使用以下形式。实际地址依用户网络而定；保留原配置备份。`daemon-reload` 只重读 systemd 配置，代理环境变更通常还需重启 Docker 才生效，按 SKILL.md 的共享服务授权规则操作。

```ini
[Service]
Environment="HTTP_PROXY=http://127.0.0.1:7894"
Environment="HTTPS_PROXY=http://127.0.0.1:7894"
Environment="NO_PROXY=localhost,127.0.0.1,::1"
```

## 新建实例

以下步骤只用于新实例。已有目录中存在 Compose 或 `.env` 时先比较配置，不覆盖已有账号、密码或运行状态。部署目录应位于技能仓库之外；本机使用 `/data/ghs/services/aistudio2api`。

新实例的 `docker-compose.yml`：

```yaml
services:
  aistudio2api:
    image: ghcr.io/mag1cfall/aistudio2api:v0.2.16
    container_name: aistudio2api
    restart: unless-stopped
    init: true
    network_mode: host
    environment:
      TZ: Asia/Shanghai
      LISTEN_ADDR: 127.0.0.1:2048
      PREVIEW_LISTEN_ADDR: 127.0.0.1:2050
    volumes:
      - ./data:/data
```

在新实例目录中生成配置与两个独立的随机凭证，脚本遇到已有 `.env` 会停止：

```bash
mkdir -p data
python3 - <<'PY'
import os
import secrets
from pathlib import Path

values = {
    'PROXY_API_KEY': secrets.token_urlsafe(36),
    'ADMIN_AUTH_ENABLED': 'true',
    'ADMIN_USERNAME': 'admin',
    'ADMIN_PASSWORD': secrets.token_urlsafe(30),
    'AISTUDIO_AUTH_STATES': 'auth',
    'AUTO_START': 'false',
    'PROXY': 'http://127.0.0.1:7894',
    'WAA_BACKEND': 'camoufox',
    'WARM_WORKER_LIMIT': '1',
    'MAX_ACTIVE_WORKERS': '1',
    'WARM_STARTUP_CONCURRENCY': '1',
    'PER_ACCOUNT_CONCURRENCY': '1',
    'ROUTING_STRATEGY': 'round-robin',
    'UPSTREAM_CHANNELS': 'playground',
    'FAKE_STREAM': 'false',
    'REQUEST_BODY_LOG': 'false',
}
path = Path('data/.env')
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as output:
    output.writelines(f'{key}={value}\n' for key, value in values.items())
print('Created data/.env; credential values omitted.')
PY
docker compose config --quiet
docker compose pull --quiet
docker compose up -d --no-build
```

这些是起步配置，并发和通道应按实际需求调整。其中 `WARM_STARTUP_CONCURRENCY` 必须满足 `1 <= 值 <= MAX_ACTIVE_WORKERS`；只把 `MAX_ACTIVE_WORKERS` 改为1却保留默认预热并发5，会导致启动失败。

## 从 Windows 登录服务器上的 Google 账号

在用户**本地 Windows 的 PowerShell/Windows Terminal**执行，而不是在服务器执行：

```powershell
ssh -N -L 2048:127.0.0.1:2048 用户名@服务器地址
```

如果 SSH 使用自定义端口，沿用用户已有 SSH 命令的 `-p` 参数或 SSH 主机别名。保持窗口打开，在 Windows 浏览器访问 `http://127.0.0.1:2048`。

1. 管理员用户名来自 `ADMIN_USERNAME`，管理密码来自 `ADMIN_PASSWORD`。通过用户自己的安全终端/本地文件访问这些值，不把它们写入聊天记录或仓库。
2. 进入“账户 → 添加账户 → 浏览器登录”。服务器没有桌面也可用，隔离浏览器画面显示在管理页中。
3. 由用户完成 Google 登录、手机/两步验证，以及页面显示的 Google Drive 授权。
4. 账号就绪后启动生成服务，确认状态 `RUNNING`，再查询模型并做一次简短生成测试。

只有用户确实需要 HTML 预览页面时，再按相同方式转发本机2050到服务器2050；普通管理、Google 登录与 API 调用只需2048。

## 自动启动与多账号

- `restart: unless-stopped` 保证容器随 Docker 恢复，不代表应用内的生成服务会启动。
- 首次账号和生成请求验证成功后，将 `AUTO_START=true` 写入服务配置，仅重启本项目容器，确认生成服务能自动恢复为 `RUNNING`。
- 通过管理页添加其他自有或获授权账号。根据实际内存和账号状态调整 Worker 与并发，不把多个账号等同于无限额度。
- 实验默认只启用 Playground，避免通道切换改变测试条件；如用户明确需要 Build，再说明差异并配置。带 `-build` 后缀的模型可能带有代码助手的系统提示词。

## 维护与故障定位

在实际服务目录执行：

```bash
docker compose ps
docker compose restart aistudio2api
```

需要日志时只提取本次故障的时间窗口和必要字段，输出前隐藏密钥、Cookie、认证头与邮箱。`data/auth/` 是登录凭证，`data/runtime/` 是浏览器、缓存和日志。容器以 root 运行，应用写入的数据可能归 root 所有，不要用递归放宽权限来解决读取问题。

| 现象 | 下一步 |
|---|---|
| 拉取镜像失败 | 核对 Docker 守护进程的代理，并测试镜像仓库连通性；`/v2/` 返回401可能只是正常的未认证响应，不能当作网络失败 |
| 容器运行但管理端口不通 | 看首次浏览器下载/初始化是否完成，再看容器退出或重启原因 |
| 管理页面可访问但模型接口503 | 检查账号与生成服务状态，尤其是 `service_stopped` |
| Google 页面打不开或反复要求认证 | 核对应用 `PROXY`、账号状态及网页中的验证提示；交给用户完成身份验证 |
| 设置单 Worker 后启动失败 | 检查预热并发是否仍为默认5，按上述约束修正 |
| Docker 显示 active，但 docker.sock 不存在 | 检查 service/socket 状态和既有容器；这是连接入口故障，不是代理问题，不直接批量重启服务 |

共享 Docker 的修复应先备份配置、记录运行中的容器及进程，确认当前会话授权并说明影响，再实施维护和核对恢复状态。即使临时使用 `live-restore`，也不把“保证无中断”作为承诺；临时修改的全局配置应在完成后恢复。不要把某次部署时的容器数量硬编码为以后检查的预期值。

升级前备份配置和认证数据，核对发布说明与兼容性，更新指定镜像版本，只重建本项目；不要默认运行带卷删除的清理命令。
