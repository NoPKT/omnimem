from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from omnimem.core import (
    MemoryPaths,
    build_temporal_memory_tree,
    compress_session_context,
    consolidate_memories,
    distill_session_memory,
    infer_adaptive_governance_thresholds,
    rehearse_memory_traces,
    retrieve_thread,
    trigger_reflective_summaries,
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

    def test_session_distill_preview_and_apply(self) -> None:
        for i in range(12):
            self._write(
                layer="short" if i % 2 == 0 else "long",
                summary=f"decision step runbook {i}",
                session_id="s-distill",
                importance=0.7,
                confidence=0.7,
                stability=0.7,
                reuse_count=1,
                volatility=0.2,
            )
        pre = distill_session_memory(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s-distill",
            limit=80,
            min_items=8,
            dry_run=True,
        )
        self.assertTrue(pre.get("ok"))
        self.assertIn("semantic_preview", pre)
        self.assertIn("procedural_preview", pre)

        ap = distill_session_memory(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s-distill",
            limit=80,
            min_items=8,
            dry_run=False,
        )
        self.assertTrue(ap.get("ok"))
        self.assertTrue(ap.get("distilled"))
        source_ids = [str(x) for x in (ap.get("source_ids") or []) if str(x)]
        self.assertGreaterEqual(len(source_ids), 8)
        sem_id = str(ap.get("semantic_memory_id") or "")
        proc_id = str(ap.get("procedural_memory_id") or "")
        self.assertTrue(sem_id)
        self.assertTrue(proc_id)
        with sqlite3.connect(self.paths.sqlite_path) as conn:
            sem_ref_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_refs WHERE memory_id = ? AND ref_type = 'memory' AND note = 'distill-source'",
                    (sem_id,),
                ).fetchone()[0]
                or 0
            )
            proc_ref_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_refs WHERE memory_id = ? AND ref_type = 'memory' AND note = 'distill-source'",
                    (proc_id,),
                ).fetchone()[0]
                or 0
            )
        self.assertGreaterEqual(sem_ref_count, min(8, len(source_ids)))
        self.assertGreaterEqual(proc_ref_count, min(8, len(source_ids)))

    def test_build_temporal_memory_tree_apply(self) -> None:
        for i in range(10):
            self._write(
                layer="short" if i % 2 == 0 else "long",
                summary=f"timeline step {i}",
                session_id="s-tree",
                importance=0.7,
                confidence=0.7,
                stability=0.7,
                reuse_count=1,
                volatility=0.2,
            )
        distill_session_memory(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s-tree",
            limit=100,
            min_items=8,
            dry_run=False,
        )
        out = build_temporal_memory_tree(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            days=30,
            max_sessions=5,
            per_session_limit=100,
            dry_run=False,
            tool="test",
            actor_session_id="s-tree",
        )
        self.assertTrue(out.get("ok"))
        self.assertGreaterEqual(int(out.get("temporal_links", 0)), 8)
        self.assertGreaterEqual(int(out.get("distill_links", 0)), 1)
        with sqlite3.connect(self.paths.sqlite_path) as conn:
            n_temporal = int(conn.execute("SELECT COUNT(*) FROM memory_links WHERE link_type='temporal_next'").fetchone()[0] or 0)
            n_distill = int(conn.execute("SELECT COUNT(*) FROM memory_links WHERE link_type='distill_of'").fetchone()[0] or 0)
        self.assertGreaterEqual(n_temporal, 8)
        self.assertGreaterEqual(n_distill, 1)

    def test_rehearsal_preview_and_apply(self) -> None:
        ids: list[str] = []
        for i in range(12):
            ids.append(
                self._write(
                    layer="long" if i % 3 else "short",
                    summary=f"rehearsal candidate {i}",
                    session_id="s-rehearse",
                    importance=min(1.0, 0.45 + (i * 0.04)),
                    confidence=min(1.0, 0.35 + (i * 0.03)),
                    stability=min(1.0, 0.30 + (i * 0.02)),
                    reuse_count=0 if i < 6 else 2,
                    volatility=max(0.0, 0.85 - (i * 0.03)),
                )
            )
        pre = rehearse_memory_traces(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            days=90,
            limit=6,
            dry_run=True,
        )
        self.assertTrue(pre.get("ok"))
        picks = [str(x.get("id") or "") for x in (pre.get("selected") or []) if str(x.get("id") or "")]
        self.assertGreaterEqual(len(picks), 1)

        with sqlite3.connect(self.paths.sqlite_path) as conn:
            before = {
                str(r[0]): int(r[1])
                for r in conn.execute(
                    "SELECT id, reuse_count FROM memories WHERE id IN ({})".format(",".join(["?"] * len(picks))),
                    tuple(picks),
                ).fetchall()
            }

        ap = rehearse_memory_traces(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            days=90,
            limit=6,
            dry_run=False,
            tool="test",
            actor_session_id="s-rehearse",
        )
        self.assertTrue(ap.get("ok"))
        self.assertGreaterEqual(int(ap.get("selected_count", 0)), 1)
        with sqlite3.connect(self.paths.sqlite_path) as conn:
            after = {
                str(r[0]): int(r[1])
                for r in conn.execute(
                    "SELECT id, reuse_count FROM memories WHERE id IN ({})".format(",".join(["?"] * len(picks))),
                    tuple(picks),
                ).fetchall()
            }
        bumped = [mid for mid in picks if int(after.get(mid, 0)) >= int(before.get(mid, 0)) + 1]
        self.assertGreaterEqual(len(bumped), 1)

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
            diversify=True,
            mmr_lambda=0.72,
            max_items=6,
        )
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("explain", {}).get("ranking_mode"), "ppr")
        self.assertTrue(bool(out.get("explain", {}).get("diversify")))
        self.assertTrue(len(out.get("items") or []) >= 1)
        self.assertLessEqual(len(out.get("items") or []), 6)
        self.assertTrue(any("score=" in " | ".join(x.get("why_recalled") or []) for x in (out.get("items") or [])))

    def test_trigger_reflective_summaries_preview_and_apply(self) -> None:
        for i in range(4):
            write_memory(
                paths=self.paths,
                schema_sql_path=self.schema,
                layer="instant",
                kind="retrieve",
                summary=f"Retrieved 0 memories for context #{i}",
                body=(
                    "Automatic retrieval trace created by test.\n\n"
                    "- project_id: OM\n"
                    "- session_id: s-reflect\n"
                    "- query: how to rollback bad migration\n"
                    "- retrieved_count: 0\n"
                ),
                tags=["auto:retrieve", "project:OM"],
                refs=[],
                cred_refs=[],
                tool="test",
                account="test",
                device="local",
                session_id="s-reflect",
                project_id="OM",
                workspace=str(self.root),
                importance=0.2,
                confidence=0.9,
                stability=0.2,
                reuse_count=0,
                volatility=0.8,
                event_type="memory.retrieve",
            )

        pre = trigger_reflective_summaries(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            days=14,
            limit=4,
            min_repeats=2,
            max_avg_retrieved=1.0,
            dry_run=True,
        )
        self.assertTrue(pre.get("ok"))
        self.assertGreaterEqual(len(pre.get("selected") or []), 1)

        ap = trigger_reflective_summaries(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            days=14,
            limit=4,
            min_repeats=2,
            max_avg_retrieved=1.0,
            dry_run=False,
            tool="test",
            actor_session_id="s-reflect",
        )
        self.assertTrue(ap.get("ok"))
        self.assertGreaterEqual(int(ap.get("created_count", 0)), 1)
        with sqlite3.connect(self.paths.sqlite_path) as conn:
            cnt = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM memories
                    WHERE kind='task'
                      AND EXISTS (SELECT 1 FROM json_each(memories.tags_json) WHERE value='auto:reflection')
                    """
                ).fetchone()[0]
                or 0
            )
        self.assertGreaterEqual(cnt, 1)

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
        q = dict(out.get("quantiles") or {})
        for k in [
            "q_promote_imp",
            "q_promote_conf",
            "q_promote_stab",
            "q_promote_vol",
            "q_demote_vol",
            "q_demote_stab",
            "q_demote_reuse",
        ]:
            self.assertIn(k, q)

    def test_adaptive_threshold_inference_custom_quantiles(self) -> None:
        for i in range(16):
            self._write(
                layer="short" if i < 8 else "long",
                summary=f"adaptive custom {i}",
                session_id="s-adapt-q",
                importance=min(1.0, 0.20 + (i * 0.05)),
                confidence=min(1.0, 0.25 + (i * 0.04)),
                stability=min(1.0, 0.30 + (i * 0.03)),
                reuse_count=i % 5,
                volatility=max(0.0, 0.95 - (i * 0.04)),
            )

        low = infer_adaptive_governance_thresholds(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s-adapt-q",
            days=30,
            q_promote_imp=0.50,
            q_promote_conf=0.50,
            q_promote_stab=0.50,
            q_promote_vol=0.30,
            q_demote_vol=0.70,
            q_demote_stab=0.20,
            q_demote_reuse=0.20,
        )
        high = infer_adaptive_governance_thresholds(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s-adapt-q",
            days=30,
            q_promote_imp=0.85,
            q_promote_conf=0.85,
            q_promote_stab=0.85,
            q_promote_vol=0.60,
            q_demote_vol=0.90,
            q_demote_stab=0.40,
            q_demote_reuse=0.40,
        )
        self.assertTrue(low.get("ok"))
        self.assertTrue(high.get("ok"))
        low_th = dict(low.get("thresholds") or {})
        high_th = dict(high.get("thresholds") or {})
        self.assertLessEqual(float(low_th.get("p_imp", 1.0)), float(high_th.get("p_imp", 0.0)))
        self.assertLessEqual(float(low_th.get("p_conf", 1.0)), float(high_th.get("p_conf", 0.0)))


if __name__ == "__main__":
    unittest.main()
