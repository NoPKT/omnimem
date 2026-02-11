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
- Optional approval gate for apply actions: `webui.approval_required=true`
- Optional preview-only window for maintenance apply: `webui.maintenance_preview_only_until=<ISO-8601 UTC>`

Recommended safe rollout:

```bash
PYTHONPATH=. python3 scripts/enable_governance_preview.py --days 7
```

After preview period, disable or clear `webui.maintenance_preview_only_until` in config and keep `approval_required=true`.
