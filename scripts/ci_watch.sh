#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WORKFLOW=""
BRANCH=""
COMMIT=""
RUN_ID=""
MAX_WAIT_MIN=30
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: bash scripts/ci_watch.sh [options]

Watch the latest GitHub Actions run for this repo (or a specified run id).
Exit non-zero if the run fails.

Options:
  --run-id <id>            explicit workflow run id (skip auto-detect)
  --workflow <name|file>   filter workflow when auto-detecting run
  --branch <name>          filter branch when auto-detecting run
  --commit <sha>           commit sha to match (default: git rev-parse HEAD)
  --max-wait-min <min>     max watch duration in minutes (default: 30)
  --dry-run                print resolved command without waiting
  -h, --help               show help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id)
      RUN_ID="${2:-}"
      shift 2
      ;;
    --workflow)
      WORKFLOW="${2:-}"
      shift 2
      ;;
    --branch)
      BRANCH="${2:-}"
      shift 2
      ;;
    --commit)
      COMMIT="${2:-}"
      shift 2
      ;;
    --max-wait-min)
      MAX_WAIT_MIN="${2:-30}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ERR] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! [[ "$MAX_WAIT_MIN" =~ ^[0-9]+$ ]] || [[ "$MAX_WAIT_MIN" -le 0 ]]; then
  echo "[ERR] --max-wait-min must be a positive integer" >&2
  exit 2
fi

if [[ -z "$COMMIT" ]]; then
  COMMIT="$(git rev-parse HEAD 2>/dev/null || true)"
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "[ERR] gh CLI is required. Install from https://cli.github.com/" >&2
  exit 127
fi

if [[ "$DRY_RUN" -eq 0 ]]; then
  if ! gh auth status >/dev/null 2>&1; then
    echo "[ERR] gh auth not ready. Run: gh auth login" >&2
    exit 1
  fi
fi

resolve_run_id() {
  if [[ -n "$RUN_ID" ]]; then
    printf '%s\n' "$RUN_ID"
    return 0
  fi

  local args=()
  if [[ -n "$WORKFLOW" ]]; then
    args+=(--workflow "$WORKFLOW")
  fi
  if [[ -n "$BRANCH" ]]; then
    args+=(--branch "$BRANCH")
  fi

  local raw
  raw="$(gh run list -L 60 --json databaseId,headSha,status,conclusion,workflowName,headBranch "${args[@]}")"

  RUN_ID="$(python3 - "$COMMIT" "$raw" <<'PY'
import json, sys

commit = (sys.argv[1] or '').strip().lower()
raw = sys.argv[2] if len(sys.argv) > 2 else '[]'

try:
    rows = json.loads(raw or '[]')
except Exception:
    rows = []

if commit:
    for r in rows:
        if str(r.get('headSha') or '').lower().startswith(commit):
            print(str(r.get('databaseId') or '').strip())
            raise SystemExit(0)
for r in rows:
    rid = str(r.get('databaseId') or '').strip()
    if rid:
        print(rid)
        raise SystemExit(0)
print('')
PY
)"

  if [[ -z "$RUN_ID" ]]; then
    echo "[ERR] no workflow run found (workflow=${WORKFLOW:-any}, branch=${BRANCH:-any}, commit=${COMMIT:-unknown})" >&2
    return 1
  fi

  printf '%s\n' "$RUN_ID"
}

RID="$(resolve_run_id)"

echo "[ci-watch] run_id=$RID workflow=${WORKFLOW:-any} branch=${BRANCH:-any} commit=${COMMIT:-unknown}"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[ci-watch] dry-run: gh run watch $RID --interval 10 --exit-status"
  exit 0
fi

# timeout is minutes -> seconds
TIMEOUT_S=$(( MAX_WAIT_MIN * 60 ))
if command -v gtimeout >/dev/null 2>&1; then
  TO=(gtimeout "$TIMEOUT_S")
elif command -v timeout >/dev/null 2>&1; then
  TO=(timeout "$TIMEOUT_S")
else
  TO=()
fi

set +e
"${TO[@]}" gh run watch "$RID" --interval 10 --exit-status
WATCH_RC=$?
set -e

VIEW_JSON="$(gh run view "$RID" --json status,conclusion,url,workflowName,createdAt,updatedAt)"
python3 - <<'PY' "$WATCH_RC" "$VIEW_JSON"
import json, sys
rc = int(sys.argv[1])
obj = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
print('[ci-watch] summary:')
print(json.dumps({
    'ok': rc == 0,
    'workflow': obj.get('workflowName'),
    'status': obj.get('status'),
    'conclusion': obj.get('conclusion'),
    'url': obj.get('url'),
    'createdAt': obj.get('createdAt'),
    'updatedAt': obj.get('updatedAt'),
}, ensure_ascii=False, indent=2))
PY

if [[ "$WATCH_RC" -ne 0 ]]; then
  echo "[ci-watch] run failed or timed out; showing failed job logs" >&2
  gh run view "$RID" --log-failed || true
  exit "$WATCH_RC"
fi

echo "[ci-watch] success"
