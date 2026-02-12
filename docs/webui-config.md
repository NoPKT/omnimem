# WebUI and Configuration

Default config path:

- `$OMNIMEM_HOME/omnimem.config.json`
- fallback: `~/.omnimem/omnimem.config.json`

Start app:

```bash
~/.omnimem/bin/omnimem
```

Security defaults:

- WebUI binds to local host by default (`127.0.0.1`).
- Binding a non-local host requires explicit `--allow-non-localhost`.
- Optional API token auth:

```bash
OMNIMEM_WEBUI_TOKEN='your-token' ~/.omnimem/bin/omnimem start
# or
~/.omnimem/bin/omnimem start --webui-token 'your-token'
```

When token auth is enabled, API requests must include header `X-OmniMem-Token: <token>`.

Daemon retry tuning (optional):

```bash
~/.omnimem/bin/omnimem start \
  --daemon-retry-max-attempts 4 \
  --daemon-retry-initial-backoff 1 \
  --daemon-retry-max-backoff 8
```

WebUI provides:

- Status & actions tab
- Configuration tab
- Memory browser tab
- Daemon toggle and bootstrap sync action
- Daemon metrics via `/api/daemon` (`success_count`, `failure_count`, retry settings, last run timestamps)
- Daemon API schema: `spec/daemon-state.schema.json`
- Failure kind classification in daemon metrics: `auth`, `network`, `conflict`, `unknown`
- Remediation guidance is returned as `remediation_hint` in `/api/daemon`
- When `last_error_kind=conflict`, WebUI shows a one-click recovery flow (`status -> pull -> push`)
- Maintenance dashboard summary via `/api/maintenance/summary` (recent runs/decay/promote/demote and event counts)
- Runtime health diagnosis via `/api/health/check` (sqlite reachability, daemon status, fd pressure)
- Memory-level governance explainability via `/api/governance/explain?id=<memory_id>&adaptive=1&days=14`
- Memory route retrieval in WebUI (`auto`/`episodic`/`semantic`/`procedural`) for intent-aware filtering
- Drawer actions: `Undo Last Move` and one-click memory typing tags (`mem:episodic`, `mem:semantic`, `mem:procedural`)
- Drawer move history with event-level undo (`/api/memory/move-history`, `/api/memory/undo-move-event`)
- Drawer supports rollback to timestamp (`/api/memory/rollback-to-time`)
- Drawer supports rollback preview (`/api/memory/rollback-preview`) with before/after layer diff
- Insights quality panel (`/api/quality/summary`) with week-over-week deltas for conflicts/reuse/decay/writes and signal averages
- Quality panel now returns alert hints (`alerts`) and supports preview actions from UI
- Layer Board batch typing (`/api/memory/tag-batch`) for selected cards
- Layer Board supports route templates (save/apply) for faster episodic/semantic/procedural labeling workflows
- Route templates can be persisted server-side (`/api/route-templates`) and shared across sessions/devices via config sync
- Optional approval gate for apply actions: `webui.approval_required=true`
- Optional preview-only window for maintenance apply: `webui.maintenance_preview_only_until=<ISO-8601 UTC>`
- GitHub quick auth/setup actions on Config tab:
  - `Sign In via GitHub`: launches browser auth via local `gh auth login --web`
  - Pure OAuth device flow (no `gh` needed): fill `OAuth Client ID`, click `Sign In via GitHub`; WebUI auto-polls completion (manual `Complete OAuth Login` is also available)
  - Optional OAuth broker mode: set `OAuth Broker URL` to route device-flow `start/poll` via a lightweight server while keeping sync local-only
  - `Check GitHub Auth`: checks local `gh auth status`
  - `Refresh Repo List` + `Use Selected Repo`: pick `owner/repo` from `gh repo list`
  - `Apply GitHub Setup`: writes sync remote settings from selected protocol/repo

OAuth token handling:

- Token file is stored at `<OMNIMEM_HOME>/runtime/github_oauth_token.json` by default.
- Git sync (`github-pull`/`github-push`) uses this token via `GIT_ASKPASS` for `https://github.com/...` remotes.
- Do not commit token files; runtime folder is excluded from sync.
- See `docs/oauth-broker.md` for broker API contract and a Cloudflare Worker reference implementation.

Recommended safe rollout:

```bash
PYTHONPATH=. python3 scripts/enable_governance_preview.py --days 7
```

After preview period, disable or clear `webui.maintenance_preview_only_until` in config and keep `approval_required=true`.
