#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: bash scripts/detach_project.sh <project_path>"
  exit 1
fi

PROJECT_PATH="$1"

if [[ ! -d "$PROJECT_PATH" ]]; then
  echo "Project path not found: $PROJECT_PATH"
  exit 1
fi

rm -f "$PROJECT_PATH/.omnimem.json" \
      "$PROJECT_PATH/.omnimem-session.md" \
      "$PROJECT_PATH/.omnimem-ignore" \
      "$PROJECT_PATH/.omnimem-hooks.sh"

echo "Detached OmniMem from: $PROJECT_PATH"
