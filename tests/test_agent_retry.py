from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from omnimem.agent import _extract_retry_after_seconds, _is_transient_tool_error, _run_tool_with_retry


class AgentRetryTest(unittest.TestCase):
    def test_transient_classifier(self) -> None:
        self.assertTrue(_is_transient_tool_error("429 rate limit exceeded"))
        self.assertTrue(_is_transient_tool_error("Service Unavailable 503"))
        self.assertTrue(_is_transient_tool_error("temporarily overloaded, try again"))
        self.assertFalse(_is_transient_tool_error("invalid api key"))

    def test_extract_retry_after_seconds(self) -> None:
        self.assertAlmostEqual(float(_extract_retry_after_seconds("retry-after: 3") or 0.0), 3.0, places=6)
        self.assertAlmostEqual(float(_extract_retry_after_seconds("retry_after=1.5") or 0.0), 1.5, places=6)
        self.assertIsNone(_extract_retry_after_seconds("no hint"))

    def test_run_tool_with_retry_recovers_after_transient(self) -> None:
        calls: list[int] = []

        def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(1)
            if len(calls) == 1:
                return subprocess.CompletedProcess(args[0], returncode=1, stdout="", stderr="429 rate limit")
            return subprocess.CompletedProcess(args[0], returncode=0, stdout="ok", stderr="")

        with patch("omnimem.agent.subprocess.run", side_effect=_fake_run), patch("omnimem.agent.time.sleep", return_value=None):
            out = _run_tool_with_retry(
                cmd=["echo", "x"],
                cwd=None,
                retry_max_attempts=3,
                retry_initial_backoff_s=0.01,
                retry_max_backoff_s=0.02,
            )
        self.assertEqual(int(out.process.returncode), 0)
        self.assertEqual(int(out.attempts), 2)
        self.assertEqual(int(out.retried), 1)
        self.assertEqual(int(out.transient_failures), 1)
        self.assertEqual(len(calls), 2)

    def test_run_tool_with_retry_stops_on_non_transient(self) -> None:
        with patch(
            "omnimem.agent.subprocess.run",
            return_value=subprocess.CompletedProcess(["x"], returncode=1, stdout="", stderr="invalid request"),
        ) as m_run, patch("omnimem.agent.time.sleep", return_value=None) as m_sleep:
            out = _run_tool_with_retry(
                cmd=["x"],
                cwd=None,
                retry_max_attempts=4,
                retry_initial_backoff_s=0.01,
                retry_max_backoff_s=0.02,
            )
        self.assertEqual(int(out.process.returncode), 1)
        self.assertEqual(int(out.attempts), 1)
        self.assertEqual(int(out.retried), 0)
        self.assertEqual(int(out.transient_failures), 0)
        self.assertEqual(m_run.call_count, 1)
        self.assertEqual(m_sleep.call_count, 0)

    def test_run_tool_with_retry_honors_retry_after_hint(self) -> None:
        calls: list[int] = []

        def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(1)
            if len(calls) == 1:
                return subprocess.CompletedProcess(args[0], returncode=1, stdout="", stderr="429 retry-after: 2")
            return subprocess.CompletedProcess(args[0], returncode=0, stdout="ok", stderr="")

        sleep_vals: list[float] = []

        def _fake_sleep(v: float) -> None:
            sleep_vals.append(float(v))

        with (
            patch("omnimem.agent.subprocess.run", side_effect=_fake_run),
            patch("omnimem.agent.random.uniform", return_value=0.0),
            patch("omnimem.agent.time.sleep", side_effect=_fake_sleep),
        ):
            out = _run_tool_with_retry(
                cmd=["echo", "x"],
                cwd=None,
                retry_max_attempts=3,
                retry_initial_backoff_s=0.2,
                retry_max_backoff_s=5.0,
            )
        self.assertEqual(int(out.process.returncode), 0)
        self.assertGreaterEqual(len(sleep_vals), 1)
        self.assertGreaterEqual(float(sleep_vals[0]), 2.0)


if __name__ == "__main__":
    unittest.main()
