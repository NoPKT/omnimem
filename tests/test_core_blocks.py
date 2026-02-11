from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from omnimem.core import MemoryPaths, get_core_block, list_core_blocks, retrieve_thread, upsert_core_block


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class CoreBlocksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-core-blocks.")
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

    def test_upsert_get_list_core_blocks(self) -> None:
        c1 = upsert_core_block(
            paths=self.paths,
            schema_sql_path=self.schema,
            name="persona",
            content="Respond in concise technical style.",
            project_id="OM",
            session_id="s1",
        )
        self.assertTrue(c1.get("ok"))
        self.assertEqual(str(c1.get("action")), "created")

        c2 = upsert_core_block(
            paths=self.paths,
            schema_sql_path=self.schema,
            name="persona",
            content="Respond in concise technical style. Prefer bullet points.",
            project_id="OM",
            session_id="s1",
        )
        self.assertTrue(c2.get("ok"))
        self.assertEqual(str(c2.get("action")), "updated")
        self.assertEqual(str(c1.get("memory_id")), str(c2.get("memory_id")))

        got = get_core_block(
            paths=self.paths,
            schema_sql_path=self.schema,
            name="persona",
            project_id="OM",
            session_id="s1",
        )
        self.assertTrue(got.get("ok"))
        block = got.get("block") or {}
        self.assertIn("Prefer bullet points", str(block.get("content") or ""))

        ls = list_core_blocks(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s1",
            limit=16,
        )
        self.assertTrue(ls.get("ok"))
        items = list(ls.get("items") or [])
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(any(str(x.get("name") or "") == "persona" for x in items))

    def test_retrieve_can_inject_core_blocks(self) -> None:
        upsert_core_block(
            paths=self.paths,
            schema_sql_path=self.schema,
            name="constraints",
            content="Always include security and rollback notes.",
            project_id="OM",
            session_id="s1",
        )
        out = retrieve_thread(
            paths=self.paths,
            schema_sql_path=self.schema,
            query="unrelated query",
            project_id="OM",
            session_id="s1",
            max_items=4,
            include_core_blocks=True,
            core_block_limit=2,
        )
        self.assertTrue(out.get("ok"))
        ex = out.get("explain") or {}
        cb = ex.get("core_blocks") or {}
        self.assertTrue(bool(cb.get("enabled")))
        self.assertGreaterEqual(int(cb.get("injected", 0) or 0), 1)
        self.assertTrue(
            any(
                any(str(w).startswith("core-block:") for w in (it.get("why_recalled") or []))
                for it in (out.get("items") or [])
            )
        )


if __name__ == "__main__":
    unittest.main()
