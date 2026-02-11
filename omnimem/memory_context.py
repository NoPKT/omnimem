from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_TOK_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", flags=re.UNICODE)


def estimate_tokens(text: str) -> int:
    s = str(text or "")
    n = len(_TOK_RE.findall(s))
    return max(1, n)


def infer_query_route(query: str) -> str:
    q = str(query or "").strip().lower()
    if not q:
        return "general"
    episodic_hits = ["when", "yesterday", "last time", "之前", "上次", "什么时候", "昨天", "session", "timeline"]
    procedural_hits = ["how to", "steps", "command", "cli", "script", "怎么", "步骤", "命令", "脚本", "如何"]
    semantic_hits = ["what is", "define", "concept", "meaning", "是什么", "定义", "概念", "原理"]
    if any(x in q for x in procedural_hits):
        return "procedural"
    if any(x in q for x in episodic_hits):
        return "episodic"
    if any(x in q for x in semantic_hits):
        return "semantic"
    return "general"


def _delta_state_path(paths_root: Path, key: str) -> Path:
    d = paths_root / "runtime" / "context_delta"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def _load_delta_state(paths_root: Path, key: str) -> dict[str, Any]:
    fp = _delta_state_path(paths_root, key)
    if not fp.exists():
        return {"seen": {}}
    try:
        obj = json.loads(fp.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            seen = obj.get("seen")
            if isinstance(seen, dict):
                carry_raw = obj.get("carry")
                carry: list[str] = []
                if isinstance(carry_raw, list):
                    carry = [str(x).strip() for x in carry_raw if str(x).strip()]
                return {"seen": {str(k): str(v) for k, v in seen.items()}, "carry": carry}
    except Exception:
        pass
    return {"seen": {}, "carry": []}


def _save_delta_state(paths_root: Path, key: str, seen: dict[str, str], carry: list[str]) -> None:
    fp = _delta_state_path(paths_root, key)
    fp.write_text(
        json.dumps(
            {
                "saved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "seen": seen,
                "carry": list(carry)[:1200],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _mem_line(x: dict[str, Any], *, route: str, delta_new: bool) -> str:
    layer = str(x.get("layer", "") or "")
    kind = str(x.get("kind", "") or "")
    summary = str(x.get("summary", "") or "").strip()
    mid = str(x.get("id", "") or "")
    mark = "new" if delta_new else "seen"
    return f"- [{layer}/{kind}/{route}/{mark}] {summary} (id={mid[:8]})"


def build_budgeted_memory_context(
    *,
    paths_root: Path,
    state_key: str,
    project_id: str,
    workspace_name: str,
    user_prompt: str,
    brief: dict[str, Any],
    candidates: list[dict[str, Any]],
    budget_tokens: int = 420,
    include_protocol: bool = True,
    include_user_request: bool = False,
    delta_enabled: bool = True,
    carry_over_enabled: bool = True,
    core_budget_ratio: float = 0.68,
    max_checkpoints: int = 3,
    max_memories: int = 8,
) -> dict[str, Any]:
    budget = max(120, int(budget_tokens))
    core_budget = max(60, min(budget, int(budget * max(0.35, min(0.9, float(core_budget_ratio))))))
    route = infer_query_route(user_prompt)
    st = _load_delta_state(paths_root, state_key) if delta_enabled else {"seen": {}, "carry": []}
    seen = dict(st.get("seen") or {})
    carry_ids = [str(x).strip() for x in (st.get("carry") or []) if str(x).strip()]

    lines: list[str] = []
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines.append(f"OmniMem: {project_id} ({workspace_name}) {now}")
    lines.append("")
    if include_protocol:
        lines.extend(
            [
                "Memory protocol (auto):",
                "- stable decisions/facts -> `omnimem write`",
                "- topic drift/phase switch -> `omnimem checkpoint`",
                "- do not store raw secrets; use credential refs",
            ]
        )
    ck = list(brief.get("checkpoints") or [])[: max(0, int(max_checkpoints))]
    if ck:
        lines.append("Recent checkpoints:")
        for x in ck:
            lines.append(f"- {x.get('updated_at','')}: {x.get('summary','')}")

    cand = list(candidates or [])[: max(1, int(max_memories) * 4)]
    delta_new: list[dict[str, Any]] = []
    delta_seen: list[dict[str, Any]] = []
    for x in cand:
        mid = str(x.get("id", "") or "")
        up = str(x.get("updated_at", "") or "")
        if not mid:
            continue
        if seen.get(mid, "") != up:
            delta_new.append(x)
        else:
            delta_seen.append(x)
    def _route_rank(x: dict[str, Any]) -> tuple[int, int]:
        layer = str(x.get("layer", "") or "")
        # Lower is better.
        if route == "semantic":
            pri = {"long": 0, "short": 1, "archive": 2, "instant": 3}.get(layer, 4)
        elif route == "procedural":
            pri = {"short": 0, "long": 1, "archive": 2, "instant": 3}.get(layer, 4)
        elif route == "episodic":
            pri = {"short": 0, "instant": 1, "long": 2, "archive": 3}.get(layer, 4)
        else:
            pri = {"short": 0, "long": 1, "instant": 2, "archive": 3}.get(layer, 4)
        score = float((x.get("retrieval") or {}).get("score", x.get("score", 0.0)) or 0.0)
        return (pri, -int(score * 1000))

    if delta_enabled and carry_over_enabled and carry_ids:
        by_id = {str(x.get("id", "")).strip(): x for x in (delta_new + delta_seen) if str(x.get("id", "")).strip()}
        carry_front = [by_id[mid] for mid in carry_ids if mid in by_id]
        rest = [x for x in (delta_new + delta_seen) if str(x.get("id", "")).strip() not in set(carry_ids)]
        rest.sort(key=_route_rank)
        ordered = carry_front + rest
    else:
        ordered = (delta_new + delta_seen) if delta_enabled else cand
        ordered.sort(key=_route_rank)
    lines.append(f"Memory recalls (route={route}, budget={budget}):")

    selected: list[dict[str, Any]] = []
    selected_core = 0
    selected_expand = 0
    cur = estimate_tokens("\n".join(lines))
    not_selected: list[str] = []
    for x in ordered:
        if len(selected) >= max(1, int(max_memories)):
            mid2 = str(x.get("id", "") or "").strip()
            if mid2:
                not_selected.append(mid2)
            break
        mid = str(x.get("id", "") or "")
        up = str(x.get("updated_at", "") or "")
        if not mid:
            continue
        one = _mem_line(x, route=route, delta_new=(seen.get(mid, "") != up))
        need = estimate_tokens(one) + 2
        # Two-phase paging: first fill a compact core memory pack, then opportunistically expand.
        if cur < core_budget and (cur + need) > core_budget:
            not_selected.append(mid)
            continue
        if cur + need > budget:
            not_selected.append(mid)
            continue
        lines.append(one)
        cur += need
        selected.append(x)
        if cur <= core_budget:
            selected_core += 1
        else:
            selected_expand += 1
    if len(selected) < max(1, int(max_memories)):
        # collect remaining non-selected ids for carry-over
        sel_set = {str(x.get("id", "")).strip() for x in selected}
        for x in ordered:
            mid = str(x.get("id", "")).strip()
            if mid and mid not in sel_set and mid not in not_selected:
                not_selected.append(mid)

    if include_user_request and str(user_prompt or "").strip():
        tail = f"\nUser request:\n{user_prompt.strip()}"
        if cur + estimate_tokens(tail) <= budget:
            lines.append("")
            lines.append("User request:")
            lines.append(user_prompt.strip())
        else:
            # Keep at least a truncated user request in prompt-injection modes.
            cut = user_prompt.strip()[: max(60, min(400, int((budget - cur) * 4)))]
            lines.append("")
            lines.append("User request:")
            lines.append(cut)

    text = "\n".join(lines).strip()
    est = estimate_tokens(text)

    if delta_enabled:
        next_seen = dict(seen)
        for x in selected:
            mid = str(x.get("id", "") or "")
            up = str(x.get("updated_at", "") or "")
            if mid:
                next_seen[mid] = up
        # keep state bounded
        if len(next_seen) > 1200:
            ks = list(next_seen.keys())[-1200:]
            next_seen = {k: next_seen[k] for k in ks}
        if carry_over_enabled:
            # prioritize fresh misses, then prior carry misses still relevant.
            seen_mids = set(str(x.get("id", "")).strip() for x in ordered)
            next_carry = [mid for mid in not_selected if mid and mid in seen_mids]
            # bound queue
            if len(next_carry) > 1200:
                next_carry = next_carry[:1200]
        else:
            next_carry = []
        _save_delta_state(paths_root, state_key, next_seen, next_carry)

    return {
        "ok": True,
        "text": text,
        "route": route,
        "budget_tokens": budget,
        "estimated_tokens": est,
        "selected_ids": [str(x.get("id", "")) for x in selected if str(x.get("id", ""))],
        "selected_count": len(selected),
        "selected_core_count": selected_core,
        "selected_expand_count": selected_expand,
        "candidate_count": len(cand),
        "delta_new_count": len(delta_new),
        "delta_seen_count": len(delta_seen),
        "carry_queued_count": len(not_selected),
        "core_budget_tokens": core_budget,
    }
