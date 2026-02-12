#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _target_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "README.zh-CN.md"]
    files.extend(sorted((ROOT / "docs").glob("*.md")))
    return [p for p in files if p.exists()]


def _analyze_file(path: Path, max_line_length: int) -> dict[str, object]:
    rel = str(path.relative_to(ROOT))
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    trailing_ws: list[int] = []
    tab_lines: list[int] = []
    long_lines: list[dict[str, object]] = []
    heading_jump_lines: list[int] = []
    malformed_heading_lines: list[int] = []
    consecutive_blank_runs: list[dict[str, int]] = []

    heading_re = re.compile(r"^(#{1,6})\s+.+$")
    malformed_heading_re = re.compile(r"^(#{1,6})[^ #].*$")
    prev_h_level = 0
    blank_run_start = 0
    blank_run_len = 0

    in_fence = False
    def _ignore_long_line(s: str, in_code_fence: bool) -> bool:
        if in_code_fence:
            return True
        stripped = s.strip()
        if not stripped:
            return True
        if stripped.startswith("|") and stripped.endswith("|"):
            return True
        if re.match(r"^[-*]\s+`https?://[^`]+`$", stripped):
            return True
        if re.match(r"^<https?://[^>]+>$", stripped):
            return True
        return False

    for idx, line in enumerate(lines, start=1):
        if re.match(r"^\s*```", line):
            in_fence = not in_fence
        if line.rstrip(" \t") != line:
            trailing_ws.append(idx)
        if "\t" in line:
            tab_lines.append(idx)
        if len(line) > max_line_length and not _ignore_long_line(line, in_fence):
            long_lines.append({"line": idx, "length": len(line)})

        if not in_fence:
            m = heading_re.match(line)
            if m:
                level = len(m.group(1))
                if prev_h_level and level > prev_h_level + 1:
                    heading_jump_lines.append(idx)
                prev_h_level = level
            elif malformed_heading_re.match(line):
                malformed_heading_lines.append(idx)

        if not line.strip():
            if blank_run_len == 0:
                blank_run_start = idx
            blank_run_len += 1
        else:
            if blank_run_len > 1:
                consecutive_blank_runs.append({"start_line": blank_run_start, "length": blank_run_len})
            blank_run_len = 0
    if blank_run_len > 1:
        consecutive_blank_runs.append({"start_line": blank_run_start, "length": blank_run_len})

    heading_count = sum(1 for ln in lines if heading_re.match(ln))
    score = (
        len(trailing_ws) * 5
        + len(tab_lines) * 3
        + len(heading_jump_lines) * 4
        + len(malformed_heading_lines) * 4
        + len(long_lines)
        + len(consecutive_blank_runs)
    )

    return {
        "file": rel,
        "line_count": len(lines),
        "heading_count": heading_count,
        "score": score,
        "issues": {
            "trailing_whitespace_lines": trailing_ws,
            "tab_lines": tab_lines,
            "long_lines": long_lines,
            "heading_level_jump_lines": heading_jump_lines,
            "malformed_heading_lines": malformed_heading_lines,
            "consecutive_blank_runs": consecutive_blank_runs,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="", help="optional output json path")
    ap.add_argument("--max-line-length", type=int, default=140)
    args = ap.parse_args()

    per_file = [_analyze_file(fp, max_line_length=args.max_line_length) for fp in _target_files()]
    totals = {
        "files": len(per_file),
        "lines": sum(int(x.get("line_count", 0)) for x in per_file),
        "headings": sum(int(x.get("heading_count", 0)) for x in per_file),
        "trailing_whitespace_lines": sum(
            len(x.get("issues", {}).get("trailing_whitespace_lines", [])) for x in per_file
        ),
        "tab_lines": sum(len(x.get("issues", {}).get("tab_lines", [])) for x in per_file),
        "long_lines": sum(len(x.get("issues", {}).get("long_lines", [])) for x in per_file),
        "heading_level_jumps": sum(len(x.get("issues", {}).get("heading_level_jump_lines", [])) for x in per_file),
        "malformed_headings": sum(len(x.get("issues", {}).get("malformed_heading_lines", [])) for x in per_file),
        "extra_blank_runs": sum(len(x.get("issues", {}).get("consecutive_blank_runs", [])) for x in per_file),
    }
    offenders = sorted(per_file, key=lambda x: int(x.get("score", 0)), reverse=True)[:8]

    out = {
        "ok": True,
        "max_line_length": args.max_line_length,
        "totals": totals,
        "top_offenders": [{"file": x["file"], "score": x["score"]} for x in offenders],
        "per_file": per_file,
    }

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
