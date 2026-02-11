from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from omnimem.core import MemoryPaths, SCHEMA_VERSION, analyze_profile_drift, ensure_storage, write_memory


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class CoreProfileDriftTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-profile-drift-test.")
        self.root = Path(self.tmp.name)
        self.paths = MemoryPaths(
            root=self.root,
            markdown_root=self.root / "data" / "markdown",
            jsonl_root=self.root / "data" / "jsonl",
            sqlite_path=self.root / "data" / "omnimem.db",
        )
        self.schema = _schema_sql_path()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, *, summary: str, body: str, tags: list[str]) -> str:
        out = write_memory(
            paths=self.paths,
            schema_sql_path=self.schema,
            layer="short",
            kind="note",
            summary=summary,
            body=body,
            tags=tags,
            refs=[],
            cred_refs=[],
            tool="test",
            account="default",
            device="local",
            session_id="s-profile-drift",
            project_id="OM",
            workspace=str(self.root),
            importance=0.6,
            confidence=0.6,
            stability=0.6,
            reuse_count=0,
            volatility=0.4,
            event_type="memory.write",
        )
        return str(out.get("memory_id") or "")

    def test_profile_drift_detects_shift(self) -> None:
        ensure_storage(self.paths, self.schema)
        old_dt = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with sqlite3.connect(self.paths.sqlite_path) as conn:
            for i in range(4):
                mid = uuid4().hex
                conn.execute(
                    """
                    INSERT INTO memories(
                      id, schema_version, created_at, updated_at, layer, kind, summary, body_md_path, body_text,
                      tags_json, importance_score, confidence_score, stability_score, reuse_count, volatility_score,
                      cred_refs_json, source_json, scope_json, integrity_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mid,
                        SCHEMA_VERSION,
                        old_dt,
                        old_dt,
                        "short",
                        "note",
                        f"sqlite retrieval tuning {i}",
                        f"short/legacy/{mid}.md",
                        "python retrieval sqlite deterministic matching",
                        json.dumps(["python", "sqlite", "retrieval"]),
                        0.6,
                        0.6,
                        0.6,
                        0,
                        0.4,
                        "[]",
                        json.dumps({"tool": "test", "account": "default", "device": "local", "session_id": "s-profile-drift"}),
                        json.dumps({"project_id": "OM", "workspace": str(self.root)}),
                        json.dumps({"content_sha256": "", "envelope_version": 1}),
                    ),
                )
            conn.commit()

        for i in range(4):
            self._write(
                summary=f"graph memory routing {i}",
                body="vector graph rerank profile drift evaluation",
                tags=["graph", "vector", "routing"],
            )

        out = analyze_profile_drift(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="",
            recent_days=14,
            baseline_days=90,
            limit=500,
        )
        self.assertTrue(out.get("ok"))
        counts = out.get("counts") or {}
        self.assertGreaterEqual(int(counts.get("recent", 0)), 4)
        self.assertGreaterEqual(int(counts.get("baseline", 0)), 4)
        drift = out.get("drift") or {}
        self.assertGreater(float(drift.get("score", 0.0) or 0.0), 0.45)
        self.assertIn(str(drift.get("status") or ""), {"moderate", "high"})


if __name__ == "__main__":
    unittest.main()
