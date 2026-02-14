from __future__ import annotations

import unittest

from omnimem.context_strategy import resolve_context_plan


class ContextStrategyTest(unittest.TestCase):
    def test_balanced_normal_keeps_shape(self) -> None:
        p = resolve_context_plan(profile="balanced", quota_mode="normal", context_budget_tokens=420, retrieve_limit=8)
        self.assertEqual(p.profile, "balanced")
        self.assertEqual(p.quota_mode, "normal")
        self.assertEqual(p.context_budget_tokens, 420)
        self.assertEqual(p.retrieve_limit, 8)
        self.assertTrue(p.prefer_delta_context)
        self.assertTrue(p.stable_prefix)
        self.assertIn("manual quota mode", p.decision_reason)

    def test_low_quota_critical_reduces_budget_and_limit(self) -> None:
        p = resolve_context_plan(profile="low_quota", quota_mode="critical", context_budget_tokens=420, retrieve_limit=8)
        self.assertLess(p.context_budget_tokens, 420)
        self.assertLess(p.retrieve_limit, 8)
        self.assertTrue(p.prefer_delta_context)

    def test_deep_research_expands_under_normal_quota(self) -> None:
        p = resolve_context_plan(profile="deep_research", quota_mode="normal", context_budget_tokens=420, retrieve_limit=8)
        self.assertGreater(p.context_budget_tokens, 420)
        self.assertGreaterEqual(p.retrieve_limit, 8)

    def test_auto_quota_mode_maps_by_prompt_size(self) -> None:
        p_small = resolve_context_plan(
            profile="balanced",
            quota_mode="auto",
            context_budget_tokens=420,
            retrieve_limit=8,
            prompt_tokens_estimate=120,
        )
        self.assertEqual(p_small.quota_mode, "normal")
        self.assertIn("prompt_tokens_estimate", p_small.decision_reason)
        p_mid = resolve_context_plan(
            profile="balanced",
            quota_mode="auto",
            context_budget_tokens=420,
            retrieve_limit=8,
            prompt_tokens_estimate=700,
        )
        self.assertEqual(p_mid.quota_mode, "low")
        p_big = resolve_context_plan(
            profile="balanced",
            quota_mode="auto",
            context_budget_tokens=420,
            retrieve_limit=8,
            prompt_tokens_estimate=1600,
        )
        self.assertEqual(p_big.quota_mode, "critical")

    def test_auto_quota_mode_uses_recent_transient_failures(self) -> None:
        p = resolve_context_plan(
            profile="balanced",
            quota_mode="auto",
            context_budget_tokens=420,
            retrieve_limit=8,
            prompt_tokens_estimate=100,
            recent_transient_failures=4,
        )
        self.assertEqual(p.quota_mode, "low")
        self.assertIn("recent transient failures", p.decision_reason)

    def test_auto_quota_mode_uses_recent_context_utilization(self) -> None:
        p = resolve_context_plan(
            profile="balanced",
            quota_mode="auto",
            context_budget_tokens=420,
            retrieve_limit=8,
            prompt_tokens_estimate=100,
            recent_context_utilization=0.91,
        )
        self.assertEqual(p.quota_mode, "low")
        self.assertIn("recent context utilization", p.decision_reason)


if __name__ == "__main__":
    unittest.main()
