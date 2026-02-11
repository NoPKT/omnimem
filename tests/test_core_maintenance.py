from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from omnimem.core import (
    MemoryPaths,
    compress_session_context,
    consolidate_memories,
    infer_adaptive_governance_thresholds,
    retrieve_thread,
    weave_links,
    write_memory,
)


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class CoreMaintenanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-maint-test.")
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

    def _write(self, *, layer: str, summary: str, session_id: str, importance: float, confidence: float, stability: float, reuse_count: int, volatility: float) -> str:
        out = write_memory(
            paths=self.paths,
            schema_sql_path=self.schema,
            layer=layer,
            kind="note",
            summary=summary,
            body="maintenance test body",
            tags=["t1", "t2"],
            refs=[],
            cred_refs=[],
            tool="test",
            account="test",
            device="local",
            session_id=session_id,
            project_id="OM",
            workspace=str(self.root),
            importance=importance,
            confidence=confidence,
            stability=stability,
            reuse_count=reuse_count,
            volatility=volatility,
            event_type="memory.write",
        )
        return str(out["memory"]["id"])

    def test_consolidate_preview_and_apply(self) -> None:
        hot_id = self._write(
            layer="instant",
            summary="promote candidate",
            session_id="s-cons",
            importance=0.95,
            confidence=0.92,
            stability=0.90,
            reuse_count=3,
            volatility=0.10,
        )
        cold_id = self._write(
            layer="long",
            summary="demote candidate",
            session_id="s-cons",
            importance=0.20,
            confidence=0.30,
            stability=0.20,
            reuse_count=0,
            volatility=0.90,
        )
        pre = consolidate_memories(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s-cons",
            limit=20,
            dry_run=True,
        )
        self.assertTrue(pre.get("ok"))
        self.assertTrue(any(str(x.get("id")) == hot_id for x in (pre.get("promote") or [])))
        self.assertTrue(any(str(x.get("id")) == cold_id for x in (pre.get("demote") or [])))

        ap = consolidate_memories(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s-cons",
            limit=20,
            dry_run=False,
        )
        self.assertTrue(ap.get("ok"))
        with sqlite3.connect(self.paths.sqlite_path) as conn:
            l_hot = conn.execute("SELECT layer FROM memories WHERE id = ?", (hot_id,)).fetchone()[0]
            l_cold = conn.execute("SELECT layer FROM memories WHERE id = ?", (cold_id,)).fetchone()[0]
        self.assertEqual(str(l_hot), "short")
        self.assertEqual(str(l_cold), "short")

    def test_session_compress_preview_and_apply(self) -> None:
        for i in range(10):
            self._write(
                layer="short",
                summary=f"session item {i}",
                session_id="s-compress",
                importance=0.6,
                confidence=0.6,
                stability=0.6,
                reuse_count=1,
                volatility=0.3,
            )
        pre = compress_session_context(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s-compress",
            min_items=8,
            dry_run=True,
        )
        self.assertTrue(pre.get("ok"))
        self.assertIn("summary_preview", pre)

        ap = compress_session_context(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s-compress",
            min_items=8,
            dry_run=False,
        )
        self.assertTrue(ap.get("ok"))
        self.assertTrue(ap.get("compressed"))
        with sqlite3.connect(self.paths.sqlite_path) as conn:
            c = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE kind='summary' AND summary LIKE 'Session digest:%'"
            ).fetchone()[0]
        self.assertGreaterEqual(int(c), 1)

    def test_retrieve_thread_ppr_mode(self) -> None:
        self._write(
            layer="short",
            summary="graph alpha shared",
            session_id="s-r",
            importance=0.8,
            confidence=0.8,
            stability=0.8,
            reuse_count=1,
            volatility=0.2,
        )
        self._write(
            layer="short",
            summary="graph beta shared",
            session_id="s-r",
            importance=0.7,
            confidence=0.7,
            stability=0.7,
            reuse_count=1,
            volatility=0.2,
        )
        weave_links(paths=self.paths, schema_sql_path=self.schema, project_id="OM", limit=50, include_archive=False)
        out = retrieve_thread(
            paths=self.paths,
            schema_sql_path=self.schema,
            query="graph shared",
            project_id="OM",
            session_id="s-r",
            ranking_mode="ppr",
            depth=2,
            per_hop=4,
        )
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("explain", {}).get("ranking_mode"), "ppr")
        self.assertTrue(len(out.get("items") or []) >= 1)

    def test_adaptive_threshold_inference(self) -> None:
        for i in range(12):
            self._write(
                layer="short" if i % 2 == 0 else "long",
                summary=f"adaptive sample {i}",
                session_id="s-adapt",
                importance=min(1.0, 0.3 + (i * 0.05)),
                confidence=min(1.0, 0.35 + (i * 0.04)),
                stability=min(1.0, 0.25 + (i * 0.05)),
                reuse_count=i % 4,
                volatility=max(0.0, 0.9 - (i * 0.05)),
            )
        out = infer_adaptive_governance_thresholds(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s-adapt",
            days=30,
        )
        self.assertTrue(out.get("ok"))
        th = dict(out.get("thresholds") or {})
        for k in ["p_imp", "p_conf", "p_stab", "p_vol", "d_vol", "d_stab", "d_reuse"]:
            self.assertIn(k, th)


if __name__ == "__main__":
    unittest.main()
