from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
import sqlite3
from unittest.mock import patch

from omnimem.core import MemoryPaths, ensure_storage, write_memory
from omnimem.webui import (
    _github_auth_start,
    _build_github_remote_url,
    _cfg_to_ui,
    _github_repo_list,
    _github_status,
    _normalize_github_full_name,
    _aggregate_event_stats,
    _apply_memory_filters,
    _build_smart_memories_cache_key,
    _cache_get,
    _cache_set,
    _dedup_memory_items,
    _evaluate_governance_action,
    _infer_memory_route,
    _maintenance_impact_forecast,
    _maintenance_status_feedback,
    _normalize_memory_route,
    _normalize_broker_url,
    _parse_float_param,
    _parse_int_param,
    _parse_memories_request,
    _normalize_route_templates,
    _parse_governance_request,
    _process_memories_items,
    _governance_scope_filters,
    _pack_governance_rows,
    _sync_options_from_cfg,
    _quality_alerts,
    _quality_window_summary,
    _rollback_preview_items,
    _run_health_check,
)


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class WebUIDiagnosticsTest(unittest.TestCase):
    def test_parse_param_bounds(self) -> None:
        self.assertEqual(_parse_int_param("bad", default=5, lo=1, hi=9), 5)
        self.assertEqual(_parse_int_param("100", default=5, lo=1, hi=9), 9)
        self.assertEqual(_parse_float_param("bad", default=0.7, lo=0.1, hi=0.9), 0.7)
        self.assertAlmostEqual(_parse_float_param("0.01", default=0.7, lo=0.1, hi=0.9), 0.1, places=6)

    def test_cache_helpers_ttl_and_eviction(self) -> None:
        cache: dict[object, tuple[float, dict[str, object]]] = {}
        _cache_set(cache, "k1", {"ok": True}, now=10.0, max_items=2)
        self.assertEqual((_cache_get(cache, "k1", now=10.5, ttl_s=1.0) or {}).get("ok"), True)
        self.assertIsNone(_cache_get(cache, "k1", now=12.5, ttl_s=1.0))
        _cache_set(cache, "a", {"v": 1}, now=20.0, max_items=2)
        _cache_set(cache, "b", {"v": 2}, now=21.0, max_items=2)
        _cache_set(cache, "c", {"v": 3}, now=22.0, max_items=2)
        self.assertEqual(len(cache), 2)
        self.assertNotIn("a", cache)

    def test_aggregate_event_stats_counts_and_filters(self) -> None:
        rows = [
            {
                "event_type": "memory.write",
                "event_time": "2026-02-11T10:00:00+00:00",
                "payload_json": '{"project_id":"OM","session_id":"s1"}',
            },
            {
                "event_type": "memory.write",
                "event_time": "2026-02-11T11:00:00+00:00",
                "payload_json": '{"project_id":"OM","session_id":"s1"}',
            },
            {
                "event_type": "memory.decay",
                "event_time": "2026-02-10T10:00:00+00:00",
                "payload_json": '{"project_id":"OM","session_id":"s2"}',
            },
        ]
        out_all = _aggregate_event_stats(rows, project_id="", session_id="", days=14)
        self.assertEqual(int(out_all.get("total", 0)), 3)
        out_s1 = _aggregate_event_stats(rows, project_id="OM", session_id="s1", days=14)
        self.assertEqual(int(out_s1.get("total", 0)), 2)
        types = {x["event_type"]: int(x["count"]) for x in (out_s1.get("types") or [])}
        self.assertEqual(types.get("memory.write"), 2)

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

    def test_parse_memories_request_defaults(self) -> None:
        req = _parse_memories_request({})
        self.assertEqual(int(req.get("limit", 0)), 20)
        self.assertEqual(str(req.get("mode") or ""), "basic")
        self.assertEqual(str(req.get("route") or ""), "general")
        self.assertTrue(bool(req.get("profile_aware")))
        self.assertTrue(bool(req.get("include_core_blocks")))

    def test_build_smart_memories_cache_key_normalizes_ranking_mode(self) -> None:
        req = _parse_memories_request(
            {
                "mode": ["smart"],
                "query": ["alpha"],
                "project_id": ["OM"],
                "session_id": ["s1"],
                "ranking_mode": ["bad-value"],
                "limit": ["3"],
            }
        )
        key = _build_smart_memories_cache_key(req)
        self.assertEqual(key[5], "hybrid")
        self.assertEqual(key[8], 8)

    def test_process_memories_items_filters_route_and_dedup(self) -> None:
        items = [
            {"id": "m1", "kind": "note", "summary": "same", "tags": ["x"], "route": "semantic", "updated_at": "2026-02-11T00:00:00+00:00"},
            {"id": "m2", "kind": "note", "summary": "same", "tags": ["x"], "route": "semantic", "updated_at": "2026-02-11T00:00:00+00:00"},
            {"id": "m3", "kind": "decision", "summary": "other", "tags": ["y"], "route": "procedural", "updated_at": "2026-02-11T00:00:00+00:00"},
        ]
        out, before = _process_memories_items(
            paths=None,
            items=items,
            route="general",
            kind_filter="note",
            tag_filter="x",
            since_days=0,
            dedup_mode="summary_kind",
        )
        self.assertEqual(before, 2)
        self.assertEqual([x["id"] for x in out], ["m1"])

    def test_parse_governance_request_bounds(self) -> None:
        req = _parse_governance_request(
            {
                "project_id": ["OM"],
                "session_id": ["s1"],
                "limit": ["9999"],
                "d_reuse": ["-3"],
                "p_imp": ["bad"],
            }
        )
        self.assertEqual(str(req.get("project_id") or ""), "OM")
        self.assertEqual(str(req.get("session_id") or ""), "s1")
        self.assertEqual(int(req.get("limit", 0)), 200)
        th = dict(req.get("thresholds") or {})
        self.assertEqual(int(th.get("d_reuse", -1)), 0)
        self.assertAlmostEqual(float(th.get("p_imp", 0.0)), 0.75, places=6)

    def test_governance_scope_filters(self) -> None:
        sql, args = _governance_scope_filters("OM", "s1")
        self.assertIn("project_id", sql)
        self.assertIn("session_id", sql)
        self.assertEqual(args, ["OM", "s1"])
        sql2, args2 = _governance_scope_filters("", "")
        self.assertEqual(sql2, "")
        self.assertEqual(args2, [])

    def test_pack_governance_rows(self) -> None:
        rows = [
            {
                "id": "m1",
                "layer": "short",
                "kind": "note",
                "summary": "s",
                "updated_at": "2026-02-11T00:00:00+00:00",
                "importance_score": 0.8,
                "confidence_score": 0.7,
                "stability_score": 0.6,
                "reuse_count": 2,
                "volatility_score": 0.3,
            }
        ]
        out = _pack_governance_rows(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "m1")
        self.assertEqual(int((out[0]["signals"] or {}).get("reuse_count", -1)), 2)

    def test_sync_options_from_cfg(self) -> None:
        layers, include_jsonl = _sync_options_from_cfg(
            {"sync": {"github": {"include_layers": ["long", "archive"], "include_jsonl": False}}}
        )
        self.assertEqual(layers, ["long", "archive"])
        self.assertFalse(include_jsonl)

    def test_cfg_to_ui_contains_prune_fields(self) -> None:
        cfg = {
            "daemon": {
                "maintenance_prune_enabled": True,
                "maintenance_prune_days": 50,
                "maintenance_prune_limit": 420,
                "maintenance_prune_layers": ["instant", "short"],
                "maintenance_prune_keep_kinds": ["decision", "checkpoint"],
            }
        }
        out = _cfg_to_ui(cfg, Path("/tmp/omnimem.config.json"))
        self.assertTrue(bool(out.get("daemon_maintenance_prune_enabled")))
        self.assertEqual(int(out.get("daemon_maintenance_prune_days", 0)), 50)
        self.assertEqual(int(out.get("daemon_maintenance_prune_limit", 0)), 420)
        self.assertEqual(str(out.get("daemon_maintenance_prune_layers") or ""), "instant,short")
        self.assertEqual(str(out.get("daemon_maintenance_prune_keep_kinds") or ""), "decision,checkpoint")

    def test_github_remote_url_builder(self) -> None:
        self.assertEqual(
            _build_github_remote_url("owner/repo", "ssh"),
            "git@github.com:owner/repo.git",
        )
        self.assertEqual(
            _build_github_remote_url("owner/repo", "https"),
            "https://github.com/owner/repo.git",
        )

    def test_normalize_github_full_name(self) -> None:
        self.assertEqual(_normalize_github_full_name("", "", "abc/def"), "abc/def")
        self.assertEqual(_normalize_github_full_name("abc", "def", ""), "abc/def")
        with self.assertRaises(ValueError):
            _normalize_github_full_name("", "", "bad")

    def test_github_status_returns_shape(self) -> None:
        out = _github_status()
        self.assertTrue(bool(out.get("ok")))
        self.assertIn("installed", out)
        self.assertIn("authenticated", out)

    def test_github_repo_list_returns_shape(self) -> None:
        out = _github_repo_list(query="", limit=5)
        self.assertTrue(bool(out.get("ok")))
        self.assertIn("installed", out)
        self.assertIn("authenticated", out)
        self.assertIn("items", out)

    def test_github_auth_start_reports_missing_cli(self) -> None:
        with patch("omnimem.webui.shutil.which", return_value=None):
            out = _github_auth_start(cfg={}, cfg_path=Path("/tmp/omnimem.config.json"), protocol="https")
        self.assertFalse(bool(out.get("ok")))
        self.assertIn("error", out)

    def test_github_auth_start_already_authenticated(self) -> None:
        with patch("omnimem.webui.shutil.which", return_value="/usr/bin/gh"), patch(
            "omnimem.webui._github_status", return_value={"ok": True, "installed": True, "authenticated": True}
        ):
            out = _github_auth_start(cfg={}, cfg_path=Path("/tmp/omnimem.config.json"), protocol="ssh")
        self.assertTrue(bool(out.get("ok")))
        self.assertTrue(bool(out.get("already_authenticated")))

    def test_memory_route_inference(self) -> None:
        self.assertEqual(_normalize_memory_route("procedural"), "procedural")
        self.assertEqual(_normalize_memory_route("bad-value"), "auto")
        self.assertEqual(_infer_memory_route("how to run omnimem script"), "procedural")
        self.assertEqual(_infer_memory_route("what is memory graph"), "semantic")
        self.assertEqual(_infer_memory_route("when did we change daemon"), "episodic")

    def test_normalize_broker_url(self) -> None:
        self.assertEqual(_normalize_broker_url("broker.example.com"), "https://broker.example.com")
        self.assertEqual(_normalize_broker_url("https://broker.example.com/"), "https://broker.example.com")
        self.assertEqual(_normalize_broker_url(""), "")

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
