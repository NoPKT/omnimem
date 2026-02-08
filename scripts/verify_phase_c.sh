#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

required_files=(
  "omnimem/adapters.py"
  "tests/test_phase_c_adapters.sh"
)

for f in "${required_files[@]}"; do
  [[ -f "$ROOT_DIR/$f" ]] || { echo "[FAIL] missing $f"; exit 1; }
done

echo "[OK] phase-c files present"

bash "$ROOT_DIR/tests/test_phase_c_adapters.sh"

echo "[OK] Phase C verification completed"
