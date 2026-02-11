from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from omnimem.core import MemoryPaths, write_memory


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class EvalRetrievalScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-eval-retrieval-script.")
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.paths = MemoryPaths(
            root=self.home,
            markdown_root=self.home / "data" / "markdown",
            jsonl_root=self.home / "data" / "jsonl",
            sqlite_path=self.home / "data" / "omnimem.db",
        )
        self.schema = _schema_sql_path()
        self.cfg_path = self.home / "omnimem.config.json"
        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg_path.write_text(
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

    def _write(self, summary: str, body: str) -> str:
        out = write_memory(
            paths=self.paths,
            schema_sql_path=self.schema,
            layer="short",
            kind="note",
            summary=summary,
            body=body,
            tags=["eval"],
            refs=[],
            cred_refs=[],
            tool="test",
            account="default",
            device="local",
            session_id="s-eval",
            project_id="OM",
            workspace=str(self.root),
            importance=0.7,
            confidence=0.7,
            stability=0.6,
            reuse_count=0,
            volatility=0.3,
            event_type="memory.write",
        )
        return str((out.get("memory") or {}).get("id") or "")

    def test_eval_retrieval_outputs_drift_ab_sections(self) -> None:
        target_id = self._write("alpha protocol runbook", "steps for alpha protocol diagnostics")
        self._write("other note", "unrelated beta content")

        dataset_path = self.root / "dataset.json"
        dataset_path.write_text(
            json.dumps(
                [
                    {
                        "query": "alpha protocol",
                        "expected_ids": [target_id],
                        "project_id": "OM",
                        "session_id": "s-eval",
                    }
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        env = dict(os.environ)
        env["PYTHONPATH"] = "."
        cp = subprocess.run(
            [
                "python3",
                "scripts/eval_retrieval.py",
                "--dataset",
                str(dataset_path),
                "--config",
                str(self.cfg_path),
                "--k",
                "5",
                "--limit",
                "8",
                "--with-drift-ab",
                "--drift-weight",
                "0.4",
            ],
            cwd=str(Path(__file__).resolve().parent.parent),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        out = json.loads(cp.stdout)
        self.assertIn("basic", out)
        self.assertIn("smart", out)
        self.assertIn("smart_drift", out)
        self.assertIn("comparisons", out)
        self.assertTrue(bool(out.get("drift_ab")))
        self.assertEqual(int((out.get("smart_drift") or {}).get("queries", 0)), 1)


if __name__ == "__main__":
    unittest.main()
