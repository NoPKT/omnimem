#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from omnimem.core import find_memories_ex, load_config, resolve_paths, retrieve_thread


def _schema_sql_path() -> Path:
    here = Path(__file__).resolve()
    for p in [here.parent.parent / "db" / "schema.sql", Path.cwd() / "db" / "schema.sql"]:
        if p.exists():
            return p
    raise FileNotFoundError("schema.sql not found")


def _rank_of_first_match(ids: list[str], expected: set[str]) -> int:
    for i, mid in enumerate(ids, start=1):
        if mid in expected:
            return i
    return 0


def _metrics(rows: list[dict[str, Any]], k: int) -> dict[str, Any]:
    n = max(1, len(rows))
    hit = 0
    mrr = 0.0
    for r in rows:
        rank = int(r.get("rank", 0) or 0)
        if 1 <= rank <= k:
            hit += 1
        if rank > 0:
            mrr += 1.0 / rank
    return {
        "queries": len(rows),
        "hit_at_k": hit / n,
        "mrr": mrr / n,
    }


def _delta(a: dict[str, Any], b: dict[str, Any], key: str) -> float:
    return float(b.get(key, 0.0) or 0.0) - float(a.get(key, 0.0) or 0.0)


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline retrieval evaluator for OmniMem")
    ap.add_argument("--dataset", required=True, help="JSON file: [{query, expected_ids, project_id?, session_id?}]")
    ap.add_argument("--config", default=None, help="omnimem config path")
    ap.add_argument("--k", type=int, default=5, help="Hit@k")
    ap.add_argument("--limit", type=int, default=20, help="retrieval limit")
    ap.add_argument(
        "--with-drift-ab",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="run smart retrieval A/B (baseline vs drift-aware)",
    )
    ap.add_argument("--drift-recent-days", type=int, default=14)
    ap.add_argument("--drift-baseline-days", type=int, default=120)
    ap.add_argument("--drift-weight", type=float, default=0.35)
    ap.add_argument("--out", default="", help="optional output report JSON path")
    args = ap.parse_args()

    cfg = load_config(Path(args.config) if args.config else None)
    paths = resolve_paths(cfg)
    schema = _schema_sql_path()
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    if not isinstance(dataset, list):
        raise ValueError("dataset must be a list")

    basic_rows: list[dict[str, Any]] = []
    smart_rows: list[dict[str, Any]] = []
    smart_drift_rows: list[dict[str, Any]] = []
    for i, item in enumerate(dataset):
        if not isinstance(item, dict):
            continue
        q = str(item.get("query", "")).strip()
        expected_ids = set(str(x) for x in (item.get("expected_ids") or []))
        pid = str(item.get("project_id", "")).strip()
        sid = str(item.get("session_id", "")).strip()
        if not q or not expected_ids:
            continue

        basic = find_memories_ex(
            paths=paths,
            schema_sql_path=schema,
            query=q,
            layer=None,
            limit=int(args.limit),
            project_id=pid,
            session_id=sid,
        )
        basic_ids = [str(x.get("id", "")) for x in (basic.get("items") or [])]
        basic_rows.append(
            {
                "idx": i,
                "query": q,
                "rank": _rank_of_first_match(basic_ids, expected_ids),
                "strategy": str(basic.get("strategy", "")),
            }
        )

        smart = retrieve_thread(
            paths=paths,
            schema_sql_path=schema,
            query=q,
            project_id=pid,
            session_id=sid,
            seed_limit=min(30, int(args.limit)),
            depth=2,
            per_hop=6,
            ranking_mode="hybrid",
        )
        smart_ids = [str(x.get("id", "")) for x in (smart.get("items") or [])]
        smart_rows.append(
            {
                "idx": i,
                "query": q,
                "rank": _rank_of_first_match(smart_ids, expected_ids),
                "ranking_mode": str((smart.get("explain") or {}).get("ranking_mode", "")),
            }
        )

        if bool(args.with_drift_ab):
            smart_drift = retrieve_thread(
                paths=paths,
                schema_sql_path=schema,
                query=q,
                project_id=pid,
                session_id=sid,
                seed_limit=min(30, int(args.limit)),
                depth=2,
                per_hop=6,
                ranking_mode="hybrid",
                drift_aware=True,
                drift_recent_days=int(args.drift_recent_days),
                drift_baseline_days=int(args.drift_baseline_days),
                drift_weight=float(args.drift_weight),
            )
            smart_drift_ids = [str(x.get("id", "")) for x in (smart_drift.get("items") or [])]
            smart_drift_rows.append(
                {
                    "idx": i,
                    "query": q,
                    "rank": _rank_of_first_match(smart_drift_ids, expected_ids),
                    "ranking_mode": str((smart_drift.get("explain") or {}).get("ranking_mode", "")),
                    "drift": dict((smart_drift.get("explain") or {}).get("drift") or {}),
                }
            )

    basic_m = _metrics(basic_rows, int(args.k))
    smart_m = _metrics(smart_rows, int(args.k))
    report = {
        "k": int(args.k),
        "drift_ab": bool(args.with_drift_ab),
        "drift_params": {
            "recent_days": int(args.drift_recent_days),
            "baseline_days": int(args.drift_baseline_days),
            "weight": float(args.drift_weight),
        },
        "basic": basic_m,
        "smart": smart_m,
        "basic_rows": basic_rows,
        "smart_rows": smart_rows,
    }
    if bool(args.with_drift_ab):
        smart_drift_m = _metrics(smart_drift_rows, int(args.k))
        report["smart_drift"] = smart_drift_m
        report["smart_drift_rows"] = smart_drift_rows
        report["comparisons"] = {
            "smart_vs_basic": {
                "delta_hit_at_k": round(_delta(basic_m, smart_m, "hit_at_k"), 6),
                "delta_mrr": round(_delta(basic_m, smart_m, "mrr"), 6),
            },
            "smart_drift_vs_smart": {
                "delta_hit_at_k": round(_delta(smart_m, smart_drift_m, "hit_at_k"), 6),
                "delta_mrr": round(_delta(smart_m, smart_drift_m, "mrr"), 6),
            },
            "smart_drift_vs_basic": {
                "delta_hit_at_k": round(_delta(basic_m, smart_drift_m, "hit_at_k"), 6),
                "delta_mrr": round(_delta(basic_m, smart_drift_m, "mrr"), 6),
            },
        }
    txt = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(txt + "\n", encoding="utf-8")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
