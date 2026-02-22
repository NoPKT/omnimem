from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


from .core import (
    MemoryPaths,
    _sqlite_connect,
    apply_decay,
    compress_hot_sessions,
    compress_session_context,
    consolidate_memories,
    ensure_storage,
    list_core_blocks,
    log_system_event,
    prune_memories,
    resolve_paths,
    sync_git,
    update_memory_content,
    utc_now,
    verify_storage,
)

def _daemon_should_attempt_push(
    *,
    now: float,
    last_push_attempt: float,
    scan_interval: int,
    current_seen: float,
    last_seen: float,
    repo_dirty: bool,
) -> bool:
    push_every = max(3, min(60, int(scan_interval)))
    if now - float(last_push_attempt) < float(push_every):
        return False
    return bool(current_seen > last_seen or repo_dirty)


def classify_sync_error(message: str, detail: Any = "") -> str:
    text = f"{message}\n{detail}".lower()

    auth_hints = [
        "authentication failed",
        "fatal: authentication",
        "bad credentials",
        "permission denied (publickey)",
        "could not read username",
        "access denied",
        "unauthorized",
    ]
    if any(x in text for x in auth_hints):
        return "auth"

    network_hints = [
        "could not resolve host",
        "network is unreachable",
        "connection timed out",
        "connection reset",
        "failed to connect",
        "temporary failure",
        "name or service not known",
        "proxy error",
        "tls",
        "ssl",
    ]
    if any(x in text for x in network_hints):
        return "network"

    conflict_hints = [
        "conflict",
        "merge conflict",
        "could not apply",
        "non-fast-forward",
        "fetch first",
        "needs merge",
        "would be overwritten",
        "rebase",
    ]
    if any(x in text for x in conflict_hints):
        return "conflict"

    return "unknown"


def should_retry_sync_error(error_kind: str) -> bool:
    # Authentication and merge-conflict failures usually require manual action.
    return error_kind in {"network", "unknown"}


def sync_error_hint(error_kind: str) -> str:
    if error_kind == "auth":
        return "Authentication failed. Verify credential refs/token/SSH key and run sync again."
    if error_kind == "network":
        return "Network issue detected. Check connectivity/DNS/proxy, then retry sync."
    if error_kind == "conflict":
        return (
            "Sync conflict detected. Run `omnimem sync --mode github-status`, resolve Git conflicts, "
            "then run `omnimem sync --mode github-pull` and `omnimem sync --mode github-push`."
        )
    if error_kind == "unknown":
        return "Unknown sync failure. Inspect logs and Git status, then retry with conservative settings."
    return ""


def run_sync_with_retry(
    *,
    runner,
    paths: MemoryPaths,
    schema_sql_path: Path,
    mode: str,
    remote_name: str,
    branch: str,
    remote_url: str | None,
    oauth_token_file: str | None = None,
    sync_include_layers: list[str] | None = None,
    sync_include_jsonl: bool = True,
    max_attempts: int = 3,
    initial_backoff: int = 1,
    max_backoff: int = 8,
    sleep_fn=time.sleep,
) -> dict[str, Any]:
    attempts = max(1, int(max_attempts))
    backoff = max(1, int(initial_backoff))
    cap = max(backoff, int(max_backoff))
    last_out: dict[str, Any] = {"ok": False, "mode": mode, "message": "sync retry not executed"}

    for i in range(1, attempts + 1):
        try:
            out = runner(
                paths,
                schema_sql_path,
                mode,
                remote_name=remote_name,
                branch=branch,
                remote_url=remote_url,
                oauth_token_file=oauth_token_file,
                sync_include_layers=sync_include_layers,
                sync_include_jsonl=bool(sync_include_jsonl),
                log_event=False,
            )
        except Exception as exc:  # pragma: no cover
            out = {"ok": False, "mode": mode, "message": f"sync runner error: {exc}"}

        out = dict(out)
        out["attempts"] = i
        if out.get("ok"):
            out["error_kind"] = "none"
            out["retryable"] = False
            return out

        error_kind = classify_sync_error(str(out.get("message", "")), out.get("detail", ""))
        out["error_kind"] = error_kind
        out["retryable"] = should_retry_sync_error(error_kind)
        last_out = out
        if not out.get("retryable", False):
            break
        if i < attempts:
            sleep_fn(backoff)
            backoff = min(cap, backoff * 2)

    return last_out


