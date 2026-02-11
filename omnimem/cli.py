from __future__ import annotations

import argparse
import json
import os
import signal
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
    build_brief,
    compress_session_context,
    consolidate_memories,
    distill_session_memory,
    find_memories,
    retrieve_thread,
    load_config,
    load_config_with_path,
    parse_list_csv,
    parse_ref,
    resolve_paths,
    run_sync_daemon,
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
    )
    if not getattr(args, "explain", False):
        out.pop("explain", None)
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

    webui_on_demand = bool(getattr(args, "webui_on_demand", False))
    if not webui_on_demand:
        v = os.getenv("OMNIMEM_WEBUI_ON_DEMAND", "").strip().lower()
        webui_on_demand = v in {"1", "true", "yes", "on"}

    if not args.no_webui:
        started_by_me = ensure_webui_running(cfg_path_arg(args), args.webui_host, args.webui_port, args.no_daemon)
        if webui_on_demand:
            home = Path(os.environ.get("OMNIMEM_HOME", "") or "").expanduser().resolve()
            if started_by_me:
                try:
                    _webui_managed_marker(home).parent.mkdir(parents=True, exist_ok=True)
                    _webui_managed_marker(home).write_text(
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
                home,
                parent_pid=os.getpid(),
                host=str(args.webui_host),
                port=int(args.webui_port),
            )
            guard_cmd = [
                sys.executable,
                "-m",
                "omnimem.cli",
                "webui-guard",
                "--home",
                str(home),
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


def ensure_webui_running(cfg_path: Path | None, host: str, port: int, no_daemon: bool) -> bool:
    if webui_alive(host, port):
        return False

    cfg = load_config(cfg_path)
    paths = resolve_paths(cfg)
    # Avoid repeatedly spawning `omnimem start` when the WebUI is already running but
    # liveness probing is flaky/slow: if a pidfile exists and the pid is alive, do not
    # attempt another bind on the same port.
    pid_fp = paths.root / "runtime" / "webui.pid"
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
    log_dir = paths.root / "runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_fp = log_dir / "webui.log"
    cmd = [sys.executable, "-m", "omnimem.cli", "start", "--host", host, "--port", str(port)]
    if no_daemon:
        cmd.append("--no-daemon")
    if cfg_path:
        cmd.extend(["--config", str(cfg_path)])

    with log_fp.open("ab") as f:
        subprocess.Popen(
            cmd,
            stdout=f,
            stderr=f,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
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


def _webui_runtime_dir(home: Path) -> Path:
    return home / "runtime"


def _webui_leases_dir(home: Path) -> Path:
    return _webui_runtime_dir(home) / "webui_leases"


def _create_webui_lease(home: Path, *, parent_pid: int, host: str, port: int) -> Path:
    d = _webui_leases_dir(home)
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


def _cleanup_stale_leases(home: Path) -> list[Path]:
    d = _webui_leases_dir(home)
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


def _webui_pid_file(home: Path) -> Path:
    return _webui_runtime_dir(home) / "webui.pid"


def _webui_managed_marker(home: Path) -> Path:
    return _webui_runtime_dir(home) / "webui.managed.json"


def _read_webui_pid(home: Path) -> int:
    fp = _webui_pid_file(home)
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


def _kill_webui(home: Path, pid: int) -> None:
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
    home = Path(args.home).expanduser().resolve()
    lease_fp = Path(args.lease).expanduser().resolve()
    parent_pid = int(args.parent_pid)

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
    if not _webui_managed_marker(home).exists():
        return 0

    keep = _cleanup_stale_leases(home)
    if keep:
        return 0

    pid = _read_webui_pid(home)
    _kill_webui(home, pid)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="omnimem")
    p.add_argument("--config", dest="global_config", help="path to omnimem config json")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_write = sub.add_parser("write", help="write a memory")
    add_common_write_args(p_write)
    p_write.set_defaults(func=cmd_write)

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
    p_retrieve.add_argument("--explain", action="store_true", help="include seed/paths explanation")
    p_retrieve.set_defaults(func=cmd_retrieve)

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
    p_guard.add_argument("--home", required=True)
    p_guard.add_argument("--parent-pid", type=int, required=True)
    p_guard.add_argument("--lease", required=True)
    p_guard.add_argument("--stop-when-idle", action="store_true")
    p_guard.set_defaults(func=cmd_webui_guard)

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
            help="auto-stop WebUI when no active wrapper sessions (shared home); can also set OMNIMEM_WEBUI_ON_DEMAND=1",
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
