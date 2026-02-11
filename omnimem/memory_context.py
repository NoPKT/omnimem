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
                return {"seen": {str(k): str(v) for k, v in seen.items()}}
    except Exception:
        pass
    return {"seen": {}}


def _save_delta_state(paths_root: Path, key: str, seen: dict[str, str]) -> None:
    fp = _delta_state_path(paths_root, key)
    fp.write_text(
        json.dumps(
            {
                "saved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "seen": seen,
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
    max_checkpoints: int = 3,
    max_memories: int = 8,
) -> dict[str, Any]:
    budget = max(120, int(budget_tokens))
    route = infer_query_route(user_prompt)
    st = _load_delta_state(paths_root, state_key) if delta_enabled else {"seen": {}}
    seen = dict(st.get("seen") or {})

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
    ordered = (delta_new + delta_seen) if delta_enabled else cand
    lines.append(f"Memory recalls (route={route}, budget={budget}):")

    selected: list[dict[str, Any]] = []
    cur = estimate_tokens("\n".join(lines))
    for x in ordered:
        if len(selected) >= max(1, int(max_memories)):
            break
        mid = str(x.get("id", "") or "")
        up = str(x.get("updated_at", "") or "")
        if not mid:
            continue
        one = _mem_line(x, route=route, delta_new=(seen.get(mid, "") != up))
        need = estimate_tokens(one) + 2
        if cur + need > budget:
            continue
        lines.append(one)
        cur += need
        selected.append(x)

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
        _save_delta_state(paths_root, state_key, next_seen)

    return {
        "ok": True,
        "text": text,
        "route": route,
        "budget_tokens": budget,
        "estimated_tokens": est,
        "selected_ids": [str(x.get("id", "")) for x in selected if str(x.get("id", ""))],
        "selected_count": len(selected),
        "candidate_count": len(cand),
        "delta_new_count": len(delta_new),
        "delta_seen_count": len(delta_seen),
    }

