from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

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

    def _write(self, summary: str, body: str, reuse_count: int = 0) -> str:
        out = write_memory(
            paths=self.paths,
            schema_sql_path=self.schema,
            layer="short",
            kind="note",
            summary=summary,
            body=body,
            tags=[],
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


if __name__ == "__main__":
    unittest.main()
