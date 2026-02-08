#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_HOME="${OMNIMEM_HOME:-$HOME/.omnimem}"

WIZARD=0
REMOTE_NAME="origin"
BRANCH="main"
REMOTE_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wizard)
      WIZARD=1
      shift
      ;;
    --remote-name)
      REMOTE_NAME="$2"
      shift 2
      ;;
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    --remote-url)
      REMOTE_URL="$2"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1"
      exit 1
      ;;
  esac
done

if [[ "$WIZARD" -eq 1 ]]; then
  echo "[OmniMem Install Wizard]"
  read -r -p "Install home [$TARGET_HOME]: " input_home
  TARGET_HOME="${input_home:-$TARGET_HOME}"

  read -r -p "Git remote name [$REMOTE_NAME]: " input_remote_name
  REMOTE_NAME="${input_remote_name:-$REMOTE_NAME}"

  read -r -p "Git branch [$BRANCH]: " input_branch
  BRANCH="${input_branch:-$BRANCH}"

  read -r -p "Git remote url (optional, e.g. git@github.com:user/repo.git): " input_remote_url
  REMOTE_URL="${input_remote_url:-$REMOTE_URL}"
fi

mkdir -p "$TARGET_HOME"
mkdir -p "$TARGET_HOME/data/markdown"/{instant,short,long,archive}
mkdir -p "$TARGET_HOME/data/jsonl"
mkdir -p "$TARGET_HOME/spec" "$TARGET_HOME/db" "$TARGET_HOME/docs"
mkdir -p "$TARGET_HOME/bin" "$TARGET_HOME/lib"

cp -f "$ROOT_DIR/spec/"*.json "$TARGET_HOME/spec/"
cp -f "$ROOT_DIR/db/schema.sql" "$TARGET_HOME/db/schema.sql"
cp -f "$ROOT_DIR/docs/architecture.md" "$TARGET_HOME/docs/architecture.md"
rm -rf "$TARGET_HOME/lib/omnimem"
cp -R "$ROOT_DIR/omnimem" "$TARGET_HOME/lib/omnimem"

cat > "$TARGET_HOME/bin/omnimem" <<SH
#!/usr/bin/env bash
set -euo pipefail
export OMNIMEM_HOME="$TARGET_HOME"
PYTHONPATH="$TARGET_HOME/lib\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m omnimem.cli "\$@"
SH
chmod +x "$TARGET_HOME/bin/omnimem"

cat > "$TARGET_HOME/omnimem.config.json" <<JSON
{
  "version": "0.1.0",
  "home": "$TARGET_HOME",
  "storage": {
    "markdown": "$TARGET_HOME/data/markdown",
    "jsonl": "$TARGET_HOME/data/jsonl",
    "sqlite": "$TARGET_HOME/data/omnimem.db"
  },
  "sync": {
    "github": {
      "remote_name": "$REMOTE_NAME",
      "remote_url": "$REMOTE_URL",
      "branch": "$BRANCH"
    }
  }
}
JSON

echo "Installed OmniMem skeleton at: $TARGET_HOME"
echo "CLI path: $TARGET_HOME/bin/omnimem"
echo "Config path: $TARGET_HOME/omnimem.config.json"
echo "Start App: $TARGET_HOME/bin/omnimem start --host 127.0.0.1 --port 8765"
