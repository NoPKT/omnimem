from __future__ import annotations

import unittest

from omnimem.webui import _build_smart_memories_cache_key
from omnimem.webui import _resolve_memories_scan_limit


class WebUIMemoriesPagingTest(unittest.TestCase):
    def test_basic_scan_limit_includes_offset(self) -> None:
        got = _resolve_memories_scan_limit(req_limit=100, req_offset=400, sort_mode="server", mode="basic")
        self.assertEqual(got, 500)

    def test_basic_scan_limit_respects_sorted_floor(self) -> None:
        got = _resolve_memories_scan_limit(req_limit=20, req_offset=0, sort_mode="updated_desc", mode="basic")
        self.assertEqual(got, 400)

    def test_smart_scan_limit_has_buffer(self) -> None:
        got = _resolve_memories_scan_limit(req_limit=80, req_offset=120, sort_mode="server", mode="smart")
        self.assertEqual(got, 320)

    def test_smart_cache_key_depends_on_offset(self) -> None:
        req = {
            "project_id": "p1",
            "session_id": "s1",
            "query": "test",
            "depth": 2,
            "per_hop": 6,
            "ranking_mode": "hybrid",
            "diversify": True,
            "mmr_lambda": 0.72,
            "limit": 50,
            "offset": 0,
            "profile_aware": True,
            "profile_weight": 0.35,
            "include_core_blocks": True,
            "core_block_limit": 2,
            "core_merge_by_topic": True,
            "drift_aware": True,
            "drift_recent_days": 14,
            "drift_baseline_days": 120,
            "drift_weight": 0.35,
            "sort_mode": "server",
        }
        k1 = _build_smart_memories_cache_key(req)
        req2 = dict(req)
        req2["offset"] = 200
        k2 = _build_smart_memories_cache_key(req2)
        self.assertNotEqual(k1, k2)


if __name__ == "__main__":
    unittest.main()
