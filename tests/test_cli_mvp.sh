#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_HOME="$(mktemp -d "${TMPDIR:-/tmp}/omnimem-b.XXXXXX")"
trap 'rm -rf "$TMP_HOME"' EXIT

cat > "$TMP_HOME/omnimem.config.json" <<JSON
{
  "version": "0.1.0",
  "home": "$TMP_HOME",
  "storage": {
    "markdown": "$TMP_HOME/data/markdown",
    "jsonl": "$TMP_HOME/data/jsonl",
    "sqlite": "$TMP_HOME/data/omnimem.db"
  }
}
JSON

OM="PYTHONPATH=$ROOT_DIR python3 -m omnimem.cli --config $TMP_HOME/omnimem.config.json"

assert_pipe_contains() {
  local needle="$1"
  if command -v rg >/dev/null 2>&1; then
    rg -F -- "$needle" >/dev/null
  else
    grep -F -- "$needle" >/dev/null
  fi
}

# write
sh -c "$OM write --layer short --kind note --summary 'test summary' --body 'hello memory world' --project-id demo --tags a,b"

# checkpoint
sh -c "$OM checkpoint --summary 'phase checkpoint' --goal 'ship mvp' --result 'done A' --next-step 'start B' --risks 'none' --project-id demo"

# find
find_out="$(sh -c "$OM find memory --limit 5")"
echo "$find_out" | assert_pipe_contains '"ok": true'

# brief
brief_out="$(sh -c "$OM brief --project-id demo --limit 5")"
echo "$brief_out" | assert_pipe_contains '"project_id": "demo"'

# verify
sh -c "$OM verify" | assert_pipe_contains '"ok": true'

# sync placeholder
sh -c "$OM sync --mode noop" | assert_pipe_contains '"ok": true'

# hard assertions
mem_count="$(sqlite3 "$TMP_HOME/data/omnimem.db" "SELECT count(*) FROM memories;")"
evt_count="$(sqlite3 "$TMP_HOME/data/omnimem.db" "SELECT count(*) FROM memory_events;")"
[[ "$mem_count" -ge 3 ]] || { echo "[FAIL] memories count too small: $mem_count"; exit 1; }
[[ "$evt_count" -ge 4 ]] || { echo "[FAIL] memory_events count too small: $evt_count"; exit 1; }

echo "[OK] Phase B CLI MVP test passed"
