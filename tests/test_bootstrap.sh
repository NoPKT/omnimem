#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_BASE="$(mktemp -d "${TMPDIR:-/tmp}/omnimem-bootstrap.XXXXXX")"
trap 'rm -rf "$TMP_BASE"' EXIT

SRC_REPO="$TMP_BASE/src"
MEM_HOME="$TMP_BASE/home"
PROJ_DIR="$TMP_BASE/proj"
mkdir -p "$SRC_REPO" "$PROJ_DIR"

# Build a local git repo as bootstrap source.
cp -R "$ROOT_DIR/." "$SRC_REPO/"
rm -rf "$SRC_REPO/.git"
git -C "$SRC_REPO" init >/dev/null
git -C "$SRC_REPO" checkout -b main >/dev/null
git -C "$SRC_REPO" config user.email test@local
git -C "$SRC_REPO" config user.name 'Bootstrap Test'
git -C "$SRC_REPO" add -A
git -C "$SRC_REPO" commit -m 'init' >/dev/null

OMNIMEM_HOME="$MEM_HOME" bash "$ROOT_DIR/scripts/bootstrap.sh" \
  --repo "$SRC_REPO" \
  --remote-url git@github.com:demo/memory.git \
  --attach "$PROJ_DIR" \
  --project-id demo-proj >/dev/null

[[ -x "$MEM_HOME/bin/omnimem" ]] || { echo "[FAIL] omnimem binary missing"; exit 1; }
[[ -f "$MEM_HOME/omnimem.config.json" ]] || { echo "[FAIL] config missing"; exit 1; }
[[ -f "$PROJ_DIR/.omnimem.json" ]] || { echo "[FAIL] project attach missing"; exit 1; }

echo "[OK] bootstrap test passed"
