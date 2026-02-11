from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from omnimem.core import MemoryPaths, find_memories_ex, write_memory


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class RetrievalRankingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-retrieval-test.")
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

    def _write(self, summary: str, *, importance: float, stability: float, confidence: float, reuse_count: int) -> None:
        write_memory(
            paths=self.paths,
            schema_sql_path=self.schema,
            layer="short",
            kind="note",
            summary=summary,
            body="retrieval ranking test body",
            tags=[],
            refs=[],
            cred_refs=[],
            tool="test",
            account="test",
            device="local",
            session_id="s1",
            project_id="OM",
            workspace=str(self.root),
            importance=importance,
            confidence=confidence,
            stability=stability,
            reuse_count=reuse_count,
            volatility=0.0,
            event_type="memory.write",
        )

    def test_find_memories_ex_attaches_retrieval_and_reranks(self) -> None:
        # Same lexical match so cognitive signals determine ordering.
        self._write(
            "alpha retrieval shared token high-priority",
            importance=1.0,
            stability=1.0,
            confidence=1.0,
            reuse_count=6,
        )
        self._write(
            "alpha retrieval shared token low-priority",
            importance=0.0,
            stability=0.0,
            confidence=0.0,
            reuse_count=0,
        )

        out = find_memories_ex(
            paths=self.paths,
            schema_sql_path=self.schema,
            query="alpha retrieval shared",
            layer="short",
            limit=10,
            project_id="OM",
            session_id="s1",
        )
        self.assertTrue(out.get("ok"))
        items = list(out.get("items") or [])
        self.assertGreaterEqual(len(items), 2)

        for it in items:
            self.assertIn("retrieval", it)
            self.assertNotIn("fts_rank", it)
            self.assertIn("score", it["retrieval"])
            self.assertIn("components", it["retrieval"])

        self.assertIn("high-priority", str(items[0].get("summary", "")))
        self.assertGreater(
            float(items[0]["retrieval"]["score"]),
            float(items[1]["retrieval"]["score"]),
        )

    def test_relevance_gating_prevents_reuse_dominating_weak_match(self) -> None:
        self._write(
            "alpha beta gamma exact match candidate",
            importance=0.55,
            stability=0.50,
            confidence=0.50,
            reuse_count=0,
        )
        self._write(
            "alpha beta gamma old reused generic note with many unrelated filler terms delta epsilon zeta theta kappa lambda",
            importance=0.60,
            stability=0.60,
            confidence=0.60,
            reuse_count=25,
        )

        out = find_memories_ex(
            paths=self.paths,
            schema_sql_path=self.schema,
            query="alpha beta gamma",
            layer="short",
            limit=10,
            project_id="OM",
            session_id="s1",
        )
        self.assertTrue(out.get("ok"))
        items = list(out.get("items") or [])
        self.assertGreaterEqual(len(items), 2)
        self.assertIn("exact match candidate", str(items[0].get("summary", "")))
        c0 = items[0]["retrieval"]["components"]
        c1 = items[1]["retrieval"]["components"]
        self.assertGreater(float(c0["lexical_overlap"]), float(c1["lexical_overlap"]))
        self.assertGreater(float(items[0]["retrieval"]["score"]), float(items[1]["retrieval"]["score"]))


if __name__ == "__main__":
    unittest.main()
