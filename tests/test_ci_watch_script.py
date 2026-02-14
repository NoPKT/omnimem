from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class CiWatchScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        cls.script = cls.root / "scripts" / "ci_watch.sh"

    def test_help(self) -> None:
        proc = subprocess.run(
            ["bash", "scripts/ci_watch.sh", "--help"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Usage:", proc.stdout)
        self.assertIn("--workflow", proc.stdout)

    def test_script_has_strict_mode(self) -> None:
        txt = self.script.read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", txt)
        self.assertIn("gh run watch", txt)

    def _fake_gh_env(self) -> tuple[Path, dict[str, str]]:
        tmpdir = Path(tempfile.mkdtemp(prefix="omnimem-gh-fake-"))
        gh = tmpdir / "gh"
        gh.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail
                if [[ "${1:-}" == "auth" && "${2:-}" == "status" ]]; then
                  exit 0
                fi
                if [[ "${1:-}" == "run" && "${2:-}" == "list" ]]; then
                  cat <<'JSON'
                [{"databaseId":1001,"headSha":"abc123def","status":"completed","conclusion":"success","workflowName":"ci","headBranch":"main"},{"databaseId":1002,"headSha":"ff00aa11","status":"in_progress","conclusion":"","workflowName":"ci","headBranch":"main"}]
                JSON
                  exit 0
                fi
                if [[ "${1:-}" == "run" && "${2:-}" == "watch" ]]; then
                  exit 0
                fi
                if [[ "${1:-}" == "run" && "${2:-}" == "view" ]]; then
                  if [[ "${4:-}" == "--json" ]]; then
                    cat <<'JSON'
                {"status":"completed","conclusion":"success","url":"https://example.invalid/r/1001","workflowName":"ci","createdAt":"2026-02-14T00:00:00Z","updatedAt":"2026-02-14T00:01:00Z"}
                JSON
                    exit 0
                  fi
                  exit 0
                fi
                echo "unexpected gh args: $*" >&2
                exit 1
                """
            ),
            encoding="utf-8",
        )
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        env = os.environ.copy()
        env["PATH"] = f"{tmpdir}:{env.get('PATH', '')}"
        return tmpdir, env

    def test_dry_run_selects_matching_commit_run_id(self) -> None:
        tmpdir, env = self._fake_gh_env()
        try:
            proc = subprocess.run(
                [
                    "bash",
                    str(self.script),
                    "--dry-run",
                    "--workflow",
                    "ci.yml",
                    "--branch",
                    "main",
                    "--commit",
                    "abc123",
                ],
                cwd=str(self.root),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            self.assertIn("run_id=1001", proc.stdout)
            self.assertIn("gh run watch 1001", proc.stdout)
        finally:
            subprocess.run(["rm", "-rf", str(tmpdir)], check=False)


if __name__ == "__main__":
    unittest.main()
