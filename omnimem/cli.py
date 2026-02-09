from __future__ import annotations

import argparse
import json
import os
import subprocess
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .agent import interactive_chat, run_turn
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
    find_memories,
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
    rows = find_memories(paths, schema_sql_path(), args.query, args.layer, args.limit)
    print_json({"ok": True, "count": len(rows), "items": rows})
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    result = build_brief(paths, schema_sql_path(), args.project_id, args.limit)
    print_json({"ok": True, **result})
    return 0


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


def cmd_webui(args: argparse.Namespace) -> int:
    cfg, cfg_path = load_config_with_path(cfg_path_arg(args))
    run_webui(
        host=args.host,
        port=args.port,
        cfg=cfg,
        cfg_path=cfg_path,
        schema_sql_path=schema_sql_path(),
        sync_runner=sync_git,
        daemon_runner=run_sync_daemon,
        enable_daemon=not args.no_daemon,
        daemon_scan_interval=args.daemon_scan_interval,
        daemon_pull_interval=args.daemon_pull_interval,
        daemon_retry_max_attempts=args.daemon_retry_max_attempts,
        daemon_retry_initial_backoff=args.daemon_retry_initial_backoff,
        daemon_retry_max_backoff=args.daemon_retry_max_backoff,
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
    )
    print_json(out)
    return 0


