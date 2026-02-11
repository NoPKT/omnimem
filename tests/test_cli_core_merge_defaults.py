from __future__ import annotations

import unittest
from unittest.mock import patch

from omnimem.cli import build_parser


class CLICoreMergeDefaultsTest(unittest.TestCase):
    def test_core_merge_uses_config_defaults_when_flags_omitted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["core-merge-suggest", "--project-id", "OM"])

        cfg = {
            "home": "/tmp/omnimem-home",
            "storage": {
                "markdown": "/tmp/omnimem-home/data/markdown",
                "jsonl": "/tmp/omnimem-home/data/jsonl",
                "sqlite": "/tmp/omnimem-home/data/omnimem.db",
            },
            "core_merge": {
                "default_limit": 150,
                "default_min_conflicts": 3,
                "default_merge_mode": "semantic",
                "default_max_merged_lines": 6,
                "default_min_apply_quality": 0.35,
                "default_loser_action": "deprioritize",
            },
        }
        calls: dict[str, object] = {}

        def _fake_suggest(**kwargs):
            calls.update(kwargs)
            return {"ok": True, "candidates": []}

        with (
            patch("omnimem.cli.load_config", return_value=cfg),
            patch("omnimem.cli.resolve_paths", return_value=object()),
            patch("omnimem.cli.schema_sql_path", return_value=object()),
            patch("omnimem.cli.suggest_core_block_merges", side_effect=_fake_suggest),
        ):
            rc = args.func(args)

        self.assertEqual(rc, 0)
        self.assertEqual(int(calls.get("limit", -1)), 150)
        self.assertEqual(int(calls.get("min_conflicts", -1)), 3)
        self.assertEqual(str(calls.get("merge_mode") or ""), "semantic")
        self.assertEqual(int(calls.get("max_merged_lines", -1)), 6)
        self.assertEqual(float(calls.get("min_apply_quality", -1.0)), 0.35)
        self.assertEqual(str(calls.get("loser_action") or ""), "deprioritize")


if __name__ == "__main__":
    unittest.main()
