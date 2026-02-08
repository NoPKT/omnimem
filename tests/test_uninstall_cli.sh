#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_HOME="$(mktemp -d "${TMPDIR:-/tmp}/omni-uninstall.XXXXXX")"
TMP_PROJ="$(mktemp -d "${TMPDIR:-/tmp}/omni-proj.XXXXXX")"
trap 'rm -rf "$TMP_HOME" "$TMP_PROJ"' EXIT

OMNIMEM_HOME="$TMP_HOME" bash "$ROOT_DIR/scripts/install.sh" >/dev/null

# Prepare project attach files
cp "$ROOT_DIR/templates/project-minimal/.omnimem.json" "$TMP_PROJ/.omnimem.json"
cp "$ROOT_DIR/templates/project-minimal/.omnimem-session.md" "$TMP_PROJ/.omnimem-session.md"
cp "$ROOT_DIR/templates/project-minimal/.omnimem-ignore" "$TMP_PROJ/.omnimem-ignore"

"$TMP_HOME/bin/omnimem" uninstall --yes --detach-project "$TMP_PROJ" >/dev/null

for _ in {1..20}; do
  [[ ! -d "$TMP_HOME" ]] && break
  sleep 0.2
done
[[ ! -d "$TMP_HOME" ]] || { echo "[FAIL] home not removed"; exit 1; }
[[ ! -f "$TMP_PROJ/.omnimem.json" ]] || { echo "[FAIL] project not detached"; exit 1; }

echo "[OK] uninstall cli test passed"
