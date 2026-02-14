from __future__ import annotations

import json
import math
import os
import random
import re
import shlex
import subprocess
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core import (
    build_brief,
    bump_reuse_counts,
    find_memories,
    retrieve_thread,
    load_config,
    resolve_paths,
    write_memory,
)
from .memory_context import build_budgeted_memory_context


WORD_RE = re.compile(r"[A-Za-z0-9_]{2,}")
TRANSIENT_TOOL_ERR_RE = re.compile(
    r"(429|rate\s*limit|too\s*many\s*requests|overloaded|temporar(?:y|ily)|timeout|try\s*again|service\s*unavailable|\b5\d\d\b)",
    flags=re.IGNORECASE,
)
RETRY_AFTER_RE = re.compile(r"(?:retry[-_ ]after|retry_after)\s*[:=]?\s*(\d+(?:\.\d+)?)", flags=re.IGNORECASE)


@dataclass
class AgentState:
    session_id: str
    project_id: str
    tool: str
    topic_vector: dict[str, float]
    turns: int
    last_checkpoint_turn: int


@dataclass(frozen=True)
class ToolRunResult:
    process: subprocess.CompletedProcess[str]
    attempts: int
    retried: int
    transient_failures: int


def _state_path(paths_root: Path, tool: str, project_id: str) -> Path:
    runtime = paths_root / "runtime" / "agent"
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime / f"{tool}-{project_id}.json"


