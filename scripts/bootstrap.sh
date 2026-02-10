#!/usr/bin/env bash
set -euo pipefail

# One-command bootstrap for new device / new account.
# Example:
#   bash scripts/bootstrap.sh --repo git@github.com:YOUR_USER/omnimem.git
#   bash scripts/bootstrap.sh --repo https://github.com/YOUR_USER/omnimem.git --attach ~/code/myproj --project-id myproj

TARGET_HOME="${OMNIMEM_HOME:-$HOME/.omnimem}"
APP_DIR="$TARGET_HOME/app"
REPO_URL=""
BRANCH="main"
REMOTE_NAME="origin"
REMOTE_URL=""
ATTACH_PATH=""
PROJECT_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO_URL="$2"
      shift 2
      ;;
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    --remote-name)
      REMOTE_NAME="$2"
      shift 2
      ;;
    --remote-url)
      REMOTE_URL="$2"
      shift 2
      ;;
    --attach)
      ATTACH_PATH="$2"
      shift 2
      ;;
    --project-id)
      PROJECT_ID="$2"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1"
      exit 1
      ;;
  esac
done

if [[ -z "$REPO_URL" ]]; then
  echo "Usage: bash scripts/bootstrap.sh --repo <git_repo_url> [--branch main] [--remote-url <memory_git_url>] [--attach <project_path> --project-id <id>]"
  exit 1
fi

mkdir -p "$TARGET_HOME"

if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch --all --prune
  git -C "$APP_DIR" checkout "$BRANCH"
  # Avoid failures when local modifications exist in the app dir.
  git -C "$APP_DIR" pull --rebase --autostash
else
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
bash scripts/install.sh --remote-name "$REMOTE_NAME" --branch "$BRANCH" ${REMOTE_URL:+--remote-url "$REMOTE_URL"}

if [[ -n "$ATTACH_PATH" ]]; then
  if [[ -z "$PROJECT_ID" ]]; then
    PROJECT_ID="$(basename "$ATTACH_PATH")"
  fi
  bash scripts/attach_project.sh "$ATTACH_PATH" "$PROJECT_ID"
fi

echo "Bootstrap done."
echo "Run: $TARGET_HOME/bin/omnimem start --host 127.0.0.1 --port 8765"
