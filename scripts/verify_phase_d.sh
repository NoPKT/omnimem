#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

required_files=(
  "omnimem/webui.py"
  "tests/test_phase_d_webui.sh"
  "scripts/bootstrap.sh"
  "tests/test_bootstrap.sh"
  "tests/test_bootstrap_cli_cmd.sh"
  "tests/test_uninstall_cli.sh"
)

for f in "${required_files[@]}"; do
  [[ -f "$ROOT_DIR/$f" ]] || { echo "[FAIL] missing $f"; exit 1; }
done

echo "[OK] phase-d files present"

python3 -m py_compile "$ROOT_DIR/omnimem/webui.py"

bash "$ROOT_DIR/tests/test_phase_d_webui.sh"
bash "$ROOT_DIR/tests/test_bootstrap.sh"
bash "$ROOT_DIR/tests/test_bootstrap_cli_cmd.sh"
bash "$ROOT_DIR/tests/test_uninstall_cli.sh"

echo "[OK] Phase D verification completed"
