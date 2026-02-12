# OmniMem

Language: [English](README.md) | [简体中文](README.zh-CN.md)

OmniMem is reusable, low-coupling memory infrastructure for AI agents across tools, devices, projects, and accounts.

## 3-Minute Quick Start

1. Install:

```bash
bash scripts/install.sh
```

2. Start WebUI + daemon:

```bash
~/.omnimem/bin/omnimem start
```

3. Open:

- `http://127.0.0.1:8765`

4. Sign in GitHub sync in WebUI (optional):

- `Configuration` -> `GitHub Quick Setup` -> `Sign In via GitHub`.

## npm Usage

Run without global install:

```bash
npm exec -y --package=omnimem --call "omnimem start"
```

Or install globally:

```bash
npm i -g omnimem
omnimem start
```

## Agent Mode

```bash
omnimem codex
omnimem claude
```

Troubleshooting:

```bash
omnimem doctor
omnimem stop
```

## FAQ

- Do I need to manually create SSH keys or tokens?
  - No for normal flow. Use WebUI GitHub sign-in (OAuth).
- Does memory sync pass through a server?
  - No. Memory sync is still local Git operations on your machine.
- What is OAuth broker for?
  - Only to simplify GitHub OAuth login. It is not in memory data path.
- One-click deploy buttons for OAuth broker?
  - Use `docs/oauth-broker.md` (Cloudflare/Vercel/Railway/Fly links + CLI fallback).

## Maintainer Docs

- Publish: `docs/publish-npm.md`
- Startup/OAuth QA: `docs/qa-startup-guide.md`
- WebUI config: `docs/webui-config.md`
- Advanced ops/eval/tuning: `docs/advanced-ops.md`
- OAuth broker deploy details: `docs/oauth-broker.md`

## Documentation

- English:
  - `docs/quickstart-10min.md`
  - `docs/webui-config.md`
  - `docs/oauth-broker.md`
  - `docs/qa-startup-guide.md`
  - `docs/install-uninstall.md`
  - `docs/publish-npm.md`
  - `docs/advanced-ops.md`
- 中文:
  - `README.zh-CN.md`
  - `docs/quickstart-10min.zh-CN.md`
  - `docs/webui-config.zh-CN.md`
  - `docs/oauth-broker.zh-CN.md`
  - `docs/qa-startup-guide.zh-CN.md`
  - `docs/install-uninstall.zh-CN.md`
  - `docs/publish-npm.zh-CN.md`
  - `docs/advanced-ops.zh-CN.md`
