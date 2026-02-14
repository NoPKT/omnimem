from __future__ import annotations

import unittest

from omnimem.agent import _context_observability


class AgentContextObservabilityTest(unittest.TestCase):
    def test_context_observability_fields(self) -> None:
        obs = _context_observability(
            {
                "budget_tokens": 400,
                "estimated_tokens": 250,
                "selected_count": 6,
                "selected_core_count": 4,
                "selected_expand_count": 2,
                "delta_new_count": 3,
                "delta_seen_count": 7,
                "carry_queued_count": 5,
                "route": "procedural",
            }
        )
        self.assertEqual(int(obs["context_budget_tokens"]), 400)
        self.assertEqual(int(obs["context_estimated_tokens"]), 250)
        self.assertAlmostEqual(float(obs["context_utilization"]), 0.625, places=3)
        self.assertEqual(str(obs["context_pressure"]), "balanced")
        self.assertIn("balanced", str(obs["context_hint"]))
        self.assertEqual(int(obs["context_selected_count"]), 6)
        self.assertEqual(int(obs["context_selected_core_count"]), 4)
        self.assertEqual(int(obs["context_selected_expand_count"]), 2)
        self.assertEqual(int(obs["context_delta_new_count"]), 3)
        self.assertEqual(int(obs["context_delta_seen_count"]), 7)
        self.assertEqual(int(obs["context_carry_queued_count"]), 5)
        self.assertEqual(str(obs["context_route"]), "procedural")

    def test_context_pressure_edges(self) -> None:
        hi = _context_observability({"budget_tokens": 100, "estimated_tokens": 99})
        self.assertEqual(str(hi["context_pressure"]), "high")
        self.assertIn("near budget cap", str(hi["context_hint"]))
        lo = _context_observability({"budget_tokens": 100, "estimated_tokens": 30})
        self.assertEqual(str(lo["context_pressure"]), "low")
        self.assertIn("spare budget", str(lo["context_hint"]))


if __name__ == "__main__":
    unittest.main()
