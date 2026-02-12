from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class WebUiI18nReportScriptTest(unittest.TestCase):
    def test_report_script_outputs_json_file(self) -> None:
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(prefix="om-webui-i18n-report.") as td:
            out = Path(td) / "report.json"
            cp = subprocess.run(
                ["python3", "scripts/report_webui_i18n_coverage.py", "--out", str(out)],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(cp.returncode, 0, msg=cp.stderr or cp.stdout)
            self.assertTrue(out.exists())
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("per_locale", data)
            self.assertIn("en", data.get("per_locale", {}))
            self.assertIn("hardcoded_text_candidates_count", data)
            zh = data.get("per_locale", {}).get("zh", {})
            self.assertEqual(zh.get("missing_data_i18n_keys"), [])


if __name__ == "__main__":
    unittest.main()
