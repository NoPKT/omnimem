# WebUI and Configuration

Language: [English](webui-config.md) | [简体中文](webui-config.zh-CN.md)

## Recommended Defaults

Most users only need this:

```bash
~/.omnimem/bin/omnimem start
```

Then open:

- `http://127.0.0.1:8765`

Default config path:

- `$OMNIMEM_HOME/omnimem.config.json`
- fallback: `~/.omnimem/omnimem.config.json`

## GitHub Sync Setup (Recommended UI Path)

In WebUI `Configuration` tab:

- `GitHub Quick Setup`
- `Sign In via GitHub`
- select/create repo
- `Apply GitHub Setup`

This keeps memory sync local (Git operations on your machine).

## Advanced Options (Only If Needed)

### WebUI auth token

```bash
OMNIMEM_WEBUI_TOKEN='your-token' ~/.omnimem/bin/omnimem start
# or
~/.omnimem/bin/omnimem start --webui-token 'your-token'
```

When enabled, API calls must include `X-OmniMem-Token: <token>`.

### Non-local bind

Only use when you understand network exposure:

```bash
~/.omnimem/bin/omnimem start --host 0.0.0.0 --allow-non-localhost --webui-token 'your-token'
```

### Daemon retry tuning

```bash
~/.omnimem/bin/omnimem start \
  --daemon-retry-max-attempts 4 \
  --daemon-retry-initial-backoff 1 \
  --daemon-retry-max-backoff 8
```

### OAuth broker (optional)

Use only to simplify OAuth login UX for users without local CLI auth.

- docs: `docs/oauth-broker.md`
- broker handles only OAuth device flow start/poll, not memory data transport

## Risk and Safety Notes

- Keep WebUI on localhost by default.
- If you expose WebUI (`--allow-non-localhost`), always enable token auth.
- Token file path: `<OMNIMEM_HOME>/runtime/github_oauth_token.json`.
- Never commit token/runtime files.
- For startup/auth diagnostics, run:

```bash
omnimem doctor
```

## Feature Map (Reference)

WebUI includes:

- status/actions/config/memory tabs
- daemon metrics, health check, and conflict recovery hints
- governance/maintenance preview workflows
- layer board + route templates + batch tagging
- multilingual UI labels and localized tooltip generation

For full API/details, see:

- `docs/advanced-ops.md`
- `spec/daemon-state.schema.json`