def cmd_agent_chat(args: argparse.Namespace) -> int:
    return interactive_chat(
        tool=args.tool,
        project_id=args.project_id,
        drift_threshold=args.drift_threshold,
        cwd=args.cwd,
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


def cmd_tool_shortcut(args: argparse.Namespace) -> int:
    tool = args.cmd
    cwd = args.cwd
    project_id = infer_project_id(cwd, args.project_id)

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

    cfg = load_config(cfg_path_arg(args))
    paths = resolve_paths(cfg)
    schema = schema_sql_path()
    brief = build_brief(paths, schema, project_id, limit=6)
    mems = find_memories(paths, schema, query="", layer=None, limit=args.retrieve_limit, project_id=project_id)

    lines = [
        "OmniMem sidecar is enabled for this session.",
        f"Project ID: {project_id}",
        "Use memory protocol automatically:",
        "- On stable decisions/facts, call `omnimem write`.",
        "- On topic drift or phase switch, call `omnimem checkpoint` and start a new thread.",
        "- Prefer short-term first; promote to long-term only when repeated and stable.",
        "- Never store raw secrets; only credential refs.",
    ]
    if brief.get("checkpoints"):
        lines.append("Recent checkpoints:")
        for x in brief["checkpoints"][:3]:
            lines.append(f"- {x.get('updated_at','')}: {x.get('summary','')}")
    if mems:
        lines.append("Recent memories:")
        for x in mems[:6]:
            lines.append(f"- [{x.get('project_id','')}/{x.get('layer','')}/{x.get('kind','')}] {x.get('summary','')}")
    memory_context = "\n".join(lines)

    if not args.no_webui:
        ensure_webui_running(cfg_path_arg(args), args.webui_host, args.webui_port, args.no_daemon)
        print(f"[omnimem] WebUI: http://{args.webui_host}:{args.webui_port}")

    prompt = " ".join(args.prompt).strip()
    if not getattr(args, "native", False):
        # Default: agent orchestrator for automatic memory read/write + drift checkpoints.
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

    # Legacy/native mode: launch tool once with injected system prompt only.
    if tool == "codex":
        native_cmd = ["codex", f"{memory_context}\n\nUser request: {prompt}" if prompt else memory_context]
    else:
        native_cmd = ["claude", "--append-system-prompt", memory_context]
        if prompt:
            native_cmd.append(prompt)

    run_env = dict(os.environ)
    if chosen_home:
        run_env["OMNIMEM_HOME"] = chosen_home
    if cfg_path_arg(args):
        run_env["OMNIMEM_CONFIG"] = str(cfg_path_arg(args))
    if cwd:
        run_cwd = str(run_cwd_path)
    else:
        run_cwd = str(run_cwd_path)
    print(f"[omnimem] launching native {tool} in {run_cwd} (project_id={project_id})")
    return subprocess.call(native_cmd, cwd=run_cwd, env=run_env)


def webui_alive(host: str, port: int) -> bool:
    url = f"http://{host}:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=0.6) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_webui_running(cfg_path: Path | None, host: str, port: int, no_daemon: bool) -> None:
    if webui_alive(host, port):
        return

    cfg = load_config(cfg_path)
    paths = resolve_paths(cfg)
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

    p_webui = sub.add_parser("webui", help="start local web ui")
    p_webui.add_argument("--config", help="path to omnimem config json")
    p_webui.add_argument("--host", default="127.0.0.1")
    p_webui.add_argument("--port", type=int, default=8765)
    p_webui.add_argument("--no-daemon", action="store_true", help="disable background quasi-realtime sync")
    p_webui.add_argument("--daemon-scan-interval", type=int, default=8)
    p_webui.add_argument("--daemon-pull-interval", type=int, default=30)
    p_webui.add_argument("--daemon-retry-max-attempts", type=int, default=3)
    p_webui.add_argument("--daemon-retry-initial-backoff", type=int, default=1)
    p_webui.add_argument("--daemon-retry-max-backoff", type=int, default=8)
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
    p_start.add_argument("--daemon-scan-interval", type=int, default=8)
    p_start.add_argument("--daemon-pull-interval", type=int, default=30)
    p_start.add_argument("--daemon-retry-max-attempts", type=int, default=3)
    p_start.add_argument("--daemon-retry-initial-backoff", type=int, default=1)
    p_start.add_argument("--daemon-retry-max-backoff", type=int, default=8)
    p_start.add_argument("--webui-token", help="optional API token, can also use OMNIMEM_WEBUI_TOKEN")
    p_start.add_argument(
        "--allow-non-localhost",
        action="store_true",
        help="allow binding to non-local host (requires explicit opt-in)",
    )
    p_start.set_defaults(func=cmd_start)

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
    p_agent_run.set_defaults(func=cmd_agent_run)

    p_agent_chat = agent_sub.add_parser("chat", help="interactive auto-memory chat loop")
    p_agent_chat.add_argument("--tool", choices=["codex", "claude"], required=True)
    p_agent_chat.add_argument("--project-id", required=True)
    p_agent_chat.add_argument("--drift-threshold", type=float, default=0.62)
    p_agent_chat.add_argument("--cwd", help="optional working directory for underlying tool")
    p_agent_chat.set_defaults(func=cmd_agent_chat)

    for tool_name in ["codex", "claude"]:
        p_short = sub.add_parser(tool_name, help=f"shortcut: auto-memory wrapper for {tool_name}")
        p_short.add_argument("prompt", nargs="*", help="optional single-turn prompt; empty starts interactive mode")
        p_short.add_argument("--project-id", help="defaults to .omnimem.json project_id or cwd basename")
        p_short.add_argument("--drift-threshold", type=float, default=0.62)
        p_short.add_argument("--cwd", help="optional working directory for underlying tool")
        p_short.add_argument("--retrieve-limit", type=int, default=8)
        p_short.add_argument("--oneshot", action="store_true", help="use internal one-shot orchestrator path")
        p_short.add_argument("--native", action="store_true", help="launch native tool directly (no per-turn memory orchestration)")
        p_short.add_argument(
            "--home-mode",
            choices=["auto", "global", "workspace"],
            default="auto",
            help="where to store OMNIMEM_HOME: auto picks global if writable else workspace-local",
        )
        p_short.add_argument("--home", help="explicit OMNIMEM_HOME override (wins over --home-mode)")
        p_short.add_argument("--no-webui", action="store_true", help="do not auto-start webui sidecar")
        p_short.add_argument("--webui-host", default="127.0.0.1")
        p_short.add_argument("--webui-port", type=int, default=8765)
        p_short.add_argument("--no-daemon", action="store_true", help="when auto-starting webui, disable sync daemon")
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
    args = parser.parse_args(raw_argv)
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
