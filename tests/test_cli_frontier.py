from __future__ import annotations

import unittest

from omnimem.cli import build_parser


class CLIFrontierCommandTest(unittest.TestCase):
    def test_raptor_command_registered(self) -> None:
        p = build_parser()
        args = p.parse_args(["raptor", "--project-id", "OM"])
        self.assertEqual(args.cmd, "raptor")

    def test_enhance_command_registered(self) -> None:
        p = build_parser()
        args = p.parse_args(["enhance", "--project-id", "OM"])
        self.assertEqual(args.cmd, "enhance")

    def test_profile_command_registered(self) -> None:
        p = build_parser()
        args = p.parse_args(["profile", "--project-id", "OM"])
        self.assertEqual(args.cmd, "profile")

    def test_profile_drift_command_registered(self) -> None:
        p = build_parser()
        args = p.parse_args(["profile-drift", "--project-id", "OM"])
        self.assertEqual(args.cmd, "profile-drift")

    def test_ingest_command_registered(self) -> None:
        p = build_parser()
        args = p.parse_args(["ingest", "--type", "text", "--text", "hello"])
        self.assertEqual(args.cmd, "ingest")

    def test_feedback_command_registered(self) -> None:
        p = build_parser()
        args = p.parse_args(["feedback", "--id", "m1", "--feedback", "positive"])
        self.assertEqual(args.cmd, "feedback")

    def test_retrieve_drift_args_registered(self) -> None:
        p = build_parser()
        args = p.parse_args(["retrieve", "hello", "--drift-aware", "--drift-weight", "0.4"])
        self.assertEqual(args.cmd, "retrieve")
        self.assertTrue(bool(args.drift_aware))

    def test_core_block_commands_registered(self) -> None:
        p = build_parser()
        a1 = p.parse_args(["core-set", "--name", "persona", "--body", "be concise"])
        self.assertEqual(a1.cmd, "core-set")
        a2 = p.parse_args(["core-get", "--name", "persona"])
        self.assertEqual(a2.cmd, "core-get")
        a3 = p.parse_args(["core-list", "--project-id", "OM"])
        self.assertEqual(a3.cmd, "core-list")


if __name__ == "__main__":
    unittest.main()
