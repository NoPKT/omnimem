from __future__ import annotations

import unittest

from omnimem.cli import _doctor_actions, _doctor_sync_issues, build_parser


class CLIDoctorTest(unittest.TestCase):
    def test_doctor_command_registered(self) -> None:
        p = build_parser()
        args = p.parse_args(["doctor", "--host", "127.0.0.1", "--port", "8765"])
        self.assertEqual(args.cmd, "doctor")

    def test_doctor_actions_for_unreachable_pid(self) -> None:
        actions = _doctor_actions(
            {
                "webui": {"host": "127.0.0.1", "port": 8765, "reachable": False, "pid_alive": True},
                "daemon": {"enabled": True, "last_error_kind": "none"},
                "sync": {"remote_url_configured": True, "dirty": False},
            }
        )
        self.assertTrue(any("omnimem stop --host 127.0.0.1 --port 8765" in x for x in actions))
        self.assertTrue(any("omnimem start --host 127.0.0.1 --port 8765" in x for x in actions))

    def test_doctor_actions_for_sync_conflict(self) -> None:
        actions = _doctor_actions(
            {
                "webui": {"host": "127.0.0.1", "port": 8765, "reachable": True, "pid_alive": True},
                "daemon": {"enabled": True, "last_error_kind": "conflict"},
                "sync": {"remote_url_configured": False, "dirty": True},
            }
        )
        self.assertTrue(any("github-bootstrap" in x for x in actions))
        self.assertTrue(any("github-status" in x for x in actions))
        self.assertTrue(any("resolve conflicts" in x for x in actions))

    def test_doctor_sync_issues_for_stale_daemon(self) -> None:
        issues = _doctor_sync_issues(
            {
                "enabled": True,
                "running": True,
                "latency": {"since_last_run_s": 420, "pull_interval_s": 30},
            },
            {"event_count": 0, "failure_rate": 0.0, "error_kinds": {}},
        )
        self.assertTrue(any("stale" in x for x in issues))

    def test_doctor_sync_issues_for_high_failure_rate(self) -> None:
        issues = _doctor_sync_issues(
            {"enabled": True, "running": True, "latency": {"since_last_run_s": 10, "pull_interval_s": 30}},
            {"event_count": 8, "failure_rate": 0.75, "error_kinds": {"network": 5}},
        )
        self.assertTrue(any("failure rate is high" in x for x in issues))
        self.assertTrue(any("dominant sync error_kind=network" in x for x in issues))


if __name__ == "__main__":
    unittest.main()
