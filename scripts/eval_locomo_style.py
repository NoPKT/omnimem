#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Prefer local workspace package when script is executed via path.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from omnimem.core import load_config, resolve_paths, retrieve_thread


def _schema_sql_path() -> Path:
    here = Path(__file__).resolve()
    for p in [here.parent.parent / "db" / "schema.sql", Path.cwd() / "db" / "schema.sql"]:
        if p.exists():
            return p
    raise FileNotFoundError("schema.sql not found")


def _answer_tokens(text: str) -> set[str]:
    toks = re.findall(r"[\w]+|[\u4e00-\u9fff]+", str(text or "").lower(), flags=re.UNICODE)
    out: set[str] = set()
    for t in toks:
        tt = t.strip()
        if len(tt) <= 1 and tt.isascii():
            continue
        out.add(tt)
    return out


def _coverage(answer: str, items: list[dict[str, Any]]) -> float:
    at = _answer_tokens(answer)
    if not at:
        return 0.0
    blob = " ".join([str((x or {}).get("summary", "") or "") for x in (items or [])[:8]])
    ht = _answer_tokens(blob)
    hit = len(at.intersection(ht))
    return float(hit) / float(max(1, len(at)))


def main() -> int:
    ap = argparse.ArgumentParser(description="LoCoMo-style long-conversation retrieval evaluation (offline)")
    ap.add_argument("--dataset", required=True, help="JSONL/JSON: [{query, answer, project_id?, session_id?}]")
    ap.add_argument("--config", default=None, help="omnimem config path")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--out", default="", help="optional output report path")
    args = ap.parse_args()

    fp = Path(args.dataset)
    raw = fp.read_text(encoding="utf-8")
    if fp.suffix.lower() == ".jsonl":
        dataset = [json.loads(x) for x in raw.splitlines() if x.strip()]
    else:
        dataset = json.loads(raw)
    if not isinstance(dataset, list):
        raise ValueError("dataset must be a list")

    cfg = load_config(Path(args.config) if args.config else None)
    paths = resolve_paths(cfg)
    schema = _schema_sql_path()

    rows: list[dict[str, Any]] = []
    for i, ex in enumerate(dataset):
        if not isinstance(ex, dict):
            continue
        query = str(ex.get("query", "")).strip()
        answer = str(ex.get("answer", "")).strip()
        if not query:
            continue
        out = retrieve_thread(
            paths=paths,
            schema_sql_path=schema,
            query=query,
            project_id=str(ex.get("project_id", "")).strip(),
            session_id=str(ex.get("session_id", "")).strip(),
            seed_limit=max(8, int(args.limit)),
            depth=2,
            per_hop=6,
            ranking_mode="hybrid",
            max_items=int(args.limit),
            self_check=True,
            adaptive_feedback=False,
        )
        items = list(out.get("items") or [])
        sc = (out.get("explain") or {}).get("self_check") or {}
        rows.append(
            {
                "idx": i,
                "query": query,
                "coverage_answer_vs_summary": round(_coverage(answer, items), 4),
                "items": len(items),
                "self_check_coverage": float(sc.get("coverage", 0.0) or 0.0),
                "self_check_confidence": float(sc.get("confidence", 0.0) or 0.0),
            }
        )

    n = max(1, len(rows))
    report = {
        "queries": len(rows),
        "avg_answer_coverage": round(sum(float(r["coverage_answer_vs_summary"]) for r in rows) / n, 4),
        "avg_self_check_coverage": round(sum(float(r["self_check_coverage"]) for r in rows) / n, 4),
        "avg_self_check_confidence": round(sum(float(r["self_check_confidence"]) for r in rows) / n, 4),
        "rows": rows,
    }
    txt = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(txt + "\n", encoding="utf-8")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
