from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
import sqlite3

from omnimem.core import MemoryPaths, ensure_storage, write_memory
from omnimem.webui import (
    _apply_memory_filters,
    _dedup_memory_items,
    _evaluate_governance_action,
    _infer_memory_route,
    _maintenance_impact_forecast,
    _maintenance_status_feedback,
    _normalize_memory_route,
    _normalize_route_templates,
    _quality_alerts,
    _quality_window_summary,
    _rollback_preview_items,
    _run_health_check,
)


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class WebUIDiagnosticsTest(unittest.TestCase):
    def test_apply_memory_filters_kind_tag_since(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        old = (now - timedelta(days=10)).isoformat()
        new = now.isoformat()
        items = [
            {"id": "1", "kind": "note", "tags": ["x", "keep"], "updated_at": new},
            {"id": "2", "kind": "decision", "tags": ["keep"], "updated_at": new},
            {"id": "3", "kind": "note", "tags": ["other"], "updated_at": old},
        ]
        out = _apply_memory_filters(
            items,
            kind_filter="note",
            tag_filter="keep",
            since_days=7,
        )
        self.assertEqual([x["id"] for x in out], ["1"])

    def test_dedup_memory_items_summary_kind(self) -> None:
        items = [
            {"id": "a1", "kind": "note", "summary": "Same   Summary"},
            {"id": "a2", "kind": "note", "summary": "same summary"},
            {"id": "b1", "kind": "decision", "summary": "same summary"},
        ]
        out = _dedup_memory_items(items, mode="summary_kind")
        self.assertEqual([x["id"] for x in out], ["a1", "b1"])

    def test_memory_route_inference(self) -> None:
        self.assertEqual(_normalize_memory_route("procedural"), "procedural")
        self.assertEqual(_normalize_memory_route("bad-value"), "auto")
        self.assertEqual(_infer_memory_route("how to run omnimem script"), "procedural")
        self.assertEqual(_infer_memory_route("what is memory graph"), "semantic")
        self.assertEqual(_infer_memory_route("when did we change daemon"), "episodic")

    def test_quality_alerts(self) -> None:
        alerts = _quality_alerts(
            cur={
                "conflicts": 3,
                "reuse_events": 1,
                "decay_events": 30,
                "avg_stability": 0.3,
                "avg_volatility": 0.8,
            },
            prev={
                "conflicts": 1,
                "reuse_events": 4,
                "decay_events": 5,
            },
        )
        self.assertTrue(any("conflicts increased" in x for x in alerts))
        self.assertTrue(any("avg stability is low" in x for x in alerts))

    def test_maintenance_impact_forecast_warn(self) -> None:
        out = _maintenance_impact_forecast(
            decay_count=120,
            promote_count=12,
            demote_count=9,
            compress_count=2,
            dry_run=True,
            approval_required=True,
            session_id="",
        )
        self.assertEqual(out.get("risk_level"), "warn")
        exp = out.get("expected") or {}
        self.assertEqual(int(exp.get("total_touches", 0)), 143)
        self.assertIn("preview forecast", str(out.get("summary", "")))

    def test_maintenance_impact_forecast_high(self) -> None:
        out = _maintenance_impact_forecast(
            decay_count=220,
            promote_count=30,
            demote_count=35,
            compress_count=9,
            dry_run=False,
            approval_required=False,
            session_id="s-1",
        )
        self.assertEqual(out.get("risk_level"), "high")
        self.assertEqual((out.get("expected") or {}).get("compress"), 9)

    def test_maintenance_status_feedback_preview(self) -> None:
        out = _maintenance_status_feedback(
            dry_run=True,
            approval_required=True,
            approval_met=False,
            risk_level="warn",
            total_touches=120,
        )
        self.assertEqual(out.get("phase"), "preview")
        self.assertTrue(out.get("ready"))
        self.assertEqual((out.get("steps") or [])[1].get("state"), "required")
        self.assertGreater(float(out.get("pressure", 0.0)), 0.0)

    def test_maintenance_status_feedback_apply_blocked(self) -> None:
        out = _maintenance_status_feedback(
            dry_run=False,
            approval_required=True,
            approval_met=False,
            risk_level="low",
            total_touches=20,
        )
        self.assertEqual(out.get("phase"), "apply")
        self.assertFalse(out.get("ready"))
        self.assertEqual((out.get("steps") or [])[2].get("state"), "blocked")

    def test_normalize_route_templates(self) -> None:
        out = _normalize_route_templates(
            [
                {"name": "A", "route": "episodic"},
                {"name": "a", "route": "semantic"},
                {"name": "B", "route": "procedural"},
                {"name": "", "route": "episodic"},
            ]
        )
        self.assertEqual(len(out), 2)
        names = {x["name"] for x in out}
        self.assertIn("A", names)
        self.assertIn("B", names)

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

    def test_rollback_preview_items(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-webui-rollback.") as d:
            root = Path(d)
            paths = MemoryPaths(
                root=root,
                markdown_root=root / "data" / "markdown",
                jsonl_root=root / "data" / "jsonl",
                sqlite_path=root / "data" / "omnimem.db",
            )
            ensure_storage(paths, _schema_sql_path())
            out = write_memory(
                paths=paths,
                schema_sql_path=_schema_sql_path(),
                layer="short",
                kind="note",
                summary="rb",
                body="b",
                tags=[],
                refs=[],
                cred_refs=[],
                tool="test",
                account="default",
                device="local",
                session_id="s-rb",
                project_id="OM",
                workspace=str(root),
                importance=0.8,
                confidence=0.7,
                stability=0.6,
                reuse_count=0,
                volatility=0.2,
                event_type="memory.write",
            )
            mid = str((out.get("memory") or {}).get("id") or "")
            from omnimem.core import move_memory_layer

            move_memory_layer(
                paths=paths,
                schema_sql_path=_schema_sql_path(),
                memory_id=mid,
                new_layer="long",
                tool="test",
                account="default",
                device="local",
                session_id="s-rb",
            )
            with sqlite3.connect(paths.sqlite_path) as conn:
                conn.row_factory = sqlite3.Row
                items, predicted = _rollback_preview_items(
                    conn,
                    memory_id=mid,
                    cutoff_iso="1970-01-01T00:00:00+00:00",
                )
            self.assertGreaterEqual(len(items), 1)
            self.assertEqual(predicted, "short")


if __name__ == "__main__":
    unittest.main()
