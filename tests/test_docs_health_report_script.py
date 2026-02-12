from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class DocsHealthReportScriptTest(unittest.TestCase):
    def test_report_script_outputs_json_file(self) -> None:
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(prefix="om-docs-health-report.") as td:
            out = Path(td) / "report.json"
            cp = subprocess.run(
                ["python3", "scripts/report_docs_health.py", "--out", str(out)],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(cp.returncode, 0, msg=cp.stderr or cp.stdout)
            self.assertTrue(out.exists())
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("totals", data)
            self.assertIn("files", data.get("totals", {}))
            self.assertIn("per_file", data)


if __name__ == "__main__":
    unittest.main()

