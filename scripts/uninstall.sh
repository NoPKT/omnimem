#!/usr/bin/env bash
set -euo pipefail

TARGET_HOME="${OMNIMEM_HOME:-$HOME/.omnimem}"
CONFIG_FILE="$TARGET_HOME/omnimem.config.json"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "No OmniMem install found at: $TARGET_HOME"
  exit 0
fi

rm -rf "$TARGET_HOME"
echo "Removed OmniMem install at: $TARGET_HOME"
