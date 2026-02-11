#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BUMP="patch"
APPLY=0
OUT_DIR="$ROOT/.release"

usage() {
  cat <<'EOF'
Usage: bash scripts/release_prepare.sh [options]

Options:
  --bump <patch|minor|major>   version bump strategy (default: patch)
  --apply                      update version files + changelog
  --out-dir <dir>              output dir for release draft (default: .release)
  -h, --help                   show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bump)
      BUMP="${2:-patch}"
      shift 2
      ;;
    --apply)
      APPLY=1
      shift
      ;;
    --out-dir)
      OUT_DIR="${2:-$OUT_DIR}"
      shift 2
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

if [[ "$BUMP" != "patch" && "$BUMP" != "minor" && "$BUMP" != "major" ]]; then
  echo "[ERR] invalid --bump: $BUMP" >&2
  exit 2
fi

CUR_VER="$(python3 - <<'PY'
import json
from pathlib import Path
p = Path("package.json")
obj = json.loads(p.read_text(encoding="utf-8"))
print(str(obj.get("version", "")).strip())
PY
)"

if [[ -z "$CUR_VER" ]]; then
  echo "[ERR] unable to read current version from package.json" >&2
  exit 1
fi

NEXT_VER="$(python3 - "$CUR_VER" "$BUMP" <<'PY'
import sys
cur = sys.argv[1].strip()
bump = sys.argv[2].strip()
parts = cur.split(".")
if len(parts) != 3 or not all(p.isdigit() for p in parts):
    raise SystemExit(1)
maj, mino, pat = [int(x) for x in parts]
if bump == "major":
    maj += 1
    mino = 0
    pat = 0
elif bump == "minor":
    mino += 1
    pat = 0
else:
    pat += 1
print(f"{maj}.{mino}.{pat}")
PY
)"

if [[ -z "$NEXT_VER" ]]; then
  echo "[ERR] failed to compute next version" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
DRAFT="$OUT_DIR/release-v$NEXT_VER.md"
TMP_UNREL="$(mktemp "${TMPDIR:-/tmp}/omnimem-unrel.XXXXXX.md")"
trap 'rm -f "$TMP_UNREL"' EXIT

python3 - "$TMP_UNREL" <<'PY'
from pathlib import Path
import re
import sys

fp = Path("CHANGELOG.md")
txt = fp.read_text(encoding="utf-8")
m = re.search(r"^## Unreleased\s*\n(.*?)(?=^##\s+|\Z)", txt, flags=re.M | re.S)
body = (m.group(1).strip() if m else "").strip()
Path(sys.argv[1]).write_text(body + "\n", encoding="utf-8")
PY

UNREL_BODY="$(cat "$TMP_UNREL")"
if [[ -z "${UNREL_BODY//[[:space:]]/}" ]]; then
  UNREL_BODY="- (fill unreleased changes)"
fi

cat > "$DRAFT" <<EOF
# Release v$NEXT_VER

Current version: \`$CUR_VER\`  
Target version: \`$NEXT_VER\`

## Highlights
$UNREL_BODY

## Publish Checklist
1. \`npm run release:gate\`
2. \`git add -A && git commit -m "release: v$NEXT_VER"\`
3. \`git tag v$NEXT_VER && git push origin main && git push origin v$NEXT_VER\`
4. \`npm publish --access public\`
EOF

if [[ "$APPLY" -eq 1 ]]; then
  TODAY="$(date +%Y-%m-%d)"
  python3 - "$CUR_VER" "$NEXT_VER" "$TODAY" <<'PY'
from pathlib import Path
import json
import re
import sys

cur = sys.argv[1]
nxt = sys.argv[2]
today = sys.argv[3]

# package.json
pj = Path("package.json")
obj = json.loads(pj.read_text(encoding="utf-8"))
obj["version"] = nxt
pj.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# omnimem/__init__.py
initp = Path("omnimem/__init__.py")
init_txt = initp.read_text(encoding="utf-8")
init_txt = re.sub(r'__version__\s*=\s*"[^"]+"', f'__version__ = "{nxt}"', init_txt, count=1)
initp.write_text(init_txt, encoding="utf-8")

# CHANGELOG: Unreleased -> versioned section
cp = Path("CHANGELOG.md")
txt = cp.read_text(encoding="utf-8")
pat = re.compile(r"(^## Unreleased\s*\n)(.*?)(?=^##\s+|\Z)", flags=re.M | re.S)
m = pat.search(txt)
if m:
    body = m.group(2).strip()
    repl = f"## Unreleased\n\n## {nxt} - {today}\n\n{body}\n\n"
    txt = txt[:m.start()] + repl + txt[m.end():]
cp.write_text(txt, encoding="utf-8")
PY
  echo "[prepare] applied version updates to $NEXT_VER"
else
  echo "[prepare] dry-run only; no file changes applied"
fi

echo "[prepare] current=$CUR_VER next=$NEXT_VER bump=$BUMP"
echo "[prepare] draft=$DRAFT"
