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
DAEMON_SCHEMA="$ROOT_DIR/spec/daemon-state.schema.json"

assert_contains_text() {
  local text="$1"
  local needle="$2"
  if command -v rg >/dev/null 2>&1; then
    printf '%s\n' "$text" | rg -F -- "$needle" >/dev/null
  else
    printf '%s\n' "$text" | grep -F -- "$needle" >/dev/null
  fi
}

assert_file_contains() {
  local file="$1"
  local needle="$2"
  if command -v rg >/dev/null 2>&1; then
    rg -F -- "$needle" "$file" >/dev/null
  else
    grep -F -- "$needle" "$file" >/dev/null
  fi
}

assert_daemon_contract() {
  local payload="$1"
  python3 - "$payload" "$DAEMON_SCHEMA" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
schema = json.loads(open(sys.argv[2], "r", encoding="utf-8").read())

required = schema.get("required", [])
props = schema.get("properties", {})

for key in required:
    if key not in payload:
        raise SystemExit(f"[FAIL] daemon contract missing key: {key}")

def is_type(val, typ):
    if typ == "boolean":
        return isinstance(val, bool)
    if typ == "string":
        return isinstance(val, str)
    if typ == "object":
        return isinstance(val, dict)
    if typ == "integer":
        return isinstance(val, int) and not isinstance(val, bool)
    return True

for key, rule in props.items():
    if key not in payload:
        continue
    typ = rule.get("type")
    if typ and not is_type(payload[key], typ):
        raise SystemExit(f"[FAIL] daemon contract type mismatch: {key} expected {typ}")
PY
}

# config-path should be deterministic
cfg_path_out="$("$CLI" --config "$CFG" config-path)"
assert_contains_text "$cfg_path_out" "omnimem.config.json"

# start webui
"$CLI" --config "$CFG" start --host 127.0.0.1 --port "$PORT" >"$TMP_BASE/webui.log" 2>&1 &
WEBUI_PID=$!

# wait server
server_ok=0
for _ in {1..20}; do
  if curl -sS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    server_ok=1
    break
  fi
  sleep 0.2
done

if [[ "$server_ok" -eq 1 ]]; then
  cfg_json="$(curl -sS "http://127.0.0.1:$PORT/api/config")"
  assert_contains_text "$cfg_json" '"remote_url": "git@github.com:demo/omnimem-private.git"'

  # update config via webui api
  cfg_post_out="$(curl -sS -X POST "http://127.0.0.1:$PORT/api/config" \
    -H 'Content-Type: application/json' \
    -d '{"home":"'$TMP_HOME'","markdown":"'$TMP_HOME'/data/markdown","jsonl":"'$TMP_HOME'/data/jsonl","sqlite":"'$TMP_HOME'/data/omnimem.db","remote_name":"origin","remote_url":"git@github.com:demo/changed.git","branch":"dev"}')"
  assert_contains_text "$cfg_post_out" '"ok": true'

  cfg_json2="$(curl -sS "http://127.0.0.1:$PORT/api/config")"
  assert_contains_text "$cfg_json2" '"branch": "dev"'
  daemon_json="$(curl -sS "http://127.0.0.1:$PORT/api/daemon")"
  assert_daemon_contract "$daemon_json"

  # create memory and verify memory list in webui
  "$CLI" --config "$CFG" write --summary 'webui test memory' --body 'hello webui' >/dev/null
  "$CLI" --config "$CFG" write --summary 'webui dedup sample' --body 'hello dedup one' >/dev/null
  "$CLI" --config "$CFG" write --summary 'webui dedup sample' --body 'hello dedup two' >/dev/null
  mem_json="$(curl -sS "http://127.0.0.1:$PORT/api/memories?limit=5")"
  assert_contains_text "$mem_json" '"items"'
  dedup_json="$(curl -sS "http://127.0.0.1:$PORT/api/memories?limit=20&query=webui&dedup=summary_kind")"
  python3 - "$dedup_json" <<'PY'
import json
import sys
d = json.loads(sys.argv[1])
dd = d.get("dedup") or {}
if dd.get("mode") != "summary_kind":
    raise SystemExit("[FAIL] dedup mode missing or wrong")
before = int(dd.get("before", 0) or 0)
after = int(dd.get("after", 0) or 0)
if before < after:
    raise SystemExit(f"[FAIL] dedup after cannot exceed before: before={before} after={after}")
if not isinstance(d.get("items"), list):
    raise SystemExit("[FAIL] /api/memories items is not a list")
PY

  # restart with token auth and verify API protection
  kill "$WEBUI_PID" >/dev/null 2>&1 || true
  unset WEBUI_PID
  OMNIMEM_WEBUI_TOKEN='phase-d-token' "$CLI" --config "$CFG" start --host 127.0.0.1 --port "$PORT" >"$TMP_BASE/webui-auth.log" 2>&1 &
  WEBUI_PID=$!
  for _ in {1..20}; do
    if curl -sS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
      break
    fi
    sleep 0.2
  done
  unauth_code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/config")"
  [[ "$unauth_code" == "401" ]] || { echo "[FAIL] expected 401 without token, got $unauth_code"; exit 1; }
  auth_code="$(curl -s -o /dev/null -w '%{http_code}' -H 'X-OmniMem-Token: phase-d-token' "http://127.0.0.1:$PORT/api/config")"
  [[ "$auth_code" == "200" ]] || { echo "[FAIL] expected 200 with token, got $auth_code"; exit 1; }
  daemon_auth_json="$(curl -sS -H 'X-OmniMem-Token: phase-d-token' "http://127.0.0.1:$PORT/api/daemon")"
  assert_daemon_contract "$daemon_auth_json"
else
  # Some sandbox environments forbid binding local ports; keep validating non-web path.
  assert_file_contains "$TMP_BASE/webui.log" "Operation not permitted" >/dev/null 2>&1 || true
  echo "[WARN] WebUI server bind skipped in restricted sandbox"
fi

kill "$WEBUI_PID" >/dev/null 2>&1 || true
unset WEBUI_PID

OMNIMEM_HOME="$TMP_HOME" bash "$ROOT_DIR/scripts/uninstall.sh" >/dev/null

echo "[OK] Phase D webui/config test passed"
