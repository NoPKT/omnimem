from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
import subprocess
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .agent import interactive_chat, run_turn
from .codex_watch import WatchOptions
from .memory_context import build_budgeted_memory_context
from .adapters import (
    notion_query_database,
    notion_write_page,
    r2_get_presigned,
    r2_put_presigned,
    resolve_cred_ref,
)
from .core import (
    KIND_SET,
    LAYER_SET,
    apply_decay,
    build_user_profile,
    build_raptor_digest,
    build_brief,
    compress_session_context,
    consolidate_memories,
    distill_session_memory,
    enhance_memory_summaries,
    find_memories,
    ingest_source,
    apply_memory_feedback,
    retrieve_thread,
    load_config,
    load_config_with_path,
    parse_list_csv,
    parse_ref,
    resolve_paths,
    run_sync_daemon,
    classify_sync_error,
    sync_error_hint,
    sync_git,
    verify_storage,
    write_memory,
)
from .webui import run_webui


def schema_sql_path() -> Path:
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


def add_common_write_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", help="path to omnimem config json")
    p.add_argument("--layer", choices=sorted(LAYER_SET), default="instant")
    p.add_argument("--kind", choices=sorted(KIND_SET), default="note")
    p.add_argument("--summary", required=True)
    p.add_argument("--body", default="")
    p.add_argument("--body-file")
    p.add_argument("--tags", help="comma-separated")
    p.add_argument("--ref", action="append", default=[], help="type:target[:note]")
    p.add_argument("--cred-ref", action="append", default=[])
    p.add_argument("--tool", default="cli")
    p.add_argument("--account", default="default")
    p.add_argument("--device", default="local")
    p.add_argument("--session-id", default="session-local")
    p.add_argument("--project-id", default="global")
    p.add_argument("--workspace", default="")
    p.add_argument("--importance", type=float, default=0.5)
    p.add_argument("--confidence", type=float, default=0.5)
    p.add_argument("--stability", type=float, default=0.5)
    p.add_argument("--reuse-count", type=int, default=0)
    p.add_argument("--volatility", type=float, default=0.5)


def body_text(args: argparse.Namespace) -> str:
    if args.body_file:
        return Path(args.body_file).read_text(encoding="utf-8")
    return args.body


