from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "0.1.0"
LAYER_SET = {"instant", "short", "long", "archive"}
KIND_SET = {"note", "decision", "task", "checkpoint", "summary", "evidence"}
EVENT_SET = {
    "memory.write",
    "memory.update",
    "memory.checkpoint",
    "memory.promote",
    "memory.verify",
    "memory.sync",
}


@dataclass
class MemoryPaths:
    root: Path
    markdown_root: Path
    jsonl_root: Path
    sqlite_path: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_id() -> str:
    return uuid.uuid4().hex


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_list_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def parse_ref(raw: str) -> dict[str, str]:
    # type:target[:note]
    parts = raw.split(":", 2)
    if len(parts) < 2:
        raise ValueError(f"invalid --ref format: {raw}")
    obj: dict[str, str] = {"type": parts[0], "target": parts[1]}
    if len(parts) == 3 and parts[2]:
        obj["note"] = parts[2]
    return obj


def load_config(path: Path | None) -> dict[str, Any]:
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    env_home = os.getenv("OMNIMEM_HOME")
    if env_home:
        default_cfg = Path(env_home) / "omnimem.config.json"
    else:
        default_cfg = Path.home() / ".omnimem" / "omnimem.config.json"

    if default_cfg.exists():
        return json.loads(default_cfg.read_text(encoding="utf-8"))

    root = default_cfg.parent
    return {
        "version": SCHEMA_VERSION,
        "home": str(root),
        "storage": {
            "markdown": str(root / "data" / "markdown"),
            "jsonl": str(root / "data" / "jsonl"),
            "sqlite": str(root / "data" / "omnimem.db"),
        },
    }


