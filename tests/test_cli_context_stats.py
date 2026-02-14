from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from omnimem.cli import _load_context_stats, _record_context_stat, _recent_context_utilization, _recent_transient_failures


class CLIContextStatsTest(unittest.TestCase):
    def test_record_and_recent_window(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-cli-cstats.") as d:
            root = Path(d)
            key = "codex|OM"
            _record_context_stat(
                root,
                key=key,
                transient_failures=1,
                attempts=2,
                profile="balanced",
                quota_mode="normal",
            )
            _record_context_stat(
                root,
                key=key,
                transient_failures=3,
                attempts=4,
                profile="balanced",
                quota_mode="low",
            )
            _record_context_stat(
                root,
                key="claude|OM",
                transient_failures=9,
                attempts=10,
                profile="balanced",
                quota_mode="critical",
            )
            self.assertEqual(_recent_transient_failures(root, key=key, window=8), 4)
            self.assertEqual(_recent_transient_failures(root, key=key, window=1), 3)


    def test_recent_context_utilization(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-cli-cstats-cu.") as d:
            root = Path(d)
            key = "codex|OM"
            _record_context_stat(
                root,
                key=key,
                transient_failures=0,
                attempts=1,
                profile="balanced",
                quota_mode="normal",
                context_utilization=0.9,
            )
            _record_context_stat(
                root,
                key=key,
                transient_failures=0,
                attempts=1,
                profile="balanced",
                quota_mode="normal",
                context_utilization=0.7,
            )
            self.assertAlmostEqual(_recent_context_utilization(root, key=key, window=8), 0.8, places=3)

    def test_record_saves_output_tokens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-cli-cstats-out.") as d:
            root = Path(d)
            key = "codex|OM"
            _record_context_stat(
                root,
                key=key,
                transient_failures=0,
                attempts=1,
                profile="balanced",
                quota_mode="normal",
                output_tokens=321,
                context_utilization=0.66,
            )
            obj = _load_context_stats(root)
            items = obj.get("items") if isinstance(obj, dict) else []
            self.assertTrue(isinstance(items, list) and items)
            row = items[-1]
            self.assertEqual(int(row.get("output_tokens") or 0), 321)
            self.assertAlmostEqual(float(row.get("context_utilization") or 0.0), 0.66, places=2)


if __name__ == "__main__":
    unittest.main()

