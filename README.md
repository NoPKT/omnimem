# OmniMem

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

## Publish and npx

After publishing to npm, end users can run:

```bash
npx -y omnimem
```

## Verification

```bash
bash scripts/verify_phase_a.sh
bash scripts/verify_phase_b.sh
bash scripts/verify_phase_c.sh
bash scripts/verify_phase_d.sh
```

## Docs

- `docs/quickstart-10min.md`
- `docs/webui-config.md`
- `docs/publish-npm.md`
- `docs/install-uninstall.md`
