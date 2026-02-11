from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from omnimem.core import MemoryPaths, upsert_core_block


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class EvalCoreMergeScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-eval-core-merge-script.")
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.paths = MemoryPaths(
            root=self.home,
            markdown_root=self.home / "data" / "markdown",
            jsonl_root=self.home / "data" / "jsonl",
            sqlite_path=self.home / "data" / "omnimem.db",
        )
        self.schema = _schema_sql_path()
        self.cfg = self.home / "omnimem.config.json"
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text(
            json.dumps(
                {
                    "version": "0.2",
                    "home": str(self.home),
                    "storage": {
                        "markdown": str(self.paths.markdown_root),
                        "jsonl": str(self.paths.jsonl_root),
                        "sqlite": str(self.paths.sqlite_path),
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_eval_core_merge_outputs_mode_comparisons(self) -> None:
        upsert_core_block(
            paths=self.paths,
            schema_sql_path=self.schema,
            name="style-1",
            topic="style",
            content="Use concise bullet output.",
            project_id="OM",
            session_id="s1",
            priority=60,
        )
        upsert_core_block(
            paths=self.paths,
            schema_sql_path=self.schema,
            name="style-2",
            topic="style",
            content="Use concise technical bullets with assumptions.",
            project_id="OM",
            session_id="s1",
            priority=90,
        )

        env = dict(os.environ)
        env["PYTHONPATH"] = "."
        cp = subprocess.run(
            [
                "python3",
                "scripts/eval_core_merge.py",
                "--config",
                str(self.cfg),
                "--project-id",
                "OM",
                "--session-id",
                "s1",
                "--modes",
                "concat,synthesize,semantic",
                "--max-merged-lines",
                "6",
            ],
            cwd=str(Path(__file__).resolve().parent.parent),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        out = json.loads(cp.stdout)
        self.assertIn("metrics", out)
        metrics = out.get("metrics") or {}
        self.assertIn("concat", metrics)
        self.assertIn("synthesize", metrics)
        self.assertIn("semantic", metrics)
        self.assertIn("comparisons", out)
        cmp = out.get("comparisons") or {}
        self.assertIn("semantic_vs_concat", cmp)


if __name__ == "__main__":
    unittest.main()
