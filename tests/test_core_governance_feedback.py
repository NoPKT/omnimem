from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from omnimem.core import MemoryPaths, apply_memory_feedback, infer_adaptive_governance_thresholds, write_memory


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class CoreGovernanceFeedbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-gov-feedback.")
        self.root = Path(self.tmp.name)
        self.paths = MemoryPaths(
            root=self.root,
            markdown_root=self.root / "data" / "markdown",
            jsonl_root=self.root / "data" / "jsonl",
            sqlite_path=self.root / "data" / "omnimem.db",
        )
        self.schema = _schema_sql_path()
        self.ids: list[str] = []
        for i in range(6):
            out = write_memory(
                paths=self.paths,
                schema_sql_path=self.schema,
                layer="short" if i < 3 else "long",
                kind="note",
                summary=f"memory {i}",
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
                importance=0.6,
                confidence=0.6,
                stability=0.6,
                reuse_count=1,
                volatility=0.4,
                event_type="memory.write",
            )
            self.ids.append(str((out.get("memory") or {}).get("id") or ""))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_feedback_bias_adjusts_thresholds(self) -> None:
        base = infer_adaptive_governance_thresholds(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s1",
            days=30,
        )
        self.assertTrue(base.get("ok"))

        for _ in range(4):
            apply_memory_feedback(
                paths=self.paths,
                schema_sql_path=self.schema,
                memory_id=self.ids[0],
                feedback="negative",
                delta=1,
                note="bad memory",
                session_id="s1",
            )
        for _ in range(2):
            apply_memory_feedback(
                paths=self.paths,
                schema_sql_path=self.schema,
                memory_id=self.ids[1],
                feedback="forget",
                delta=1,
                note="stale",
                session_id="s1",
            )

        adj = infer_adaptive_governance_thresholds(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s1",
            days=30,
        )
        self.assertTrue(adj.get("ok"))
        f = adj.get("feedback") or {}
        self.assertGreater(int((f.get("counts") or {}).get("negative", 0)), 0)
        self.assertGreater(int((f.get("counts") or {}).get("forget", 0)), 0)
        self.assertGreater(float(f.get("bias", 0.0)), 0.0)

        t0 = base.get("thresholds") or {}
        t1 = adj.get("thresholds") or {}
        self.assertGreaterEqual(float(t1.get("p_conf", 0.0)), float(t0.get("p_conf", 0.0)))
        self.assertLessEqual(float(t1.get("d_vol", 1.0)), float(t0.get("d_vol", 1.0)))

    def test_drift_aware_adjusts_thresholds(self) -> None:
        base = infer_adaptive_governance_thresholds(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s1",
            days=30,
            drift_aware=False,
        )
        self.assertTrue(base.get("ok"))

        with patch(
            "omnimem.core.analyze_profile_drift",
            return_value={"ok": True, "drift": {"status": "high", "score": 0.9}},
        ):
            drifted = infer_adaptive_governance_thresholds(
                paths=self.paths,
                schema_sql_path=self.schema,
                project_id="OM",
                session_id="s1",
                days=30,
                drift_aware=True,
                drift_weight=0.6,
            )
        self.assertTrue(drifted.get("ok"))
        di = drifted.get("drift") or {}
        self.assertTrue(bool(di.get("enabled")))
        self.assertTrue(bool(di.get("applied")))
        t0 = base.get("thresholds") or {}
        t1 = drifted.get("thresholds") or {}
        self.assertGreaterEqual(float(t1.get("p_imp", 0.0)), float(t0.get("p_imp", 0.0)))
        self.assertLessEqual(float(t1.get("d_vol", 1.0)), float(t0.get("d_vol", 1.0)))


if __name__ == "__main__":
    unittest.main()
