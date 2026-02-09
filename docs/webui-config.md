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
