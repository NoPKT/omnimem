from __future__ import annotations

import unittest

from omnimem.cli import _doctor_actions, build_parser


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


if __name__ == "__main__":
    unittest.main()
