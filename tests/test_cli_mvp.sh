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

# write
sh -c "$OM write --layer short --kind note --summary 'test summary' --body 'hello memory world' --project-id demo --tags a,b"

# checkpoint
sh -c "$OM checkpoint --summary 'phase checkpoint' --goal 'ship mvp' --result 'done A' --next-step 'start B' --risks 'none' --project-id demo"

# find
find_out="$(sh -c "$OM find memory --limit 5")"
echo "$find_out" | rg '"ok": true' >/dev/null

# brief
brief_out="$(sh -c "$OM brief --project-id demo --limit 5")"
echo "$brief_out" | rg '"project_id": "demo"' >/dev/null

# verify
sh -c "$OM verify" | rg '"ok": true' >/dev/null

# sync placeholder
sh -c "$OM sync --mode noop" | rg '"ok": true' >/dev/null

# hard assertions
mem_count="$(sqlite3 "$TMP_HOME/data/omnimem.db" "SELECT count(*) FROM memories;")"
evt_count="$(sqlite3 "$TMP_HOME/data/omnimem.db" "SELECT count(*) FROM memory_events;")"
[[ "$mem_count" -ge 3 ]] || { echo "[FAIL] memories count too small: $mem_count"; exit 1; }
[[ "$evt_count" -ge 4 ]] || { echo "[FAIL] memory_events count too small: $evt_count"; exit 1; }

echo "[OK] Phase B CLI MVP test passed"
