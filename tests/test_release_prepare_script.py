from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class ReleasePrepareScriptTest(unittest.TestCase):
    def test_release_prepare_script_has_valid_shell_syntax(self) -> None:
        script = Path(__file__).resolve().parent.parent / "scripts" / "release_prepare.sh"
        self.assertTrue(script.exists())
        cp = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(cp.returncode, 0, msg=cp.stderr or cp.stdout)

    def test_release_prepare_script_dry_run_generates_draft(self) -> None:
        root = Path(__file__).resolve().parent.parent
        script = root / "scripts" / "release_prepare.sh"
        with tempfile.TemporaryDirectory(prefix="om-release-prepare.") as d:
            out_dir = Path(d)
            before = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
            cp = subprocess.run(
                ["bash", str(script), "--out-dir", str(out_dir)],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(cp.returncode, 0, msg=cp.stderr or cp.stdout)
            self.assertIn("dry-run only", cp.stdout)
            self.assertTrue(any(p.name.startswith("release-v") and p.suffix == ".md" for p in out_dir.glob("*.md")))
            after = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
