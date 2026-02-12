# OmniMem

Language: [English](README.md) | [简体中文](README.zh-CN.md)

OmniMem is reusable, low-coupling memory infrastructure for AI agents across tools, devices, projects, and accounts.

Current status: `Phase D implemented (WebUI + auto sync daemon + bootstrap + uninstall)`

## Goals

- Cross-tool: same behavior via CLI protocol (Claude Code / Codex / Cursor).
- Cross-device: sync through a private Git repository.
- Cross-project: reusable memory patterns and references.
- Low-coupling: attach/remove with minimal project files.
- Human + machine views: Markdown + JSONL + SQLite FTS.
- Security: never store secrets in memory body, only credential references.

## Structure

- `omnimem/`: core CLI and WebUI implementation.
- `bin/omnimem`: launcher.
- `scripts/`: install, bootstrap, attach, detach, verify helpers.
- `templates/project-minimal/`: minimal project integration files.
- `spec/`: protocol and schemas.
- `db/schema.sql`: SQLite + FTS schema.
- `docs/`: architecture and operations docs.

## One-command usage

Start app (WebUI + daemon):

```bash
~/.omnimem/bin/omnimem
```

Optional host/port:

```bash
~/.omnimem/bin/omnimem --host 127.0.0.1 --port 8765
```

Optional WebUI API token:

```bash
OMNIMEM_WEBUI_TOKEN='your-token' ~/.omnimem/bin/omnimem start
```

Notes:

- Non-local bind requires explicit opt-in: `--allow-non-localhost`.
- If you opt into a non-local bind, you must also enable WebUI auth (set `OMNIMEM_WEBUI_TOKEN` or pass `--webui-token`).
- If token is enabled, API calls must send header `X-OmniMem-Token`.
- Daemon retry/backoff can be tuned with `--daemon-retry-max-attempts`, `--daemon-retry-initial-backoff`, `--daemon-retry-max-backoff`.

## Install

Local install from repo:

```bash
bash scripts/install.sh
```

Bootstrap on a new device:

```bash
bash scripts/bootstrap.sh --repo <your-omnimem-repo-url>
```

## Project attach/remove

```bash
bash scripts/attach_project.sh /path/to/project my-project-id
bash scripts/detach_project.sh /path/to/project
```

## Uninstall

```bash
~/.omnimem/bin/omnimem uninstall --yes
```

## Install via npm

End users can run directly without global install:

```bash
npm exec -y --package=omnimem --call "omnimem start"
```

Or install globally once:

```bash
npm i -g omnimem
omnimem start
```

## Auto Agent Mode (Codex / Claude)

Interactive sidecar mode (launch native tool + auto-start WebUI):

```bash
omnimem codex
omnimem claude
```

Stop sidecar explicitly (for troubleshooting):

```bash
omnimem stop
omnimem stop --all
```

Run one-shot diagnostics (webui/daemon/sync + suggested commands):

```bash
omnimem doctor
```

Single turn:

```bash
omnimem codex "your request"
omnimem claude "your request"
```

Notes:

- `omnimem codex` / `omnimem claude` launches native CLI (full tool capability).
- WebUI is auto-started by default at `http://127.0.0.1:8765`.
- Use `--no-webui` to disable sidecar UI startup.
- Wrapper sessions now auto-stop the shared WebUI when the last active wrapper exits (default on-demand lifecycle).
- Use `--webui-persist` (or `OMNIMEM_WEBUI_PERSIST=1`) to keep WebUI running after wrapper exit.
- Wrapper coordination (pid/lease) is now per-user global runtime (not tied to `OMNIMEM_HOME`), so parallel wrappers in different projects reuse the same sidecar safely.
- Daemon sync now triggers on both content mtime changes and Git dirty state (`mtime_or_dirty`), reducing missed pushes and improving near-real-time convergence.
- Injected memory context now uses a budgeted planner with delta-state by default in smart/inject flows, to reduce repeated context tokens.
- Advanced controls, frontier ops, retrieval eval, and governance tuning are in `docs/advanced-ops.md`.

## For Maintainers

- npm publish flow: `docs/publish-npm.md`
- startup/OAuth QA checklist: `docs/qa-startup-guide.md`
- WebUI and sync configuration details: `docs/webui-config.md`
- advanced operations/evaluation/tuning: `docs/advanced-ops.md`
- OAuth broker deployment and quick-deploy buttons: `docs/oauth-broker.md`
- Reports are uploaded as artifact `core-merge-eval-artifacts` (`core_merge_report.json`, `core_merge_tune_dry_run.json`).

## Docs

- Chinese:
  - `README.zh-CN.md`
  - `docs/quickstart-10min.zh-CN.md`
  - `docs/webui-config.zh-CN.md`
  - `docs/oauth-broker.zh-CN.md`
  - `docs/qa-startup-guide.zh-CN.md`
  - `docs/publish-npm.zh-CN.md`
  - `docs/install-uninstall.zh-CN.md`
- English:
- `docs/quickstart-10min.md`
- `docs/webui-config.md`
- `docs/oauth-broker.md`
- `docs/qa-startup-guide.md`
- `docs/publish-npm.md`
- `docs/install-uninstall.md`
- `docs/advanced-ops.md`
