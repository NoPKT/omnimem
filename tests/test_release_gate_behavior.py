from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class ReleaseGateBehaviorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Path(__file__).resolve().parent.parent
        cls.script = cls.repo / "scripts" / "release_gate.sh"

    def _make_fake_omnimem(self, doctor_issues: list[str]) -> tuple[Path, dict[str, str]]:
        tmpdir = Path(tempfile.mkdtemp(prefix="omnimem-gate-test-"))
        fake = tmpdir / "omnimem"
        issues_json = json.dumps(doctor_issues, ensure_ascii=False)
        fake.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                cmd="${{1:-}}"
                if [[ "$cmd" == "preflight" ]]; then
                  cat <<'JSON'
                {{"ok":true,"checks":{{"git_worktree":true,"changed_count":1}},"issues":[]}}
                JSON
                  exit 0
                fi
                if [[ "$cmd" == "doctor" ]]; then
                  cat <<'JSON'
                {{"ok":false,"issues":{issues_json},"actions":[]}}
                JSON
                  exit 1
                fi
                echo "{{\"ok\":true}}"
                exit 0
                """
            ),
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        env = os.environ.copy()
        env["PATH"] = f"{tmpdir}:{env.get('PATH', '')}"
        return tmpdir, env

    def _make_temp_repo_with_script(self, *, dirty: bool) -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="omnimem-gate-repo-"))
        scripts_dir = tmpdir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        target = scripts_dir / "release_gate.sh"
        target.write_text(self.script.read_text(encoding="utf-8"), encoding="utf-8")
        target.chmod(target.stat().st_mode | stat.S_IXUSR)

        subprocess.run(["git", "init"], cwd=str(tmpdir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "bot@example.com"], cwd=str(tmpdir), check=True)
        subprocess.run(["git", "config", "user.name", "Bot"], cwd=str(tmpdir), check=True)
        (tmpdir / "README.md").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md", "scripts/release_gate.sh"], cwd=str(tmpdir), check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmpdir), check=True, capture_output=True)
        if dirty:
            (tmpdir / "README.md").write_text("hello\nworld\n", encoding="utf-8")
        return tmpdir

    def test_doctor_tolerated_issues_are_non_blocking_by_default(self) -> None:
        tmpdir, env = self._make_fake_omnimem(
            [
                "sync remote_url not configured",
                "git worktree has uncommitted changes",
            ]
        )
        try:
            cp = subprocess.run(
                [
                    "bash",
                    str(self.script),
                    "--skip-pack",
                    "--skip-docs",
                    "--skip-phase-d",
                    "--skip-frontier",
                ],
                cwd=str(self.repo),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(cp.returncode, 0, msg=cp.stderr or cp.stdout)
            self.assertIn("doctor warnings (non-blocking)", cp.stdout)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_doctor_tolerated_issues_fail_in_strict_mode(self) -> None:
        tmpdir, env = self._make_fake_omnimem(
            [
                "sync remote_url not configured",
                "git worktree has uncommitted changes",
            ]
        )
        try:
            cp = subprocess.run(
                [
                    "bash",
                    str(self.script),
                    "--doctor-strict",
                    "--skip-pack",
                    "--skip-docs",
                    "--skip-phase-d",
                    "--skip-frontier",
                ],
                cwd=str(self.repo),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(cp.returncode, 0)
            self.assertIn("doctor failed (strict mode)", cp.stderr)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_doctor_blocking_issue_always_fails(self) -> None:
        tmpdir, env = self._make_fake_omnimem(["storage verification failed"])
        try:
            cp = subprocess.run(
                [
                    "bash",
                    str(self.script),
                    "--skip-pack",
                    "--skip-docs",
                    "--skip-phase-d",
                    "--skip-frontier",
                ],
                cwd=str(self.repo),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(cp.returncode, 0)
            combined = f"{cp.stdout}\n{cp.stderr}"
            self.assertIn("doctor blocking issues", combined)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_require_clean_fails_on_dirty_repo(self) -> None:
        repo = self._make_temp_repo_with_script(dirty=True)
        fake_dir, env = self._make_fake_omnimem([])
        try:
            cp = subprocess.run(
                [
                    "bash",
                    "scripts/release_gate.sh",
                    "--require-clean",
                    "--allow-clean",
                    "--skip-doctor",
                    "--skip-pack",
                    "--skip-docs",
                    "--skip-phase-d",
                    "--skip-frontier",
                ],
                cwd=str(repo),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(cp.returncode, 0)
            self.assertIn("--require-clean failed", cp.stderr)
        finally:
            shutil.rmtree(fake_dir, ignore_errors=True)
            shutil.rmtree(repo, ignore_errors=True)

    def test_require_clean_passes_on_clean_repo(self) -> None:
        repo = self._make_temp_repo_with_script(dirty=False)
        fake_dir, env = self._make_fake_omnimem([])
        try:
            cp = subprocess.run(
                [
                    "bash",
                    "scripts/release_gate.sh",
                    "--require-clean",
                    "--allow-clean",
                    "--skip-doctor",
                    "--skip-pack",
                    "--skip-docs",
                    "--skip-phase-d",
                    "--skip-frontier",
                ],
                cwd=str(repo),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(cp.returncode, 0, msg=cp.stderr or cp.stdout)
            self.assertIn("release gate passed", cp.stdout)
        finally:
            shutil.rmtree(fake_dir, ignore_errors=True)
            shutil.rmtree(repo, ignore_errors=True)

    def test_formal_release_implies_doctor_strict(self) -> None:
        repo = self._make_temp_repo_with_script(dirty=False)
        fake_dir, env = self._make_fake_omnimem(
            [
                "sync remote_url not configured",
                "git worktree has uncommitted changes",
            ]
        )
        try:
            cp = subprocess.run(
                [
                    "bash",
                    "scripts/release_gate.sh",
                    "--formal-release",
                    "--skip-pack",
                    "--skip-docs",
                    "--skip-phase-d",
                    "--skip-frontier",
                ],
                cwd=str(repo),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(cp.returncode, 0)
            self.assertIn("doctor failed (strict mode)", cp.stderr)
        finally:
            shutil.rmtree(fake_dir, ignore_errors=True)
            shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
