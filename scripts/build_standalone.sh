#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Building standalone binary for OmniMem..."
pyinstaller omnimem.spec

echo "Build complete. Binary is available at dist/omnimem"
