from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from omnimem.core import MemoryPaths, ingest_source


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class CoreIngestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-ingest-test.")
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

    def test_ingest_text(self) -> None:
        out = ingest_source(
            paths=self.paths,
            schema_sql_path=self.schema,
            source="",
            source_type="text",
            text_body="I prefer deterministic test outputs.",
            project_id="OM",
            session_id="s-ingest",
        )
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("source_type"), "text")
        self.assertTrue(str(out.get("memory_id") or "").strip())

    def test_ingest_url_sanitizes_query(self) -> None:
        out = ingest_source(
            paths=self.paths,
            schema_sql_path=self.schema,
            source="https://example.com/a?token=abc123&x=1",
            source_type="url",
            project_id="OM",
            session_id="s-ingest",
        )
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("source_type"), "url")
        meta = out.get("meta") or {}
        self.assertIn("***", str(meta.get("sanitized_url", "")))

    def test_ingest_file(self) -> None:
        fp = self.root / "note.txt"
        fp.write_text("First line\nSecond line\n", encoding="utf-8")
        out = ingest_source(
            paths=self.paths,
            schema_sql_path=self.schema,
            source=str(fp),
            source_type="file",
            project_id="OM",
            session_id="s-ingest",
        )
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("source_type"), "file")
        self.assertIn("ingest:file", list(out.get("tags") or []))

    def test_ingest_file_heading_chunks(self) -> None:
        fp = self.root / "doc.md"
        fp.write_text("# A\nalpha\n\n# B\nbeta\n", encoding="utf-8")
        out = ingest_source(
            paths=self.paths,
            schema_sql_path=self.schema,
            source=str(fp),
            source_type="file",
            chunk_mode="heading",
            max_chunks=8,
            project_id="OM",
            session_id="s-ingest",
        )
        self.assertTrue(out.get("ok"))
        self.assertGreaterEqual(int(out.get("chunks_written", 0)), 2)
        self.assertGreaterEqual(len(out.get("memory_ids") or []), 2)

    def test_ingest_text_fixed_chunks(self) -> None:
        txt = "x" * 1200 + "\n" + "y" * 1200
        out = ingest_source(
            paths=self.paths,
            schema_sql_path=self.schema,
            source="",
            source_type="text",
            text_body=txt,
            chunk_mode="fixed",
            chunk_chars=900,
            max_chunks=8,
            project_id="OM",
            session_id="s-ingest",
        )
        self.assertTrue(out.get("ok"))
        self.assertGreaterEqual(int(out.get("chunks_written", 0)), 2)


if __name__ == "__main__":
    unittest.main()
