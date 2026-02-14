from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from omnimem.cli import _record_context_stat, cmd_context_plan


class CLIContextPlanTest(unittest.TestCase):
    def _run(self, **kwargs: object) -> dict[str, object]:
        payload = {
            "config": None,
            "prompt": "",
            "prompt_file": None,
            "context_budget_tokens": 420,
            "retrieve_limit": 8,
            "context_profile": "balanced",
            "quota_mode": "normal",
            "recent_transient_failures": 0,
            "from_runtime": False,
            "tool": "codex",
            "project_id": "global",
        }
        payload.update(kwargs)
        args = argparse.Namespace(**payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_context_plan(args)
        self.assertEqual(rc, 0)
        return json.loads(buf.getvalue())

    def test_context_plan_normal(self) -> None:
        out = self._run(prompt="short prompt", quota_mode="normal")
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(int(out.get("recent_transient_failures_used") or 0), 0)
        eff = dict(out.get("effective") or {})
        self.assertEqual(str(eff.get("quota_mode") or ""), "normal")
        self.assertEqual(int(eff.get("context_budget_tokens") or 0), 420)
        self.assertTrue(str(eff.get("decision_reason") or ""))

    def test_context_plan_auto_promotes_to_critical(self) -> None:
        big = "x " * 2000
        out = self._run(prompt=big, quota_mode="auto")
        eff = dict(out.get("effective") or {})
        self.assertEqual(str(eff.get("quota_mode") or ""), "critical")
        self.assertLess(int(eff.get("context_budget_tokens") or 99999), 420)
        self.assertIn("prompt_tokens_estimate", str(eff.get("decision_reason") or ""))

    def test_context_plan_auto_with_recent_transient_failures(self) -> None:
        out = self._run(prompt="small", quota_mode="auto", recent_transient_failures=5)
        self.assertEqual(int(out.get("recent_transient_failures_used") or 0), 5)
        eff = dict(out.get("effective") or {})
        self.assertEqual(str(eff.get("quota_mode") or ""), "low")

    def test_context_plan_from_runtime_stats(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-cplan-runtime.") as d:
            home = Path(d)
            cfg = home / "cfg.json"
            cfg.write_text(json.dumps({"home": str(home)}), encoding="utf-8")
            _record_context_stat(
                home,
                key="codex|OM",
                transient_failures=2,
                attempts=3,
                profile="balanced",
                quota_mode="low",
                context_utilization=0.86,
            )
            _record_context_stat(
                home,
                key="codex|OM",
                transient_failures=2,
                attempts=2,
                profile="balanced",
                quota_mode="low",
                context_utilization=0.9,
            )
            out = self._run(
                config=str(cfg),
                prompt="small",
                quota_mode="auto",
                from_runtime=True,
                tool="codex",
                project_id="OM",
            )
            self.assertEqual(str(out.get("recent_transient_failures_source") or ""), "runtime")
            self.assertEqual(int(out.get("recent_transient_failures_used") or 0), 4)
            self.assertGreater(float(out.get("recent_context_utilization_used") or 0.0), 0.0)
            eff = dict(out.get("effective") or {})
            self.assertEqual(str(eff.get("quota_mode") or ""), "low")


if __name__ == "__main__":
    unittest.main()
