#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_BASE="$(mktemp -d "${TMPDIR:-/tmp}/omnimem-c.XXXXXX")"
trap 'rm -rf "$TMP_BASE"' EXIT

MEM_HOME="$TMP_BASE/memory"
REMOTE_REPO="$TMP_BASE/remote.git"
mkdir -p "$MEM_HOME"

cat > "$MEM_HOME/omnimem.config.json" <<JSON
{
  "version": "0.1.0",
  "home": "$MEM_HOME",
  "storage": {
    "markdown": "$MEM_HOME/data/markdown",
    "jsonl": "$MEM_HOME/data/jsonl",
    "sqlite": "$MEM_HOME/data/omnimem.db"
  },
  "sync": {
    "github": {
      "remote_name": "origin",
      "remote_url": "$REMOTE_REPO",
      "branch": "main"
    }
  }
}
JSON

OM="PYTHONPATH=$ROOT_DIR python3 -m omnimem.cli --config $MEM_HOME/omnimem.config.json"

assert_pipe_contains() {
  local needle="$1"
  if command -v rg >/dev/null 2>&1; then
    rg -F -- "$needle" >/dev/null
  else
    grep -F -- "$needle" >/dev/null
  fi
}

# Prepare local git identity and remote
cd "$MEM_HOME"
git init >/dev/null
git checkout -b main >/dev/null
git config user.email "omni@test.local"
git config user.name "Omni Test"
git init --bare "$REMOTE_REPO" >/dev/null

# Create one memory and push
sh -c "$OM write --summary 'phase c sync test' --body 'hello phase c' --project-id ctest" >/dev/null
sh -c "$OM sync --mode github-push" | assert_pipe_contains '"ok": true'

# Bootstrap mode should also pass (pull -> reindex -> push)
sh -c "$OM sync --mode github-bootstrap" | assert_pipe_contains '"ok": true'

# Verify remote has commits
remote_head="$(git --git-dir "$REMOTE_REPO" rev-parse --verify refs/heads/main)"
[[ -n "$remote_head" ]] || { echo "[FAIL] remote branch not found"; exit 1; }

# Cred resolver (env://)
export OMNI_TOKEN_TEST="token-xyz-123"
sh -c "$OM adapter cred-resolve --ref env://OMNI_TOKEN_TEST --mask" | assert_pipe_contains '"ok": true'

# Notion dry-run
sh -c "$OM adapter notion-write --database-id db123 --title 'hello' --content 'world' --dry-run" | assert_pipe_contains '"mode": "dry_run"'
sh -c "$OM adapter notion-query --database-id db123 --dry-run" | assert_pipe_contains '"mode": "dry_run"'

# R2 dry-run
printf 'abc' > "$TMP_BASE/sample.txt"
sh -c "$OM adapter r2-put --file $TMP_BASE/sample.txt --url 'https://example.com/presigned-put' --dry-run" | assert_pipe_contains '"mode": "dry_run"'
sh -c "$OM adapter r2-get --out $TMP_BASE/out.bin --url 'https://example.com/presigned-get' --dry-run" | assert_pipe_contains '"mode": "dry_run"'

echo "[OK] Phase C adapters test passed"
