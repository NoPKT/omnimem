#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: bash scripts/attach_project.sh <project_path> <project_id>"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_PATH="$1"
PROJECT_ID="$2"

if [[ ! -d "$PROJECT_PATH" ]]; then
  echo "Project path not found: $PROJECT_PATH"
  exit 1
fi

cp -f "$ROOT_DIR/templates/project-minimal/.omnimem.json" "$PROJECT_PATH/.omnimem.json"
cp -f "$ROOT_DIR/templates/project-minimal/.omnimem-session.md" "$PROJECT_PATH/.omnimem-session.md"
cp -f "$ROOT_DIR/templates/project-minimal/.omnimem-ignore" "$PROJECT_PATH/.omnimem-ignore"
cp -f "$ROOT_DIR/templates/project-minimal/AGENTS.md" "$PROJECT_PATH/AGENTS.md"

sed -i.bak "s/replace-with-project-id/$PROJECT_ID/g" "$PROJECT_PATH/.omnimem.json"
rm -f "$PROJECT_PATH/.omnimem.json.bak"

echo "Attached OmniMem to: $PROJECT_PATH (project_id=$PROJECT_ID)"
