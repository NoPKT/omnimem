#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROJECT_ID="OM"
GATE_HOME_OVERRIDE=""
SKIP_DOCTOR=0
SKIP_PACK=0
SKIP_DOCS=0
SKIP_PHASE_D=0
SKIP_FRONTIER=0
ALLOW_CLEAN=0
DOCTOR_STRICT=0
REQUIRE_CLEAN=0
FORMAL_RELEASE=0

if command -v omnimem >/dev/null 2>&1; then
  OM=(omnimem)
elif command -v python3 >/dev/null 2>&1; then
  OM=(python3 -m omnimem.cli)
elif command -v python >/dev/null 2>&1; then
  OM=(python -m omnimem.cli)
else
  echo "[ERR] neither 'omnimem' nor a usable Python interpreter was found in PATH" >&2
  exit 127
fi

usage() {
  cat <<'EOF_USAGE'
Usage: bash scripts/release_gate.sh [options]

Options:
  --project-id <id>      project id for frontier checks (default: OM)
  --home <path>          OMNIMEM_HOME for frontier checks (default: <repo>/.omnimem_gate)
  --skip-doctor          skip `omnimem doctor`
  --doctor-strict        treat any `omnimem doctor` issue as hard failure
  --require-clean        require zero git changes (for release cut)
  --formal-release       imply --doctor-strict --allow-clean --require-clean
  --skip-pack            skip `npm run pack:check`
  --skip-docs            skip docs i18n + docs health checks
  --skip-phase-d         skip `bash scripts/verify_phase_d.sh`
  --skip-frontier        skip frontier smoke (raptor/enhance/locomo eval)
  --allow-clean          pass --allow-clean to preflight (useful in CI)
  -h, --help             show this help
EOF_USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id)
      PROJECT_ID="${2:-}"
      shift 2
      ;;
    --home)
      GATE_HOME_OVERRIDE="${2:-}"
      shift 2
      ;;
    --skip-doctor)
      SKIP_DOCTOR=1
      shift
      ;;
    --doctor-strict)
      DOCTOR_STRICT=1
      shift
      ;;
    --require-clean)
      REQUIRE_CLEAN=1
      shift
      ;;
    --formal-release)
      FORMAL_RELEASE=1
      shift
      ;;
    --skip-pack)
      SKIP_PACK=1
      shift
      ;;
    --skip-docs)
      SKIP_DOCS=1
      shift
      ;;
    --skip-phase-d)
      SKIP_PHASE_D=1
      shift
      ;;
    --skip-frontier)
      SKIP_FRONTIER=1
      shift
      ;;
    --allow-clean)
      ALLOW_CLEAN=1
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

if [[ "$FORMAL_RELEASE" -eq 1 ]]; then
  DOCTOR_STRICT=1
  ALLOW_CLEAN=1
  REQUIRE_CLEAN=1
fi

GATE_HOME="${GATE_HOME_OVERRIDE:-$ROOT/.omnimem_gate}"
mkdir -p "$GATE_HOME"

echo "[gate] using OMNIMEM_HOME=$GATE_HOME"

if [[ "$REQUIRE_CLEAN" -eq 1 ]]; then
  if [[ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null || true)" ]]; then
    echo "[ERR] --require-clean failed: git worktree has uncommitted changes" >&2
    exit 1
  fi
fi

echo "[gate] step 1/6 preflight"
if [[ "$ALLOW_CLEAN" -eq 1 ]]; then
  "${OM[@]}" preflight --path "$ROOT" --allow-clean
else
  "${OM[@]}" preflight --path "$ROOT"
fi

if [[ "$SKIP_DOCTOR" -eq 0 ]]; then
  echo "[gate] step 2/6 doctor"
  TMP_DOCTOR="$(mktemp "${TMPDIR:-/tmp}/omnimem-doctor.XXXXXX")"
  trap 'rm -f "$TMP_DOCTOR"' EXIT
  DOCTOR_RC=0
  set +e
  OMNIMEM_HOME="$GATE_HOME" "${OM[@]}" doctor >"$TMP_DOCTOR"
  DOCTOR_RC=$?
  set -e
  cat "$TMP_DOCTOR"

  if [[ "$DOCTOR_RC" -ne 0 ]]; then
    if [[ "$DOCTOR_STRICT" -eq 1 ]]; then
      echo "[ERR] doctor failed (strict mode)" >&2
      exit "$DOCTOR_RC"
    fi
    if ! python3 - "$TMP_DOCTOR" <<'PY'
import json
import sys

tolerated = {
    "sync remote_url not configured",
    "git worktree has uncommitted changes",
}

fp = sys.argv[1]
try:
    with open(fp, "r", encoding="utf-8") as f:
        obj = json.load(f)
except Exception:
    print("[ERR] doctor output is not valid JSON", file=sys.stderr)
    raise SystemExit(1)

issues = [str(x) for x in (obj.get("issues") or []) if str(x).strip()]
blocking = [x for x in issues if x not in tolerated]
warn_only = [x for x in issues if x in tolerated]

if warn_only:
    print("[gate] doctor warnings (non-blocking):")
    for item in warn_only:
        print(f"- {item}")
if blocking:
    print("[ERR] doctor blocking issues:", file=sys.stderr)
    for item in blocking:
        print(f"- {item}", file=sys.stderr)
    raise SystemExit(1)
raise SystemExit(0)
PY
    then
      exit 1
    fi
  fi
else
  echo "[gate] step 2/6 doctor (skipped)"
fi

if [[ "$SKIP_PACK" -eq 0 ]]; then
  echo "[gate] step 3/6 npm pack dry-run"
  npm_config_cache="$ROOT/.npm-cache" npm run pack:check
else
  echo "[gate] step 3/6 npm pack dry-run (skipped)"
fi

if [[ "$SKIP_DOCS" -eq 0 ]]; then
  echo "[gate] step 4/6 docs checks"
  python3 scripts/check_docs_i18n.py > /dev/null
  python3 scripts/report_docs_health.py --out "$ROOT/eval/docs_health_report.json" > /dev/null
else
  echo "[gate] step 4/6 docs checks (skipped)"
fi

if [[ "$SKIP_PHASE_D" -eq 0 ]]; then
  echo "[gate] step 5/6 verify phase D"
  bash scripts/verify_phase_d.sh
else
  echo "[gate] step 5/6 verify phase D (skipped)"
fi

if [[ "$SKIP_FRONTIER" -eq 0 ]]; then
  echo "[gate] step 6/6 frontier smoke"
  OMNIMEM_HOME="$GATE_HOME" "${OM[@]}" raptor --project-id "$PROJECT_ID" > /dev/null
  OMNIMEM_HOME="$GATE_HOME" "${OM[@]}" enhance --project-id "$PROJECT_ID" > /dev/null
  if [[ -f "eval/locomo_style.sample.jsonl" ]]; then
    OMNIMEM_HOME="$GATE_HOME" python3 scripts/eval_locomo_style.py \
      --dataset eval/locomo_style.sample.jsonl \
      --out "$ROOT/.omnimem_gate.locomo_report.json" > /dev/null
  fi
else
  echo "[gate] step 6/6 frontier smoke (skipped)"
fi

echo "[gate] OK: release gate passed"
