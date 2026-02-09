# Changelog

## 0.2.2

- WebUI: fix unreachable `/api/memories` and `/api/layer-stats` routes (handler indentation bug).
- WebUI: add Maintenance panel and `POST /api/maintenance/decay` (preview/apply signal decay), and surface `memory.decay` in Governance Log filters.
- CLI: add `omnimem decay` subcommand (preview by default; `--apply` to commit).
- Storage: repair legacy SQLite schemas where `memory_refs`/`memory_events` foreign keys incorrectly reference `memories_old`.
