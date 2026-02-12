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

- Entry: `docs/README.md`

## Documentation

- English index: `docs/README.md`
- 中文索引: `docs/README.zh-CN.md`
