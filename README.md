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

### OAuth Broker One-Click Deploy

[![Deploy to Cloudflare Worker](https://img.shields.io/badge/Deploy-Cloudflare%20Worker-F38020?logo=cloudflare&logoColor=white)](https://deploy.workers.cloudflare.com/?url=https://github.com/NoPKT/omnimem/tree/main/examples/oauth-broker/cloudflare-worker)
[![Deploy to Vercel](https://img.shields.io/badge/Deploy-Vercel-000000?logo=vercel&logoColor=white)](https://vercel.com/new/clone?repository-url=https://github.com/NoPKT/omnimem&root-directory=examples%2Foauth-broker%2Fvercel&project-name=omnimem-oauth-broker)
[![Deploy to Railway](https://img.shields.io/badge/Deploy-Railway-0B0D0E?logo=railway&logoColor=white)](https://railway.app/new/template?template=https://github.com/NoPKT/omnimem/tree/main/examples/oauth-broker/railway)
[![Fly.io Template](https://img.shields.io/badge/Template-Fly.io-8B5CF6?logo=flydotio&logoColor=white)](https://github.com/NoPKT/omnimem/tree/main/examples/oauth-broker/fly)

After deploy, paste broker URL in WebUI `Configuration` -> `OAuth Broker URL`.

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
  - Already listed above in this README. Full details: `docs/oauth-broker.md`.

## Maintainer Docs

- Entry: `docs/README.md`

## Documentation

- English index: `docs/README.md`
- 中文索引: `docs/README.zh-CN.md`
