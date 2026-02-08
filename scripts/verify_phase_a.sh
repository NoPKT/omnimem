#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

required_files=(
  "README.md"
  "docs/architecture.md"
  "docs/decisions.md"
  "docs/integration-spec.md"
  "docs/sync-and-adapters.md"
  "docs/phase-workflow.md"
  "docs/install-uninstall.md"
  "docs/webui-plan.md"
  "spec/protocol.md"
  "spec/memory-envelope.schema.json"
  "spec/memory-event.schema.json"
  "db/schema.sql"
  "scripts/install.sh"
  "scripts/uninstall.sh"
  "scripts/attach_project.sh"
  "scripts/detach_project.sh"
  "templates/project-minimal/.omnimem.json"
)

missing=0
for f in "${required_files[@]}"; do
  if [[ ! -f "$ROOT_DIR/$f" ]]; then
    echo "[FAIL] missing $f"
    missing=1
  fi
done

if [[ $missing -ne 0 ]]; then
  exit 1
fi

echo "[OK] required files present"

if command -v sqlite3 >/dev/null 2>&1; then
  tmpdb="$(mktemp "${TMPDIR:-/tmp}/omnimem.verify.XXXXXX.db")"
  sqlite3 "$tmpdb" < "$ROOT_DIR/db/schema.sql"
  table_count="$(sqlite3 "$tmpdb" "SELECT count(*) FROM sqlite_master WHERE type IN ('table','view');")"
  signal_col_count="$(sqlite3 "$tmpdb" "SELECT count(*) FROM pragma_table_info('memories') WHERE name IN ('importance_score','confidence_score','stability_score','reuse_count','volatility_score');")"
  rm -f "$tmpdb"
  echo "[OK] sqlite schema applies, table/view count=$table_count"
  echo "[OK] memory signals columns count=$signal_col_count"
else
  echo "[WARN] sqlite3 not found; schema apply check skipped"
fi

echo "[OK] Phase A verification completed"
