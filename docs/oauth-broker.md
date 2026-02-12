# Optional GitHub OAuth Broker

Use this only to simplify login UX. It is not used for memory sync data flow.

## Why

- Without broker: each user needs a local `gh` CLI login or a local OAuth client id.
- With broker: WebUI can start/poll device login through one shared endpoint.
- Sync remains local Git operations (`github-pull` / `github-push`) on the user machine.

## Quick Start (Automated)

Use the built-in CLI helper to scaffold and deploy broker templates:

```bash
# 1) Initialize provider template
omnimem oauth-broker init --provider cloudflare --dir ./oauth-broker-cloudflare --client-id Iv1.your_client_id

# 2) Preview deploy command
omnimem oauth-broker deploy --provider cloudflare --dir ./oauth-broker-cloudflare

# 3) Execute deploy
omnimem oauth-broker deploy --provider cloudflare --dir ./oauth-broker-cloudflare --apply
```

Or use guided mode (minimal prompts):

```bash
omnimem oauth-broker wizard
```

Pre-check readiness and suggested next actions:

```bash
omnimem oauth-broker doctor
```

Semi-automatic pipeline (doctor + init + deploy preview/apply):

```bash
# preview deploy command
omnimem oauth-broker auto

# actually deploy
omnimem oauth-broker auto --apply

# deploy and write broker_url into local omnimem config
omnimem oauth-broker auto --apply --set-config-broker-url --broker-url https://your-broker.example.com
```

Startup-triggered guide:

- `omnimem start` / `omnimem webui` can auto-prompt setup when sync/auth is missing.
- It uses one confirm step, then executes `oauth-broker auto --apply` automatically.
- If OmniMem detects a provider CLI that is already logged in and an available OAuth client id, it can auto-run without prompting.
- If OAuth client id is missing, startup guide asks once inline and then continues.
- If recommended provider CLI exists but is not logged in, startup guide can run provider login command and resume auto flow.
- It also attempts to auto-detect broker URL from deploy output and write local config directly.
- If URL detection fails, it will not block startup and prints a manual follow-up command.
- Disable via `--no-startup-guide` or env `OMNIMEM_STARTUP_GUIDE=0`.

Supported providers:

- `cloudflare`
- `vercel`
- `railway`
- `fly`

Provider templates live under `examples/oauth-broker/`.

## Threat model and scope

- Broker should only proxy GitHub OAuth device flow.
- Broker should not read/write OmniMem memory data.
- Broker should not store tokens long-term.
- Token is still persisted locally by OmniMem in runtime credential file.

## WebUI config

- `OAuth Broker URL (optional)`: e.g. `https://om-auth.example.workers.dev`
- Keep `OAuth Client ID` empty if broker handles client id.
- Click `Sign In via GitHub` and complete browser authorization.

## Broker API contract

- `POST /v1/github/device/start`
  - request json: `{ "scope": "repo", "client_id": "optional" }`
  - response json: `{ "ok": true, "device_code": "...", "user_code": "...", "verification_uri": "...", "verification_uri_complete": "...", "interval": 5, "expires_in": 900, "client_id": "optional" }`
- `POST /v1/github/device/poll`
  - request json: `{ "device_code": "...", "client_id": "optional" }`
  - response json (pending): `{ "ok": true, "pending": true, "error": "authorization_pending", "retry_after": 5 }`
  - response json (success): `{ "ok": true, "access_token": "...", "token_type": "bearer", "scope": "repo" }`

## Minimal Cloudflare Worker

See `examples/oauth-broker/cloudflare-worker/cloudflare-worker.js`.

Alternative templates:

- `examples/oauth-broker/vercel/`
- `examples/oauth-broker/railway/`
- `examples/oauth-broker/fly/`

Required secret/env:

- `GITHUB_OAUTH_CLIENT_ID` (or pass `client_id` from request if you allow it)

Recommended hardening:

- Rate limit by IP.
- Restrict origins (CORS allowlist).
- Keep request logs but never log access tokens.
- Return short error messages to clients.
- Set aggressive scale-to-zero/auto-sleep so idle traffic costs stay near zero.
