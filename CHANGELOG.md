# Changelog

## Unreleased

- Profile modeling: add deterministic user profile builder (`omnimem profile`) and WebUI API endpoint (`GET /api/profile`) to summarize preferences/goals/focus tags from memory traces.
- Ingestion: add `omnimem ingest` for URL/file/text sources with safe URL query redaction and structured source refs, improving external knowledge onboarding workflow.
- Ingestion upgrade: support structured chunking (`--chunk-mode heading|fixed`) with multi-memory writes and chunk metadata for long document ingestion.
- Feedback loop: add explicit memory feedback operation (`omnimem feedback` / `POST /api/memory/feedback`) supporting positive/negative/forget/correct signals with deterministic score updates.
- Retrieval upgrade: add profile-aware re-ranking (`retrieve --profile-aware`) and expose profile settings in retrieval explain output; WebUI smart retrieval now enables profile bias by default.

## 0.2.21 - 2026-02-11

- Release workflow: add one-command release gate script `scripts/release_gate.sh` to run preflight, doctor, pack dry-run, phase-D verification, and frontier smoke checks.
- CI: keep frontier smoke checks in CI and align docs/scripts so local pre-publish flow matches automated checks.
- Release automation: add `scripts/release_prepare.sh` (`npm run release:prepare`) to compute next semver, build release draft notes, and optionally apply version/changelog updates.

## 0.2.20

- Retrieval frontier: `retrieve_thread` now exposes deterministic self-check (`coverage`, `missing_tokens`, `confidence`) and end-to-end pipeline timing metrics (`seed/graph/materialize/total`), with optional adaptive feedback to increment reuse on retrieved memories.
- New memory operations: add `omnimem raptor` (RAPTOR-style hierarchical digest builder) and `omnimem enhance` (heuristic summary enhancement) with preview-by-default and `--apply` write mode.
- WebUI smart retrieval: enable self-check + adaptive feedback in advanced retrieval path and surface self-check coverage/confidence in the retrieval hint for faster quality inspection.
- Evaluation tooling: add `scripts/eval_locomo_style.py` plus sample dataset `eval/locomo_style.sample.jsonl` for offline long-conversation retrieval scoring.
- Tests: add frontier regression coverage for self-check/timing metrics, adaptive feedback behavior, CLI parser wiring, and digest/enhance preview flow.
- Versioning: align Python runtime version and npm package version to `0.2.20`.

## 0.2.19

- Release guard: add `omnimem preflight` and block clean-worktree releases by default; update publish docs and README pre-check flow.
- Retrieval ranking: tune cognitive scoring to gate reuse bonus by lexical relevance, reducing weak-match domination; add regression tests.
- Doctor diagnostics: enrich `omnimem doctor` with daemon sync latency signals and recent `memory.sync` failure aggregation (`failure_rate`, error-kind distribution, dominant failure issues).
- WebUI memories: add `dedup` query mode (`off` / `summary+kind`), compact `why` line rendering controls, and return dedup metadata (`before`/`after`).
- WebUI cleanup: refactor duplicated memories filtering logic into shared helpers (`_apply_memory_filters`, `_dedup_memory_items`) and simplify front-end query URL assembly.
- Versioning: align Python runtime version and npm package version to `0.2.19`.

## 0.2.18

- CLI: add `omnimem doctor` diagnostics with actionable remediation hints for WebUI runtime health, daemon status, sync readiness, and storage verification.
- Sync daemon: trigger GitHub push checks on `mtime_or_dirty` (not only mtime) so local commits are propagated even when repository timestamps do not move as expected.
- Versioning: align Python runtime version and npm package version to `0.2.18`.

## 0.2.17

- WebUI: add maintenance impact forecast + progressive disclosure UX (`risk_level`, expected touches, and collapsible explain details) and fix Guided Check preview counters to consume forecast output consistently.
- Wrapper lifecycle: `omnimem codex/claude` now default to on-demand sidecar lifecycle and emit daemon sync-status hints on startup when auto-sync is disabled or unhealthy.
- Runtime coordination: move sidecar pid/lease/marker coordination to a per-user global runtime directory (keyed by `host:port`), decoupling parallel wrapper safety from `OMNIMEM_HOME` and reducing `address already in use` issues across projects.
- CLI: add `omnimem stop` / `omnimem stop --all` for explicit sidecar cleanup and endpoint-level troubleshooting.
- Versioning: align Python runtime version and npm package version to `0.2.17`.

## 0.2.14

- WebUI: add on-demand sidecar lifecycle for `omnimem codex/claude` via `--webui-on-demand` (or `OMNIMEM_WEBUI_ON_DEMAND=1`). WebUI auto-stops when the last active wrapper session exits.

## 0.2.13

- WebUI security: require an API token when binding to a non-local host (in addition to `--allow-non-localhost`) so `/api/*` is not exposed unauthenticated on LAN/WAN.
- WebUI reliability: sidecar liveness probe now checks `/` instead of `/api/health` to avoid false negatives against older WebUI versions (reduces redundant respawns / port-in-use churn).
- Core: make config writes atomic (tempfile + fsync + replace) and best-effort restrict permissions to 0600.
- Bootstrap: use `git pull --rebase --autostash` to reduce failures when local modifications exist.
- DevX: add `requirements-dev.txt`, `npm run test`, and GitHub Actions CI; `npm run pack:check` uses a local npm cache to avoid permissions issues from a broken global cache.

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

## 0.2.12

- Auto graph maintenance: sync daemon now periodically runs `weave_links` when content changes or after a successful pull+reindex, so users don't need to run `omnimem weave` manually.
- Retrieval: `retrieve_thread` can best-effort auto-weave (guarded) when the graph is empty and no daemon is running.

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
