from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


class DocsI18nScriptTest(unittest.TestCase):
    def test_docs_i18n_script_passes(self) -> None:
        root = Path(__file__).resolve().parent.parent
        cp = subprocess.run(
            ["python3", "scripts/check_docs_i18n.py"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(cp.returncode, 0, msg=cp.stderr or cp.stdout)
        out = json.loads(cp.stdout)
        self.assertTrue(bool(out.get("ok")))
        self.assertGreaterEqual(int(out.get("checked_pairs", 0)), 7)


if __name__ == "__main__":
    unittest.main()
