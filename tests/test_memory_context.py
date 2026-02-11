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
                {"id": "a1", "layer": "short", "kind": "summary", "summary": "first memory", "updated_at": "2026-02-11T00:00:01+00:00"},
                {"id": "a2", "layer": "long", "kind": "decision", "summary": "second memory", "updated_at": "2026-02-11T00:00:02+00:00"},
                {"id": "a3", "layer": "long", "kind": "decision", "summary": "third memory", "updated_at": "2026-02-11T00:00:03+00:00"},
            ]
            out1 = build_budgeted_memory_context(
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
                max_checkpoints=2,
                max_memories=3,
            )
            self.assertTrue(out1.get("ok"))
            self.assertLessEqual(int(out1.get("estimated_tokens", 999999)), 180)
            self.assertGreaterEqual(int(out1.get("selected_count", 0)), 1)

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
                max_checkpoints=2,
                max_memories=3,
            )
            self.assertTrue(out2.get("ok"))
            self.assertGreaterEqual(int(out2.get("delta_seen_count", 0)), int(out1.get("selected_count", 0)))


if __name__ == "__main__":
    unittest.main()

