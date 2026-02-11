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
            priority=70,
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
            priority=75,
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
        self.assertEqual(int(block.get("priority", 0) or 0), 75)

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
            priority=90,
        )
        upsert_core_block(
            paths=self.paths,
            schema_sql_path=self.schema,
            name="expired-note",
            content="this should not be injected",
            project_id="OM",
            session_id="s1",
            priority=99,
            ttl_days=1,
        )
        # Force one block to expired by replacing with an explicit old expiry.
        upsert_core_block(
            paths=self.paths,
            schema_sql_path=self.schema,
            name="expired-note",
            content="this should not be injected",
            project_id="OM",
            session_id="s1",
            priority=99,
            expires_at="2000-01-01T00:00:00+00:00",
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
        self.assertFalse(
            any(
                any(str(w) == "core-block:expired-note" for w in (it.get("why_recalled") or []))
                for it in (out.get("items") or [])
            )
        )

    def test_list_core_blocks_exclude_expired_by_default(self) -> None:
        upsert_core_block(
            paths=self.paths,
            schema_sql_path=self.schema,
            name="a",
            content="active",
            project_id="OM",
            session_id="s1",
            priority=60,
        )
        upsert_core_block(
            paths=self.paths,
            schema_sql_path=self.schema,
            name="b",
            content="expired",
            project_id="OM",
            session_id="s1",
            priority=80,
            expires_at="2000-01-01T00:00:00+00:00",
        )
        out0 = list_core_blocks(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s1",
            include_expired=False,
        )
        names0 = [str(x.get("name") or "") for x in (out0.get("items") or [])]
        self.assertIn("a", names0)
        self.assertNotIn("b", names0)

        out1 = list_core_blocks(
            paths=self.paths,
            schema_sql_path=self.schema,
            project_id="OM",
            session_id="s1",
            include_expired=True,
        )
        names1 = [str(x.get("name") or "") for x in (out1.get("items") or [])]
        self.assertIn("b", names1)

    def test_retrieve_core_conflict_merge_by_topic(self) -> None:
        upsert_core_block(
            paths=self.paths,
            schema_sql_path=self.schema,
            name="style-a",
            topic="style",
            content="Use short bullets.",
            project_id="OM",
            session_id="s1",
            priority=60,
        )
        upsert_core_block(
            paths=self.paths,
            schema_sql_path=self.schema,
            name="style-b",
            topic="style",
            content="Use numbered lists with technical detail.",
            project_id="OM",
            session_id="s1",
            priority=90,
        )
        out_merge = retrieve_thread(
            paths=self.paths,
            schema_sql_path=self.schema,
            query="anything",
            project_id="OM",
            session_id="s1",
            max_items=6,
            include_core_blocks=True,
            core_block_limit=6,
            core_merge_by_topic=True,
        )
        self.assertTrue(out_merge.get("ok"))
        items_m = list(out_merge.get("items") or [])
        style_hits = [
            it
            for it in items_m
            if any(str(w) == "core-topic:style" for w in (it.get("why_recalled") or []))
        ]
        self.assertEqual(len(style_hits), 1)
        self.assertTrue(
            any(str(w) == "core-block:style-b" for w in (style_hits[0].get("why_recalled") or []))
        )

        out_no_merge = retrieve_thread(
            paths=self.paths,
            schema_sql_path=self.schema,
            query="anything",
            project_id="OM",
            session_id="s1",
            max_items=6,
            include_core_blocks=True,
            core_block_limit=6,
            core_merge_by_topic=False,
        )
        self.assertTrue(out_no_merge.get("ok"))
        items_nm = list(out_no_merge.get("items") or [])
        style_hits_nm = [
            it
            for it in items_nm
            if any(str(w) == "core-topic:style" for w in (it.get("why_recalled") or []))
        ]
        self.assertGreaterEqual(len(style_hits_nm), 2)


if __name__ == "__main__":
    unittest.main()
