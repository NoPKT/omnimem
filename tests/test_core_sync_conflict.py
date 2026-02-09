from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from omnimem.core import MemoryPaths, run_sync_with_retry, sync_git, sync_error_hint


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["git", *args]
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


class SyncConflictTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omnimem-sync-conflict.")
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote.git"
        self.repo_a = self.root / "repo-a"
        self.repo_b = self.root / "repo-b"
        self.schema = _schema_sql_path()

        _git("init", "--bare", str(self.remote))
        _git("clone", str(self.remote), str(self.repo_a))
        _git("clone", str(self.remote), str(self.repo_b))
        self._setup_repo(self.repo_a)
        self._setup_repo(self.repo_b)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _setup_repo(self, repo: Path) -> None:
        _git("config", "user.email", "sync@test.local", cwd=repo)
        _git("config", "user.name", "Sync Test", cwd=repo)
        _git("checkout", "-B", "main", cwd=repo)

    def test_non_fast_forward_is_classified_as_conflict(self) -> None:
        # Seed remote with first commit from repo-a.
        (self.repo_a / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git("add", "-A", cwd=self.repo_a)
        _git("commit", "-m", "seed", cwd=self.repo_a)
        _git("push", "-u", "origin", "main", cwd=self.repo_a)

        # Repo-b syncs to seed state.
        _git("fetch", "origin", "main", cwd=self.repo_b)
        _git("reset", "--hard", "origin/main", cwd=self.repo_b)

        # Advance remote from repo-a.
        (self.repo_a / "a.txt").write_text("from a\n", encoding="utf-8")
        _git("add", "-A", cwd=self.repo_a)
        _git("commit", "-m", "a-commit", cwd=self.repo_a)
        _git("push", "origin", "main", cwd=self.repo_a)

        # Create divergent local commit in repo-b without pulling.
        (self.repo_b / "b.txt").write_text("from b\n", encoding="utf-8")
        _git("add", "-A", cwd=self.repo_b)
        _git("commit", "-m", "b-commit", cwd=self.repo_b)

        paths = MemoryPaths(
            root=self.repo_b,
            markdown_root=self.repo_b / "data" / "markdown",
            jsonl_root=self.repo_b / "data" / "jsonl",
            sqlite_path=self.repo_b / "data" / "omnimem.db",
        )
        out = run_sync_with_retry(
            runner=sync_git,
            paths=paths,
            schema_sql_path=self.schema,
            mode="github-push",
            remote_name="origin",
            branch="main",
            remote_url=None,
            max_attempts=4,
            initial_backoff=1,
            max_backoff=1,
            sleep_fn=lambda _s: None,
        )

        self.assertFalse(out.get("ok", True))
        self.assertEqual(out.get("error_kind"), "conflict")
        self.assertFalse(out.get("retryable", True))
        self.assertEqual(out.get("attempts"), 1)
        self.assertIn("Sync conflict detected", sync_error_hint("conflict"))


if __name__ == "__main__":
    unittest.main()
