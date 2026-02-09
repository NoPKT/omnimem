# Changelog

## 0.2.5

- Codex UX: `omnimem codex` now defaults to a smart start mode that keeps native interaction while enabling OmniMem guidance and context.
- Codex Memory: add `--auto-write` background watcher that captures Codex session turns from `~/.codex/sessions` into OmniMem (best-effort, skips obvious secrets).
- Project integration: auto-create minimal `.omnimem.json` / `.omnimem-session.md` / `.omnimem-ignore` / `AGENTS.md` when missing; add `templates/project-minimal/AGENTS.md`.
- WebUI: fix `GET /api/memory` DB connection usage bug.

## 0.2.4

- CLI: `omnimem codex/claude` now behave like the native tools by default; pass `--agent` to re-enable the OmniMem orchestrator path.
- Core: `_rebuild_child_tables` can run inside existing transactions, enabling legacy schemas to be migrated to the `kind IN (...)` check that allows `retrieve`.

## 0.2.2

- WebUI: fix unreachable `/api/memories` and `/api/layer-stats` routes (handler indentation bug).
- WebUI: add Maintenance panel and `POST /api/maintenance/decay` (preview/apply signal decay), and surface `memory.decay` in Governance Log filters.
- CLI: add `omnimem decay` subcommand (preview by default; `--apply` to commit).
- Storage: repair legacy SQLite schemas where `memory_refs`/`memory_events` foreign keys incorrectly reference `memories_old`.
