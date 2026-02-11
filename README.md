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

## Publish and npx

Pre-check before npm publish:

```bash
npm run release:gate
```

Prepare next release draft (dry-run):

```bash
npm run release:prepare
```

Optional (partial gate):

```bash
bash scripts/release_gate.sh --skip-doctor --project-id OM --home ./.omnimem_gate
```

After publishing to npm, end users can run:

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

Frontier memory ops (preview by default):

```bash
omnimem raptor --project-id OM
omnimem enhance --project-id OM
omnimem profile --project-id OM
omnimem profile-drift --project-id OM --recent-days 14 --baseline-days 120
omnimem core-set --project-id OM --name persona --body "Be concise, explicit, and test-first." --priority 80
omnimem core-set --project-id OM --name style-a --topic style --body "Use short bullets." --priority 60
omnimem core-set --project-id OM --name style-b --topic style --body "Use numbered technical lists." --priority 90
omnimem core-set --project-id OM --name temporary-guardrail --body "Prefer safe default ops." --ttl-days 7
omnimem core-merge-suggest --project-id OM --min-conflicts 2
omnimem core-merge-suggest --project-id OM --min-conflicts 2 --apply
omnimem core-merge-suggest --project-id OM --apply --loser-action deprioritize --min-apply-quality 0.25
omnimem core-merge-suggest --project-id OM --merge-mode synthesize --max-merged-lines 6
omnimem core-merge-suggest --project-id OM --merge-mode semantic --max-merged-lines 6
omnimem core-list --project-id OM
omnimem core-list --project-id OM --include-expired
omnimem core-get --project-id OM --name persona
omnimem retrieve "workflow guide" --project-id OM --drift-aware --drift-weight 0.4 --explain
omnimem retrieve "workflow guide" --project-id OM --include-core-blocks --core-block-limit 2 --explain
omnimem retrieve "workflow guide" --project-id OM --include-core-blocks --core-merge-by-topic --explain
omnimem ingest --type url "https://example.com/doc?token=***"
omnimem ingest --type file ./docs/notes.md
omnimem ingest --type file ./docs/design.md --chunk-mode heading --max-chunks 12
omnimem ingest --type text --text "..." --chunk-mode fixed --chunk-chars 1800
omnimem feedback --id <memory_id> --feedback positive --note "high value"
omnimem sync --mode github-push --sync-layers long,archive --no-sync-include-jsonl
omnimem prune --project-id OM --days 45 --layers instant,short --keep-kinds decision,checkpoint
omnimem prune --project-id OM --days 45 --layers instant,short --keep-kinds decision,checkpoint --apply
```

Offline LoCoMo-style retrieval eval:

```bash
python3 scripts/eval_locomo_style.py --dataset eval/locomo_style.sample.jsonl
```

Retrieval A/B eval (basic vs smart vs smart+drift-aware):

```bash
python3 scripts/eval_retrieval.py --dataset eval/retrieval_dataset_om.json --with-drift-ab --drift-weight 0.4
```

Core merge mode eval (concat vs synthesize vs semantic):

```bash
python3 scripts/eval_core_merge.py --project-id OM --modes concat,synthesize,semantic --max-merged-lines 6
```

Tune `core-merge-suggest` defaults from the merge eval report:

```bash
python3 scripts/tune_core_merge_from_eval.py --report eval/core_merge_report_om.json
python3 scripts/tune_core_merge_from_eval.py --report eval/core_merge_report_om.json --dry-run
```

Single turn:

```bash
omnimem codex "your request"
omnimem claude "your request"
```

Advanced controls (optional):

