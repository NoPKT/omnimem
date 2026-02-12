# OmniMem（中文说明）

> English: [README.md](README.md)

OmniMem 是一套可复用、低耦合的 AI Agent 记忆基础设施，支持跨工具、跨设备、跨项目与跨账号。

当前状态：`Phase D 已完成（WebUI + 自动同步守护进程 + bootstrap + uninstall）`

## 目标

- 跨工具：通过统一 CLI 协议保持一致行为（Claude Code / Codex / Cursor）。
- 跨设备：通过私有 Git 仓库同步。
- 跨项目：复用记忆模式与引用。
- 低耦合：最小化项目侵入，易于挂载/移除。
- 人机双视图：Markdown + JSONL + SQLite FTS。
- 安全：记忆正文不存密钥，只存凭据引用。

## 目录结构

- `omnimem/`：CLI 与 WebUI 核心实现
- `bin/omnimem`：启动器
- `scripts/`：安装、引导、挂载、校验等脚本
- `templates/project-minimal/`：项目最小接入模板
- `spec/`：协议与 schema
- `db/schema.sql`：SQLite + FTS 表结构
- `docs/`：架构与运维文档

## 一条命令启动

```bash
~/.omnimem/bin/omnimem
```

可选主机/端口：

```bash
~/.omnimem/bin/omnimem --host 127.0.0.1 --port 8765
```

可选 WebUI Token：

```bash
OMNIMEM_WEBUI_TOKEN='your-token' ~/.omnimem/bin/omnimem start
```

说明：

- 非本地监听需显式开启：`--allow-non-localhost`
- 非本地监听时必须启用 WebUI 鉴权（`OMNIMEM_WEBUI_TOKEN` 或 `--webui-token`）
- 启用 token 后，API 请求必须带 `X-OmniMem-Token`

## 安装与设备引导

本地安装：

```bash
bash scripts/install.sh
```

新设备引导：

```bash
bash scripts/bootstrap.sh --repo <your-omnimem-repo-url>
```

## 项目挂载/移除

```bash
bash scripts/attach_project.sh /path/to/project my-project-id
bash scripts/detach_project.sh /path/to/project
```

## 卸载

```bash
~/.omnimem/bin/omnimem uninstall --yes
```

## 发布与 npx

发布前检查：

```bash
npm run release:gate
```

生成下个版本草案（dry-run）：

```bash
npm run release:prepare
```

发布后用户可直接运行：

```bash
npm exec -y --package=omnimem --call "omnimem start"
```

或全局安装：

```bash
npm i -g omnimem
omnimem start
```

## Agent 模式（Codex / Claude）

```bash
omnimem codex
omnimem claude
```

排障时可显式关闭 sidecar：

```bash
omnimem stop
omnimem stop --all
```

诊断：

```bash
omnimem doctor
```

## 校验

```bash
python3 -m pytest -q
bash scripts/release_gate.sh --allow-clean --skip-doctor --skip-pack --project-id OM --home ./.omnimem_gate
```

## 文档（中文）

- [docs/quickstart-10min.zh-CN.md](docs/quickstart-10min.zh-CN.md)
- [docs/webui-config.zh-CN.md](docs/webui-config.zh-CN.md)
- [docs/oauth-broker.zh-CN.md](docs/oauth-broker.zh-CN.md)
- [docs/qa-startup-guide.zh-CN.md](docs/qa-startup-guide.zh-CN.md)
- [docs/publish-npm.zh-CN.md](docs/publish-npm.zh-CN.md)
- [docs/install-uninstall.zh-CN.md](docs/install-uninstall.zh-CN.md)

## 文档（英文原版）

- [README.md](README.md)
- [docs/quickstart-10min.md](docs/quickstart-10min.md)
- [docs/webui-config.md](docs/webui-config.md)
- [docs/oauth-broker.md](docs/oauth-broker.md)
- [docs/qa-startup-guide.md](docs/qa-startup-guide.md)
- [docs/publish-npm.md](docs/publish-npm.md)
- [docs/install-uninstall.md](docs/install-uninstall.md)
