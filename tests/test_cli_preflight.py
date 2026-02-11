from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path

from omnimem.cli import build_parser, cmd_preflight


@unittest.skipIf(shutil.which("git") is None, "git is required")
class CLIPreflightTest(unittest.TestCase):
    def _run_preflight(self, repo_dir: Path, allow_clean: bool = False) -> tuple[int, dict]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cmd_preflight(Namespace(path=str(repo_dir), allow_clean=allow_clean))
        out = json.loads(buf.getvalue())
        return code, out

    def test_preflight_command_registered(self) -> None:
        p = build_parser()
        args = p.parse_args(["preflight", "--path", "."])
        self.assertEqual(args.cmd, "preflight")

    def test_preflight_blocks_clean_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True, text=True)
            code, out = self._run_preflight(repo)
            self.assertEqual(code, 1)
            self.assertFalse(out["ok"])
            self.assertIn("no local changes detected", " ".join(out.get("issues") or []))

    def test_preflight_passes_when_worktree_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True, text=True)
            (repo / "README.md").write_text("dirty\n", encoding="utf-8")
            code, out = self._run_preflight(repo)
            self.assertEqual(code, 0)
            self.assertTrue(out["ok"])
            self.assertGreaterEqual(int(out["checks"]["changed_count"]), 1)


if __name__ == "__main__":
    unittest.main()
