#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from omnimem.webui import HTML_PAGE

LOCALES = ["en", "zh", "ja", "de", "fr", "ru", "it", "ko"]


def _extract_block(src: str, marker: str, next_marker: str) -> str:
    a = src.find(marker)
    if a < 0:
        return ""
    b = src.find(next_marker, a + len(marker))
    if b < 0:
        return src[a:]
    return src[a:b]


def _collect_locale_keys(block: str, quoted: bool = False) -> dict[str, set[str]]:
    out = {lc: set() for lc in LOCALES}
    current = ""
    for line in block.splitlines():
        m_loc = re.match(r"^\s{6}([a-z]{2}):\s*\{\s*$", line)
        if m_loc and m_loc.group(1) in out:
            current = m_loc.group(1)
            continue
        if current and re.match(r"^\s{6}\},?\s*$", line):
            current = ""
            continue
        if not current:
            continue
        if quoted:
            m_key = re.match(r"^\s{8}'([^']+)'\s*:\s*", line)
        else:
            m_key = re.match(r"^\s{8}([A-Za-z_][A-Za-z0-9_]*)\s*:\s*", line)
        if m_key:
            out[current].add(m_key.group(1))
    return out


def _extract_hardcoded_text_candidates(html: str) -> list[str]:
    body = _extract_block(html, "<body>", "<script>")
    txt = re.sub(r"<[^>]+>", "\n", body)
    cands = []
    for raw in txt.splitlines():
        s = raw.strip()
        if not s:
            continue
        if len(s) < 3:
            continue
        if "{" in s or "}" in s:
            continue
        if re.search(r"[A-Za-z]", s):
            cands.append(s)
    uniq = []
    seen = set()
    for s in cands:
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="", help="optional output json path")
    args = ap.parse_args()

    keys_data_i18n = sorted(set(re.findall(r'data-i18n="([^"]+)"', HTML_PAGE)))

    block_i18n = _extract_block(HTML_PAGE, "const I18N = {", "const I18N_PATCH = {")
    block_patch = _extract_block(HTML_PAGE, "const I18N_PATCH = {", "const I18N_LITERALS = {")
    block_literals = _extract_block(HTML_PAGE, "const I18N_LITERALS = {", "function safeGetLang()")

    keys_i18n = _collect_locale_keys(block_i18n, quoted=False)
    keys_patch = _collect_locale_keys(block_patch, quoted=False)
    keys_literals = _collect_locale_keys(block_literals, quoted=True)

    per_locale = {}
    for lc in LOCALES:
        merged = set(keys_i18n.get(lc, set())) | set(keys_patch.get(lc, set()))
        missing = sorted([k for k in keys_data_i18n if k not in merged])
        per_locale[lc] = {
            "data_i18n_keys": len(keys_data_i18n),
            "resolved_keys": len(merged),
            "missing_data_i18n_keys": missing,
            "literal_patch_keys": len(keys_literals.get(lc, set())),
        }

    candidates = _extract_hardcoded_text_candidates(HTML_PAGE)
    out = {
        "ok": True,
        "data_i18n_key_count": len(keys_data_i18n),
        "data_i18n_keys": keys_data_i18n,
        "per_locale": per_locale,
        "hardcoded_text_candidates_count": len(candidates),
        "hardcoded_text_candidates_sample": candidates[:120],
    }

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
