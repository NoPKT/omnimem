from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from omnimem.memory_context import build_budgeted_memory_context, infer_query_route


class MemoryContextTest(unittest.TestCase):
    def test_route_inference(self) -> None:
        self.assertEqual(infer_query_route("how to run script"), "procedural")
        self.assertEqual(infer_query_route("when did this happen"), "episodic")
        self.assertEqual(infer_query_route("what is memory graph"), "semantic")

    def test_budget_and_delta(self) -> None:
        with tempfile.TemporaryDirectory(prefix="om-mctx.") as d:
            root = Path(d)
            brief = {
                "checkpoints": [
                    {"updated_at": "2026-02-11T00:00:00+00:00", "summary": "ck1"},
                ]
            }
            candidates = [
                {
                    "id": "a1",
                    "layer": "short",
                    "kind": "summary",
                    "summary": "first memory with many details and long text repeated repeated repeated repeated repeated repeated",
                    "updated_at": "2026-02-11T00:00:01+00:00",
                },
                {
                    "id": "a2",
                    "layer": "long",
                    "kind": "decision",
                    "summary": "second memory with many details and long text repeated repeated repeated repeated repeated repeated",
                    "updated_at": "2026-02-11T00:00:02+00:00",
                },
                {
                    "id": "a3",
                    "layer": "long",
                    "kind": "decision",
                    "summary": "third memory with many details and long text repeated repeated repeated repeated repeated repeated",
                    "updated_at": "2026-02-11T00:00:03+00:00",
                },
                {
                    "id": "a4",
                    "layer": "short",
                    "kind": "summary",
                    "summary": "fourth memory with many details and long text repeated repeated repeated repeated repeated repeated",
                    "updated_at": "2026-02-11T00:00:04+00:00",
                },
                {
                    "id": "a5",
                    "layer": "short",
                    "kind": "summary",
                    "summary": "fifth memory with many details and long text repeated repeated repeated repeated repeated repeated",
                    "updated_at": "2026-02-11T00:00:05+00:00",
                },
            ]
            out1 = build_budgeted_memory_context(
                paths_root=root,
                state_key="k1",
                project_id="OM",
                workspace_name="OM",
                user_prompt="how to do rollback",
                brief=brief,
                candidates=candidates,
                budget_tokens=90,
                include_protocol=True,
                include_user_request=True,
                delta_enabled=True,
                carry_over_enabled=True,
                max_checkpoints=2,
                max_memories=3,
            )
            self.assertTrue(out1.get("ok"))
            self.assertLessEqual(int(out1.get("estimated_tokens", 999999)), 180)
            self.assertGreaterEqual(int(out1.get("selected_count", 0)), 1)
            self.assertGreaterEqual(int(out1.get("carry_queued_count", 0)), 1)
            self.assertGreaterEqual(int(out1.get("core_budget_tokens", 0)), 60)
            self.assertGreaterEqual(int(out1.get("selected_core_count", 0)), 0)
            self.assertGreaterEqual(int(out1.get("selected_expand_count", 0)), 0)

            out2 = build_budgeted_memory_context(
                paths_root=root,
                state_key="k1",
                project_id="OM",
                workspace_name="OM",
                user_prompt="how to do rollback",
                brief=brief,
                candidates=candidates,
                budget_tokens=120,
                include_protocol=True,
                include_user_request=True,
                delta_enabled=True,
                carry_over_enabled=True,
                max_checkpoints=2,
                max_memories=3,
            )
            self.assertTrue(out2.get("ok"))
            self.assertGreaterEqual(int(out2.get("delta_seen_count", 0)), int(out1.get("selected_count", 0)))
            self.assertGreaterEqual(int(out2.get("selected_count", 0)), int(out1.get("selected_count", 0)))


if __name__ == "__main__":
    unittest.main()
