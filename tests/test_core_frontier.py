from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from omnimem.core import (
    MemoryPaths,
    build_raptor_digest,
    enhance_memory_summaries,
    retrieve_thread,
    write_memory,
)


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class CoreFrontierFeatureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-frontier-test.")
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

    def _write(self, summary: str, body: str, reuse_count: int = 0, tags: list[str] | None = None) -> str:
        out = write_memory(
            paths=self.paths,
            schema_sql_path=self.schema,
            layer="short",
            kind="note",
            summary=summary,
            body=body,
            tags=list(tags or []),
            refs=[],
            cred_refs=[],
            tool="test",
            account="test",
            device="local",
            session_id="s1",
            project_id="OM",
            workspace=str(self.root),
            importance=0.6,
            confidence=0.6,
            stability=0.6,
            reuse_count=reuse_count,
            volatility=0.3,
            event_type="memory.write",
        )
        return str((out.get("memory") or {}).get("id") or "")

    def test_retrieve_thread_self_check_and_timings(self) -> None:
        self._write("alpha runbook", "steps for alpha")
        out = retrieve_thread(
            paths=self.paths,
            schema_sql_path=self.schema,
            query="alpha missingtoken",
            project_id="OM",
            session_id="s1",
            max_items=5,
            self_check=True,
            adaptive_feedback=False,
        )
        self.assertTrue(out.get("ok"))
        ex = out.get("explain") or {}
        self.assertIn("self_check", ex)
        self.assertIn("pipeline_ms", ex)
        self.assertIn("profile", ex)
        sc = ex.get("self_check") or {}
        self.assertTrue(isinstance(sc.get("missing_tokens"), list))

    def test_retrieve_thread_adaptive_feedback_bumps_reuse(self) -> None:
        mid = self._write("adaptive feedback target", "body")
        retrieve_thread(
            paths=self.paths,
            schema_sql_path=self.schema,
            query="adaptive feedback",
            project_id="OM",
            session_id="s1",
            max_items=3,
            self_check=True,
            adaptive_feedback=True,
            feedback_reuse_step=1,
        )
        with sqlite3.connect(self.paths.sqlite_path) as conn:
            row = conn.execute("SELECT reuse_count FROM memories WHERE id = ?", (mid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertGreaterEqual(int(row[0]), 1)

    def test_raptor_digest_preview(self) -> None:
        self._write("day memory one", "body one")
        self._write("day memory two", "body two")
        out = build_raptor_digest(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s1",
            dry_run=True,
        )
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("digest_built"))
        self.assertIn("preview", out)

    def test_enhance_memory_summaries_preview(self) -> None:
        self._write("short", "This is a longer body line that should become a better summary.")
        out = enhance_memory_summaries(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s1",
            dry_run=True,
            min_short_len=24,
        )
        self.assertTrue(out.get("ok"))
        self.assertGreaterEqual(len(out.get("candidates") or []), 1)

    def test_retrieve_thread_profile_aware_explain(self) -> None:
        self._write("python workflow guide", "prefer python workflows", tags=["python"])
        self._write("generic workflow guide", "generic steps", tags=["general"])
        out = retrieve_thread(
            paths=self.paths,
            schema_sql_path=self.schema,
            query="workflow guide",
            project_id="OM",
            session_id="s1",
            max_items=5,
            profile_aware=True,
            profile_weight=0.5,
        )
        self.assertTrue(out.get("ok"))
        ex = out.get("explain") or {}
        prof = ex.get("profile") or {}
        self.assertTrue(bool(prof.get("enabled")))

    def test_retrieve_thread_drift_aware_adjusts_params(self) -> None:
        self._write("drift runbook one", "content one")
        self._write("drift runbook two", "content two")
        with patch(
            "omnimem.core.analyze_profile_drift",
            return_value={"ok": True, "drift": {"status": "high", "score": 0.9}},
        ):
            out = retrieve_thread(
                paths=self.paths,
                schema_sql_path=self.schema,
                query="drift runbook",
                project_id="OM",
                session_id="s1",
                depth=1,
                per_hop=3,
                mmr_lambda=0.72,
                profile_aware=True,
                profile_weight=0.40,
                drift_aware=True,
                drift_weight=0.50,
            )
        self.assertTrue(out.get("ok"))
        ex = out.get("explain") or {}
        dr = ex.get("drift") or {}
        self.assertTrue(bool(dr.get("enabled")))
        self.assertTrue(bool(dr.get("applied")))
        adj = dr.get("adjustments") or {}
        self.assertGreaterEqual(int(((adj.get("depth") or {}).get("to", 0))), 1)
        self.assertLess(float(((adj.get("mmr_lambda") or {}).get("to", 1.0))), 0.72)


if __name__ == "__main__":
    unittest.main()
