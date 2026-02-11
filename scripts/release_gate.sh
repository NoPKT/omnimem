#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROJECT_ID="OM"
GATE_HOME_OVERRIDE=""
SKIP_DOCTOR=0
SKIP_PACK=0
SKIP_PHASE_D=0
SKIP_FRONTIER=0
ALLOW_CLEAN=0

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
  cat <<'EOF'
Usage: bash scripts/release_gate.sh [options]

Options:
  --project-id <id>      project id for frontier checks (default: OM)
  --home <path>          OMNIMEM_HOME for frontier checks (default: <repo>/.omnimem_gate)
  --skip-doctor          skip `omnimem doctor`
  --skip-pack            skip `npm run pack:check`
  --skip-phase-d         skip `bash scripts/verify_phase_d.sh`
  --skip-frontier        skip frontier smoke (raptor/enhance/locomo eval)
  --allow-clean          pass --allow-clean to preflight (useful in CI)
  -h, --help             show this help
EOF
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
    --skip-pack)
      SKIP_PACK=1
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

echo "[gate] step 1/5 preflight"
if [[ "$ALLOW_CLEAN" -eq 1 ]]; then
  "${OM[@]}" preflight --path "$ROOT" --allow-clean
else
  "${OM[@]}" preflight --path "$ROOT"
fi

if [[ "$SKIP_DOCTOR" -eq 0 ]]; then
  echo "[gate] step 2/5 doctor"
  "${OM[@]}" doctor
else
  echo "[gate] step 2/5 doctor (skipped)"
fi

if [[ "$SKIP_PACK" -eq 0 ]]; then
  echo "[gate] step 3/5 npm pack dry-run"
  npm_config_cache="$ROOT/.npm-cache" npm run pack:check
else
  echo "[gate] step 3/5 npm pack dry-run (skipped)"
fi

if [[ "$SKIP_PHASE_D" -eq 0 ]]; then
  echo "[gate] step 4/5 verify phase D"
  bash scripts/verify_phase_d.sh
else
  echo "[gate] step 4/5 verify phase D (skipped)"
fi

if [[ "$SKIP_FRONTIER" -eq 0 ]]; then
  echo "[gate] step 5/5 frontier smoke"
  GATE_HOME="${GATE_HOME_OVERRIDE:-$ROOT/.omnimem_gate}"
  mkdir -p "$GATE_HOME"
  OMNIMEM_HOME="$GATE_HOME" "${OM[@]}" raptor --project-id "$PROJECT_ID" > /dev/null
  OMNIMEM_HOME="$GATE_HOME" "${OM[@]}" enhance --project-id "$PROJECT_ID" > /dev/null
  if [[ -f "eval/locomo_style.sample.jsonl" ]]; then
    OMNIMEM_HOME="$GATE_HOME" python3 scripts/eval_locomo_style.py \
      --dataset eval/locomo_style.sample.jsonl \
      --out "$ROOT/.omnimem_gate.locomo_report.json" > /dev/null
  fi
else
  echo "[gate] step 5/5 frontier smoke (skipped)"
fi

echo "[gate] OK: release gate passed"
