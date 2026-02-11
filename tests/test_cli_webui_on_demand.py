from __future__ import annotations

import unittest

from omnimem.cli import build_parser


class CLIDemandWebUITest(unittest.TestCase):
    def test_codex_default_on_demand(self) -> None:
        p = build_parser()
        args = p.parse_args(["codex"])
        self.assertFalse(getattr(args, "webui_persist", False))

    def test_codex_flag_is_parsable(self) -> None:
        p = build_parser()
        args = p.parse_args(["codex", "--webui-on-demand"])
        self.assertTrue(getattr(args, "webui_on_demand", False))

    def test_codex_persist_flag_is_parsable(self) -> None:
        p = build_parser()
        args = p.parse_args(["codex", "--webui-persist"])
        self.assertTrue(getattr(args, "webui_persist", False))

    def test_claude_flag_is_parsable(self) -> None:
        p = build_parser()
        args = p.parse_args(["claude", "--webui-on-demand"])
        self.assertTrue(getattr(args, "webui_on_demand", False))

    def test_webui_guard_command_is_registered(self) -> None:
        p = build_parser()
        args = p.parse_args(
            [
                "webui-guard",
                "--runtime-dir",
                "/tmp/omnimem-runtime",
                "--host",
                "127.0.0.1",
                "--port",
                "8765",
                "--parent-pid",
                "123",
                "--lease",
                "/tmp/lease.json",
            ]
        )
        self.assertEqual(args.cmd, "webui-guard")

    def test_stop_command_is_registered(self) -> None:
        p = build_parser()
        args = p.parse_args(["stop", "--host", "127.0.0.1", "--port", "8765"])
        self.assertEqual(args.cmd, "stop")

    def test_stop_all_flag_is_parsable(self) -> None:
        p = build_parser()
        args = p.parse_args(["stop", "--all"])
        self.assertTrue(getattr(args, "all", False))


if __name__ == "__main__":
    unittest.main()
