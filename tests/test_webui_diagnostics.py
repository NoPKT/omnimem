from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from omnimem.core import MemoryPaths, ensure_storage
from omnimem.webui import _evaluate_governance_action, _run_health_check


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class WebUIDiagnosticsTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

