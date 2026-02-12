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

Docs/WebUI i18n automation:

- `python3 scripts/check_docs_i18n.py` validates bilingual doc pairs and language-navigation links.
- `python3 scripts/report_webui_i18n_coverage.py --out eval/webui_i18n_report.json` emits WebUI i18n coverage + hardcoded-text candidate report.

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

GitHub quick setup in WebUI:

- Config page now includes `GitHub Quick Setup` (repo `owner/repo`, protocol, optional create-if-missing).
- `Sign In via GitHub` starts browser auth (`gh auth login --web`) so you can authenticate without manually creating SSH keys/tokens in OM.
- Pure OAuth path (no local `gh` required): set `OAuth Client ID`, click `Sign In via GitHub`, authorize in browser, then click `Complete OAuth Login`.
- OAuth login now auto-polls after start; manual `Complete OAuth Login` remains available as fallback.
- Optional `OAuth Broker URL` can offload device-flow start/poll to a lightweight service (Cloudflare/Fly/Vercel/Railway), while memory sync still stays local.
- OAuth token is stored locally at `<OMNIMEM_HOME>/runtime/github_oauth_token.json` (outside synced markdown/jsonl data) and used for HTTPS Git sync auth via `GIT_ASKPASS`.
- `Check GitHub Auth` uses local `gh auth status` (if `gh` is installed).
- `Refresh Repo List` can pull account-visible repos (via `gh repo list`) and fill `owner/repo` by selection.
- `Apply GitHub Setup` writes sync remote config without manually pasting long remote URLs.
- Optional repo auto-create requires authenticated `gh` CLI on the server host.

Optional OAuth broker deploy shortcuts (auth-only service, no memory data path):

- [![Cloudflare Broker](https://img.shields.io/badge/OAuth%20Broker-Cloudflare-f38020?logo=cloudflare&logoColor=white)](docs/oauth-broker.md#quick-start-automated)
- [![Vercel Broker](https://img.shields.io/badge/OAuth%20Broker-Vercel-black?logo=vercel&logoColor=white)](docs/oauth-broker.md#quick-start-automated)
- [![Railway Broker](https://img.shields.io/badge/OAuth%20Broker-Railway-0B0D0E?logo=railway&logoColor=white)](docs/oauth-broker.md#quick-start-automated)
- [![Fly Broker](https://img.shields.io/badge/OAuth%20Broker-Fly.io-7B3FF2?logo=flydotio&logoColor=white)](docs/oauth-broker.md#quick-start-automated)
- CLI automation:
  - `omnimem oauth-broker init --provider cloudflare --dir ./oauth-broker-cloudflare --client-id Iv1.your_client_id`
  - `omnimem oauth-broker deploy --provider cloudflare --dir ./oauth-broker-cloudflare --apply`
  - `omnimem oauth-broker wizard` (guided mode with minimal prompts)
  - `omnimem oauth-broker doctor` (readiness diagnostics + suggested fixes)
  - `omnimem oauth-broker auto --apply` (doctor + auto-select provider + init + deploy)

Startup auto-guidance:

- `omnimem start` / `omnimem webui` now auto-detect missing sync/auth config in interactive terminals and can launch guided setup automatically.
- Startup guide uses a single confirmation prompt, then runs broker `auto --apply` directly.
- If OmniMem detects an already authenticated provider CLI and available OAuth client id, startup guide auto-runs without prompt.
- If OAuth client id is missing, startup guide asks once inline and reuses that value for auto deploy.
- If recommended provider CLI is installed but not logged in, startup guide can run its login command and continue automatically.
- When deploy output contains a service URL, OmniMem auto-writes `sync.github.oauth.broker_url` (no manual paste needed).
- If URL auto-detection fails, startup still continues and prints a one-line follow-up command for manual URL write-back.
- Disable once permanently in prompt via `never`, or disable explicitly with `--no-startup-guide`.
- Environment switch: `OMNIMEM_STARTUP_GUIDE=0` disables startup guidance globally.

Nightly memory-eval workflow:

- GitHub Actions `nightly-memory-eval` runs `eval_core_merge` + `tune_core_merge_from_eval --dry-run` on deterministic seeded core blocks.
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
