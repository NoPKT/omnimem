from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
import sqlite3

from omnimem.core import MemoryPaths, ensure_storage, write_memory
from omnimem.webui import (
    _evaluate_governance_action,
    _infer_memory_route,
    _normalize_memory_route,
    _quality_window_summary,
    _run_health_check,
)


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class WebUIDiagnosticsTest(unittest.TestCase):
    def test_memory_route_inference(self) -> None:
        self.assertEqual(_normalize_memory_route("procedural"), "procedural")
        self.assertEqual(_normalize_memory_route("bad-value"), "auto")
        self.assertEqual(_infer_memory_route("how to run omnimem script"), "procedural")
        self.assertEqual(_infer_memory_route("what is memory graph"), "semantic")
        self.assertEqual(_infer_memory_route("when did we change daemon"), "episodic")

    def test_evaluate_governance_action_promote(self) -> None:
        out = _evaluate_governance_action(
            layer="short",
            signals={
                "importance_score": 0.9,
                "confidence_score": 0.8,
                "stability_score": 0.8,
                "reuse_count": 2,
                "volatility_score": 0.2,
            },
            thresholds={
                "p_imp": 0.75,
                "p_conf": 0.65,
                "p_stab": 0.65,
                "p_vol": 0.65,
                "d_vol": 0.75,
                "d_stab": 0.45,
                "d_reuse": 1,
            },
        )
        self.assertEqual(out.get("action"), "promote")

    def test_evaluate_governance_action_demote(self) -> None:
        out = _evaluate_governance_action(
            layer="long",
            signals={
                "importance_score": 0.4,
                "confidence_score": 0.4,
                "stability_score": 0.3,
                "reuse_count": 0,
                "volatility_score": 0.9,
            },
            thresholds={
                "p_imp": 0.75,
                "p_conf": 0.65,
                "p_stab": 0.65,
                "p_vol": 0.65,
                "d_vol": 0.75,
                "d_stab": 0.45,
                "d_reuse": 1,
            },
        )
        self.assertEqual(out.get("action"), "demote")

    def test_run_health_check_ok(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-webui-health.") as d:
            root = Path(d)
            paths = MemoryPaths(
                root=root,
                markdown_root=root / "data" / "markdown",
                jsonl_root=root / "data" / "jsonl",
                sqlite_path=root / "data" / "omnimem.db",
            )
            ensure_storage(paths, _schema_sql_path())
            out = _run_health_check(
                paths=paths,
                daemon_state={"running": True, "enabled": True, "last_error_kind": "none"},
            )
            self.assertTrue(out.get("ok"))
            self.assertTrue(out.get("storage", {}).get("sqlite_ok"))
            self.assertIn(out.get("health_level"), {"ok", "warn", "error"})

    def test_quality_window_summary_counts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-webui-quality.") as d:
            root = Path(d)
            paths = MemoryPaths(
                root=root,
                markdown_root=root / "data" / "markdown",
                jsonl_root=root / "data" / "jsonl",
                sqlite_path=root / "data" / "omnimem.db",
            )
            ensure_storage(paths, _schema_sql_path())
            write_memory(
                paths=paths,
                schema_sql_path=_schema_sql_path(),
                layer="short",
                kind="note",
                summary="quality window write",
                body="b",
                tags=[],
                refs=[],
                cred_refs=[],
                tool="test",
                account="default",
                device="local",
                session_id="s-q",
                project_id="OM",
                workspace=str(root),
                importance=0.8,
                confidence=0.7,
                stability=0.6,
                reuse_count=0,
                volatility=0.2,
                event_type="memory.write",
            )
            now = datetime.now(timezone.utc).replace(microsecond=0)
            start = (now - timedelta(days=1)).isoformat()
            end = (now + timedelta(days=1)).isoformat()
            with sqlite3.connect(paths.sqlite_path) as conn:
                conn.row_factory = sqlite3.Row
                out = _quality_window_summary(
                    conn,
                    start_iso=start,
                    end_iso=end,
                    project_id="OM",
                    session_id="s-q",
                )
            self.assertGreaterEqual(int(out.get("writes", 0)), 1)
            self.assertGreater(float(out.get("avg_importance", 0.0)), 0.0)


if __name__ == "__main__":
    unittest.main()
