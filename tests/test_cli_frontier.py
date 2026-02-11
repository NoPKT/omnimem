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

    def test_ingest_command_registered(self) -> None:
        p = build_parser()
        args = p.parse_args(["ingest", "--type", "text", "--text", "hello"])
        self.assertEqual(args.cmd, "ingest")

    def test_feedback_command_registered(self) -> None:
        p = build_parser()
        args = p.parse_args(["feedback", "--id", "m1", "--feedback", "positive"])
        self.assertEqual(args.cmd, "feedback")


if __name__ == "__main__":
    unittest.main()
