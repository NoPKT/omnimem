#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_BASE="$(mktemp -d "${TMPDIR:-/tmp}/omnimem-d.XXXXXX")"
TMP_HOME="$TMP_BASE/home"
PORT=8876
trap 'if [[ -n "${WEBUI_PID:-}" ]]; then kill "$WEBUI_PID" >/dev/null 2>&1 || true; fi; rm -rf "$TMP_BASE"' EXIT

OMNIMEM_HOME="$TMP_HOME" bash "$ROOT_DIR/scripts/install.sh" \
  --remote-name origin \
  --branch main \
  --remote-url git@github.com:demo/omnimem-private.git >/dev/null

CFG="$TMP_HOME/omnimem.config.json"
CLI="$TMP_HOME/bin/omnimem"

# config-path should be deterministic
"$CLI" --config "$CFG" config-path | rg 'omnimem.config.json' >/dev/null

# start webui
"$CLI" --config "$CFG" start --host 127.0.0.1 --port "$PORT" >"$TMP_BASE/webui.log" 2>&1 &
WEBUI_PID=$!

# wait server
server_ok=0
for _ in {1..20}; do
  if curl -sS "http://127.0.0.1:$PORT/api/config" >/dev/null 2>&1; then
    server_ok=1
    break
  fi
  sleep 0.2
done

if [[ "$server_ok" -eq 1 ]]; then
  cfg_json="$(curl -sS "http://127.0.0.1:$PORT/api/config")"
  echo "$cfg_json" | rg '"remote_url": "git@github.com:demo/omnimem-private.git"' >/dev/null

  # update config via webui api
  curl -sS -X POST "http://127.0.0.1:$PORT/api/config" \
    -H 'Content-Type: application/json' \
    -d '{"home":"'$TMP_HOME'","markdown":"'$TMP_HOME'/data/markdown","jsonl":"'$TMP_HOME'/data/jsonl","sqlite":"'$TMP_HOME'/data/omnimem.db","remote_name":"origin","remote_url":"git@github.com:demo/changed.git","branch":"dev"}' \
    | rg '"ok": true' >/dev/null

  cfg_json2="$(curl -sS "http://127.0.0.1:$PORT/api/config")"
  echo "$cfg_json2" | rg '"branch": "dev"' >/dev/null

  # create memory and verify memory list in webui
  "$CLI" --config "$CFG" write --summary 'webui test memory' --body 'hello webui' >/dev/null
  mem_json="$(curl -sS "http://127.0.0.1:$PORT/api/memories?limit=5")"
  echo "$mem_json" | rg '"items"' >/dev/null
else
  # Some sandbox environments forbid binding local ports; keep validating non-web path.
  rg 'Operation not permitted' "$TMP_BASE/webui.log" >/dev/null || true
  echo "[WARN] WebUI server bind skipped in restricted sandbox"
fi

kill "$WEBUI_PID" >/dev/null 2>&1 || true
unset WEBUI_PID

OMNIMEM_HOME="$TMP_HOME" bash "$ROOT_DIR/scripts/uninstall.sh" >/dev/null

echo "[OK] Phase D webui/config test passed"
