from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from omnimem.webui import _context_runtime_summary


class WebUIContextRuntimeTest(unittest.TestCase):
    def test_empty_runtime_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-webui-ctxrt.") as d:
            out = _context_runtime_summary(paths_root=Path(d), project_id="", tool="", window=12)
            self.assertTrue(bool(out.get("ok")))
            self.assertEqual(int(out.get("count") or 0), 0)
            self.assertEqual(float(out.get("avg_context_utilization") or 0.0), 0.0)
            self.assertEqual(str(out.get("risk_level") or ""), "none")

    def test_runtime_summary_with_filters(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-webui-ctxrt.") as d:
            root = Path(d)
            runtime = root / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            fp = runtime / "context_strategy_stats.json"
            fp.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "key": "codex|OM",
                                "transient_failures": 1,
                                "attempts": 2,
                                "context_utilization": 0.8,
                                "output_tokens": 200,
                            },
                            {
                                "key": "codex|OM",
                                "transient_failures": 0,
                                "attempts": 1,
                                "context_utilization": 1.0,
                                "output_tokens": 400,
                            },
                            {
                                "key": "claude|OM",
                                "transient_failures": 3,
                                "attempts": 4,
                                "context_utilization": 0.5,
                                "output_tokens": 100,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            out = _context_runtime_summary(paths_root=root, project_id="OM", tool="codex", window=12)
            self.assertTrue(bool(out.get("ok")))
            self.assertEqual(int(out.get("count") or 0), 2)
            self.assertEqual(int(out.get("transient_failures_sum") or 0), 1)
            self.assertEqual(int(out.get("attempts_sum") or 0), 3)
            self.assertAlmostEqual(float(out.get("avg_context_utilization") or 0.0), 0.9, places=3)
            self.assertAlmostEqual(float(out.get("avg_output_tokens") or 0.0), 300.0, places=3)
            self.assertGreaterEqual(float(out.get("p95_context_utilization") or 0.0), 1.0)
            self.assertGreaterEqual(float(out.get("p95_output_tokens") or 0.0), 400.0)
            self.assertEqual(str(out.get("risk_level") or ""), "critical")
            self.assertEqual(str(out.get("recommended_quota_mode") or ""), "critical")
            self.assertEqual(str(out.get("recommended_context_profile") or ""), "low_quota")
            by_tool = out.get("by_tool") or []
            self.assertEqual(len(by_tool), 1)
            self.assertEqual(str(by_tool[0].get("tool") or ""), "codex")


if __name__ == "__main__":
    unittest.main()
