#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from omnimem.core import load_config, resolve_paths, suggest_core_block_merges


def _schema_sql_path() -> Path:
    here = Path(__file__).resolve()
    for p in [here.parent.parent / "db" / "schema.sql", Path.cwd() / "db" / "schema.sql"]:
        if p.exists():
            return p
    raise FileNotFoundError("schema.sql not found")


def _guidance_lines(text: str) -> list[str]:
    out: list[str] = []
    for ln in str(text or "").splitlines():
        s = re.sub(r"\s+", " ", ln).strip()
        if s:
            out.append(s)
    return out


def _mode_metrics(cands: list[dict[str, Any]]) -> dict[str, Any]:
    n = max(1, len(cands))
    q = sum(float(x.get("quality", 0.0) or 0.0) for x in cands) / n
    sup = sum(float((x.get("synthesis") or {}).get("support", 0.0) or 0.0) for x in cands) / n
    lines = [len(_guidance_lines(str(x.get("suggested_guidance", "") or ""))) for x in cands]
    avg_lines = sum(lines) / n if lines else 0.0
    avg_chars = sum(int(x.get("suggested_guidance_chars", 0) or 0) for x in cands) / n
    uniq_ratio = 0.0
    if cands:
        rs: list[float] = []
        for x in cands:
            ls = _guidance_lines(str(x.get("suggested_guidance", "") or ""))
            if not ls:
                rs.append(0.0)
                continue
            rs.append(float(len(set(ls))) / float(max(1, len(ls))))
        uniq_ratio = sum(rs) / max(1, len(rs))
    return {
        "topics": len(cands),
        "avg_quality": round(float(q), 4),
        "avg_support": round(float(sup), 4),
        "avg_guidance_lines": round(float(avg_lines), 3),
        "avg_guidance_chars": round(float(avg_chars), 2),
        "avg_unique_line_ratio": round(float(uniq_ratio), 4),
    }


def _delta(a: dict[str, Any], b: dict[str, Any], key: str) -> float:
    return float(b.get(key, 0.0) or 0.0) - float(a.get(key, 0.0) or 0.0)


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline evaluator for core-block merge modes")
    ap.add_argument("--config", default=None, help="omnimem config path")
    ap.add_argument("--project-id", default="")
    ap.add_argument("--session-id", default="")
    ap.add_argument("--limit", type=int, default=160)
    ap.add_argument("--min-conflicts", type=int, default=2)
    ap.add_argument("--max-merged-lines", type=int, default=8)
    ap.add_argument("--modes", default="concat,synthesize,semantic", help="comma-separated merge modes")
    ap.add_argument("--out", default="", help="optional report output path")
    args = ap.parse_args()

    cfg = load_config(Path(args.config) if args.config else None)
    paths = resolve_paths(cfg)
    schema = _schema_sql_path()

    modes = [str(x).strip().lower() for x in str(args.modes or "").split(",") if str(x).strip()]
    modes = [m for m in modes if m in {"concat", "synthesize", "semantic"}]
    if not modes:
        modes = ["concat", "synthesize", "semantic"]

    by_mode: dict[str, Any] = {}
    rows_by_mode: dict[str, list[dict[str, Any]]] = {}
    for mode in modes:
        out = suggest_core_block_merges(
            paths=paths,
            schema_sql_path=schema,
            project_id=str(args.project_id or "").strip(),
            session_id=str(args.session_id or "").strip(),
            limit=int(args.limit),
            min_conflicts=int(args.min_conflicts),
            apply=False,
            merge_mode=mode,
            max_merged_lines=int(args.max_merged_lines),
            loser_action="none",
            min_apply_quality=0.0,
            tool="eval",
        )
        cands = list(out.get("candidates") or [])
        rows_by_mode[mode] = cands
        by_mode[mode] = _mode_metrics(cands)

    baseline = by_mode.get("concat", {})
    comparisons: dict[str, Any] = {}
    for mode, m in by_mode.items():
        if mode == "concat":
            continue
        comparisons[f"{mode}_vs_concat"] = {
            "delta_avg_quality": round(_delta(baseline, m, "avg_quality"), 4),
            "delta_avg_support": round(_delta(baseline, m, "avg_support"), 4),
            "delta_avg_unique_line_ratio": round(_delta(baseline, m, "avg_unique_line_ratio"), 4),
            "delta_avg_guidance_chars": round(_delta(baseline, m, "avg_guidance_chars"), 2),
        }

    report = {
        "modes": modes,
        "project_id": str(args.project_id or ""),
        "session_id": str(args.session_id or ""),
        "limit": int(args.limit),
        "min_conflicts": int(args.min_conflicts),
        "max_merged_lines": int(args.max_merged_lines),
        "metrics": by_mode,
        "comparisons": comparisons,
        "rows": rows_by_mode,
    }
    txt = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(txt + "\n", encoding="utf-8")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
