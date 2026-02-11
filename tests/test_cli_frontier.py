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
        a1 = p.parse_args(
            ["core-set", "--name", "persona", "--body", "be concise", "--topic", "style", "--priority", "80", "--ttl-days", "7"]
        )
        self.assertEqual(a1.cmd, "core-set")
        a2 = p.parse_args(["core-get", "--name", "persona"])
        self.assertEqual(a2.cmd, "core-get")
        a3 = p.parse_args(["core-list", "--project-id", "OM", "--include-expired"])
        self.assertEqual(a3.cmd, "core-list")
        a4 = p.parse_args(["retrieve", "hello", "--include-core-blocks", "--core-merge-by-topic"])
        self.assertEqual(a4.cmd, "retrieve")
        a5 = p.parse_args(
            [
                "core-merge-suggest",
                "--project-id",
                "OM",
                "--min-conflicts",
                "2",
                "--loser-action",
                "deprioritize",
                "--min-apply-quality",
                "0.2",
                "--merge-mode",
                "synthesize",
                "--max-merged-lines",
                "6",
            ]
        )
        self.assertEqual(a5.cmd, "core-merge-suggest")


if __name__ == "__main__":
    unittest.main()
