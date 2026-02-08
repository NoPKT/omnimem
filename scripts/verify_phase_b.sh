#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

required_files=(
  "omnimem/cli.py"
  "omnimem/core.py"
  "bin/omnimem"
  "tests/test_cli_mvp.sh"
)

for f in "${required_files[@]}"; do
  [[ -f "$ROOT_DIR/$f" ]] || { echo "[FAIL] missing $f"; exit 1; }
done

echo "[OK] phase-b files present"

bash "$ROOT_DIR/tests/test_cli_mvp.sh"

echo "[OK] Phase B verification completed"
