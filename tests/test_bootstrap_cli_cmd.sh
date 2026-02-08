#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_HOME="$(mktemp -d "${TMPDIR:-/tmp}/omni-bootstrap-cli.XXXXXX")"
trap 'rm -rf "$TMP_HOME"' EXIT

PYTHONPATH="$ROOT_DIR" python3 -m omnimem.cli bootstrap \
  --home "$TMP_HOME" \
  --remote-name origin \
  --branch main >/dev/null

[[ -x "$TMP_HOME/bin/omnimem" ]] || { echo "[FAIL] bootstrap cli binary missing"; exit 1; }
[[ -f "$TMP_HOME/omnimem.config.json" ]] || { echo "[FAIL] bootstrap cli config missing"; exit 1; }

echo "[OK] bootstrap cli command test passed"
