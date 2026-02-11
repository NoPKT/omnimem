#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from omnimem.core import load_config, resolve_paths


def main() -> int:
    ap = argparse.ArgumentParser(description="Bootstrap retrieval eval dataset from recent memories")
    ap.add_argument("--config", default=None)
    ap.add_argument("--project-id", default="")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg = load_config(Path(args.config) if args.config else None)
    paths = resolve_paths(cfg)
    out_fp = Path(args.out)
    out_fp.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(paths.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, summary,
                   COALESCE(json_extract(scope_json, '$.project_id'), '') AS project_id,
                   COALESCE(json_extract(source_json, '$.session_id'), '') AS session_id
            FROM memories
            WHERE (?='' OR json_extract(scope_json, '$.project_id') = ?)
              AND kind NOT IN ('retrieve')
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (str(args.project_id or "").strip(), str(args.project_id or "").strip(), max(10, min(500, int(args.limit)))),
        ).fetchall()

    dataset = []
    for r in rows:
        summary = str(r["summary"] or "").strip()
        toks = re.findall(r"[\w\u4e00-\u9fff]+", summary, flags=re.UNICODE)
        q = " ".join(toks[:4]).strip() or summary[:24].strip()
        if not q:
            continue
        dataset.append(
            {
                "query": q,
                "expected_ids": [str(r["id"])],
                "project_id": str(r["project_id"] or ""),
                "session_id": str(r["session_id"] or ""),
                "note": "auto-generated; review expected_ids for production-grade evaluation",
            }
        )

    out_fp.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "count": len(dataset), "out": str(out_fp)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
