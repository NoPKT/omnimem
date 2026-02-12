#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DOC_PAIRS = [
    ("README.md", "README.zh-CN.md"),
    ("docs/quickstart-10min.md", "docs/quickstart-10min.zh-CN.md"),
    ("docs/webui-config.md", "docs/webui-config.zh-CN.md"),
    ("docs/oauth-broker.md", "docs/oauth-broker.zh-CN.md"),
    ("docs/qa-startup-guide.md", "docs/qa-startup-guide.zh-CN.md"),
    ("docs/publish-npm.md", "docs/publish-npm.zh-CN.md"),
    ("docs/install-uninstall.md", "docs/install-uninstall.zh-CN.md"),
    ("docs/advanced-ops.md", "docs/advanced-ops.zh-CN.md"),
]


def _head_text(path: Path, lines: int = 24) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8").splitlines()[:lines])
    except Exception:
        return ""


def main() -> int:
    issues: list[str] = []
    checks: list[dict[str, object]] = []

    for en_rel, zh_rel in DOC_PAIRS:
        en = ROOT / en_rel
        zh = ROOT / zh_rel
        ok_en = en.exists()
        ok_zh = zh.exists()

        en_head = _head_text(en) if ok_en else ""
        zh_head = _head_text(zh) if ok_zh else ""

        en_has_lang_link = ("Language:" in en_head) and (Path(zh_rel).name in en_head)
        zh_has_lang_link = ("English:" in zh_head) and (Path(en_rel).name in zh_head)

        if not ok_en:
            issues.append(f"missing English doc: {en_rel}")
        if not ok_zh:
            issues.append(f"missing zh-CN doc: {zh_rel}")
        if ok_en and not en_has_lang_link:
            issues.append(f"missing language link in English doc head: {en_rel}")
        if ok_zh and not zh_has_lang_link:
            issues.append(f"missing language link in zh-CN doc head: {zh_rel}")

        checks.append(
            {
                "en": en_rel,
                "zh_cn": zh_rel,
                "exists": {"en": ok_en, "zh_cn": ok_zh},
                "lang_links": {"en_head_has_zh": en_has_lang_link, "zh_head_has_en": zh_has_lang_link},
            }
        )

    out = {
        "ok": not issues,
        "checked_pairs": len(DOC_PAIRS),
        "checks": checks,
        "issues": issues,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
