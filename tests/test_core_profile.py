from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from omnimem.core import MemoryPaths, build_user_profile, write_memory


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class CoreProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-profile-test.")
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

    def _write(self, *, kind: str, summary: str, body: str, tags: list[str]) -> None:
        write_memory(
            paths=self.paths,
            schema_sql_path=self.schema,
            layer="short",
            kind=kind,
            summary=summary,
            body=body,
            tags=tags,
            refs=[],
            cred_refs=[],
            tool="test",
            account="default",
            device="local",
            session_id="s-profile",
            project_id="OM",
            workspace=str(self.root),
            importance=0.6,
            confidence=0.6,
            stability=0.6,
            reuse_count=0,
            volatility=0.4,
            event_type="memory.write",
        )

    def test_build_user_profile(self) -> None:
        self._write(
            kind="note",
            summary="Python retrieval tuning",
            body="I prefer deterministic retrieval and I usually use sqlite for local experiments.",
            tags=["python", "retrieval"],
        )
        self._write(
            kind="task",
            summary="Improve memory quality scoring",
            body="next: add more robust profile endpoint",
            tags=["roadmap"],
        )
        out = build_user_profile(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s-profile",
            limit=120,
        )
        self.assertTrue(out.get("ok"))
        self.assertGreaterEqual(int(out.get("analyzed", 0)), 2)
        profile = out.get("profile") or {}
        self.assertTrue(len(profile.get("top_tags") or []) >= 1)
        self.assertTrue(any("prefer" in str(x).lower() for x in (profile.get("preferences") or [])))


if __name__ == "__main__":
    unittest.main()
