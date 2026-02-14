from __future__ import annotations

import unittest

from omnimem.cli import _runtime_tuning_hints


class CLIRuntimeHintsTest(unittest.TestCase):
    def test_hints_cover_retry_and_pressure(self) -> None:
        out = {
            "tool_retried": True,
            "tool_attempts": 3,
            "tool_transient_failures": 2,
            "context_pressure": "high",
            "context_route": "procedural",
        }
        hs = _runtime_tuning_hints(out)
        joined = "\n".join(hs)
        self.assertIn("transient recovery", joined)
        self.assertIn("context pressure is high", joined)
        self.assertIn("route inferred as procedural", joined)

    def test_hints_for_low_pressure(self) -> None:
        out = {"context_pressure": "low", "tool_retried": False, "context_route": "general"}
        hs = _runtime_tuning_hints(out)
        self.assertEqual(len(hs), 1)
        self.assertIn("deep_research", hs[0])

    def test_hints_include_output_size_suggestion(self) -> None:
        out = {"answer": "alpha " * 300, "tool_retried": False}
        hs = _runtime_tuning_hints(out)
        joined = "\n".join(hs)
        self.assertIn("observed output size", joined)
        self.assertIn("max_output_tokens", joined)


if __name__ == "__main__":
    unittest.main()
