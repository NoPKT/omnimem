from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from omnimem.webui import HTML_PAGE


class WebUiScriptSyntaxTest(unittest.TestCase):
    def test_embedded_script_is_valid_javascript(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not available")
        scripts = re.findall(r"<script>([\s\S]*?)</script>", HTML_PAGE)
        self.assertGreaterEqual(len(scripts), 1, "embedded script not found in HTML_PAGE")
        with tempfile.TemporaryDirectory(prefix="om-webui-js.") as d:
            for i, script in enumerate(scripts):
                src = str(script or "").strip()
                if not src:
                    continue
                fp = Path(d) / f"webui-{i}.js"
                fp.write_text(src, encoding="utf-8")
                cp = subprocess.run([node, "--check", str(fp)], capture_output=True, text=True)
                self.assertEqual(0, cp.returncode, msg=(cp.stderr or cp.stdout or f"node --check failed for script #{i}"))

    def test_script_contains_forecast_and_disclosure_hooks(self) -> None:
        self.assertIn('id="maintForecast"', HTML_PAGE)
        self.assertIn("function renderMaintenanceForecast", HTML_PAGE)
        self.assertIn('details class="disclosure"', HTML_PAGE)
        self.assertIn("status_feedback", HTML_PAGE)
        self.assertIn("change pressure", HTML_PAGE)


if __name__ == "__main__":
    unittest.main()