def run_sync_daemon(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    remote_name: str,
    branch: str,
    remote_url: str | None,
    oauth_token_file: str | None = None,
    sync_include_layers: list[str] | None = None,
    sync_include_jsonl: bool = True,
    scan_interval: int = 8,
    pull_interval: int = 30,
    weave_enabled: bool = True,
    weave_interval: int = 300,
    weave_limit: int = 220,
    weave_min_weight: float = 0.18,
    weave_max_per_src: int = 6,
    weave_max_wait_s: float = 12.0,
    weave_include_archive: bool = False,
    maintenance_enabled: bool = True,
    maintenance_interval: int = 300,
    maintenance_decay_days: int = 14,
    maintenance_decay_limit: int = 120,
    maintenance_prune_enabled: bool = False,
    maintenance_prune_days: int = 45,
    maintenance_prune_limit: int = 300,
    maintenance_prune_layers: list[str] | None = None,
    maintenance_prune_keep_kinds: list[str] | None = None,
    maintenance_consolidate_limit: int = 80,
    maintenance_compress_sessions: int = 2,
    maintenance_compress_min_items: int = 8,
    maintenance_distill_enabled: bool = True,
    maintenance_distill_sessions: int = 1,
    maintenance_distill_min_items: int = 12,
    maintenance_temporal_tree_enabled: bool = True,
    maintenance_temporal_tree_days: int = 30,
    maintenance_rehearsal_enabled: bool = True,
    maintenance_rehearsal_days: int = 45,
    maintenance_rehearsal_limit: int = 16,
    maintenance_reflection_enabled: bool = True,
    maintenance_reflection_days: int = 14,
    maintenance_reflection_limit: int = 4,
    maintenance_reflection_min_repeats: int = 2,
    maintenance_reflection_max_avg_retrieved: float = 2.0,
    maintenance_adaptive_q_promote_imp: float = 0.68,
    maintenance_adaptive_q_promote_conf: float = 0.60,
    maintenance_adaptive_q_promote_stab: float = 0.62,
    maintenance_adaptive_q_promote_vol: float = 0.42,
    maintenance_adaptive_q_demote_vol: float = 0.78,
    maintenance_adaptive_q_demote_stab: float = 0.28,
    maintenance_adaptive_q_demote_reuse: float = 0.30,
    retry_max_attempts: int = 3,
    retry_initial_backoff: int = 1,
    retry_max_backoff: int = 8,
    once: bool = False,
) -> dict[str, Any]:
    ensure_storage(paths, schema_sql_path)
    ensure_system_memory(paths, schema_sql_path)
    last_seen = latest_content_mtime(paths)
    last_pull = 0.0
    last_push_attempt = 0.0
    cycles = 0
    pull_failures = 0
    push_failures = 0
    reindex_failures = 0
    last_pull_result: dict[str, Any] = {}
    last_push_result: dict[str, Any] = {}
    last_reindex_result: dict[str, Any] = {}
    weave_runs = 0
    weave_failures = 0
    last_weave = 0.0
    last_weave_seen = last_seen
    last_weave_result: dict[str, Any] = {}
    maintenance_runs = 0
    maintenance_failures = 0
    last_maintenance = 0.0
    last_maintenance_result: dict[str, Any] = {}
    last_error_kind = "none"

    while True:
        cycles += 1
        now = time.time()
        want_weave = False

        if now - last_pull >= pull_interval:
            last_pull_result = run_sync_with_retry(
                runner=sync_git,
                paths=paths,
                schema_sql_path=schema_sql_path,
                mode="github-pull",
                remote_name=remote_name,
                branch=branch,
                remote_url=remote_url,
                oauth_token_file=oauth_token_file,
                sync_include_layers=sync_include_layers,
                sync_include_jsonl=bool(sync_include_jsonl),
                max_attempts=retry_max_attempts,
                initial_backoff=retry_initial_backoff,
                max_backoff=retry_max_backoff,
            )
            if last_pull_result.get("ok"):
                last_reindex_result = reindex_from_jsonl(paths, schema_sql_path, reset=True)
                if not last_reindex_result.get("ok"):
                    reindex_failures += 1
                    last_error_kind = "unknown"
                else:
                    want_weave = True
            else:
                pull_failures += 1
                last_error_kind = str(last_pull_result.get("error_kind", "unknown"))
            last_pull = now
            last_seen = latest_content_mtime(paths)

        current_seen = latest_content_mtime(paths)
        repo_dirty = _repo_has_pending_sync_changes(paths)
        if _daemon_should_attempt_push(
            now=now,
            last_push_attempt=last_push_attempt,
            scan_interval=scan_interval,
            current_seen=current_seen,
            last_seen=last_seen,
            repo_dirty=repo_dirty,
        ):
            last_push_result = run_sync_with_retry(
                runner=sync_git,
                paths=paths,
                schema_sql_path=schema_sql_path,
                mode="github-push",
                remote_name=remote_name,
                branch=branch,
                remote_url=remote_url,
                oauth_token_file=oauth_token_file,
                sync_include_layers=sync_include_layers,
                sync_include_jsonl=bool(sync_include_jsonl),
                max_attempts=retry_max_attempts,
                initial_backoff=retry_initial_backoff,
                max_backoff=retry_max_backoff,
            )
            if not last_push_result.get("ok"):
                push_failures += 1
                last_error_kind = str(last_push_result.get("error_kind", "unknown"))
            last_seen = latest_content_mtime(paths)
            last_push_attempt = now
            want_weave = True

        if weave_enabled:
            weave_due = (now - last_weave) >= max(30, int(weave_interval))
            changed_since_weave = current_seen > last_weave_seen
            if (want_weave and weave_due) or (weave_due and changed_since_weave):
                try:
                    last_weave_result = weave_links(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        project_id="",
                        limit=int(weave_limit),
                        min_weight=float(weave_min_weight),
                        max_per_src=int(weave_max_per_src),
                        include_archive=bool(weave_include_archive),
                        portable=False,
                        max_wait_s=float(weave_max_wait_s),
                        tool="daemon",
                        session_id="system",
                    )
                    if last_weave_result.get("ok"):
                        weave_runs += 1
                        last_weave = time.time()
                        last_weave_seen = latest_content_mtime(paths)
                    else:
                        weave_failures += 1
                except Exception as exc:  # pragma: no cover
                    weave_failures += 1
                    last_weave_result = {"ok": False, "error": str(exc)}

        if maintenance_enabled and ((now - last_maintenance) >= max(60, int(maintenance_interval))):
            try:
                decay_out = apply_decay(
                    paths=paths,
                    schema_sql_path=schema_sql_path,
                    days=int(maintenance_decay_days),
                    limit=int(maintenance_decay_limit),
                    project_id="",
                    layers=["instant", "short", "long"],
                    dry_run=False,
                    tool="daemon",
                    session_id="system",
                )
                prune_out = {"ok": True, "enabled": False, "count": 0, "deleted": 0}
                if bool(maintenance_prune_enabled):
                    prune_out = prune_memories(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        days=int(maintenance_prune_days),
                        limit=int(maintenance_prune_limit),
                        project_id="",
                        session_id="",
                        layers=list(maintenance_prune_layers or ["instant", "short"]),
                        keep_kinds=list(maintenance_prune_keep_kinds or ["decision", "checkpoint"]),
                        dry_run=False,
                        tool="daemon",
                        actor_session_id="system",
                    )
                cons_out = consolidate_memories(
                    paths=paths,
                    schema_sql_path=schema_sql_path,
                    project_id="",
                    session_id="",
                    limit=int(maintenance_consolidate_limit),
                    dry_run=False,
                    adaptive=True,
                    adaptive_days=14,
                    adaptive_q_promote_imp=float(maintenance_adaptive_q_promote_imp),
                    adaptive_q_promote_conf=float(maintenance_adaptive_q_promote_conf),
                    adaptive_q_promote_stab=float(maintenance_adaptive_q_promote_stab),
                    adaptive_q_promote_vol=float(maintenance_adaptive_q_promote_vol),
                    adaptive_q_demote_vol=float(maintenance_adaptive_q_demote_vol),
                    adaptive_q_demote_stab=float(maintenance_adaptive_q_demote_stab),
                    adaptive_q_demote_reuse=float(maintenance_adaptive_q_demote_reuse),
                    tool="daemon",
                    actor_session_id="system",
                )
                comp_out = compress_hot_sessions(
                    paths=paths,
                    schema_sql_path=schema_sql_path,
                    project_id="",
                    max_sessions=int(maintenance_compress_sessions),
                    per_session_limit=120,
                    min_items=int(maintenance_compress_min_items),
                    dry_run=False,
                    tool="daemon",
                    actor_session_id="system",
                )
                distill_items: list[dict[str, Any]] = []
                if bool(maintenance_distill_enabled):
                    with _sqlite_connect(paths.sqlite_path, timeout=6.0) as conn_d:
                        conn_d.row_factory = sqlite3.Row
                        srows = conn_d.execute(
                            """
                            SELECT COALESCE(json_extract(source_json, '$.session_id'), '') AS sid, COUNT(*) AS c
                            FROM memories
                            WHERE COALESCE(json_extract(source_json, '$.session_id'), '') != ''
                              AND kind NOT IN ('retrieve')
                            GROUP BY sid
                            ORDER BY c DESC
                            LIMIT ?
                            """,
                            (max(1, int(maintenance_distill_sessions)) * 3,),
                        ).fetchall()
                    ds = [
                        str(r["sid"])
                        for r in srows
                        if str(r["sid"]).strip() and str(r["sid"]) not in {"system", "webui-session"}
                    ][: max(1, int(maintenance_distill_sessions))]
                    for sid in ds:
                        try:
                            d_out = distill_session_memory(
                                paths=paths,
                                schema_sql_path=schema_sql_path,
                                project_id="",
                                session_id=sid,
                                limit=140,
                                min_items=int(maintenance_distill_min_items),
                                dry_run=False,
                                semantic_layer="long",
                                procedural_layer="short",
                                tool="daemon",
                                actor_session_id="system",
                            )
                            distill_items.append(d_out)
                        except Exception as exc:  # pragma: no cover
                            distill_items.append({"ok": False, "session_id": sid, "error": str(exc)})
                tree_out = {"ok": True, "made": 0, "temporal_links": 0, "distill_links": 0}
                if bool(maintenance_temporal_tree_enabled):
                    tree_out = build_temporal_memory_tree(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        project_id="",
                        days=int(maintenance_temporal_tree_days),
                        max_sessions=max(6, int(maintenance_compress_sessions) * 4),
                        per_session_limit=120,
                        dry_run=False,
                        tool="daemon",
                        actor_session_id="system",
                    )
                rehearsal_out = {"ok": True, "selected_count": 0}
                if bool(maintenance_rehearsal_enabled):
                    rehearsal_out = rehearse_memory_traces(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        project_id="",
                        days=int(maintenance_rehearsal_days),
                        limit=int(maintenance_rehearsal_limit),
                        dry_run=False,
                        tool="daemon",
                        actor_session_id="system",
                    )
                reflection_out = {"ok": True, "created_count": 0}
                if bool(maintenance_reflection_enabled):
                    reflection_out = trigger_reflective_summaries(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        project_id="",
                        days=int(maintenance_reflection_days),
                        limit=int(maintenance_reflection_limit),
                        min_repeats=int(maintenance_reflection_min_repeats),
                        max_avg_retrieved=float(maintenance_reflection_max_avg_retrieved),
                        dry_run=False,
                        tool="daemon",
                        actor_session_id="system",
                    )
                last_maintenance_result = {
                    "ok": bool(decay_out.get("ok") and prune_out.get("ok") and cons_out.get("ok") and comp_out.get("ok")),
                    "decay": decay_out,
                    "prune": {
                        "enabled": bool(maintenance_prune_enabled),
                        "days": int(maintenance_prune_days),
                        "limit": int(maintenance_prune_limit),
                        "layers": list(maintenance_prune_layers or ["instant", "short"]),
                        "keep_kinds": list(maintenance_prune_keep_kinds or ["decision", "checkpoint"]),
                        "candidates": int(prune_out.get("count", 0) or 0),
                        "deleted": int(prune_out.get("deleted", 0) or 0),
                        "ok": bool(prune_out.get("ok", True)),
                    },
                    "consolidate": {
                        "promoted": len(cons_out.get("promoted") or []),
                        "demoted": len(cons_out.get("demoted") or []),
                        "errors": len(cons_out.get("errors") or []),
                    },
                    "compress": {
                        "sessions": len(comp_out.get("sessions") or []),
                        "compressed": len([x for x in (comp_out.get("items") or []) if x.get("compressed")]),
                    },
                    "distill": {
                        "enabled": bool(maintenance_distill_enabled),
                        "sessions": len(distill_items),
                        "distilled": len([x for x in distill_items if x.get("distilled")]),
                        "errors": len([x for x in distill_items if not x.get("ok")]),
                    },
                    "temporal_tree": {
                        "enabled": bool(maintenance_temporal_tree_enabled),
                        "days": int(maintenance_temporal_tree_days),
                        "made": int(tree_out.get("made", 0) or 0),
                        "temporal_links": int(tree_out.get("temporal_links", 0) or 0),
                        "distill_links": int(tree_out.get("distill_links", 0) or 0),
                        "ok": bool(tree_out.get("ok", True)),
                    },
                    "rehearsal": {
                        "enabled": bool(maintenance_rehearsal_enabled),
                        "days": int(maintenance_rehearsal_days),
                        "limit": int(maintenance_rehearsal_limit),
                        "selected": int(rehearsal_out.get("selected_count", 0) or len(rehearsal_out.get("selected") or [])),
                        "ok": bool(rehearsal_out.get("ok", True)),
                    },
                    "reflection": {
                        "enabled": bool(maintenance_reflection_enabled),
                        "days": int(maintenance_reflection_days),
                        "limit": int(maintenance_reflection_limit),
                        "min_repeats": int(maintenance_reflection_min_repeats),
                        "max_avg_retrieved": float(maintenance_reflection_max_avg_retrieved),
                        "created": int(reflection_out.get("created_count", 0) or len(reflection_out.get("created") or [])),
                        "ok": bool(reflection_out.get("ok", True)),
                    },
                }
                maintenance_runs += 1
                last_maintenance = time.time()
            except Exception as exc:  # pragma: no cover
                maintenance_failures += 1
                last_maintenance_result = {"ok": False, "error": str(exc)}

        if once:
            break
        time.sleep(max(1, scan_interval))

    ok = pull_failures == 0 and push_failures == 0 and reindex_failures == 0
    result = {
        "ok": ok,
        "cycles": cycles,
        "mode": "once" if once else "daemon",
        "pull_failures": pull_failures,
        "push_failures": push_failures,
        "reindex_failures": reindex_failures,
        "last_pull": last_pull_result,
        "last_push": last_push_result,
        "last_reindex": last_reindex_result,
        "weave": {
            "enabled": bool(weave_enabled),
            "interval": int(weave_interval),
            "runs": weave_runs,
            "failures": weave_failures,
            "last_weave_at": last_weave,
            "last_result": last_weave_result,
        },
        "maintenance": {
            "enabled": bool(maintenance_enabled),
            "interval": int(maintenance_interval),
            "runs": maintenance_runs,
            "failures": maintenance_failures,
            "last_run_at": last_maintenance,
            "last_result": last_maintenance_result,
        },
        "last_error_kind": last_error_kind,
        "remediation_hint": sync_error_hint(last_error_kind),
        "retry": {
            "max_attempts": max(1, int(retry_max_attempts)),
            "initial_backoff": max(1, int(retry_initial_backoff)),
            "max_backoff": max(1, int(retry_max_backoff)),
        },
        "push_strategy": {
            "mode": "mtime_or_dirty",
            "push_check_interval": max(3, min(60, int(scan_interval))),
        },
    }
    log_system_event(paths, schema_sql_path, "memory.sync", {"daemon": result}, portable=False)
    return result