def print_json(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cfg_path_arg(args: argparse.Namespace) -> Path | None:
    raw = getattr(args, "config", None) or getattr(args, "global_config", None)
    return Path(raw) if raw else None


def cli_error_hint(msg: str) -> str:
    m = (msg or "").lower()
    if "readonly database" in m or "attempt to write a readonly database" in m or "unable to open database file" in m:
        return "Set OMNIMEM_HOME to a writable directory, e.g. `OMNIMEM_HOME=$PWD/.omnimem_local`."
    if "permission denied" in m and ".npm" in m:
        return "Set npm cache to a writable dir, e.g. `NPM_CONFIG_CACHE=$PWD/.npm-cache`."
    if "operation not permitted" in m or "errno 1" in m:
        # Common in restricted sandboxes that disallow binding local ports (WebUI can't listen).
        return (
            "Your environment may forbid binding local ports (WebUI can't start). "
            "Try running without the WebUI sidecar (`--no-webui`) or run `omnimem start` in a less restricted environment."
        )
    return ""


def cmd_write(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    refs = [parse_ref(x) for x in args.ref]
    result = write_memory(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        layer=args.layer,
        kind=args.kind,
        summary=args.summary,
        body=body_text(args),
        tags=parse_list_csv(args.tags),
        refs=refs,
        cred_refs=args.cred_ref,
        tool=args.tool,
        account=args.account,
        device=args.device,
        session_id=args.session_id,
        project_id=args.project_id,
        workspace=args.workspace,
        importance=args.importance,
        confidence=args.confidence,
        stability=args.stability,
        reuse_count=args.reuse_count,
        volatility=args.volatility,
        event_type="memory.write",
    )
    print_json({
        "ok": True,
        "memory_id": result["memory"]["id"],
        "layer": result["memory"]["layer"],
        "kind": result["memory"]["kind"],
        "body_md_path": result["memory"]["body_md_path"],
    })
    return 0


def cmd_checkpoint(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    body = (
        "## Checkpoint\n\n"
        f"- Session: {args.session_id}\n"
        f"- Goal: {args.goal}\n"
        f"- Result: {args.result}\n"
        f"- Next: {args.next_step}\n"
        f"- Risks: {args.risks}\n"
    )
    result = write_memory(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        layer=args.layer,
        kind="checkpoint",
        summary=args.summary,
        body=body,
        tags=parse_list_csv(args.tags),
        refs=[parse_ref(x) for x in args.ref],
        cred_refs=args.cred_ref,
        tool=args.tool,
        account=args.account,
        device=args.device,
        session_id=args.session_id,
        project_id=args.project_id,
        workspace=args.workspace,
        importance=args.importance,
        confidence=args.confidence,
        stability=args.stability,
        reuse_count=args.reuse_count,
        volatility=args.volatility,
        event_type="memory.checkpoint",
    )
    print_json({
        "ok": True,
        "checkpoint_id": result["memory"]["id"],
        "body_md_path": result["memory"]["body_md_path"],
    })
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    source = str(getattr(args, "source", "") or "").strip()
    text_body = str(getattr(args, "text", "") or "")
    if not source and not text_body:
        print_json({"ok": False, "error": "source or --text is required"})
        return 1
    out = ingest_source(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        source=source,
        source_type=str(getattr(args, "type", "auto") or "auto"),
        text_body=text_body,
        summary=str(getattr(args, "summary", "") or ""),
        project_id=str(getattr(args, "project_id", "") or ""),
        session_id=str(getattr(args, "session_id", "session-local") or "session-local"),
        workspace=str(getattr(args, "workspace", "") or ""),
        layer=str(getattr(args, "layer", "short") or "short"),
        kind=str(getattr(args, "kind", "note") or "note"),
        tags=parse_list_csv(getattr(args, "tags", "")),
        tool=str(getattr(args, "tool", "cli") or "cli"),
        account=str(getattr(args, "account", "default") or "default"),
        device=str(getattr(args, "device", "local") or "local"),
        max_chars=int(getattr(args, "max_chars", 12000) or 12000),
        chunk_mode=str(getattr(args, "chunk_mode", "none") or "none"),
        chunk_chars=int(getattr(args, "chunk_chars", 2000) or 2000),
        max_chunks=int(getattr(args, "max_chunks", 8) or 8),
    )
    print_json(out)
    return 0 if out.get("ok") else 1


def cmd_find(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    from .core import find_memories_ex

    out = find_memories_ex(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        query=args.query,
        layer=args.layer,
        limit=args.limit,
        project_id=str(getattr(args, "project_id", "") or "").strip(),
        session_id=str(getattr(args, "session_id", "") or "").strip(),
    )
    items = list(out.get("items") or [])
    resp = {"ok": True, "count": len(items), "items": items}
    if getattr(args, "explain", False):
        resp["explain"] = {
            "strategy": out.get("strategy"),
            "query_used": out.get("query_used"),
            "tried": out.get("tried") or [],
        }
    print_json(resp)
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    result = build_brief(paths, schema_sql_path(), args.project_id, args.limit)
    print_json({"ok": True, **result})
    return 0


def cmd_weave(args: argparse.Namespace) -> int:
    from .core import weave_links

    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    out = weave_links(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        project_id=str(args.project_id or "").strip(),
        limit=int(args.limit),
        min_weight=float(args.min_weight),
        max_per_src=int(args.max_per_src),
        include_archive=not bool(args.no_archive),
        portable=bool(getattr(args, "portable", False)),
        max_wait_s=float(getattr(args, "max_wait_s", 20.0)),
        tool="cli",
        session_id=str(args.session_id or "system"),
    )
    print_json(out)
    return 0 if out.get("ok") else 1


def cmd_retrieve(args: argparse.Namespace) -> int:
    from .core import retrieve_thread

    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    out = retrieve_thread(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        query=str(args.query or "").strip(),
        project_id=str(args.project_id or "").strip(),
        session_id=str(args.session_id or "").strip(),
        seed_limit=int(args.seed_limit),
        depth=int(args.depth),
        per_hop=int(args.per_hop),
        min_weight=float(args.min_weight),
        ranking_mode=str(getattr(args, "ranking_mode", "hybrid") or "hybrid"),
        ppr_alpha=float(getattr(args, "ppr_alpha", 0.85)),
        ppr_iters=int(getattr(args, "ppr_iters", 16)),
        diversify=bool(getattr(args, "diversify", True)),
        mmr_lambda=float(getattr(args, "mmr_lambda", 0.72)),
        max_items=int(getattr(args, "max_items", 12)),
        profile_aware=bool(getattr(args, "profile_aware", False)),
        profile_weight=float(getattr(args, "profile_weight", 0.35)),
        profile_limit=int(getattr(args, "profile_limit", 240)),
    )
    if not getattr(args, "explain", False):
        out.pop("explain", None)
    print_json(out)
    return 0 if out.get("ok") else 1


def cmd_profile(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    out = build_user_profile(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        project_id=str(args.project_id or "").strip(),
        session_id=str(args.session_id or "").strip(),
        limit=int(args.limit),
    )
    print_json(out)
    return 0 if out.get("ok") else 1


def cmd_feedback(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    out = apply_memory_feedback(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        memory_id=str(args.id or "").strip(),
        feedback=str(args.feedback or "").strip().lower(),
        note=str(args.note or ""),
        correction=str(args.correction or ""),
        delta=int(args.delta),
        tool="cli",
        account="default",
        device="local",
        session_id=str(args.session_id or "session-local"),
    )
    print_json(out)
    return 0 if out.get("ok") else 1


def cmd_verify(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    result = verify_storage(paths, schema_sql_path())
    print_json(result)
    return 0 if result.get("ok") else 1


def cmd_sync(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    sync_cfg = cfg.get("sync", {}).get("github", {})
    remote_name = args.remote_name or sync_cfg.get("remote_name", "origin")
    branch = args.branch or sync_cfg.get("branch", "main")
    remote_url = args.remote_url or sync_cfg.get("remote_url")
    out = sync_git(
        paths,
        schema_sql_path(),
        args.mode,
        remote_name=remote_name,
        branch=branch,
        remote_url=remote_url,
        commit_message=args.commit_message,
    )
    print_json(out)
    return 0 if out.get("ok") else 1


def cmd_decay(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    layers = None
    if args.layers:
        layers = [x.strip() for x in str(args.layers).split(",") if x.strip()]
    out = apply_decay(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        days=args.days,
        limit=args.limit,
        project_id=str(args.project_id or "").strip(),
        layers=layers,
        dry_run=not bool(args.apply),
        tool="cli",
        session_id=str(args.session_id or "system"),
    )
    print_json(out)
    return 0 if out.get("ok") else 1


def cmd_consolidate(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    out = consolidate_memories(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        project_id=str(args.project_id or "").strip(),
        session_id=str(args.session_id or "").strip(),
        limit=int(args.limit),
        dry_run=not bool(args.apply),
        p_imp=float(args.p_imp),
        p_conf=float(args.p_conf),
        p_stab=float(args.p_stab),
        p_vol=float(args.p_vol),
        d_vol=float(args.d_vol),
        d_stab=float(args.d_stab),
        d_reuse=int(args.d_reuse),
        tool="cli",
        actor_session_id=str(args.actor_session_id or "system"),
    )
    print_json(out)
    return 0 if out.get("ok") else 1


def cmd_compress(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    out = compress_session_context(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        project_id=str(args.project_id or "").strip(),
        session_id=str(args.session_id or "").strip(),
        limit=int(args.limit),
        min_items=int(args.min_items),
        target_layer=str(args.layer or "short").strip(),
        dry_run=not bool(args.apply),
        tool="cli",
        actor_session_id=str(args.actor_session_id or "system"),
    )
    print_json(out)
    return 0 if out.get("ok") else 1


def cmd_distill(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    out = distill_session_memory(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        project_id=str(args.project_id or "").strip(),
        session_id=str(args.session_id or "").strip(),
        limit=int(args.limit),
        min_items=int(args.min_items),
        dry_run=not bool(args.apply),
        semantic_layer=str(args.semantic_layer or "long").strip(),
        procedural_layer=str(args.procedural_layer or "short").strip(),
        tool="cli",
        actor_session_id=str(args.actor_session_id or "system"),
    )
    print_json(out)
    return 0 if out.get("ok") else 1


def cmd_raptor(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    out = build_raptor_digest(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        project_id=str(args.project_id or "").strip(),
        session_id=str(args.session_id or "").strip(),
        days=int(args.days),
        limit=int(args.limit),
        target_layer=str(args.layer or "long").strip(),
        dry_run=not bool(args.apply),
        tool="cli",
        actor_session_id=str(args.actor_session_id or "system"),
    )
    print_json(out)
    return 0 if out.get("ok") else 1


def cmd_enhance(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    out = enhance_memory_summaries(
        paths=paths,
        schema_sql_path=schema_sql_path(),
        project_id=str(args.project_id or "").strip(),
        session_id=str(args.session_id or "").strip(),
        limit=int(args.limit),
        min_short_len=int(args.min_short_len),
        dry_run=not bool(args.apply),
        tool="cli",
        actor_session_id=str(args.actor_session_id or "system"),
    )
    print_json(out)
    return 0 if out.get("ok") else 1


def cmd_webui(args: argparse.Namespace) -> int:
    cfg, cfg_path = load_config_with_path(cfg_path_arg(args))
    dm = cfg.get("daemon", {})

    def _pick_int(name: str, arg_value: int | None, default: int, mn: int, mx: int) -> int:
        raw = arg_value if arg_value is not None else dm.get(name, default)
        try:
            v = int(raw)
        except Exception:
            v = default
        return max(mn, min(mx, v))

    def _pick_bool(name: str, arg_value: bool | None, default: bool) -> bool:
        if arg_value is not None:
            return bool(arg_value)
        raw = dm.get(name, default)
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in {"1", "true", "yes", "on"}:
            return True
        if s in {"0", "false", "no", "off"}:
            return False
        return bool(default)

    run_webui(
        host=args.host,
        port=args.port,
        cfg=cfg,
        cfg_path=cfg_path,
        schema_sql_path=schema_sql_path(),
        sync_runner=sync_git,
        daemon_runner=run_sync_daemon,
        enable_daemon=not args.no_daemon,
        daemon_scan_interval=_pick_int("scan_interval", getattr(args, "daemon_scan_interval", None), 8, 1, 3600),
        daemon_pull_interval=_pick_int("pull_interval", getattr(args, "daemon_pull_interval", None), 30, 5, 86400),
        daemon_retry_max_attempts=_pick_int("retry_max_attempts", getattr(args, "daemon_retry_max_attempts", None), 3, 1, 20),
        daemon_retry_initial_backoff=_pick_int("retry_initial_backoff", getattr(args, "daemon_retry_initial_backoff", None), 1, 1, 120),
        daemon_retry_max_backoff=_pick_int("retry_max_backoff", getattr(args, "daemon_retry_max_backoff", None), 8, 1, 600),
        daemon_maintenance_enabled=_pick_bool("maintenance_enabled", getattr(args, "daemon_maintenance_enabled", None), True),
        daemon_maintenance_interval=_pick_int("maintenance_interval", getattr(args, "daemon_maintenance_interval", None), 300, 60, 86400),
        daemon_maintenance_decay_days=_pick_int("maintenance_decay_days", getattr(args, "daemon_maintenance_decay_days", None), 14, 1, 365),
        daemon_maintenance_decay_limit=_pick_int("maintenance_decay_limit", getattr(args, "daemon_maintenance_decay_limit", None), 120, 1, 2000),
        daemon_maintenance_consolidate_limit=_pick_int("maintenance_consolidate_limit", getattr(args, "daemon_maintenance_consolidate_limit", None), 80, 1, 1000),
        daemon_maintenance_compress_sessions=_pick_int("maintenance_compress_sessions", getattr(args, "daemon_maintenance_compress_sessions", None), 2, 1, 20),
        daemon_maintenance_compress_min_items=_pick_int("maintenance_compress_min_items", getattr(args, "daemon_maintenance_compress_min_items", None), 8, 2, 200),
        daemon_maintenance_temporal_tree_enabled=_pick_bool("maintenance_temporal_tree_enabled", getattr(args, "daemon_maintenance_temporal_tree_enabled", None), True),
        daemon_maintenance_temporal_tree_days=_pick_int("maintenance_temporal_tree_days", getattr(args, "daemon_maintenance_temporal_tree_days", None), 30, 1, 365),
        daemon_maintenance_rehearsal_enabled=_pick_bool("maintenance_rehearsal_enabled", getattr(args, "daemon_maintenance_rehearsal_enabled", None), True),
        daemon_maintenance_rehearsal_days=_pick_int("maintenance_rehearsal_days", getattr(args, "daemon_maintenance_rehearsal_days", None), 45, 1, 365),
        daemon_maintenance_rehearsal_limit=_pick_int("maintenance_rehearsal_limit", getattr(args, "daemon_maintenance_rehearsal_limit", None), 16, 1, 200),
        daemon_maintenance_reflection_enabled=_pick_bool("maintenance_reflection_enabled", getattr(args, "daemon_maintenance_reflection_enabled", None), True),
        daemon_maintenance_reflection_days=_pick_int("maintenance_reflection_days", getattr(args, "daemon_maintenance_reflection_days", None), 14, 1, 365),
        daemon_maintenance_reflection_limit=_pick_int("maintenance_reflection_limit", getattr(args, "daemon_maintenance_reflection_limit", None), 4, 1, 20),
        daemon_maintenance_reflection_min_repeats=_pick_int("maintenance_reflection_min_repeats", getattr(args, "daemon_maintenance_reflection_min_repeats", None), 2, 1, 12),
        daemon_maintenance_reflection_max_avg_retrieved=max(
            0.0,
            min(
                20.0,
                float(
                    (
                        getattr(args, "daemon_maintenance_reflection_max_avg_retrieved", None)
                        if getattr(args, "daemon_maintenance_reflection_max_avg_retrieved", None) is not None
                        else dm.get("maintenance_reflection_max_avg_retrieved", 2.0)
                    )
                    or 2.0
                ),
            ),
        ),
        auth_token=args.webui_token,
        allow_non_localhost=args.allow_non_localhost,
    )
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    return cmd_webui(args)


def cmd_config_path(args: argparse.Namespace) -> int:
    _, cfg_path = load_config_with_path(cfg_path_arg(args))
    print_json({"ok": True, "config_path": str(cfg_path)})
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    cfg, cfg_path = load_config_with_path(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    target = paths.root

    if not args.yes:
        print_json(
            {
                "ok": False,
                "error": "destructive action requires --yes",
                "target": str(target),
            }
        )
        return 1

    # Safety rail: avoid catastrophic deletion.
    if str(target) in {"/", str(Path.home().resolve())}:
        print_json({"ok": False, "error": f"refuse to uninstall unsafe target: {target}"})
        return 1

    detached = False
    if args.detach_project:
        project = Path(args.detach_project).expanduser().resolve()
        for name in [".omnimem.json", ".omnimem-session.md", ".omnimem-ignore", ".omnimem-hooks.sh"]:
            fp = project / name
            if fp.exists():
                fp.unlink()
        detached = True

    if target.exists():
        try:
            shutil.rmtree(target)
        except Exception:
            # On some systems deleting the currently running install tree can fail.
            # Fallback to detached delayed cleanup.
            subprocess.Popen(
                ["/bin/sh", "-c", f"sleep 1; rm -rf '{str(target)}'"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    if cfg_path.exists() and not str(cfg_path).startswith(str(target)):
        cfg_path.unlink(missing_ok=True)

    print_json(
        {
            "ok": True,
            "uninstalled": str(target),
            "project_detached": detached,
        }
    )
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    install_script = repo_root / "scripts" / "install.sh"
    attach_script = repo_root / "scripts" / "attach_project.sh"

    if not install_script.exists():
        print_json({"ok": False, "error": f"install script not found: {install_script}"})
        return 1

    env = dict(os.environ)
    if args.home:
        env["OMNIMEM_HOME"] = str(Path(args.home).expanduser().resolve())

    install_cmd = ["bash", str(install_script)]
    if args.wizard:
        install_cmd.append("--wizard")
    if args.remote_name:
        install_cmd.extend(["--remote-name", args.remote_name])
    if args.branch:
        install_cmd.extend(["--branch", args.branch])
    if args.remote_url:
        install_cmd.extend(["--remote-url", args.remote_url])
    subprocess.run(install_cmd, check=True, env=env)

    attached = False
    if args.attach_project:
        if not attach_script.exists():
            print_json({"ok": False, "error": f"attach script not found: {attach_script}"})
            return 1
        project_id = args.project_id or Path(args.attach_project).name
        subprocess.run(["bash", str(attach_script), args.attach_project, project_id], check=True)
        attached = True

    print_json(
        {
            "ok": True,
            "installed_home": str(Path(args.home).expanduser().resolve()) if args.home else None,
            "attached_project": attached,
            "next": "~/.omnimem/bin/omnimem start --host 127.0.0.1 --port 8765",
        }
    )
    return 0


def cmd_adapter_cred_resolve(args: argparse.Namespace) -> int:
    value = resolve_cred_ref(args.ref)
    if args.mask:
        shown = value[:2] + "***" + value[-2:] if len(value) >= 6 else "***"
        print_json({"ok": True, "ref": args.ref, "value_preview": shown})
    else:
        print_json({"ok": True, "ref": args.ref, "value": value})
    return 0


def _resolve_token(args: argparse.Namespace) -> str:
    if args.token:
        return args.token
    if args.token_ref:
        return resolve_cred_ref(args.token_ref)
    raise ValueError("token not provided, use --token or --token-ref")


def _resolve_url(url: str | None, url_ref: str | None) -> str:
    if url:
        return url
    if url_ref:
        return resolve_cred_ref(url_ref)
    raise ValueError("url not provided, use --url or --url-ref")


def cmd_adapter_notion_write(args: argparse.Namespace) -> int:
    token = ""
    if not args.dry_run:
        token = _resolve_token(args)
    if args.content_file:
        content = Path(args.content_file).read_text(encoding="utf-8")
    else:
        content = args.content
    out = notion_write_page(
        token=token,
        database_id=args.database_id,
        title=args.title,
        content=content,
        title_property=args.title_property,
        dry_run=args.dry_run,
    )
    print_json(out)
    return 0


def cmd_adapter_notion_query(args: argparse.Namespace) -> int:
    token = ""
    if not args.dry_run:
        token = _resolve_token(args)
    out = notion_query_database(
        token=token,
        database_id=args.database_id,
        page_size=args.page_size,
        dry_run=args.dry_run,
    )
    print_json(out)
    return 0


def cmd_adapter_r2_put(args: argparse.Namespace) -> int:
    out = r2_put_presigned(
        file_path=Path(args.file),
        presigned_url=_resolve_url(args.url, args.url_ref),
        dry_run=args.dry_run,
    )
    print_json(out)
    return 0


def cmd_adapter_r2_get(args: argparse.Namespace) -> int:
    out = r2_get_presigned(
        presigned_url=_resolve_url(args.url, args.url_ref),
        out_path=Path(args.out),
        dry_run=args.dry_run,
    )
    print_json(out)
    return 0


def cmd_agent_run(args: argparse.Namespace) -> int:
    out = run_turn(
        tool=args.tool,
        project_id=args.project_id,
        user_prompt=args.prompt,
        drift_threshold=args.drift_threshold,
        cwd=args.cwd,
        limit=args.retrieve_limit,
        context_budget_tokens=int(getattr(args, "context_budget_tokens", 420)),
        delta_enabled=not bool(getattr(args, "no_delta_context", False)),
    )
    print_json(out)
    return 0


def cmd_agent_chat(args: argparse.Namespace) -> int:
    return interactive_chat(
        tool=args.tool,
        project_id=args.project_id,
        drift_threshold=args.drift_threshold,
        cwd=args.cwd,
        context_budget_tokens=int(getattr(args, "context_budget_tokens", 420)),
        delta_enabled=not bool(getattr(args, "no_delta_context", False)),
    )


def infer_project_id(cwd: str | None, explicit: str | None) -> str:
    if explicit:
        return explicit
    base = Path(cwd or Path.cwd()).resolve()
    cfg = base / ".omnimem.json"
    if cfg.exists():
        try:
            obj = json.loads(cfg.read_text(encoding="utf-8"))
            pid = str(obj.get("project_id", "")).strip()
            if pid:
                return pid
        except Exception:
            pass
    return base.name or "global"


def _ensure_project_files(project_dir: Path, project_id: str) -> None:
    """Create minimal integration files if missing (never overwrites)."""
    root = Path(__file__).resolve().parent.parent
    # Avoid polluting the OmniMem source repo when running from this checkout.
    if project_dir.resolve() == root.resolve():
        return
    tmpl = root / "templates" / "project-minimal"
    if not tmpl.exists():
        return

    def _copy_if_missing(name: str, dest_name: str | None = None) -> None:
        src = tmpl / name
        if not src.exists():
            return
        dst = project_dir / (dest_name or name)
        if dst.exists():
            return
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    _copy_if_missing(".omnimem-session.md")
    _copy_if_missing(".omnimem-ignore")
    _copy_if_missing("AGENTS.md")

    cfg_dst = project_dir / ".omnimem.json"
    if not cfg_dst.exists():
        src = tmpl / ".omnimem.json"
        if src.exists():
            txt = src.read_text(encoding="utf-8").replace("replace-with-project-id", project_id)
            cfg_dst.write_text(txt, encoding="utf-8")


def cmd_tool_shortcut(args: argparse.Namespace) -> int:
    tool = args.cmd
    cwd = args.cwd
    project_id = infer_project_id(cwd, args.project_id)
    tool_args = list(getattr(args, "tool_args", []) or [])

    run_cwd_path = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()

    def _can_write_dir(p: Path) -> bool:
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".omnimem-probe.tmp"
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    chosen_home: str | None = None
    if getattr(args, "home", None):
        chosen_home = str(Path(args.home).expanduser().resolve())
    else:
        mode = getattr(args, "home_mode", "auto")
        global_home = Path.home().expanduser().resolve() / ".omnimem"
        workspace_home = run_cwd_path / ".omnimem-home"
        if mode == "global":
            chosen_home = str(global_home)
        elif mode == "workspace":
            chosen_home = str(workspace_home)
        else:
            # auto: prefer global if writable, else fall back to workspace-local.
            chosen_home = str(global_home if _can_write_dir(global_home) else workspace_home)
    if chosen_home:
        os.environ["OMNIMEM_HOME"] = chosen_home

    # Make the "smart + auto-write" path the default for codex interactive use, so users can
    # just run `omnimem codex` and get stronger memory without extra steps.
    if tool == "codex":
        if not getattr(args, "smart", False) and not getattr(args, "inject", False) and not getattr(args, "agent", False):
            if not getattr(args, "native", False) and not getattr(args, "oneshot", False):
                args.smart = True
        if not getattr(args, "auto_write", False) and not getattr(args, "agent", False):
            if not getattr(args, "native", False) and not getattr(args, "oneshot", False):
                args.auto_write = True

    # Auto-create project integration files if missing (no overwrites).
    try:
        _ensure_project_files(run_cwd_path, project_id)
    except Exception:
        pass

    # Optional one-shot path kept for automation scripts.
    if args.oneshot:
        prompt = " ".join(args.prompt).strip()
        if not prompt:
            print_json({"ok": False, "error": "oneshot requires prompt text"})
            return 1
        out = run_turn(
            tool=tool,
            project_id=project_id,
            user_prompt=prompt,
            drift_threshold=args.drift_threshold,
            cwd=cwd,
            limit=args.retrieve_limit,
        )
        print_json(out)
        return 0

    def _truthy_env(name: str) -> bool:
        return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}

    # Default to on-demand lifecycle for wrapper commands to avoid stale sidecar ports.
    # Users can still opt into persistent WebUI via --webui-persist or OMNIMEM_WEBUI_PERSIST=1.
    webui_on_demand = True
    if bool(getattr(args, "webui_persist", False)) or _truthy_env("OMNIMEM_WEBUI_PERSIST"):
        webui_on_demand = False
    elif bool(getattr(args, "webui_on_demand", False)) or _truthy_env("OMNIMEM_WEBUI_ON_DEMAND"):
        webui_on_demand = True

    if not args.no_webui:
        fallback_home = Path(os.environ.get("OMNIMEM_HOME", "") or "").expanduser().resolve()
        runtime_dir = _resolve_shared_runtime_dir(fallback_home=fallback_home)
        started_by_me = ensure_webui_running(
            cfg_path_arg(args),
            args.webui_host,
            args.webui_port,
            args.no_daemon,
            runtime_dir=runtime_dir,
        )
        try:
            daemon_url = f"http://{args.webui_host}:{int(args.webui_port)}/api/daemon"
            with urllib.request.urlopen(daemon_url, timeout=1.0) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
                ds = json.loads(raw) if raw else {}
                if isinstance(ds, dict):
                    if not bool(ds.get("enabled", True)):
                        sys.stderr.write("[omnimem] WebUI daemon is disabled; GitHub sync will not run automatically.\n")
                    elif str(ds.get("last_error_kind", "none")) not in {"none", ""}:
                        hint = str(ds.get("remediation_hint", "") or "")
                        sys.stderr.write(
                            f"[omnimem] WebUI daemon last_error_kind={ds.get('last_error_kind')}. "
                            + (hint + "\n" if hint else "\n")
                        )
                    sys.stderr.flush()
        except Exception:
            pass
        if webui_on_demand:
            if started_by_me:
                try:
                    _webui_managed_marker(runtime_dir, host=str(args.webui_host), port=int(args.webui_port)).parent.mkdir(
                        parents=True, exist_ok=True
                    )
                    _webui_managed_marker(runtime_dir, host=str(args.webui_host), port=int(args.webui_port)).write_text(
                        json.dumps(
                            {
                                "mode": "on_demand",
                                "host": str(args.webui_host),
                                "port": int(args.webui_port),
                                "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                            },
                            ensure_ascii=False,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                except Exception:
                    pass

            lease_fp = _create_webui_lease(
                runtime_dir,
                parent_pid=os.getpid(),
                host=str(args.webui_host),
                port=int(args.webui_port),
            )
            guard_cmd = [
                sys.executable,
                "-m",
                "omnimem.cli",
                "webui-guard",
                "--runtime-dir",
                str(runtime_dir),
                "--host",
                str(args.webui_host),
                "--port",
                str(int(args.webui_port)),
                "--parent-pid",
                str(os.getpid()),
                "--lease",
                str(lease_fp),
                "--stop-when-idle",
            ]
            # Detached guard; it will stop the WebUI only when the last active lease ends.
            subprocess.Popen(
                guard_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=dict(os.environ),
            )

    prompt = " ".join(args.prompt).strip()
    use_agent = bool(getattr(args, "agent", False))
    if getattr(args, "native", False):
        use_agent = False
    if use_agent:
        # OmniMem agent orchestrator for automatic memory read/write + drift checkpoints.
        if prompt:
            out = run_turn(
                tool=tool,
                project_id=project_id,
                user_prompt=prompt,
                drift_threshold=args.drift_threshold,
                cwd=cwd,
                limit=args.retrieve_limit,
            )
            print(out["answer"])
            return 0
        return interactive_chat(
            tool=tool,
            project_id=project_id,
            drift_threshold=args.drift_threshold,
            cwd=cwd,
        )

    smart = bool(getattr(args, "smart", False))
    inject = bool(getattr(args, "inject", False) or smart)
    if getattr(args, "native", False):
        inject = False

    memory_context = ""
    if inject:
        cfg = load_config(cfg_path_arg(args))
        paths = resolve_paths(cfg)
        schema = schema_sql_path()
        brief = build_brief(paths, schema, project_id, limit=6)
        if prompt:
            rel_out = retrieve_thread(
                paths=paths,
                schema_sql_path=schema,
                query=prompt,
                project_id=project_id,
                session_id="",
                seed_limit=min(12, max(4, int(args.retrieve_limit))),
                depth=2,
                per_hop=6,
                min_weight=0.18,
                ranking_mode="hybrid",
            )
            mems = list(rel_out.get("items") or [])
        else:
            mems = find_memories(paths, schema, query="", layer=None, limit=max(10, int(args.retrieve_limit)), project_id=project_id)
        place = run_cwd_path.name or "workspace"
        ctx = build_budgeted_memory_context(
            paths_root=paths.root,
            state_key=f"shortcut-{tool}-{project_id}",
            project_id=project_id,
            workspace_name=place,
            user_prompt=prompt,
            brief=brief,
            candidates=mems,
            budget_tokens=int(getattr(args, "context_budget_tokens", 420)),
            include_protocol=True,
            include_user_request=(tool == "codex" and bool(prompt)),
            delta_enabled=(not bool(getattr(args, "no_delta_context", False))) and bool(prompt),
            max_checkpoints=3,
            max_memories=min(10, max(3, int(args.retrieve_limit))),
        )
        memory_context = str(ctx.get("text", "") or "")

    # Native mode: launch the underlying tool with as little interference as possible.
    if tool == "codex":
        if inject:
            if not prompt:
                # Start an interactive session with an initial prompt (Codex CLI supports `codex [OPTIONS] [PROMPT]`).
                native_cmd = ["codex", *tool_args, memory_context]
            else:
                native_cmd = ["codex", "exec", *tool_args, memory_context]
        else:
            native_cmd = ["codex", *tool_args] if not prompt else ["codex", "exec", *tool_args, prompt]
    else:
        # claude: best-effort parity with agent.py defaults.
        if inject and memory_context:
            native_cmd = ["claude", *tool_args, "--append-system-prompt", memory_context]
            if prompt:
                native_cmd.extend(["-p", prompt])
        else:
            native_cmd = ["claude", *tool_args] if not prompt else ["claude", *tool_args, "-p", prompt]

    run_env = dict(os.environ)
    if chosen_home:
        run_env["OMNIMEM_HOME"] = chosen_home
    if cfg_path_arg(args):
        run_env["OMNIMEM_CONFIG"] = str(cfg_path_arg(args))
    run_cwd = str(run_cwd_path)

    # Optional background capture: write assistant turns into OmniMem without requiring the model
    # to explicitly call omnimem CLI. This keeps the native Codex UI unchanged.
    auto_write = bool(getattr(args, "auto_write", False)) and tool == "codex"
    inject_or_prompt = bool(prompt or inject)
    if auto_write and not inject_or_prompt:
        # Spawn watcher as a separate process, then exec codex to preserve native UX.
        started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        watch_cmd = [
            sys.executable,
            "-m",
            "omnimem.codex_watch",
            "--project-id",
            project_id,
            "--workspace",
            run_cwd,
            "--parent-pid",
            str(os.getpid()),
            "--started-at",
            started_at,
        ]
        if cfg_path_arg(args):
            watch_cmd.extend(["--config", str(cfg_path_arg(args))])
        # Run watcher in background, discard output.
        subprocess.Popen(
            watch_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=run_env,
        )
        os.chdir(run_cwd)
        os.execvpe(native_cmd[0], native_cmd, run_env)
        raise RuntimeError("unreachable")  # pragma: no cover

    return subprocess.call(native_cmd, cwd=run_cwd, env=run_env)


def webui_alive(host: str, port: int) -> bool:
    # Use the root HTML route for liveness. It is intentionally unauthenticated and stable.
    # Older WebUIs may not implement newer /api/* endpoints, but "/" should always exist.
    url = f"http://{host}:{port}/"
    try:
        # Keep this reasonably short so wrapper startup isn't slow, but not so short that
        # transient load makes the wrapper think a healthy WebUI is down.
        with urllib.request.urlopen(url, timeout=1.2) as resp:
            return 200 <= resp.status < 500
    except urllib.error.HTTPError:
        # HTTP errors still mean the server is alive and responding.
        return True
    except Exception:
        return False


def ensure_webui_running(
    cfg_path: Path | None,
    host: str,
    port: int,
    no_daemon: bool,
    *,
    runtime_dir: Path | None = None,
) -> bool:
    if webui_alive(host, port):
        return False

    cfg = load_config(cfg_path)
    paths = resolve_paths(cfg)
    rt_dir = runtime_dir or _resolve_shared_runtime_dir(fallback_home=paths.root)
    # Avoid repeatedly spawning `omnimem start` when the WebUI is already running but
    # liveness probing is flaky/slow: if a pidfile exists and the pid is alive, do not
    # attempt another bind on the same port.
    pid_fp = _webui_pid_file(rt_dir, host=host, port=port)
    if pid_fp.exists():
        try:
            obj = json.loads(pid_fp.read_text(encoding="utf-8"))
            pid = int(obj.get("pid") or 0)
            pid_port = int(obj.get("port") or 0)
            pid_host = str(obj.get("host") or "")
            if pid > 0 and _pid_alive(pid) and pid_port == int(port) and (not pid_host or pid_host == str(host)):
                return False
        except Exception:
            pass
    log_dir = rt_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_fp = log_dir / "webui.log"
    cmd = [sys.executable, "-m", "omnimem.cli", "start", "--host", host, "--port", str(port)]
    if no_daemon:
        cmd.append("--no-daemon")
    if cfg_path:
        cmd.extend(["--config", str(cfg_path)])

    env = dict(os.environ)
    env["OMNIMEM_RUNTIME_DIR"] = str(rt_dir)
    with log_fp.open("ab") as f:
        subprocess.Popen(
            cmd,
            stdout=f,
            stderr=f,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    # Best-effort: give the background server a brief moment to bind and serve.
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if webui_alive(host, port):
            return True
        time.sleep(0.12)

    # If it didn't come up, surface a minimal hint to the wrapper user; details are in the log file.
    try:
        sys.stderr.write(
            f"[omnimem] WebUI did not become reachable at http://{host}:{port}/. "
            f"Check {str(log_fp)} (or disable auto-start with --no-webui).\n"
        )
        sys.stderr.flush()
    except Exception:
        pass
    return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _endpoint_key(host: str, port: int) -> str:
    raw = f"{str(host).strip().lower()}_{int(port)}"
    return "".join(ch if ch.isalnum() else "_" for ch in raw)


def _resolve_shared_runtime_dir(*, fallback_home: Path | None = None) -> Path:
    candidates: list[Path] = []
    env_dir = os.getenv("OMNIMEM_RUNTIME_DIR", "").strip()
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    xdg = os.getenv("XDG_RUNTIME_DIR", "").strip()
    if xdg:
        candidates.append(Path(xdg).expanduser() / "omnimem")
    uid = getattr(os, "getuid", lambda: None)()
    if uid is not None:
        candidates.append(Path("/tmp") / f"omnimem-{int(uid)}")
    else:
        candidates.append(Path("/tmp") / "omnimem")
    if fallback_home is not None:
        candidates.append(fallback_home / "runtime")

    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".probe"
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return d
        except Exception:
            continue
    raise RuntimeError("unable to create runtime dir for webui coordination")


def _webui_leases_dir(runtime_dir: Path, *, host: str, port: int) -> Path:
    return runtime_dir / "webui_leases" / _endpoint_key(host, port)


def _create_webui_lease(runtime_dir: Path, *, parent_pid: int, host: str, port: int) -> Path:
    d = _webui_leases_dir(runtime_dir, host=host, port=port)
    d.mkdir(parents=True, exist_ok=True)
    lease_fp = d / f"lease-{uuid.uuid4().hex}.json"
    lease_fp.write_text(
        json.dumps(
            {
                "parent_pid": int(parent_pid),
                "host": str(host),
                "port": int(port),
                "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return lease_fp


def _cleanup_stale_leases(runtime_dir: Path, *, host: str, port: int) -> list[Path]:
    d = _webui_leases_dir(runtime_dir, host=host, port=port)
    if not d.exists():
        return []
    keep: list[Path] = []
    for fp in sorted(d.glob("lease-*.json")):
        try:
            obj = json.loads(fp.read_text(encoding="utf-8"))
            pid = int(obj.get("parent_pid") or 0)
            if _pid_alive(pid):
                keep.append(fp)
            else:
                fp.unlink(missing_ok=True)
        except Exception:
            # If a lease file is corrupt, treat it as stale.
            try:
                fp.unlink(missing_ok=True)
            except Exception:
                pass
    return keep


def _webui_pid_file(runtime_dir: Path, *, host: str, port: int) -> Path:
    return runtime_dir / f"webui-{_endpoint_key(host, port)}.pid"


def _webui_managed_marker(runtime_dir: Path, *, host: str, port: int) -> Path:
    return runtime_dir / f"webui-{_endpoint_key(host, port)}.managed.json"


def _read_webui_pid(runtime_dir: Path, *, host: str, port: int) -> int:
    fp = _webui_pid_file(runtime_dir, host=host, port=port)
    if not fp.exists():
        return 0
    try:
        obj = json.loads(fp.read_text(encoding="utf-8"))
        return int(obj.get("pid") or 0)
    except Exception:
        try:
            return int(fp.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            return 0


def _kill_webui(pid: int) -> None:
    if pid <= 0:
        return
    # WebUI is started with start_new_session=True; pid is typically its own process group id.
    try:
        os.killpg(pid, signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            return
    # Give it a moment to flush and exit.
    for _ in range(10):
        if not _pid_alive(pid):
            return
        time.sleep(0.15)
    try:
        os.killpg(pid, signal.SIGKILL)
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


def cmd_webui_guard(args: argparse.Namespace) -> int:
    runtime_dir = Path(args.runtime_dir).expanduser().resolve()
    lease_fp = Path(args.lease).expanduser().resolve()
    parent_pid = int(args.parent_pid)
    host = str(args.host)
    port = int(args.port)

    # Wait until the parent (wrapper which becomes codex/claude) exits.
    while _pid_alive(parent_pid):
        time.sleep(0.8)

    # Release our lease.
    try:
        lease_fp.unlink(missing_ok=True)
    except Exception:
        pass

    if not bool(getattr(args, "stop_when_idle", False)):
        return 0

    # Only auto-stop WebUI if it was started/managed by the wrapper (avoid killing a manually started server).
    if not _webui_managed_marker(runtime_dir, host=host, port=port).exists():
        return 0

    keep = _cleanup_stale_leases(runtime_dir, host=host, port=port)
    if keep:
        return 0

    pid = _read_webui_pid(runtime_dir, host=host, port=port)
    _kill_webui(pid)
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    fallback_home: Path | None = None
    cfgp = cfg_path_arg(args)
    if cfgp:
        try:
            cfg = load_config(cfgp)
            fallback_home = resolve_paths(cfg).root
        except Exception:
            fallback_home = None
    if fallback_home is None:
        raw_home = os.getenv("OMNIMEM_HOME", "").strip()
        if raw_home:
            fallback_home = Path(raw_home).expanduser()

    runtime_dir = _resolve_shared_runtime_dir(fallback_home=fallback_home)
    if bool(getattr(args, "all", False)):
        stopped: list[dict[str, Any]] = []
        for fp in sorted(runtime_dir.glob("webui-*.pid")):
            pid = 0
            host = ""
            port = 0
            try:
                obj = json.loads(fp.read_text(encoding="utf-8"))
                pid = int(obj.get("pid") or 0)
                host = str(obj.get("host") or "")
                port = int(obj.get("port") or 0)
            except Exception:
                pid = 0
            alive_before = _pid_alive(pid) if pid > 0 else False
            _kill_webui(pid)
            alive_after = _pid_alive(pid) if pid > 0 else False
            try:
                fp.unlink(missing_ok=True)
            except Exception:
                pass
            stopped.append(
                {
                    "pid": pid,
                    "host": host,
                    "port": port,
                    "alive_before": alive_before,
                    "alive_after": alive_after,
                    "stopped": bool(alive_before and not alive_after),
                }
            )

        for m in runtime_dir.glob("webui-*.managed.json"):
            try:
                m.unlink(missing_ok=True)
            except Exception:
                pass
        leases_root = runtime_dir / "webui_leases"
        if leases_root.exists():
            for fp in leases_root.rglob("*.json"):
                try:
                    fp.unlink(missing_ok=True)
                except Exception:
                    pass
            for d in sorted(leases_root.rglob("*"), reverse=True):
                if d.is_dir():
                    try:
                        d.rmdir()
                    except Exception:
                        pass
            try:
                leases_root.rmdir()
            except Exception:
                pass
        print_json({"ok": True, "all": True, "runtime_dir": str(runtime_dir), "stopped": stopped})
        return 0

    host = str(getattr(args, "host", "127.0.0.1"))
    port = int(getattr(args, "port", 8765))
    pid = _read_webui_pid(runtime_dir, host=host, port=port)
    alive_before = _pid_alive(pid) if pid > 0 else False
    _kill_webui(pid)
    alive_after = _pid_alive(pid) if pid > 0 else False

    try:
        _webui_pid_file(runtime_dir, host=host, port=port).unlink(missing_ok=True)
    except Exception:
        pass
    try:
        _webui_managed_marker(runtime_dir, host=host, port=port).unlink(missing_ok=True)
    except Exception:
        pass
    lease_dir = _webui_leases_dir(runtime_dir, host=host, port=port)
    if lease_dir.exists():
        for fp in lease_dir.glob("lease-*.json"):
            try:
                fp.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            lease_dir.rmdir()
        except Exception:
            pass

    print_json(
        {
            "ok": True,
            "all": False,
            "runtime_dir": str(runtime_dir),
            "host": host,
            "port": port,
            "pid": pid,
            "alive_before": alive_before,
            "alive_after": alive_after,
            "stopped": bool(alive_before and not alive_after),
        }
    )
    return 0


def _doctor_actions(facts: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    webui = facts.get("webui") if isinstance(facts.get("webui"), dict) else {}
    daemon = facts.get("daemon") if isinstance(facts.get("daemon"), dict) else {}
    sync = facts.get("sync") if isinstance(facts.get("sync"), dict) else {}
    host = str(webui.get("host", "127.0.0.1"))
    port = int(webui.get("port", 8765) or 8765)

    if bool(webui.get("pid_alive", False)) and not bool(webui.get("reachable", False)):
        actions.append(f"omnimem stop --host {host} --port {port}")
        actions.append(f"omnimem start --host {host} --port {port}")
    elif not bool(webui.get("reachable", False)):
        actions.append(f"omnimem start --host {host} --port {port}")

    if bool(daemon) and not bool(daemon.get("enabled", True)):
        actions.append(f"omnimem start --host {host} --port {port}")
    err_kind = str(daemon.get("last_error_kind", "none") or "none")
    if err_kind not in {"none", ""}:
        actions.append("omnimem sync --mode github-status")
        if err_kind in {"network", "unknown"}:
            actions.append("omnimem sync --mode github-pull")
        if err_kind == "conflict":
            actions.append("omnimem sync --mode github-pull  # then resolve conflicts and push")

    if not bool(sync.get("remote_url_configured", False)):
        actions.append("omnimem sync --mode github-bootstrap --remote-url <git-url>")
    if bool(sync.get("dirty", False)):
        actions.append("omnimem sync --mode github-status")

    dedup: list[str] = []
    seen: set[str] = set()
    for a in actions:
        k = a.strip()
        if not k or k in seen:
            continue
        seen.add(k)
        dedup.append(k)
    return dedup


def _seconds_since_iso(raw: str) -> float | None:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return None


def _doctor_sync_history(paths, *, limit: int = 24) -> dict[str, Any]:
    out: dict[str, Any] = {
        "event_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "failure_rate": 0.0,
        "error_kinds": {},
        "mode_counts": {},
        "last_event_at": "",
        "last_event_age_s": None,
    }
    try:
        with sqlite3.connect(paths.sqlite_path, timeout=1.2) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT event_time, payload_json
                FROM memory_events
                WHERE event_type = 'memory.sync'
                ORDER BY event_time DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
    except Exception as exc:
        out["error"] = str(exc)
        return out

    out["event_count"] = len(rows)
    if rows:
        out["last_event_at"] = str(rows[0]["event_time"] or "")
        out["last_event_age_s"] = _seconds_since_iso(out["last_event_at"])

    error_kinds: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    success_count = 0
    failure_count = 0
    for r in rows:
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(r["payload_json"] or "{}") or {}
        except Exception:
            payload = {}
        daemon_payload = payload.get("daemon") if isinstance(payload, dict) else None
        if isinstance(daemon_payload, dict):
            mode = "daemon"
            ok = bool(daemon_payload.get("ok", False))
            err_kind = str(daemon_payload.get("last_error_kind", "none") or "none")
        else:
            mode = str((payload or {}).get("mode", "unknown") or "unknown")
            ok = bool((payload or {}).get("ok", False))
            if ok:
                err_kind = "none"
            else:
                err_kind = classify_sync_error(str((payload or {}).get("message", "")), (payload or {}).get("detail", ""))

        mode_counts[mode] = int(mode_counts.get(mode, 0)) + 1
        if ok:
            success_count += 1
        else:
            failure_count += 1
            error_kinds[err_kind] = int(error_kinds.get(err_kind, 0)) + 1

    total = max(1, success_count + failure_count)
    out["success_count"] = success_count
    out["failure_count"] = failure_count
    out["failure_rate"] = round(float(failure_count) / float(total), 4)
    out["error_kinds"] = error_kinds
    out["mode_counts"] = mode_counts
    return out


def _doctor_sync_issues(daemon_info: dict[str, Any], sync_recent: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    latency = daemon_info.get("latency") if isinstance(daemon_info.get("latency"), dict) else {}
    run_age_s = latency.get("since_last_run_s")
    pull_interval_s = latency.get("pull_interval_s")
    if bool(daemon_info.get("enabled", False)) and bool(daemon_info.get("running", False)):
        if isinstance(run_age_s, (int, float)) and isinstance(pull_interval_s, (int, float)) and pull_interval_s > 0:
            stale_threshold = max(90.0, float(pull_interval_s) * 2.5)
            if float(run_age_s) > stale_threshold:
                issues.append(
                    f"daemon sync appears stale (last_run_age_s={int(run_age_s)}, expected<={int(stale_threshold)})"
                )

    event_count = int(sync_recent.get("event_count", 0) or 0)
    failure_rate = float(sync_recent.get("failure_rate", 0.0) or 0.0)
    if event_count >= 5 and failure_rate >= 0.6:
        issues.append(
            f"recent sync failure rate is high ({int(round(failure_rate * 100))}% over {event_count} events)"
        )

    ek = sync_recent.get("error_kinds") if isinstance(sync_recent.get("error_kinds"), dict) else {}
    if isinstance(ek, dict) and ek:
        top_kind, top_count = max(ek.items(), key=lambda kv: int(kv[1]))
        if str(top_kind) and str(top_kind) not in {"none", ""} and int(top_count) >= 3:
            issues.append(f"recent dominant sync error_kind={top_kind} ({int(top_count)} events)")
    return issues


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    host = str(getattr(args, "host", "127.0.0.1"))
    port = int(getattr(args, "port", 8765))
    runtime_dir = _resolve_shared_runtime_dir(fallback_home=paths.root)

    verify = verify_storage(paths, schema_sql_path())
    pid = _read_webui_pid(runtime_dir, host=host, port=port)
    pid_alive = _pid_alive(pid) if pid > 0 else False
    reachable = webui_alive(host, port)

    lease_alive = 0
    lease_total = 0
    lease_dir = _webui_leases_dir(runtime_dir, host=host, port=port)
    if lease_dir.exists():
        for fp in lease_dir.glob("lease-*.json"):
            lease_total += 1
            try:
                obj = json.loads(fp.read_text(encoding="utf-8"))
                if _pid_alive(int(obj.get("parent_pid") or 0)):
                    lease_alive += 1
            except Exception:
                continue

    daemon_info: dict[str, Any] = {}
    if reachable:
        try:
            daemon_url = f"http://{host}:{port}/api/daemon"
            with urllib.request.urlopen(daemon_url, timeout=1.2) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            d = json.loads(raw) if raw else {}
            if isinstance(d, dict):
                run_age = _seconds_since_iso(str(d.get("last_run_at", "")))
                success_age = _seconds_since_iso(str(d.get("last_success_at", "")))
                failure_age = _seconds_since_iso(str(d.get("last_failure_at", "")))
                pull_iv = int(d.get("pull_interval", 0) or 0)
                daemon_info = {
                    "enabled": bool(d.get("enabled", False)),
                    "running": bool(d.get("running", False)),
                    "initialized": bool(d.get("initialized", False)),
                    "cycles": int(d.get("cycles", 0) or 0),
                    "success_count": int(d.get("success_count", 0) or 0),
                    "failure_count": int(d.get("failure_count", 0) or 0),
                    "last_run_at": str(d.get("last_run_at", "")),
                    "last_success_at": str(d.get("last_success_at", "")),
                    "last_failure_at": str(d.get("last_failure_at", "")),
                    "last_error_kind": str(d.get("last_error_kind", "none")),
                    "last_error": str(d.get("last_error", "")),
                    "remediation_hint": str(d.get("remediation_hint", "")),
                    "latency": {
                        "scan_interval_s": int(d.get("scan_interval", 0) or 0),
                        "pull_interval_s": pull_iv,
                        "since_last_run_s": int(run_age) if isinstance(run_age, (int, float)) else None,
                        "since_last_success_s": int(success_age) if isinstance(success_age, (int, float)) else None,
                        "since_last_failure_s": int(failure_age) if isinstance(failure_age, (int, float)) else None,
                    },
                }
        except Exception as exc:
            daemon_info = {"error": str(exc), "last_error_kind": "unknown", "enabled": False, "running": False}

    sync_cfg = cfg.get("sync", {}).get("github", {})
    remote_name = str(sync_cfg.get("remote_name", "origin"))
    branch = str(sync_cfg.get("branch", "main"))
    remote_url = str(sync_cfg.get("remote_url", "") or "")
    dirty = False
    try:
        cp = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(paths.root),
            capture_output=True,
            text=True,
            check=False,
        )
        dirty = bool((cp.stdout or "").strip())
    except Exception:
        dirty = False

    sync_recent = _doctor_sync_history(paths, limit=24)

    facts = {
        "webui": {
            "host": host,
            "port": port,
            "reachable": reachable,
            "pid": pid,
            "pid_alive": pid_alive,
            "managed": _webui_managed_marker(runtime_dir, host=host, port=port).exists(),
            "leases_alive": lease_alive,
            "leases_total": lease_total,
            "runtime_dir": str(runtime_dir),
        },
        "daemon": daemon_info,
        "sync": {
            "remote_name": remote_name,
            "branch": branch,
            "remote_url_configured": bool(remote_url.strip()),
            "dirty": dirty,
            "recent": sync_recent,
        },
    }
    actions = _doctor_actions(facts)
    issues: list[str] = []
    if not verify.get("ok", False):
        issues.append("storage verification failed")
    if pid_alive and not reachable:
        issues.append("webui pid alive but endpoint unreachable")
    if daemon_info and str(daemon_info.get("last_error_kind", "none")) not in {"none", ""}:
        ek = str(daemon_info.get("last_error_kind", "unknown"))
        issues.append(f"daemon last_error_kind={ek}: {sync_error_hint(ek)}")
    if not bool(facts["sync"]["remote_url_configured"]):
        issues.append("sync remote_url not configured")
    if bool(dirty):
        issues.append("git worktree has uncommitted changes")
    issues.extend(_doctor_sync_issues(daemon_info, sync_recent))

    out = {
        "ok": len(issues) == 0,
        "facts": facts,
        "verify": verify,
        "issues": issues,
        "actions": actions,
    }
    print_json(out)
    return 0 if out.get("ok") else 1


def _git_changed_files(cwd: Path) -> tuple[bool, list[str], str]:
    try:
        probe = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode != 0 or str(probe.stdout or "").strip().lower() != "true":
            err = str(probe.stderr or probe.stdout or "").strip() or "not a git worktree"
            return False, [], err
    except Exception as exc:
        return False, [], str(exc)

    try:
        cp = subprocess.run(
            ["git", "-C", str(cwd), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return True, [], str(exc)
    if cp.returncode != 0:
        return True, [], str(cp.stderr or cp.stdout or "").strip() or "git status failed"

    files: list[str] = []
    for raw in (cp.stdout or "").splitlines():
        line = str(raw or "").rstrip()
        if len(line) < 4:
            continue
        path_part = line[3:].strip()
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1].strip()
        if path_part:
            files.append(path_part)
    return True, files, ""


def cmd_preflight(args: argparse.Namespace) -> int:
    target = Path(str(getattr(args, "path", ".") or ".")).expanduser().resolve()
    allow_clean = bool(getattr(args, "allow_clean", False))

    in_git, changed_files, git_error = _git_changed_files(target)
    issues: list[str] = []
    if not in_git:
        issues.append("path is not inside a git worktree")
    if in_git and not changed_files and not allow_clean:
        issues.append("no local changes detected; release is blocked")

    out = {
        "ok": len(issues) == 0,
        "path": str(target),
        "checks": {
            "git_worktree": in_git,
            "changed_count": len(changed_files),
            "changed_files": changed_files,
            "allow_clean": allow_clean,
        },
        "issues": issues,
    }
    if git_error:
        out["checks"]["git_error"] = git_error
    print_json(out)
    return 0 if out.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="omnimem")
    p.add_argument("--config", dest="global_config", help="path to omnimem config json")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_write = sub.add_parser("write", help="write a memory")
    add_common_write_args(p_write)
    p_write.set_defaults(func=cmd_write)

    p_ingest = sub.add_parser("ingest", help="ingest url/file/text into memory")
    p_ingest.add_argument("--config", help="path to omnimem config json")
    p_ingest.add_argument("--type", choices=["auto", "file", "url", "text"], default="auto")
    p_ingest.add_argument("source", nargs="?", default="")
    p_ingest.add_argument("--text", default="", help="inline text body (used by --type text)")
    p_ingest.add_argument("--summary", default="", help="optional summary override")
    p_ingest.add_argument("--layer", choices=sorted(LAYER_SET), default="short")
    p_ingest.add_argument("--kind", choices=sorted(KIND_SET), default="note")
    p_ingest.add_argument("--tags", default="", help="comma-separated tags")
    p_ingest.add_argument("--project-id", default="")
    p_ingest.add_argument("--session-id", default="session-local")
    p_ingest.add_argument("--workspace", default="")
    p_ingest.add_argument("--tool", default="cli")
    p_ingest.add_argument("--account", default="default")
    p_ingest.add_argument("--device", default="local")
    p_ingest.add_argument("--max-chars", type=int, default=12000)
    p_ingest.add_argument("--chunk-mode", choices=["none", "heading", "fixed"], default="none")
    p_ingest.add_argument("--chunk-chars", type=int, default=2000)
    p_ingest.add_argument("--max-chunks", type=int, default=8)
    p_ingest.set_defaults(func=cmd_ingest)

    p_find = sub.add_parser("find", help="find memories")
    p_find.add_argument("--config", help="path to omnimem config json")
    p_find.add_argument("query", nargs="?", default="")
    p_find.add_argument("--layer", choices=sorted(LAYER_SET))
    p_find.add_argument("--limit", type=int, default=10)
    p_find.add_argument("--project-id", default="", help="optional project filter (scope.project_id)")
    p_find.add_argument("--session-id", default="", help="optional session filter (source.session_id)")
    p_find.add_argument("--explain", action="store_true", help="include query normalization/fallback strategy details")
    p_find.set_defaults(func=cmd_find)

    p_checkpoint = sub.add_parser("checkpoint", help="create checkpoint memory")
    p_checkpoint.add_argument("--config", help="path to omnimem config json")
    p_checkpoint.add_argument("--summary", required=True)
    p_checkpoint.add_argument("--goal", default="")
    p_checkpoint.add_argument("--result", default="")
    p_checkpoint.add_argument("--next-step", default="")
    p_checkpoint.add_argument("--risks", default="")
    p_checkpoint.add_argument("--layer", choices=sorted(LAYER_SET), default="short")
    p_checkpoint.add_argument("--tags", help="comma-separated")
    p_checkpoint.add_argument("--ref", action="append", default=[])
    p_checkpoint.add_argument("--cred-ref", action="append", default=[])
    p_checkpoint.add_argument("--tool", default="cli")
    p_checkpoint.add_argument("--account", default="default")
    p_checkpoint.add_argument("--device", default="local")
    p_checkpoint.add_argument("--session-id", default="session-local")
    p_checkpoint.add_argument("--project-id", default="global")
    p_checkpoint.add_argument("--workspace", default="")
    p_checkpoint.add_argument("--importance", type=float, default=0.7)
    p_checkpoint.add_argument("--confidence", type=float, default=0.7)
    p_checkpoint.add_argument("--stability", type=float, default=0.6)
    p_checkpoint.add_argument("--reuse-count", type=int, default=0)
    p_checkpoint.add_argument("--volatility", type=float, default=0.4)
    p_checkpoint.set_defaults(func=cmd_checkpoint)

    p_brief = sub.add_parser("brief", help="startup summary")
    p_brief.add_argument("--config", help="path to omnimem config json")
    p_brief.add_argument("--project-id", default="")
    p_brief.add_argument("--limit", type=int, default=8)
    p_brief.set_defaults(func=cmd_brief)

    p_weave = sub.add_parser("weave", help="build/refresh memory relationship links (graph)")
    p_weave.add_argument("--config", help="path to omnimem config json")
    p_weave.add_argument("--project-id", default="", help="optional project filter")
    p_weave.add_argument("--session-id", default="system", help="event session_id for instrumentation")
    p_weave.add_argument("--limit", type=int, default=120, help="number of recent memories to consider")
    p_weave.add_argument("--min-weight", type=float, default=0.18, help="minimum similarity to create a link")
    p_weave.add_argument("--max-per-src", type=int, default=6, help="max outgoing links per memory")
    p_weave.add_argument("--no-archive", action="store_true", help="exclude archive layer from graph")
    p_weave.add_argument("--portable", action="store_true", help="also write link events to JSONL (more sync churn)")
    p_weave.add_argument("--max-wait-s", type=float, default=20.0, help="seconds to wait/retry on sqlite busy/locked")
    p_weave.set_defaults(func=cmd_weave)

    p_retrieve = sub.add_parser("retrieve", help="progressive multi-hop retrieval using memory graph")
    p_retrieve.add_argument("--config", help="path to omnimem config json")
    p_retrieve.add_argument("query", nargs="?", default="")
    p_retrieve.add_argument("--project-id", default="", help="optional project filter")
    p_retrieve.add_argument("--session-id", default="", help="optional session filter")
    p_retrieve.add_argument("--seed-limit", type=int, default=8, help="max seed memories from shallow layers")
    p_retrieve.add_argument("--depth", type=int, default=2, help="max hops to expand via links")
    p_retrieve.add_argument("--per-hop", type=int, default=6, help="fan-out per hop")
    p_retrieve.add_argument("--min-weight", type=float, default=0.18, help="minimum link weight to traverse")
    p_retrieve.add_argument("--ranking-mode", choices=["path", "ppr", "hybrid"], default="hybrid")
    p_retrieve.add_argument("--ppr-alpha", type=float, default=0.85)
    p_retrieve.add_argument("--ppr-iters", type=int, default=16)
    p_retrieve.add_argument(
        "--diversify",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="enable MMR result diversification",
    )
    p_retrieve.add_argument("--mmr-lambda", type=float, default=0.72, help="MMR relevance/diversity tradeoff (0..1)")
    p_retrieve.add_argument("--max-items", type=int, default=12, help="maximum retrieval results")
    p_retrieve.add_argument(
        "--profile-aware",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="use profile-aware re-ranking",
    )
    p_retrieve.add_argument("--profile-weight", type=float, default=0.35, help="profile boost weight (0..1)")
    p_retrieve.add_argument("--profile-limit", type=int, default=240, help="max memories sampled for profile inference")
    p_retrieve.add_argument("--explain", action="store_true", help="include seed/paths explanation")
    p_retrieve.set_defaults(func=cmd_retrieve)

    p_profile = sub.add_parser("profile", help="build deterministic user profile from memories")
    p_profile.add_argument("--config", help="path to omnimem config json")
    p_profile.add_argument("--project-id", default="", help="optional project filter")
    p_profile.add_argument("--session-id", default="", help="optional session filter")
    p_profile.add_argument("--limit", type=int, default=240)
    p_profile.set_defaults(func=cmd_profile)

    p_feedback = sub.add_parser("feedback", help="apply explicit feedback to one memory")
    p_feedback.add_argument("--config", help="path to omnimem config json")
    p_feedback.add_argument("--id", required=True, help="memory id")
    p_feedback.add_argument("--feedback", required=True, choices=["positive", "negative", "forget", "correct"])
    p_feedback.add_argument("--delta", type=int, default=1)
    p_feedback.add_argument("--note", default="")
    p_feedback.add_argument("--correction", default="")
    p_feedback.add_argument("--session-id", default="session-local")
    p_feedback.set_defaults(func=cmd_feedback)

    p_verify = sub.add_parser("verify", help="consistency verification")
    p_verify.add_argument("--config", help="path to omnimem config json")
    p_verify.set_defaults(func=cmd_verify)

    p_sync = sub.add_parser("sync", help="sync actions")
    p_sync.add_argument("--config", help="path to omnimem config json")
    p_sync.add_argument(
        "--mode",
        choices=["noop", "git", "github-status", "github-push", "github-pull", "github-bootstrap"],
        default="noop",
    )
    p_sync.add_argument("--remote-name", help="git remote name, default origin")
    p_sync.add_argument("--remote-url", help="remote url (https://... or git@...); optional")
    p_sync.add_argument("--branch", help="target branch, default main")
    p_sync.add_argument("--commit-message", default="chore(memory): sync snapshot")
    p_sync.set_defaults(func=cmd_sync)

    p_decay = sub.add_parser("decay", help="apply or preview time-based signal decay")
    p_decay.add_argument("--config", help="path to omnimem config json")
    p_decay.add_argument("--project-id", default="")
    p_decay.add_argument("--session-id", default="system")
    p_decay.add_argument("--days", type=int, default=14)
    p_decay.add_argument("--layers", default="instant,short,long", help="comma-separated layers, default instant,short,long")
    p_decay.add_argument("--limit", type=int, default=200)
    p_decay.add_argument("--apply", action="store_true", help="apply decay (default is preview/dry-run)")
    p_decay.set_defaults(func=cmd_decay)

    p_consolidate = sub.add_parser("consolidate", help="preview/apply adaptive memory consolidation (promote/demote)")
    p_consolidate.add_argument("--config", help="path to omnimem config json")
    p_consolidate.add_argument("--project-id", default="")
    p_consolidate.add_argument("--session-id", default="")
    p_consolidate.add_argument("--actor-session-id", default="system")
    p_consolidate.add_argument("--limit", type=int, default=80)
    p_consolidate.add_argument("--p-imp", type=float, default=0.75)
    p_consolidate.add_argument("--p-conf", type=float, default=0.65)
    p_consolidate.add_argument("--p-stab", type=float, default=0.65)
    p_consolidate.add_argument("--p-vol", type=float, default=0.65)
    p_consolidate.add_argument("--d-vol", type=float, default=0.75)
    p_consolidate.add_argument("--d-stab", type=float, default=0.45)
    p_consolidate.add_argument("--d-reuse", type=int, default=1)
    p_consolidate.add_argument("--apply", action="store_true", help="apply actions (default preview)")
    p_consolidate.set_defaults(func=cmd_consolidate)

    p_compress = sub.add_parser("compress", help="preview/apply session memory compression digest")
    p_compress.add_argument("--config", help="path to omnimem config json")
    p_compress.add_argument("--project-id", default="")
    p_compress.add_argument("--session-id", required=True)
    p_compress.add_argument("--actor-session-id", default="system")
    p_compress.add_argument("--limit", type=int, default=120)
    p_compress.add_argument("--min-items", type=int, default=8)
    p_compress.add_argument("--layer", choices=sorted(LAYER_SET), default="short")
    p_compress.add_argument("--apply", action="store_true", help="write summary memory (default preview)")
    p_compress.set_defaults(func=cmd_compress)

    p_distill = sub.add_parser("distill", help="distill session memories into semantic/procedural summaries")
    p_distill.add_argument("--config", help="path to omnimem config json")
    p_distill.add_argument("--project-id", default="", help="optional project filter")
    p_distill.add_argument("--session-id", required=True, help="target session id")
    p_distill.add_argument("--limit", type=int, default=140, help="source memory scan limit")
    p_distill.add_argument("--min-items", type=int, default=10, help="minimum source memories to distill")
    p_distill.add_argument("--semantic-layer", choices=sorted(LAYER_SET), default="long")
    p_distill.add_argument("--procedural-layer", choices=sorted(LAYER_SET), default="short")
    p_distill.add_argument("--apply", action="store_true", help="write distilled memories (default preview)")
    p_distill.add_argument("--actor-session-id", default="session-local")
    p_distill.set_defaults(func=cmd_distill)

    p_raptor = sub.add_parser("raptor", help="build hierarchical digest (RAPTOR-style)")
    p_raptor.add_argument("--config", help="path to omnimem config json")
    p_raptor.add_argument("--project-id", default="", help="optional project filter")
    p_raptor.add_argument("--session-id", default="", help="optional session filter")
    p_raptor.add_argument("--days", type=int, default=30)
    p_raptor.add_argument("--limit", type=int, default=180)
    p_raptor.add_argument("--layer", choices=sorted(LAYER_SET), default="long")
    p_raptor.add_argument("--apply", action="store_true", help="write digest memory (default preview)")
    p_raptor.add_argument("--actor-session-id", default="system")
    p_raptor.set_defaults(func=cmd_raptor)

    p_enhance = sub.add_parser("enhance", help="heuristically enhance weak memory summaries")
    p_enhance.add_argument("--config", help="path to omnimem config json")
    p_enhance.add_argument("--project-id", default="", help="optional project filter")
    p_enhance.add_argument("--session-id", default="", help="optional session filter")
    p_enhance.add_argument("--limit", type=int, default=80)
    p_enhance.add_argument("--min-short-len", type=int, default=24)
    p_enhance.add_argument("--apply", action="store_true", help="apply summary updates (default preview)")
    p_enhance.add_argument("--actor-session-id", default="system")
    p_enhance.set_defaults(func=cmd_enhance)

    p_webui = sub.add_parser("webui", help="start local web ui")
    p_webui.add_argument("--config", help="path to omnimem config json")
    p_webui.add_argument("--host", default="127.0.0.1")
    p_webui.add_argument("--port", type=int, default=8765)
    p_webui.add_argument("--no-daemon", action="store_true", help="disable background quasi-realtime sync")
    p_webui.add_argument("--daemon-scan-interval", type=int, default=None)
    p_webui.add_argument("--daemon-pull-interval", type=int, default=None)
    p_webui.add_argument("--daemon-retry-max-attempts", type=int, default=None)
    p_webui.add_argument("--daemon-retry-initial-backoff", type=int, default=None)
    p_webui.add_argument("--daemon-retry-max-backoff", type=int, default=None)
    p_webui.add_argument("--daemon-maintenance-interval", type=int, default=None)
    p_webui.add_argument("--daemon-maintenance-decay-days", type=int, default=None)
    p_webui.add_argument("--daemon-maintenance-decay-limit", type=int, default=None)
    p_webui.add_argument("--daemon-maintenance-consolidate-limit", type=int, default=None)
    p_webui.add_argument("--daemon-maintenance-compress-sessions", type=int, default=None)
    p_webui.add_argument("--daemon-maintenance-compress-min-items", type=int, default=None)
    p_webui.add_argument("--daemon-maintenance-temporal-tree-days", type=int, default=None)
    p_webui.add_argument("--daemon-maintenance-rehearsal-days", type=int, default=None)
    p_webui.add_argument("--daemon-maintenance-rehearsal-limit", type=int, default=None)
    p_webui.add_argument("--daemon-maintenance-reflection-days", type=int, default=None)
    p_webui.add_argument("--daemon-maintenance-reflection-limit", type=int, default=None)
    p_webui.add_argument("--daemon-maintenance-reflection-min-repeats", type=int, default=None)
    p_webui.add_argument("--daemon-maintenance-reflection-max-avg-retrieved", type=float, default=None)
    p_webui.add_argument(
        "--daemon-maintenance-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable/disable daemon maintenance passes",
    )
    p_webui.add_argument(
        "--daemon-maintenance-temporal-tree-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable/disable temporal memory tree maintenance",
    )
    p_webui.add_argument(
        "--daemon-maintenance-rehearsal-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable/disable rehearsal maintenance",
    )
    p_webui.add_argument(
        "--daemon-maintenance-reflection-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable/disable reflective gap maintenance",
    )
    p_webui.add_argument("--webui-token", help="optional API token, can also use OMNIMEM_WEBUI_TOKEN")
    p_webui.add_argument(
        "--allow-non-localhost",
        action="store_true",
        help="allow binding to non-local host (requires explicit opt-in)",
    )
    p_webui.set_defaults(func=cmd_webui)

    p_start = sub.add_parser("start", help="start app (webui + sync daemon)")
    p_start.add_argument("--config", help="path to omnimem config json")
    p_start.add_argument("--host", default="127.0.0.1")
    p_start.add_argument("--port", type=int, default=8765)
    p_start.add_argument("--no-daemon", action="store_true", help="disable background quasi-realtime sync")
    p_start.add_argument("--daemon-scan-interval", type=int, default=None)
    p_start.add_argument("--daemon-pull-interval", type=int, default=None)
    p_start.add_argument("--daemon-retry-max-attempts", type=int, default=None)
    p_start.add_argument("--daemon-retry-initial-backoff", type=int, default=None)
    p_start.add_argument("--daemon-retry-max-backoff", type=int, default=None)
    p_start.add_argument("--daemon-maintenance-interval", type=int, default=None)
    p_start.add_argument("--daemon-maintenance-decay-days", type=int, default=None)
    p_start.add_argument("--daemon-maintenance-decay-limit", type=int, default=None)
    p_start.add_argument("--daemon-maintenance-consolidate-limit", type=int, default=None)
    p_start.add_argument("--daemon-maintenance-compress-sessions", type=int, default=None)
    p_start.add_argument("--daemon-maintenance-compress-min-items", type=int, default=None)
    p_start.add_argument("--daemon-maintenance-temporal-tree-days", type=int, default=None)
    p_start.add_argument("--daemon-maintenance-rehearsal-days", type=int, default=None)
    p_start.add_argument("--daemon-maintenance-rehearsal-limit", type=int, default=None)
    p_start.add_argument("--daemon-maintenance-reflection-days", type=int, default=None)
    p_start.add_argument("--daemon-maintenance-reflection-limit", type=int, default=None)
    p_start.add_argument("--daemon-maintenance-reflection-min-repeats", type=int, default=None)
    p_start.add_argument("--daemon-maintenance-reflection-max-avg-retrieved", type=float, default=None)
    p_start.add_argument(
        "--daemon-maintenance-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable/disable daemon maintenance passes",
    )
    p_start.add_argument(
        "--daemon-maintenance-temporal-tree-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable/disable temporal memory tree maintenance",
    )
    p_start.add_argument(
        "--daemon-maintenance-rehearsal-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable/disable rehearsal maintenance",
    )
    p_start.add_argument(
        "--daemon-maintenance-reflection-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable/disable reflective gap maintenance",
    )
    p_start.add_argument("--webui-token", help="optional API token, can also use OMNIMEM_WEBUI_TOKEN")
    p_start.add_argument(
        "--allow-non-localhost",
        action="store_true",
        help="allow binding to non-local host (requires explicit opt-in)",
    )
    p_start.set_defaults(func=cmd_start)

    # Internal helper: background guard used by wrappers to implement "on-demand" WebUI lifecycle.
    p_guard = sub.add_parser("webui-guard", help=argparse.SUPPRESS)
    p_guard.add_argument("--runtime-dir", required=True)
    p_guard.add_argument("--host", required=True)
    p_guard.add_argument("--port", type=int, required=True)
    p_guard.add_argument("--parent-pid", type=int, required=True)
    p_guard.add_argument("--lease", required=True)
    p_guard.add_argument("--stop-when-idle", action="store_true")
    p_guard.set_defaults(func=cmd_webui_guard)

    p_stop = sub.add_parser("stop", help="stop wrapper-managed webui sidecar")
    p_stop.add_argument("--config", help="path to omnimem config json")
    p_stop.add_argument("--host", default="127.0.0.1")
    p_stop.add_argument("--port", type=int, default=8765)
    p_stop.add_argument("--all", action="store_true", help="stop all known sidecar endpoints and cleanup runtime leases")
    p_stop.set_defaults(func=cmd_stop)

    p_doctor = sub.add_parser("doctor", help="diagnose webui/daemon/sync health and suggest fixes")
    p_doctor.add_argument("--config", help="path to omnimem config json")
    p_doctor.add_argument("--host", default="127.0.0.1")
    p_doctor.add_argument("--port", type=int, default=8765)
    p_doctor.set_defaults(func=cmd_doctor)

    p_preflight = sub.add_parser("preflight", help="release preflight checks (blocks publish on clean worktree)")
    p_preflight.add_argument("--path", default=".", help="project path to check")
    p_preflight.add_argument("--allow-clean", action="store_true", help="allow release when no local changes are detected")
    p_preflight.set_defaults(func=cmd_preflight)

    p_cfg_path = sub.add_parser("config-path", help="print active config path")
    p_cfg_path.add_argument("--config", help="path to omnimem config json")
    p_cfg_path.set_defaults(func=cmd_config_path)

    p_uninstall = sub.add_parser("uninstall", help="uninstall local omnimem home")
    p_uninstall.add_argument("--config", help="path to omnimem config json")
    p_uninstall.add_argument("--yes", action="store_true", help="confirm deletion")
    p_uninstall.add_argument("--detach-project", help="optional project path to detach omni files")
    p_uninstall.set_defaults(func=cmd_uninstall)

    p_bootstrap = sub.add_parser("bootstrap", help="install local runtime from packaged files")
    p_bootstrap.add_argument("--config", help="path to omnimem config json")
    p_bootstrap.add_argument("--wizard", action="store_true")
    p_bootstrap.add_argument("--home", help="optional override via OMNIMEM_HOME")
    p_bootstrap.add_argument("--remote-name", default="origin")
    p_bootstrap.add_argument("--branch", default="main")
    p_bootstrap.add_argument("--remote-url")
    p_bootstrap.add_argument("--attach-project", help="optional project path to attach")
    p_bootstrap.add_argument("--project-id", help="optional project id for attach")
    p_bootstrap.set_defaults(func=cmd_bootstrap)

    p_adapter = sub.add_parser("adapter", help="external adapters")
    p_adapter.add_argument("--config", help="path to omnimem config json")
    adapter_sub = p_adapter.add_subparsers(dest="adapter_cmd", required=True)

    p_cred = adapter_sub.add_parser("cred-resolve", help="resolve credential reference")
    p_cred.add_argument("--ref", required=True, help="env://KEY or op://vault/item/field")
    p_cred.add_argument("--mask", action="store_true", help="hide sensitive value in output")
    p_cred.set_defaults(func=cmd_adapter_cred_resolve)

    p_notion_write = adapter_sub.add_parser("notion-write", help="write a page to notion database")
    p_notion_write.add_argument("--database-id", required=True)
    p_notion_write.add_argument("--title", required=True)
    p_notion_write.add_argument("--content", default="")
    p_notion_write.add_argument("--content-file")
    p_notion_write.add_argument("--title-property", default="Name")
    p_notion_write.add_argument("--token")
    p_notion_write.add_argument("--token-ref")
    p_notion_write.add_argument("--dry-run", action="store_true")
    p_notion_write.set_defaults(func=cmd_adapter_notion_write)

    p_notion_query = adapter_sub.add_parser("notion-query", help="query notion database")
    p_notion_query.add_argument("--database-id", required=True)
    p_notion_query.add_argument("--page-size", type=int, default=5)
    p_notion_query.add_argument("--token")
    p_notion_query.add_argument("--token-ref")
    p_notion_query.add_argument("--dry-run", action="store_true")
    p_notion_query.set_defaults(func=cmd_adapter_notion_query)

    p_r2_put = adapter_sub.add_parser("r2-put", help="upload file via presigned PUT URL")
    p_r2_put.add_argument("--file", required=True)
    p_r2_put.add_argument("--url")
    p_r2_put.add_argument("--url-ref")
    p_r2_put.add_argument("--dry-run", action="store_true")
    p_r2_put.set_defaults(func=cmd_adapter_r2_put)

    p_r2_get = adapter_sub.add_parser("r2-get", help="download file via presigned GET URL")
    p_r2_get.add_argument("--out", required=True)
    p_r2_get.add_argument("--url")
    p_r2_get.add_argument("--url-ref")
    p_r2_get.add_argument("--dry-run", action="store_true")
    p_r2_get.set_defaults(func=cmd_adapter_r2_get)

    p_agent = sub.add_parser("agent", help="automatic memory orchestration wrappers")
    p_agent.add_argument("--config", help="path to omnimem config json")
    agent_sub = p_agent.add_subparsers(dest="agent_cmd", required=True)

    p_agent_run = agent_sub.add_parser("run", help="single-turn auto-memory call")
    p_agent_run.add_argument("--tool", choices=["codex", "claude"], required=True)
    p_agent_run.add_argument("--project-id", required=True)
    p_agent_run.add_argument("--prompt", required=True)
    p_agent_run.add_argument("--drift-threshold", type=float, default=0.62)
    p_agent_run.add_argument("--cwd", help="optional working directory for underlying tool")
    p_agent_run.add_argument("--retrieve-limit", type=int, default=8)
    p_agent_run.add_argument("--context-budget-tokens", type=int, default=420)
    p_agent_run.add_argument("--no-delta-context", action="store_true")
    p_agent_run.set_defaults(func=cmd_agent_run)

    p_agent_chat = agent_sub.add_parser("chat", help="interactive auto-memory chat loop")
    p_agent_chat.add_argument("--tool", choices=["codex", "claude"], required=True)
    p_agent_chat.add_argument("--project-id", required=True)
    p_agent_chat.add_argument("--drift-threshold", type=float, default=0.62)
    p_agent_chat.add_argument("--cwd", help="optional working directory for underlying tool")
    p_agent_chat.add_argument("--context-budget-tokens", type=int, default=420)
    p_agent_chat.add_argument("--no-delta-context", action="store_true")
    p_agent_chat.set_defaults(func=cmd_agent_chat)

    for tool_name in ["codex", "claude"]:
        p_short = sub.add_parser(tool_name, help=f"shortcut: auto-memory wrapper for {tool_name}")
        p_short.add_argument("prompt", nargs="*", help="optional single-turn prompt; empty starts interactive mode")
        p_short.add_argument("--project-id", help="defaults to .omnimem.json project_id or cwd basename")
        p_short.add_argument("--drift-threshold", type=float, default=0.62)
        p_short.add_argument("--cwd", help="optional working directory for underlying tool")
        p_short.add_argument("--retrieve-limit", type=int, default=8)
        p_short.add_argument("--context-budget-tokens", type=int, default=420, help="max tokens for injected memory context")
        p_short.add_argument("--no-delta-context", action="store_true", help="disable delta-only memory injection")
        p_short.add_argument("--oneshot", action="store_true", help="use internal one-shot orchestrator path")
        p_short.add_argument("--native", action="store_true", help="launch native tool directly (no per-turn memory orchestration)")
        p_short.add_argument("--agent", action="store_true", help="run the OmniMem agent for auto memory context and checkpoints")
        p_short.add_argument(
            "--inject",
            action="store_true",
            help="inject OmniMem context into the first call (changes native UX)",
        )
        p_short.add_argument(
            "--smart",
            action="store_true",
            help="start native tool with OmniMem protocol + recent memory context (more automatic; changes session by adding an initial prompt)",
        )
        p_short.add_argument(
            "--home-mode",
            choices=["auto", "global", "workspace"],
            default="auto",
            help="where to store OMNIMEM_HOME: auto picks global if writable else workspace-local",
        )
        p_short.add_argument("--home", help="explicit OMNIMEM_HOME override (wins over --home-mode)")
        p_short.add_argument("--no-webui", action="store_true", help="do not auto-start webui sidecar")
        p_short.add_argument(
            "--webui-on-demand",
            action="store_true",
            help="auto-stop WebUI when no active wrapper sessions (default behavior)",
        )
        p_short.add_argument(
            "--webui-persist",
            action="store_true",
            help="keep WebUI running after wrapper exits; can also set OMNIMEM_WEBUI_PERSIST=1",
        )
        p_short.add_argument("--webui-host", default="127.0.0.1")
        p_short.add_argument("--webui-port", type=int, default=8765)
        p_short.add_argument("--no-daemon", action="store_true", help="when auto-starting webui, disable sync daemon")
        p_short.add_argument(
            "--auto-write",
            action="store_true",
            help="auto-capture Codex assistant turns from ~/.codex/sessions into OmniMem (skips obvious secrets; still use with care)",
        )
        p_short.add_argument("--config", help="path to omnimem config json")
        p_short.set_defaults(func=cmd_tool_shortcut)

    return p


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if not raw_argv:
        raw_argv = ["start"]
    elif raw_argv[0] in {"--host", "--port"} or raw_argv[0].startswith("--host=") or raw_argv[0].startswith("--port="):
        raw_argv = ["start", *raw_argv]

    parser = build_parser()
    tool_args: list[str] = []
    if raw_argv and raw_argv[0] in {"codex", "claude"} and "--" in raw_argv:
        i = raw_argv.index("--")
        tool_args = raw_argv[i + 1 :]
        raw_argv = raw_argv[:i]
    args = parser.parse_args(raw_argv)
    if getattr(args, "cmd", "") in {"codex", "claude"}:
        setattr(args, "tool_args", tool_args)
    try:
        return args.func(args)
    except Exception as exc:
        hint = cli_error_hint(str(exc))
        out: dict[str, object] = {"ok": False, "error": str(exc)}
        if hint:
            out["hint"] = hint
        print_json(out)
        return 1


if __name__ == "__main__":
    sys.exit(main())
