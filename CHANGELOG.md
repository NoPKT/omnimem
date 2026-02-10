# Changelog

## 0.2.9

- Sync: add cross-process repo lock to prevent WebUI/daemon/CLI from mutating storage during Git operations (reduces conflict/corruption risk).
- Sync: keep Git snapshots focused on portable artifacts by auto-maintaining a `.gitignore` and untracking common runtime/install/SQLite files in the memory repo.
- Sync: improve `github-pull` robustness for root commits/unrelated histories and auto-resolve add/add conflicts for `data/jsonl/events-*.jsonl` when safe.
- Sync: make `memory.sync` events non-portable (SQLite only) to avoid leaving the repo dirty after sync operations.
- WebUI: add Simple/Advanced mode toggle, hide noisy advanced panels by default, and show build version via `/api/version`.

## 0.2.10

- Find: make `omnimem find` resilient to FTS5 query syntax (e.g. `v0.2.6`) by normalizing punctuation and retrying multiple safe FTS variants.
- Find: add automatic fallback to a LIKE-based search when FTS fails/returns empty, plus `--explain`, `--project-id`, `--session-id` filters.

## 0.2.11

- Memory graph: add `memory_links` table and `omnimem weave` to build a lightweight relationship graph (derived, heuristic links).
- Retrieval: add `omnimem retrieve` for progressive multi-hop retrieval (seed shallow, then pull deeper via links) with optional explanations.
- Agent: switch agent retrieval to graph-aware `retrieve_thread` when available.
- Codex UX: make the injected first line short + unique so Codex resume list entries are distinguishable.
- Robustness: `weave` retries on SQLite busy/locked instead of requiring manual process killing; optional `--max-wait-s`.

## 0.2.8

- WebUI: fix another JS syntax error (`lines.join('\n')` in Python triple-quoted HTML emitted a literal newline in a JS string).

## 0.2.7

- WebUI: fix a JS syntax error in the in-place editor (`stripMdTitle`) that could break all UI actions and i18n.

## 0.2.6

- Sync: `github-pull` now uses `git pull --rebase --autostash` to avoid failures when the memory repo has local modifications.
- WebUI: add in-place editing for memory `summary/tags/body` with a new `POST /api/memory/update`.
- WebUI: improve layer visibility with clickable layer stats pills and a shortcut to the Insights Layer Board.

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