```bash
omnimem codex --project-id <project_id> --drift-threshold 0.62 --cwd /path/to/project
omnimem claude --project-id <project_id> --drift-threshold 0.62 --cwd /path/to/project
omnimem codex --smart --context-budget-tokens 420
omnimem codex --smart --no-delta-context
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
- For safer governance rollout in WebUI, you can enable apply approval and a preview-only window in Configuration:
  - `webui.approval_required=true`
  - `webui.maintenance_preview_only_until=<ISO-8601 UTC>`

## Retrieval/Governance Evaluation Helpers

Bootstrap a retrieval eval dataset from recent memories:

```bash
PYTHONPATH=. python3 scripts/build_eval_dataset.py --project-id OM --limit 60 --out eval/retrieval_dataset_om.json
```

Run retrieval quality evaluation (`basic` vs `smart` vs `smart_drift`):

```bash
PYTHONPATH=. python3 scripts/eval_retrieval.py --dataset eval/retrieval_dataset_om.json --with-drift-ab --drift-weight 0.4 --out eval/retrieval_report_om.json
```

Distill one session into compact semantic/procedural memories (preview by default):

```bash
PYTHONPATH=. python3 -m omnimem.cli distill --project-id OM --session-id <session_id>
PYTHONPATH=. python3 -m omnimem.cli distill --project-id OM --session-id <session_id> --apply
```

Profile-aware retrieval (optional):

```bash
PYTHONPATH=. python3 -m omnimem.cli retrieve "workflow guide" --project-id OM --profile-aware --profile-weight 0.5 --explain
```

Tune daemon adaptive governance quantiles from the eval report:

```bash
PYTHONPATH=. python3 scripts/tune_governance_from_eval.py --report eval/retrieval_report_om.json
```

`core-merge-suggest` also supports config-driven defaults (overridden by CLI flags):

```json
{
  "core_merge": {
    "default_limit": 120,
    "default_min_conflicts": 2,
    "default_merge_mode": "semantic",
    "default_max_merged_lines": 6,
    "default_min_apply_quality": 0.3,
    "default_loser_action": "deprioritize"
  }
}
```

Enable a temporary preview-only governance window:

```bash
PYTHONPATH=. python3 scripts/enable_governance_preview.py --days 7
```

## Verification

```bash
bash scripts/verify_phase_a.sh
bash scripts/verify_phase_b.sh
bash scripts/verify_phase_c.sh
bash scripts/verify_phase_d.sh
```

CI-parity checks (same shape as GitHub Actions):

```bash
python3 -m pytest -q
bash scripts/release_gate.sh --allow-clean --skip-doctor --skip-pack --project-id OM --home ./.omnimem_gate
NPM_CONFIG_CACHE=./.npm-cache npm pack --dry-run
```

If `npm pack --dry-run` fails with cache permission errors (`EPERM` under `~/.npm`), run it with a writable cache:

```bash
NPM_CONFIG_CACHE=./.npm-cache npm pack --dry-run
```

`scripts/release_gate.sh` now supports environments without a global `omnimem` binary (e.g. CI): it auto-falls back to `python -m omnimem.cli`.

Git sync size-control options:

- `sync.github.include_layers`: markdown layers to include in Git sync (e.g. `["long","archive"]`).
- `sync.github.include_jsonl`: whether to include `data/jsonl` event files in Git sync (default `true`).
- CLI overrides: `omnimem sync --sync-layers long,archive --no-sync-include-jsonl`.
- Same options are also respected by WebUI-triggered sync and daemon background sync.

Optional daemon prune maintenance (default off):

- WebUI/`start` flags: `--daemon-maintenance-prune-enabled`, `--daemon-maintenance-prune-days`, `--daemon-maintenance-prune-limit`, `--daemon-maintenance-prune-layers`, `--daemon-maintenance-prune-keep-kinds`.
- Config keys under `daemon`: `maintenance_prune_enabled`, `maintenance_prune_days`, `maintenance_prune_limit`, `maintenance_prune_layers`, `maintenance_prune_keep_kinds`.
- Recommended safe baseline: keep prune disabled until you validate `omnimem prune` preview output for your dataset.

Nightly memory-eval workflow:

- GitHub Actions `nightly-memory-eval` runs `eval_core_merge` + `tune_core_merge_from_eval --dry-run` on deterministic seeded core blocks.
- Reports are uploaded as artifact `core-merge-eval-artifacts` (`core_merge_report.json`, `core_merge_tune_dry_run.json`).

## Docs

- `docs/quickstart-10min.md`
- `docs/webui-config.md`
- `docs/publish-npm.md`
- `docs/install-uninstall.md`
