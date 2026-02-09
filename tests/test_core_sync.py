from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from omnimem.core import MemoryPaths, sync_git, sync_placeholder


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class SyncCoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-sync-test.")
        self.root = Path(self.tmp.name)
        self.paths = MemoryPaths(
            root=self.root,
            markdown_root=self.root / "data" / "markdown",
            jsonl_root=self.root / "data" / "jsonl",
            sqlite_path=self.root / "data" / "omnimem.db",
        )
        self.schema = _schema_sql_path()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _sync_modes(self) -> list[str]:
        with sqlite3.connect(self.paths.sqlite_path) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM memory_events WHERE event_type = 'memory.sync' ORDER BY event_time"
            ).fetchall()
        modes: list[str] = []
        for (payload_json,) in rows:
            payload = json.loads(payload_json)
            if "mode" in payload:
                modes.append(str(payload["mode"]))
        return modes

    def test_noop_sync_logs_event(self) -> None:
        out = sync_git(self.paths, self.schema, "noop")
        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "noop")
        self.assertIn("noop", self._sync_modes())

    def test_push_sync_logs_event(self) -> None:
        subprocess.run(["git", "-C", str(self.root), "init"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "sync@test.local"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Sync Test"], check=True)

        out = sync_git(self.paths, self.schema, "github-push")
        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "github-push")
        self.assertIn("github-push", self._sync_modes())

    def test_placeholder_alias_is_backward_compatible(self) -> None:
        out = sync_placeholder(self.paths, self.schema, "noop")
        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "noop")


if __name__ == "__main__":
    unittest.main()
