# OmniMem（中文说明）

English: [README.md](README.md)

OmniMem 是一套可复用、低耦合的 AI Agent 记忆基础设施，支持跨工具、跨设备、跨项目与跨账号。

## 3 分钟上手

1. 安装：

```bash
bash scripts/install.sh
```

2. 启动 WebUI + 守护进程：

```bash
~/.omnimem/bin/omnimem start
```

3. 打开：

- `http://127.0.0.1:8765`

4. 在 WebUI 完成 GitHub 同步登录（可选）：

- `Configuration` -> `GitHub Quick Setup` -> `Sign In via GitHub`。

### OAuth Broker 一键部署

[![部署到 Cloudflare Worker](https://img.shields.io/badge/Deploy-Cloudflare%20Worker-F38020?logo=cloudflare&logoColor=white)](https://deploy.workers.cloudflare.com/?url=https://github.com/NoPKT/omnimem/tree/main/examples/oauth-broker/cloudflare-worker)
[![部署到 Vercel](https://img.shields.io/badge/Deploy-Vercel-000000?logo=vercel&logoColor=white)](https://vercel.com/new/clone?repository-url=https://github.com/NoPKT/omnimem&root-directory=examples%2Foauth-broker%2Fvercel&project-name=omnimem-oauth-broker)
[![部署到 Railway](https://img.shields.io/badge/Deploy-Railway-0B0D0E?logo=railway&logoColor=white)](https://railway.app/new/template?template=https://github.com/NoPKT/omnimem/tree/main/examples/oauth-broker/railway)
[![Fly.io 模板](https://img.shields.io/badge/Template-Fly.io-8B5CF6?logo=flydotio&logoColor=white)](https://github.com/NoPKT/omnimem/tree/main/examples/oauth-broker/fly)

部署完成后，把 broker URL 填到 WebUI `Configuration` -> `OAuth Broker URL`。

快速健康检查（把 `<BROKER_URL>` 替换成你的地址）：

```bash
curl -sS -X POST "<BROKER_URL>/v1/github/device/start" \
  -H 'Content-Type: application/json' \
  -d '{}' | jq .
```

预期：返回类似 `missing client_id` 的 JSON 错误（说明 broker 端点可达）。

## npm 使用

无需全局安装直接运行：

```bash
npm exec -y --package=omnimem --call "omnimem start"
```

或全局安装：

```bash
npm i -g omnimem
omnimem start
```

## Agent 模式

```bash
omnimem codex
omnimem claude
```

排障命令：

```bash
omnimem doctor
omnimem stop
```

## 常见问题

- 需要手动创建 SSH key 或 token 吗？
  - 常规流程不需要。可直接用 WebUI 的 GitHub OAuth 登录。
- 记忆同步是否经过服务器中转？
  - 不会。记忆同步仍是本机 Git 操作。
- OAuth broker 是做什么的？
  - 仅用于简化 GitHub OAuth 登录，不在记忆数据链路中。
- OAuth broker 一键部署按钮在哪？
  - 已在本 README 上方给出。完整说明见 `docs/oauth-broker.zh-CN.md`。

## 文档索引

- 中文文档入口：`docs/README.zh-CN.md`
- English docs entry: `docs/README.md`
