from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class ReleaseGateScriptTest(unittest.TestCase):
    def test_release_gate_script_has_valid_shell_syntax(self) -> None:
        script = Path(__file__).resolve().parent.parent / "scripts" / "release_gate.sh"
        self.assertTrue(script.exists())
        cp = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(cp.returncode, 0, msg=cp.stderr or cp.stdout)

    def test_release_gate_script_contains_expected_steps(self) -> None:
        script = Path(__file__).resolve().parent.parent / "scripts" / "release_gate.sh"
        txt = script.read_text(encoding="utf-8")
        self.assertIn("command -v omnimem", txt)
        self.assertIn("python3 -m omnimem.cli", txt)
        self.assertIn("\"${OM[@]}\" preflight --path", txt)
        self.assertIn("\"${OM[@]}\" doctor", txt)
        self.assertIn("npm run pack:check", txt)
        self.assertIn("bash scripts/verify_phase_d.sh", txt)
        self.assertIn("\"${OM[@]}\" raptor", txt)
        self.assertIn("python3 scripts/eval_locomo_style.py", txt)


if __name__ == "__main__":
    unittest.main()
