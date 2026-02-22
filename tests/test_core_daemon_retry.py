from __future__ import annotations

import unittest
from pathlib import Path

from omnimem.daemon import _daemon_should_attempt_push, run_sync_daemon
from omnimem.core import (
    MemoryPaths,

    classify_sync_error,
    run_sync_with_retry,
    should_retry_sync_error,
    sync_error_hint,
)


class SyncRetryTest(unittest.TestCase):
    def test_daemon_push_trigger_on_repo_dirty(self) -> None:
        self.assertTrue(
            _daemon_should_attempt_push(
                now=20.0,
                last_push_attempt=0.0,
                scan_interval=8,
                current_seen=100.0,
                last_seen=100.0,
                repo_dirty=True,
            )
        )

    def test_daemon_push_not_triggered_before_interval(self) -> None:
        self.assertFalse(
            _daemon_should_attempt_push(
                now=2.0,
                last_push_attempt=0.0,
                scan_interval=8,
                current_seen=101.0,
                last_seen=100.0,
                repo_dirty=True,
            )
        )

    def test_retry_succeeds_after_transient_failures(self) -> None:
        calls = {"n": 0}

        def fake_runner(*args, **kwargs):  # noqa: ANN001, ANN003
            calls["n"] += 1
            if calls["n"] < 3:
                return {"ok": False, "mode": "github-pull", "message": "temporary failure"}
            return {"ok": True, "mode": "github-pull", "message": "ok"}

        paths = MemoryPaths(Path("."), Path("."), Path("."), Path("tmp.db"))
        out = run_sync_with_retry(
            runner=fake_runner,
            paths=paths,
            schema_sql_path=Path("db/schema.sql"),
            mode="github-pull",
            remote_name="origin",
            branch="main",
            remote_url=None,
            max_attempts=4,
            initial_backoff=1,
            max_backoff=1,
            sleep_fn=lambda _s: None,
        )

        self.assertTrue(out["ok"])
        self.assertEqual(out["attempts"], 3)

    def test_retry_exhaustion_returns_last_error(self) -> None:
        def fake_runner(*args, **kwargs):  # noqa: ANN001, ANN003
            return {"ok": False, "mode": "github-push", "message": "persistent failure"}

        paths = MemoryPaths(Path("."), Path("."), Path("."), Path("tmp.db"))
        out = run_sync_with_retry(
            runner=fake_runner,
            paths=paths,
            schema_sql_path=Path("db/schema.sql"),
            mode="github-push",
            remote_name="origin",
            branch="main",
            remote_url=None,
            max_attempts=2,
            initial_backoff=1,
            max_backoff=1,
            sleep_fn=lambda _s: None,
        )

        self.assertFalse(out["ok"])
        self.assertEqual(out["attempts"], 2)
        self.assertEqual(out["message"], "persistent failure")

    def test_auth_error_should_not_retry(self) -> None:
        calls = {"n": 0}

        def fake_runner(*args, **kwargs):  # noqa: ANN001, ANN003
            calls["n"] += 1
            return {"ok": False, "mode": "github-pull", "message": "fatal: Authentication failed"}

        paths = MemoryPaths(Path("."), Path("."), Path("."), Path("tmp.db"))
        out = run_sync_with_retry(
            runner=fake_runner,
            paths=paths,
            schema_sql_path=Path("db/schema.sql"),
            mode="github-pull",
            remote_name="origin",
            branch="main",
            remote_url=None,
            max_attempts=5,
            initial_backoff=1,
            max_backoff=1,
            sleep_fn=lambda _s: None,
        )

        self.assertFalse(out["ok"])
        self.assertEqual(out["error_kind"], "auth")
        self.assertFalse(out["retryable"])
        self.assertEqual(out["attempts"], 1)
        self.assertEqual(calls["n"], 1)

    def test_error_classification_and_policy(self) -> None:
        self.assertEqual(classify_sync_error("permission denied (publickey)"), "auth")
        self.assertEqual(classify_sync_error("could not resolve host: github.com"), "network")
        self.assertEqual(classify_sync_error("non-fast-forward update rejected"), "conflict")
        self.assertEqual(classify_sync_error("unexpected failure"), "unknown")
        self.assertFalse(should_retry_sync_error("auth"))
        self.assertFalse(should_retry_sync_error("conflict"))
        self.assertTrue(should_retry_sync_error("network"))
        self.assertTrue(should_retry_sync_error("unknown"))
        self.assertIn("Authentication failed", sync_error_hint("auth"))
        self.assertIn("Network issue", sync_error_hint("network"))
        self.assertIn("Sync conflict", sync_error_hint("conflict"))
        self.assertIn("Unknown sync failure", sync_error_hint("unknown"))


if __name__ == "__main__":
    unittest.main()
