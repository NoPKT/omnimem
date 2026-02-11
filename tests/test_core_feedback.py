from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from omnimem.core import MemoryPaths, apply_memory_feedback, write_memory


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class CoreFeedbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-feedback-test.")
        self.root = Path(self.tmp.name)
        self.paths = MemoryPaths(
            root=self.root,
            markdown_root=self.root / "data" / "markdown",
            jsonl_root=self.root / "data" / "jsonl",
            sqlite_path=self.root / "data" / "omnimem.db",
        )
        self.schema = _schema_sql_path()
        out = write_memory(
            paths=self.paths,
            schema_sql_path=self.schema,
            layer="short",
            kind="note",
            summary="feedback target",
            body="body",
            tags=[],
            refs=[],
            cred_refs=[],
            tool="test",
            account="default",
            device="local",
            session_id="s1",
            project_id="OM",
            workspace=str(self.root),
            importance=0.5,
            confidence=0.5,
            stability=0.5,
            reuse_count=0,
            volatility=0.5,
            event_type="memory.write",
        )
        self.mid = str((out.get("memory") or {}).get("id") or "")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_positive_feedback_increases_reuse(self) -> None:
        out = apply_memory_feedback(
            paths=self.paths,
            schema_sql_path=self.schema,
            memory_id=self.mid,
            feedback="positive",
            delta=2,
            note="helpful",
        )
        self.assertTrue(out.get("ok"))
        self.assertEqual(int((out.get("signals") or {}).get("reuse_count", 0)), 2)
        with sqlite3.connect(self.paths.sqlite_path) as conn:
            row = conn.execute("SELECT reuse_count FROM memories WHERE id = ?", (self.mid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(int(row[0]), 2)

    def test_correct_feedback_appends_body_note(self) -> None:
        out = apply_memory_feedback(
            paths=self.paths,
            schema_sql_path=self.schema,
            memory_id=self.mid,
            feedback="correct",
            correction="rename field to score_value",
            delta=1,
        )
        self.assertTrue(out.get("ok"))
        with sqlite3.connect(self.paths.sqlite_path) as conn:
            row = conn.execute("SELECT body_text, tags_json FROM memories WHERE id = ?", (self.mid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertIn("Feedback Correction", str(row[0] or ""))
        self.assertIn("feedback:correct", str(row[1] or ""))


if __name__ == "__main__":
    unittest.main()