def default_config_path() -> Path:
    env_home = os.getenv("OMNIMEM_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve() / "omnimem.config.json"
    return Path.home().expanduser().resolve() / ".omnimem" / "omnimem.config.json"


def load_config_with_path(path: Path | None) -> tuple[dict[str, Any], Path]:
    if path:
        p = path.expanduser().resolve()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8")), p
        return load_config(None), p

    p = default_config_path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8")), p
    return load_config(None), p


def save_config(path: Path, cfg: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_paths(cfg: dict[str, Any]) -> MemoryPaths:
    home = Path(cfg.get("home", Path.cwd())).expanduser().resolve()
    storage = cfg.get("storage", {})
    markdown_root = Path(storage.get("markdown", home / "data" / "markdown")).expanduser().resolve()
    jsonl_root = Path(storage.get("jsonl", home / "data" / "jsonl")).expanduser().resolve()
    sqlite_path = Path(storage.get("sqlite", home / "data" / "omnimem.db")).expanduser().resolve()
    return MemoryPaths(root=home, markdown_root=markdown_root, jsonl_root=jsonl_root, sqlite_path=sqlite_path)


def ensure_storage(paths: MemoryPaths, schema_sql_path: Path) -> None:
    for layer in sorted(LAYER_SET):
        (paths.markdown_root / layer).mkdir(parents=True, exist_ok=True)
    paths.jsonl_root.mkdir(parents=True, exist_ok=True)
    paths.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(paths.sqlite_path) as conn:
        conn.executescript(schema_sql_path.read_text(encoding="utf-8"))


def ensure_system_memory(paths: MemoryPaths, schema_sql_path: Path) -> str:
    ensure_storage(paths, schema_sql_path)
    system_id = "system000"
    rel_path = "archive/system/system000.md"
    md_path = paths.markdown_root / rel_path
    if not md_path.exists():
        md_path.parent.mkdir(parents=True, exist_ok=True)
        body = "# system\n\nreserved memory for system audit events\n"
        md_path.write_text(body, encoding="utf-8")
    else:
        body = md_path.read_text(encoding="utf-8")

    with sqlite3.connect(paths.sqlite_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            INSERT OR IGNORE INTO memories(
              id, schema_version, created_at, updated_at, layer, kind, summary, body_md_path, body_text,
              tags_json, importance_score, confidence_score, stability_score, reuse_count, volatility_score,
              cred_refs_json, source_json, scope_json, integrity_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                system_id,
                SCHEMA_VERSION,
                utc_now(),
                utc_now(),
                "archive",
                "summary",
                "system",
                rel_path,
                body,
                "[]",
                1.0,
                1.0,
                1.0,
                0,
                0.0,
                "[]",
                '{"tool":"system","session_id":"system"}',
                '{"project_id":"global","workspace":""}',
                json.dumps({"content_sha256": sha256_text(body), "envelope_version": 1}),
            ),
        )
        conn.commit()

    return system_id


def event_file_path(paths: MemoryPaths, when: datetime) -> Path:
    return paths.jsonl_root / f"events-{when.strftime('%Y-%m')}.jsonl"


def md_rel_path(layer: str, mem_id: str, when: datetime) -> str:
    return f"{layer}/{when.strftime('%Y/%m')}/{mem_id}.md"


def write_markdown(paths: MemoryPaths, rel_path: str, content: str) -> Path:
    full = paths.markdown_root / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def insert_memory(conn: sqlite3.Connection, envelope: dict[str, Any], body_text: str) -> None:
    sig = envelope["signals"]
    conn.execute(
        """
        INSERT OR REPLACE INTO memories(
          id, schema_version, created_at, updated_at, layer, kind, summary, body_md_path, body_text,
          tags_json, importance_score, confidence_score, stability_score, reuse_count, volatility_score,
          cred_refs_json, source_json, scope_json, integrity_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            envelope["id"],
            envelope["schema_version"],
            envelope["created_at"],
            envelope["updated_at"],
            envelope["layer"],
            envelope["kind"],
            envelope["summary"],
            envelope["body_md_path"],
            body_text,
            json.dumps(envelope["tags"], ensure_ascii=False),
            float(sig["importance_score"]),
            float(sig["confidence_score"]),
            float(sig["stability_score"]),
            int(sig["reuse_count"]),
            float(sig["volatility_score"]),
            json.dumps(envelope["cred_refs"], ensure_ascii=False),
            json.dumps(envelope["source"], ensure_ascii=False),
            json.dumps(envelope["scope"], ensure_ascii=False),
            json.dumps(envelope["integrity"], ensure_ascii=False),
        ),
    )

    conn.execute("DELETE FROM memory_refs WHERE memory_id = ?", (envelope["id"],))
    for ref in envelope["refs"]:
        conn.execute(
            "INSERT INTO memory_refs(memory_id, ref_type, target, note) VALUES (?, ?, ?, ?)",
            (envelope["id"], ref.get("type", "memory"), ref.get("target", ""), ref.get("note")),
        )


def insert_event(conn: sqlite3.Connection, evt: dict[str, Any]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO memory_events(event_id, event_type, event_time, memory_id, payload_json) VALUES (?, ?, ?, ?, ?)",
        (evt["event_id"], evt["event_type"], evt["event_time"], evt["memory_id"], json.dumps(evt["payload"], ensure_ascii=False)),
    )


def log_system_event(paths: MemoryPaths, schema_sql_path: Path, event_type: str, payload: dict[str, Any]) -> None:
    system_id = ensure_system_memory(paths, schema_sql_path)
    evt = {
        "event_id": make_id(),
        "event_type": event_type,
        "event_time": utc_now(),
        "memory_id": system_id,
        "payload": payload,
    }
    append_jsonl(event_file_path(paths, datetime.now(timezone.utc)), evt)
    with sqlite3.connect(paths.sqlite_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        insert_event(conn, evt)
        conn.commit()


def reindex_from_jsonl(paths: MemoryPaths, schema_sql_path: Path, reset: bool = True) -> dict[str, Any]:
    ensure_storage(paths, schema_sql_path)
    system_id = ensure_system_memory(paths, schema_sql_path)
    files = sorted(paths.jsonl_root.glob("events-*.jsonl"))
    parsed_events = 0
    indexed_memories = 0
    skipped_events = 0

    with sqlite3.connect(paths.sqlite_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        if reset:
            conn.execute("DELETE FROM memory_events")
            conn.execute("DELETE FROM memory_refs")
            conn.execute("DELETE FROM memories WHERE id != ?", (system_id,))

        for fp in files:
            for line in fp.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                parsed_events += 1
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    skipped_events += 1
                    continue

                memory_id = evt.get("memory_id", system_id)
                if evt.get("event_type") not in EVENT_SET:
                    skipped_events += 1
                    continue

                payload = evt.get("payload", {})
                env = payload.get("envelope")
                if isinstance(env, dict):
                    rel = env.get("body_md_path", "")
                    body = ""
                    if rel:
                        mdp = paths.markdown_root / rel
                        if mdp.exists():
                            body = mdp.read_text(encoding="utf-8")
                    try:
                        insert_memory(conn, env, body)
                        indexed_memories += 1
                    except Exception:
                        skipped_events += 1
                        continue

                # Keep foreign key intact for system-level events or legacy lines.
                evt["memory_id"] = memory_id if memory_id else system_id
                try:
                    insert_event(conn, evt)
                except Exception:
                    skipped_events += 1
                    continue

        conn.commit()

    result = {
        "ok": True,
        "reset": reset,
        "jsonl_files": len(files),
        "events_parsed": parsed_events,
        "memories_indexed": indexed_memories,
        "events_skipped": skipped_events,
    }
    log_system_event(paths, schema_sql_path, "memory.update", {"action": "reindex", **result})
    return result


def build_envelope(
    *,
    mem_id: str,
    when_iso: str,
    layer: str,
    kind: str,
    summary: str,
    body_md_path: str,
    tags: list[str],
    refs: list[dict[str, str]],
    cred_refs: list[str],
    tool: str,
    account: str,
    device: str,
    session_id: str,
    project_id: str,
    workspace: str,
    importance: float,
    confidence: float,
    stability: float,
    reuse_count: int,
    volatility: float,
    content_sha256: str,
) -> dict[str, Any]:
    if layer not in LAYER_SET:
        raise ValueError(f"invalid layer: {layer}")
    if kind not in KIND_SET:
        raise ValueError(f"invalid kind: {kind}")

    return {
        "id": mem_id,
        "schema_version": SCHEMA_VERSION,
        "created_at": when_iso,
        "updated_at": when_iso,
        "layer": layer,
        "kind": kind,
        "summary": summary,
        "body_md_path": body_md_path,
        "tags": tags,
        "refs": refs,
        "signals": {
            "importance_score": importance,
            "confidence_score": confidence,
            "stability_score": stability,
            "reuse_count": reuse_count,
            "volatility_score": volatility,
        },
        "cred_refs": cred_refs,
        "source": {
            "tool": tool,
            "account": account,
            "device": device,
            "session_id": session_id,
        },
        "scope": {
            "project_id": project_id,
            "workspace": workspace,
        },
        "integrity": {
            "content_sha256": content_sha256,
            "envelope_version": 1,
        },
    }


def write_memory(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    layer: str,
    kind: str,
    summary: str,
    body: str,
    tags: list[str],
    refs: list[dict[str, str]],
    cred_refs: list[str],
    tool: str,
    account: str,
    device: str,
    session_id: str,
    project_id: str,
    workspace: str,
    importance: float,
    confidence: float,
    stability: float,
    reuse_count: int,
    volatility: float,
    event_type: str,
) -> dict[str, Any]:
    ensure_storage(paths, schema_sql_path)
    if event_type not in EVENT_SET:
        raise ValueError(f"invalid event_type: {event_type}")

    when_dt = datetime.now(timezone.utc)
    when_iso = when_dt.replace(microsecond=0).isoformat()
    mem_id = make_id()
    rel_path = md_rel_path(layer, mem_id, when_dt)
    body_md = f"# {summary}\n\n{body.strip()}\n"
    write_markdown(paths, rel_path, body_md)

    env = build_envelope(
        mem_id=mem_id,
        when_iso=when_iso,
        layer=layer,
        kind=kind,
        summary=summary,
        body_md_path=rel_path,
        tags=tags,
        refs=refs,
        cred_refs=cred_refs,
        tool=tool,
        account=account,
        device=device,
        session_id=session_id,
        project_id=project_id,
        workspace=workspace,
        importance=importance,
        confidence=confidence,
        stability=stability,
        reuse_count=reuse_count,
        volatility=volatility,
        content_sha256=sha256_text(body_md),
    )

    evt = {
        "event_id": make_id(),
        "event_type": event_type,
        "event_time": when_iso,
        "memory_id": mem_id,
        "payload": {
            "summary": summary,
            "layer": layer,
            "kind": kind,
            "body_md_path": rel_path,
            "envelope": env,
        },
    }

    append_jsonl(event_file_path(paths, when_dt), evt)

    with sqlite3.connect(paths.sqlite_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        insert_memory(conn, env, body_md)
        insert_event(conn, evt)
        conn.commit()

    return {"memory": env, "event": evt}


def find_memories(
    paths: MemoryPaths,
    schema_sql_path: Path,
    query: str,
    layer: str | None,
    limit: int,
    project_id: str = "",
) -> list[dict[str, Any]]:
    ensure_storage(paths, schema_sql_path)
    with sqlite3.connect(paths.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        if query:
            if layer:
                rows = conn.execute(
                    """
                    SELECT m.id, m.layer, m.kind, m.summary, m.updated_at, m.body_md_path,
                           COALESCE(json_extract(m.scope_json, '$.project_id'), '') AS project_id
                    FROM memories_fts f
                    JOIN memories m ON m.id = f.id
                    WHERE f.memories_fts MATCH ? AND m.layer = ?
                      AND (json_extract(m.scope_json, '$.project_id') = ? OR ? = '')
                    ORDER BY bm25(memories_fts), m.updated_at DESC
                    LIMIT ?
                    """,
                    (query, layer, project_id, project_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT m.id, m.layer, m.kind, m.summary, m.updated_at, m.body_md_path,
                           COALESCE(json_extract(m.scope_json, '$.project_id'), '') AS project_id
                    FROM memories_fts f
                    JOIN memories m ON m.id = f.id
                    WHERE f.memories_fts MATCH ?
                      AND (json_extract(m.scope_json, '$.project_id') = ? OR ? = '')
                    ORDER BY bm25(memories_fts), m.updated_at DESC
                    LIMIT ?
                    """,
                    (query, project_id, project_id, limit),
                ).fetchall()
        else:
            if layer:
                rows = conn.execute(
                    """
                    SELECT id, layer, kind, summary, updated_at, body_md_path,
                           COALESCE(json_extract(scope_json, '$.project_id'), '') AS project_id
                    FROM memories
                    WHERE layer = ? AND (json_extract(scope_json, '$.project_id') = ? OR ? = '')
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (layer, project_id, project_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, layer, kind, summary, updated_at, body_md_path,
                           COALESCE(json_extract(scope_json, '$.project_id'), '') AS project_id
                    FROM memories
                    WHERE (json_extract(scope_json, '$.project_id') = ? OR ? = '')
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (project_id, project_id, limit),
                ).fetchall()

    return [dict(r) for r in rows]


def build_brief(paths: MemoryPaths, schema_sql_path: Path, project_id: str, limit: int) -> dict[str, Any]:
    ensure_storage(paths, schema_sql_path)
    with sqlite3.connect(paths.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        recent = conn.execute(
            """
            SELECT id, layer, kind, summary, updated_at, body_md_path
            FROM memories
            WHERE json_extract(scope_json, '$.project_id') = ? OR ? = ''
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (project_id, project_id, limit),
        ).fetchall()

        checkpoints = conn.execute(
            """
            SELECT id, summary, updated_at
            FROM memories
            WHERE kind = 'checkpoint' AND (json_extract(scope_json, '$.project_id') = ? OR ? = '')
            ORDER BY updated_at DESC
            LIMIT 3
            """,
            (project_id, project_id),
        ).fetchall()

    return {
        "project_id": project_id,
        "recent": [dict(r) for r in recent],
        "checkpoints": [dict(r) for r in checkpoints],
    }


def verify_storage(paths: MemoryPaths, schema_sql_path: Path) -> dict[str, Any]:
    ensure_storage(paths, schema_sql_path)
    ensure_system_memory(paths, schema_sql_path)
    issues: list[str] = []

    with sqlite3.connect(paths.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        table_count = conn.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('table','view')").fetchone()[0]
        rows = conn.execute("SELECT id, body_md_path, integrity_json FROM memories ORDER BY updated_at DESC").fetchall()

        checked = 0
        for row in rows:
            checked += 1
            md_path = paths.markdown_root / row["body_md_path"]
            if not md_path.exists():
                issues.append(f"missing_markdown:{row['id']}:{row['body_md_path']}")
                continue

            data = md_path.read_text(encoding="utf-8")
            expected = json.loads(row["integrity_json"]).get("content_sha256", "")
            actual = sha256_text(data)
            if expected != actual:
                issues.append(f"hash_mismatch:{row['id']}")

    jsonl_count = 0
    bad_jsonl = 0
    for fp in sorted(paths.jsonl_root.glob("events-*.jsonl")):
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            jsonl_count += 1
            try:
                obj = json.loads(line)
                if obj.get("event_type") not in EVENT_SET:
                    bad_jsonl += 1
            except json.JSONDecodeError:
                bad_jsonl += 1

    if bad_jsonl:
        issues.append(f"jsonl_invalid_lines:{bad_jsonl}")

    result = {
        "ok": len(issues) == 0,
        "sqlite_table_view_count": table_count,
        "memory_rows_checked": checked,
        "jsonl_events_checked": jsonl_count,
        "issues": issues,
    }

    log_system_event(
        paths,
        schema_sql_path,
        "memory.verify",
        {
            "ok": result["ok"],
            "issues": issues,
            "memory_rows_checked": checked,
            "jsonl_events_checked": jsonl_count,
        },
    )

    return result


def _run_git(paths: MemoryPaths, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(paths.root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _ensure_git_repo(paths: MemoryPaths) -> None:
    if not (paths.root / ".git").exists():
        _run_git(paths, ["init"])


def _ensure_remote(paths: MemoryPaths, remote_name: str, remote_url: str | None) -> None:
    remotes = _run_git(paths, ["remote"]).stdout.split()
    if remote_url:
        if remote_name in remotes:
            _run_git(paths, ["remote", "set-url", remote_name, remote_url])
        else:
            _run_git(paths, ["remote", "add", remote_name, remote_url])


SYNC_MODES = {"noop", "git", "github-status", "github-push", "github-pull", "github-bootstrap"}
SYNC_ERROR_KINDS = {"auth", "network", "conflict", "unknown"}


def sync_git(
    paths: MemoryPaths,
    schema_sql_path: Path,
    mode: str,
    remote_name: str = "origin",
    branch: str = "main",
    remote_url: str | None = None,
    commit_message: str = "chore(memory): sync snapshot",
    log_event: bool = True,
) -> dict[str, Any]:
    if mode not in SYNC_MODES:
        raise ValueError("mode must be one of: noop, git, github-status, github-push, github-pull, github-bootstrap")

    ensure_system_memory(paths, schema_sql_path)
    if mode == "noop":
        message = "sync noop"
        ok = True
        detail = ""
    elif mode in {"git", "github-status"}:
        try:
            _ensure_git_repo(paths)
            proc = _run_git(paths, ["status", "--short"])
            message = "github status ok"
            ok = True
            detail = proc.stdout.strip()
        except Exception as exc:  # pragma: no cover
            message = f"github status failed ({exc})"
            ok = False
            detail = ""
    elif mode == "github-push":
        try:
            _ensure_git_repo(paths)
            _ensure_remote(paths, remote_name, remote_url)
            _run_git(paths, ["add", "-A"])
            commit_proc = subprocess.run(
                ["git", "-C", str(paths.root), "commit", "-m", commit_message],
                check=False,
                capture_output=True,
                text=True,
            )
            if commit_proc.returncode != 0 and "nothing to commit" not in commit_proc.stdout + commit_proc.stderr:
                raise RuntimeError(commit_proc.stderr.strip() or commit_proc.stdout.strip() or "git commit failed")
            if remote_url or remote_name in _run_git(paths, ["remote"]).stdout.split():
                _run_git(paths, ["push", "-u", remote_name, branch])
                message = "github push ok"
            else:
                message = "local commit ok; remote not configured"
            ok = True
            detail = _run_git(paths, ["status", "--short"]).stdout.strip()
        except Exception as exc:  # pragma: no cover
            message = f"github push failed ({exc})"
            ok = False
            detail = ""
    elif mode == "github-pull":
        try:
            _ensure_git_repo(paths)
            _ensure_remote(paths, remote_name, remote_url)
            _run_git(paths, ["fetch", remote_name, branch])
            _run_git(paths, ["pull", "--rebase", remote_name, branch])
            message = "github pull ok"
            ok = True
            detail = _run_git(paths, ["status", "--short"]).stdout.strip()
        except Exception as exc:  # pragma: no cover
            message = f"github pull failed ({exc})"
            ok = False
            detail = ""
    elif mode == "github-bootstrap":
        pull_out = sync_git(
            paths,
            schema_sql_path,
            "github-pull",
            remote_name=remote_name,
            branch=branch,
            remote_url=remote_url,
            commit_message=commit_message,
            log_event=False,
        )
        reindex_out = reindex_from_jsonl(paths, schema_sql_path, reset=True)
        push_out = sync_git(
            paths,
            schema_sql_path,
            "github-push",
            remote_name=remote_name,
            branch=branch,
            remote_url=remote_url,
            commit_message=commit_message,
            log_event=False,
        )
        ok = bool(pull_out.get("ok") and reindex_out.get("ok") and push_out.get("ok"))
        message = "github bootstrap ok" if ok else "github bootstrap finished with errors"
        detail = {"pull": pull_out, "reindex": reindex_out, "push": push_out}
    should_log_event = log_event
    if should_log_event:
        log_system_event(
            paths,
            schema_sql_path,
            "memory.sync",
            {"mode": mode, "ok": ok, "message": message, "remote_name": remote_name, "branch": branch},
        )

    out: dict[str, Any] = {"ok": ok, "mode": mode, "message": message}
    if mode in {"git", "github-status", "github-push", "github-pull", "github-bootstrap"}:
        out["detail"] = detail
    return out


def sync_placeholder(
    paths: MemoryPaths,
    schema_sql_path: Path,
    mode: str,
    remote_name: str = "origin",
    branch: str = "main",
    remote_url: str | None = None,
    commit_message: str = "chore(memory): sync snapshot",
    log_event: bool = True,
) -> dict[str, Any]:
    # Backward-compatible alias for older callers/docs.
    return sync_git(
        paths=paths,
        schema_sql_path=schema_sql_path,
        mode=mode,
        remote_name=remote_name,
        branch=branch,
        remote_url=remote_url,
        commit_message=commit_message,
        log_event=log_event,
    )


def latest_content_mtime(paths: MemoryPaths) -> float:
    latest = 0.0
    for root in [paths.markdown_root, paths.jsonl_root]:
        if not root.exists():
            continue
        for base, _, files in os.walk(root):
            for name in files:
                p = Path(base) / name
                try:
                    mt = p.stat().st_mtime
                except FileNotFoundError:
                    continue
                if mt > latest:
                    latest = mt
    return latest


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
    scan_interval: int,
    pull_interval: int,
    retry_max_attempts: int = 3,
    retry_initial_backoff: int = 1,
    retry_max_backoff: int = 8,
    once: bool = False,
) -> dict[str, Any]:
    ensure_storage(paths, schema_sql_path)
    ensure_system_memory(paths, schema_sql_path)
    last_seen = latest_content_mtime(paths)
    last_pull = 0.0
    cycles = 0
    pull_failures = 0
    push_failures = 0
    reindex_failures = 0
    last_pull_result: dict[str, Any] = {}
    last_push_result: dict[str, Any] = {}
    last_reindex_result: dict[str, Any] = {}
    last_error_kind = "none"

    while True:
        cycles += 1
        now = time.time()

        if now - last_pull >= pull_interval:
            last_pull_result = run_sync_with_retry(
                runner=sync_git,
                paths=paths,
                schema_sql_path=schema_sql_path,
                mode="github-pull",
                remote_name=remote_name,
                branch=branch,
                remote_url=remote_url,
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
                pull_failures += 1
                last_error_kind = str(last_pull_result.get("error_kind", "unknown"))
            last_pull = now
            last_seen = latest_content_mtime(paths)

        current_seen = latest_content_mtime(paths)
        if current_seen > last_seen:
            last_push_result = run_sync_with_retry(
                runner=sync_git,
                paths=paths,
                schema_sql_path=schema_sql_path,
                mode="github-push",
                remote_name=remote_name,
                branch=branch,
                remote_url=remote_url,
                max_attempts=retry_max_attempts,
                initial_backoff=retry_initial_backoff,
                max_backoff=retry_max_backoff,
            )
            if not last_push_result.get("ok"):
                push_failures += 1
                last_error_kind = str(last_push_result.get("error_kind", "unknown"))
            last_seen = current_seen

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
        "last_error_kind": last_error_kind,
        "remediation_hint": sync_error_hint(last_error_kind),
        "retry": {
            "max_attempts": max(1, int(retry_max_attempts)),
            "initial_backoff": max(1, int(retry_initial_backoff)),
            "max_backoff": max(1, int(retry_max_backoff)),
        },
    }
    log_system_event(paths, schema_sql_path, "memory.sync", {"daemon": result})
    return result
