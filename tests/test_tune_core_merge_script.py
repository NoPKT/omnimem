from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class TuneCoreMergeScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-tune-core-merge-script.")
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.cfg_path = self.home / "omnimem.config.json"
        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg_path.write_text(
            json.dumps(
                {
                    "version": "0.2",
                    "home": str(self.home),
                    "storage": {
                        "markdown": str(self.home / "data" / "markdown"),
                        "jsonl": str(self.home / "data" / "jsonl"),
                        "sqlite": str(self.home / "data" / "omnimem.db"),
                    },
                    "core_merge": {
                        "default_merge_mode": "synthesize",
                        "default_max_merged_lines": 8,
                        "default_min_apply_quality": 0.0,
                        "default_loser_action": "none",
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        self.report_path = self.root / "core_merge_report.json"
        self.report_path.write_text(
            json.dumps(
                {
                    "metrics": {
                        "concat": {
                            "avg_quality": 0.40,
                            "avg_support": 0.50,
                            "avg_unique_line_ratio": 0.55,
                            "avg_guidance_lines": 7.0,
                            "avg_guidance_chars": 420.0,
                        },
                        "synthesize": {
                            "avg_quality": 0.52,
                            "avg_support": 0.62,
                            "avg_unique_line_ratio": 0.68,
                            "avg_guidance_lines": 5.0,
                            "avg_guidance_chars": 260.0,
                        },
                        "semantic": {
                            "avg_quality": 0.73,
                            "avg_support": 0.71,
                            "avg_unique_line_ratio": 0.81,
                            "avg_guidance_lines": 4.0,
                            "avg_guidance_chars": 190.0,
                        },
                    }
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_tune_core_merge_updates_config(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = "."
        cp = subprocess.run(
            [
                "python3",
                "scripts/tune_core_merge_from_eval.py",
                "--report",
                str(self.report_path),
                "--config",
                str(self.cfg_path),
            ],
            cwd=str(Path(__file__).resolve().parent.parent),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        out = json.loads(cp.stdout)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(str(out.get("chosen_mode") or ""), "semantic")
        updated = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        cm = dict(updated.get("core_merge") or {})
        self.assertEqual(str(cm.get("default_merge_mode") or ""), "semantic")
        self.assertGreater(float(cm.get("default_min_apply_quality") or 0.0), 0.2)
        self.assertLessEqual(int(cm.get("default_max_merged_lines") or 0), 10)


if __name__ == "__main__":
    unittest.main()
