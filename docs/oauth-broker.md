# Optional GitHub OAuth Broker

Language: [English](oauth-broker.md) | [简体中文](oauth-broker.zh-CN.md)

Use this only to simplify GitHub OAuth login UX. It is not in memory sync data path.

## Minimum Steps (Recommended)

1. Deploy broker (one-click link or CLI).
2. Copy broker URL (for example: `https://xxx.workers.dev`).
3. In WebUI `Configuration`:
   - set `OAuth Broker URL`
   - click `Sign In via GitHub`

Sync still runs locally via Git on user machine.

Health check (replace `<BROKER_URL>`):

```bash
curl -sS -X POST "<BROKER_URL>/v1/github/device/start" \
  -H 'Content-Type: application/json' \
  -d '{}' | jq .
```

Expected: JSON error like `missing client_id` (endpoint reachable).

## One-Click Deploy Entry Points

- Cloudflare Worker:
  - `https://deploy.workers.cloudflare.com/?url=https://github.com/NoPKT/omnimem/tree/main/examples/oauth-broker/cloudflare-worker`
- Vercel:
  - `https://vercel.com/new/clone?repository-url=https://github.com/NoPKT/omnimem&root-directory=examples%2Foauth-broker%2Fvercel&project-name=omnimem-oauth-broker`
- Railway:
  - `https://railway.app/new/template?template=https://github.com/NoPKT/omnimem/tree/main/examples/oauth-broker/railway`
- Fly.io template reference:
  - `https://github.com/NoPKT/omnimem/tree/main/examples/oauth-broker/fly`

## CLI Fallback (Deterministic)

```bash
# readiness check
omnimem oauth-broker doctor

# one-command auto pipeline (doctor + init + deploy preview)
omnimem oauth-broker auto

# execute deploy
omnimem oauth-broker auto --apply
```

Manual (provider-explicit) example:

```bash
omnimem oauth-broker init --provider cloudflare --dir ./oauth-broker-cloudflare --client-id Iv1.your_client_id
omnimem oauth-broker deploy --provider cloudflare --dir ./oauth-broker-cloudflare --apply
```

## Startup Auto-Guide Integration

When sync/auth config is missing, `omnimem start` and `omnimem webui` can trigger startup guide and run OAuth broker setup flow.

Disable if needed:

- `--no-startup-guide`
- `OMNIMEM_STARTUP_GUIDE=0`

## Security Boundary (Important)

- Broker proxies only GitHub OAuth device flow (`start/poll`).
- Broker must not read/write OmniMem memory data.
- Broker should not persist access tokens long-term.
- Local token file remains at `<OMNIMEM_HOME>/runtime/github_oauth_token.json`.

## Minimal API Contract

- `POST /v1/github/device/start`
  - req: `{ "scope": "repo", "client_id": "optional" }`
  - resp: `{ "ok": true, "device_code": "...", "user_code": "...", "verification_uri": "...", "interval": 5, "expires_in": 900 }`
- `POST /v1/github/device/poll`
  - req: `{ "device_code": "...", "client_id": "optional" }`
  - pending: `{ "ok": true, "pending": true, "retry_after": 5 }`
  - success: `{ "ok": true, "access_token": "...", "token_type": "bearer", "scope": "repo" }`

## References

- templates: `examples/oauth-broker/`
- Cloudflare worker sample: `examples/oauth-broker/cloudflare-worker/cloudflare-worker.js`