def _tokenize(text: str) -> Counter[str]:
    return Counter(w.lower() for w in WORD_RE.findall(text))


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a).intersection(b)
    dot = sum(a[k] * b[k] for k in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _merge_topic(old: dict[str, float], new: Counter[str], alpha: float = 0.25) -> dict[str, float]:
    # Exponential moving average to keep session topic stable but adaptive.
    out = dict(old)
    for k in list(out.keys()):
        out[k] = out[k] * (1 - alpha)
        if out[k] < 0.001:
            out.pop(k, None)
    for k, v in new.items():
        out[k] = out.get(k, 0.0) + alpha * float(v)
    return out


def _load_state(paths_root: Path, tool: str, project_id: str) -> AgentState:
    fp = _state_path(paths_root, tool, project_id)
    if fp.exists():
        obj = json.loads(fp.read_text(encoding="utf-8"))
        return AgentState(
            session_id=obj.get("session_id", uuid.uuid4().hex),
            project_id=project_id,
            tool=tool,
            topic_vector=obj.get("topic_vector", {}),
            turns=int(obj.get("turns", 0)),
            last_checkpoint_turn=int(obj.get("last_checkpoint_turn", 0)),
        )
    return AgentState(
        session_id=uuid.uuid4().hex,
        project_id=project_id,
        tool=tool,
        topic_vector={},
        turns=0,
        last_checkpoint_turn=0,
    )


def _save_state(paths_root: Path, st: AgentState) -> None:
    fp = _state_path(paths_root, st.tool, st.project_id)
    fp.write_text(
        json.dumps(
            {
                "session_id": st.session_id,
                "project_id": st.project_id,
                "tool": st.tool,
                "topic_vector": st.topic_vector,
                "turns": st.turns,
                "last_checkpoint_turn": st.last_checkpoint_turn,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _tool_command(tool: str, prompt: str) -> list[str]:
    env_key = f"OMNIMEM_AGENT_{tool.upper()}_CMD"
    override = os.getenv(env_key, "").strip()
    if override:
        return [*shlex.split(override), prompt]
    if tool == "codex":
        return ["codex", "exec", prompt]
    if tool == "claude":
        return ["claude", "-p", prompt]
    raise ValueError(f"unsupported tool: {tool}")


def _is_transient_tool_error(msg: str) -> bool:
    return bool(TRANSIENT_TOOL_ERR_RE.search(str(msg or "")))


def _extract_retry_after_seconds(msg: str) -> float | None:
    m = RETRY_AFTER_RE.search(str(msg or ""))
    if not m:
        return None
    try:
        v = float(m.group(1))
    except Exception:
        return None
    if not math.isfinite(v):
        return None
    return max(0.0, min(120.0, v))


def _run_tool_with_retry(
    *,
    cmd: list[str],
    cwd: str | None,
    retry_max_attempts: int = 3,
    retry_initial_backoff_s: float = 1.0,
    retry_max_backoff_s: float = 8.0,
    retry_jitter_ratio: float = 0.15,
) -> ToolRunResult:
    attempts = max(1, int(retry_max_attempts))
    backoff = max(0.1, float(retry_initial_backoff_s))
    backoff_cap = max(backoff, float(retry_max_backoff_s))
    jitter = max(0.0, min(0.5, float(retry_jitter_ratio)))
    last: subprocess.CompletedProcess[str] | None = None
    transient_failures = 0
    for idx in range(attempts):
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        last = proc
        if int(proc.returncode) == 0:
            used = idx + 1
            return ToolRunResult(
                process=proc,
                attempts=used,
                retried=max(0, used - 1),
                transient_failures=transient_failures,
            )
        msg = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
        transient = _is_transient_tool_error(msg)
        if (idx + 1) >= attempts or not transient:
            used = idx + 1
            return ToolRunResult(
                process=proc,
                attempts=used,
                retried=max(0, used - 1),
                transient_failures=transient_failures,
            )
        transient_failures += 1
        sleep_for = min(backoff_cap, backoff)
        retry_after_s = _extract_retry_after_seconds(msg)
        if retry_after_s is not None:
            sleep_for = min(backoff_cap, max(sleep_for, retry_after_s))
        if jitter > 0:
            sleep_for = min(backoff_cap, sleep_for * (1.0 + random.uniform(0.0, jitter)))
        time.sleep(sleep_for)
        backoff = min(backoff_cap, backoff * 2.0)
    fallback = last if last is not None else subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="tool failed")
    return ToolRunResult(
        process=fallback,
        attempts=max(1, attempts),
        retried=max(0, attempts - 1),
        transient_failures=transient_failures,
    )


def _build_injected_prompt(*, project_id: str, user_prompt: str, brief: dict[str, Any], mems: list[dict[str, Any]]) -> str:
    blocks = []
    blocks.append(f"Project ID: {project_id}")
    if brief.get("checkpoints"):
        ck = brief["checkpoints"][:3]
        blocks.append("Recent checkpoints:")
        for x in ck:
            blocks.append(f"- {x.get('updated_at','')}: {x.get('summary','')}")
    if mems:
        blocks.append("Relevant memory snippets:")
        for x in mems[:6]:
            blocks.append(f"- [{x.get('layer','')}/{x.get('kind','')}] {x.get('summary','')}")
    blocks.append("User request:")
    blocks.append(user_prompt)
    return "\n".join(blocks)


def _context_observability(ctx: dict[str, Any]) -> dict[str, Any]:
    budget = max(1, int(ctx.get("budget_tokens", 0) or 0))
    est = max(0, int(ctx.get("estimated_tokens", 0) or 0))
    util = max(0.0, min(1.0, float(est) / float(budget)))
    if util >= 0.92:
        pressure = "high"
        hint = "context near budget cap; consider lower retrieve_limit or quota_mode=low/critical"
    elif util <= 0.45:
        pressure = "low"
        hint = "context has spare budget; consider deep_research profile for broader retrieval"
    else:
        pressure = "balanced"
        hint = "context budget utilization is balanced"
    return {
        "context_budget_tokens": budget,
        "context_estimated_tokens": est,
        "context_utilization": round(util, 4),
        "context_pressure": pressure,
        "context_hint": hint,
        "context_selected_count": int(ctx.get("selected_count", 0) or 0),
        "context_selected_core_count": int(ctx.get("selected_core_count", 0) or 0),
        "context_selected_expand_count": int(ctx.get("selected_expand_count", 0) or 0),
        "context_delta_new_count": int(ctx.get("delta_new_count", 0) or 0),
        "context_delta_seen_count": int(ctx.get("delta_seen_count", 0) or 0),
        "context_carry_queued_count": int(ctx.get("carry_queued_count", 0) or 0),
        "context_route": str(ctx.get("route", "") or ""),
    }


def _choose_layer(summary: str, response: str, drift: float) -> tuple[str, float, float, float]:
    s = (summary + "\n" + response).lower()
    important = 0.55
    confidence = 0.6
    stability = 0.55
    layer = "short"
    if any(k in s for k in ["decision", "final", "must", "rule", "constraint"]):
        important = 0.8
        confidence = 0.75
        stability = 0.7
        layer = "long"
    if drift > 0.62:
        layer = "short"
        stability = min(stability, 0.5)
    return layer, important, confidence, stability


def _schema_sql_path() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "db" / "schema.sql",
        here.parent.parent.parent / "db" / "schema.sql",
        Path.cwd() / "db" / "schema.sql",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("schema.sql not found in expected locations")


def run_turn(
    *,
    tool: str,
    project_id: str,
    user_prompt: str,
    drift_threshold: float = 0.62,
    cwd: str | None = None,
    limit: int = 8,
    context_budget_tokens: int = 420,
    delta_enabled: bool = True,
    retry_max_attempts: int = 3,
    retry_initial_backoff_s: float = 1.0,
    retry_max_backoff_s: float = 8.0,
) -> dict[str, Any]:
    cfg = load_config(None)
    paths = resolve_paths(cfg)
    schema = _schema_sql_path()

    st = _load_state(paths.root, tool, project_id)
    st.turns += 1

    prompt_vec = _tokenize(user_prompt)
    sim = _cosine(st.topic_vector, {k: float(v) for k, v in prompt_vec.items()}) if st.topic_vector else 1.0
    drift = 1.0 - sim

    brief = build_brief(paths, schema, project_id, limit=6)
    # Progressive retrieval: seed shallow memories, then pull deeper ones via graph links when available.
    # Falls back to plain FTS/LIKE if the graph isn't built yet.
    rel_out = retrieve_thread(
        paths=paths,
        schema_sql_path=schema,
        query=user_prompt,
        project_id=project_id,
        session_id="",
        seed_limit=min(12, max(4, int(limit))),
        depth=2,
        per_hop=6,
        min_weight=0.18,
    )
    rel = list(rel_out.get("items") or [])
    if not rel:
        rel = find_memories(paths, schema, query=user_prompt, layer=None, limit=limit, project_id=project_id)
    bump_reuse_counts(
        paths=paths,
        schema_sql_path=schema,
        ids=[m.get("id", "") for m in rel if m.get("id")],
        delta=1,
        tool="omnimem-agent",
        session_id=st.session_id,
        project_id=project_id,
    )
    write_memory(
        paths=paths,
        schema_sql_path=schema,
        layer="instant",
        kind="retrieve",
        summary=f"Retrieved {len(rel)} memories for context",
        body=(
            "Automatic retrieval trace created by omnimem agent.\n\n"
            f"- project_id: {project_id}\n"
            f"- session_id: {st.session_id}\n"
            f"- query: {user_prompt}\n"
            f"- retrieved_count: {len(rel)}\n"
            + "\n".join([f"- memory_id: {m.get('id','')}" for m in rel[:20]])
        ),
        tags=[f"project:{project_id}", "auto:retrieve", f"tool:{tool}"],
        refs=[],
        cred_refs=[],
        tool="omnimem-agent",
        account="default",
        device="local",
        session_id=st.session_id,
        project_id=project_id,
        workspace=cwd or "",
        importance=0.25,
        confidence=0.9,
        stability=0.2,
        reuse_count=0,
        volatility=0.8,
        event_type="memory.retrieve",
    )
    workspace_name = Path(cwd).name if cwd else (Path.cwd().name or "workspace")
    ctx = build_budgeted_memory_context(
        paths_root=paths.root,
        state_key=f"agent-{tool}-{project_id}",
        project_id=project_id,
        workspace_name=workspace_name,
        user_prompt=user_prompt,
        brief=brief,
        candidates=rel,
        budget_tokens=int(context_budget_tokens),
        include_protocol=True,
        include_user_request=True,
        delta_enabled=bool(delta_enabled),
        max_checkpoints=3,
        max_memories=min(10, max(3, int(limit))),
    )
    injected = str(ctx.get("text") or _build_injected_prompt(project_id=project_id, user_prompt=user_prompt, brief=brief, mems=rel))

    cmd = _tool_command(tool, injected)
    tool_run = _run_tool_with_retry(
        cmd=cmd,
        cwd=cwd,
        retry_max_attempts=retry_max_attempts,
        retry_initial_backoff_s=retry_initial_backoff_s,
        retry_max_backoff_s=retry_max_backoff_s,
    )
    proc = tool_run.process
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip() or f"{tool} failed with code {proc.returncode}")
    answer = (proc.stdout or "").strip()

    switched = False
    if drift >= drift_threshold and st.turns - st.last_checkpoint_turn >= 2:
        write_memory(
            paths=paths,
            schema_sql_path=schema,
            layer="short",
            kind="checkpoint",
            summary=f"Auto checkpoint before topic switch (drift={drift:.2f})",
            body=(
                "Automatic checkpoint created by omnimem agent.\n\n"
                f"- project_id: {project_id}\n"
                f"- old_session_id: {st.session_id}\n"
                f"- topic_drift: {drift:.3f}\n"
                f"- trigger_prompt: {user_prompt}\n"
            ),
            tags=[f"project:{project_id}", "auto:checkpoint", f"tool:{tool}"],
            refs=[],
            cred_refs=[],
            tool="omnimem-agent",
            account="default",
            device="local",
            session_id=st.session_id,
            project_id=project_id,
            workspace=cwd or "",
            importance=0.75,
            confidence=0.7,
            stability=0.55,
            reuse_count=0,
            volatility=0.45,
            event_type="memory.checkpoint",
        )
        st.session_id = uuid.uuid4().hex
        st.last_checkpoint_turn = st.turns
        st.topic_vector = {}
        switched = True

    layer, importance, confidence, stability = _choose_layer(user_prompt, answer, drift)
    summary = user_prompt.strip().splitlines()[0][:120] or "conversation turn"
    write_memory(
        paths=paths,
        schema_sql_path=schema,
        layer=layer,
        kind="summary",
        summary=f"Auto turn: {summary}",
        body=(
            "Automatic memory from agent turn.\n\n"
            f"## User\n{user_prompt}\n\n"
            f"## Assistant\n{answer}\n\n"
            f"## Metrics\n- drift={drift:.3f}\n- similarity={sim:.3f}\n"
        ),
        tags=[f"project:{project_id}", "auto:turn", f"tool:{tool}"],
        refs=[],
        cred_refs=[],
        tool="omnimem-agent",
        account="default",
        device="local",
        session_id=st.session_id,
        project_id=project_id,
        workspace=cwd or "",
        importance=importance,
        confidence=confidence,
        stability=stability,
        reuse_count=0,
        volatility=max(0.15, min(0.8, drift)),
        event_type="memory.write",
    )

    st.topic_vector = _merge_topic(st.topic_vector, prompt_vec)
    _save_state(paths.root, st)
    return {
        "ok": True,
        "tool": tool,
        "project_id": project_id,
        "session_id": st.session_id,
        "drift": drift,
        "switched": switched,
        "answer": answer,
        "retrieved_count": len(rel),
        "tool_attempts": int(tool_run.attempts),
        "tool_retried": bool(tool_run.retried > 0),
        "tool_transient_failures": int(tool_run.transient_failures),
        **_context_observability(ctx),
    }


def interactive_chat(
    *,
    tool: str,
    project_id: str,
    drift_threshold: float = 0.62,
    cwd: str | None = None,
    context_budget_tokens: int = 420,
    delta_enabled: bool = True,
    retry_max_attempts: int = 3,
    retry_initial_backoff_s: float = 1.0,
    retry_max_backoff_s: float = 8.0,
) -> int:
    print(f"[omnimem-agent] tool={tool} project={project_id} drift_threshold={drift_threshold}")
    print("[omnimem-agent] type /exit to quit")
    while True:
        try:
            user_prompt = input("you> ").strip()
        except EOFError:
            break
        if not user_prompt:
            continue
        if user_prompt in {"/exit", "exit", "quit"}:
            break
        out = run_turn(
            tool=tool,
            project_id=project_id,
            user_prompt=user_prompt,
            drift_threshold=drift_threshold,
            cwd=cwd,
            context_budget_tokens=context_budget_tokens,
            delta_enabled=delta_enabled,
            retry_max_attempts=retry_max_attempts,
            retry_initial_backoff_s=retry_initial_backoff_s,
            retry_max_backoff_s=retry_max_backoff_s,
        )
        marker = " [session-switched]" if out.get("switched") else ""
        print(f"assistant>{marker}\n{out['answer']}\n")
    return 0
