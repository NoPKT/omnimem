from __future__ import annotations

from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover
    import fcntl  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

SCHEMA_VERSION = "0.1.0"
LAYER_SET = {"instant", "short", "long", "archive"}
# Keep KIND_SET permissive for internal instrumentation (e.g. retrieve traces) while
# still validating obvious typos.
KIND_SET = {"note", "decision", "task", "checkpoint", "summary", "evidence", "retrieve"}
EVENT_SET = {
    "memory.write",
    "memory.update",
    "memory.checkpoint",
    "memory.promote",
    "memory.verify",
    "memory.sync",
    "memory.retrieve",
    "memory.reuse",
    "memory.decay",
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


@contextmanager
def repo_lock(root: Path, timeout_s: float = 12.0):
    """
    Cross-process advisory lock for a single OmniMem home.

    This prevents two processes (WebUI/daemon/CLI) from mutating JSONL/SQLite/Git state
    concurrently, which is a common source of sync conflicts and corrupted indexes.
    """
    key = str(root.expanduser().resolve())
    depth = _REPO_LOCK_DEPTH.get(key, 0)
    if depth > 0:
        _REPO_LOCK_DEPTH[key] = depth + 1
        try:
            yield
        finally:
            _REPO_LOCK_DEPTH[key] = max(0, _REPO_LOCK_DEPTH.get(key, 1) - 1)
        return
    lock_path = root / "runtime" / "omnimem.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:  # pragma: no cover
        yield
        return
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    start = time.time()
    try:
        _REPO_LOCK_DEPTH[key] = 1
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if (time.time() - start) >= timeout_s:
                    raise TimeoutError(
                        f"omnimem home is busy (lock: {lock_path}); stop other omnimem processes (webui/daemon) and retry"
                    )
                time.sleep(0.12)
        yield
    finally:
        _REPO_LOCK_DEPTH[key] = 0
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


_REPO_LOCK_DEPTH: dict[str, int] = {}

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

    def has_schema(conn: sqlite3.Connection) -> bool:
        rows = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type IN ('table','view','trigger')
              AND name IN ('memories','memory_refs','memory_events','memories_fts','memories_ai','memories_ad','memories_au')
            """
        ).fetchall()
        names = {r[0] for r in rows}
        required = {"memories", "memory_refs", "memory_events", "memories_fts"}
        return required.issubset(names)

    schema_sql = schema_sql_path.read_text(encoding="utf-8")
    # Avoid re-applying DDL on every call. This also reduces cross-process startup races
    # when WebUI and CLI hit ensure_storage concurrently.
    for attempt in range(2):
        try:
            with sqlite3.connect(paths.sqlite_path, timeout=2.0) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("PRAGMA busy_timeout = 1500")
                try:
                    conn.execute("PRAGMA journal_mode = WAL")
                except sqlite3.OperationalError:
                    # Some environments/filesystems may not support WAL; keep default.
                    pass
                if not has_schema(conn):
                    conn.executescript(schema_sql)
            break
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if attempt == 0 and ("cannot start a transaction within a transaction" in msg or "database is locked" in msg):
                time.sleep(0.2)
                continue
            raise

    with sqlite3.connect(paths.sqlite_path, timeout=2.0) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 1500")
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            pass
        _maybe_migrate_memories_table(conn)
        _maybe_repair_fk_targets(conn)


def _memories_table_sql(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='memories'"
    ).fetchone()
    return str(row[0] or "") if row else ""


def _maybe_migrate_memories_table(conn: sqlite3.Connection) -> None:
    """Migrate memories table when DB-level CHECK constraints lag behind app kinds.

    This is needed because schema.sql uses CREATE TABLE IF NOT EXISTS, so older installs may
    keep stricter CHECK constraints that reject new kinds (e.g. 'retrieve').
    """
    sql = _memories_table_sql(conn)
    if not sql:
        return
    if "CHECK" in sql and "'retrieve'" not in sql:
        _rebuild_memories_table(conn)


def _table_sql(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return str(row[0] or "") if row else ""


def _maybe_repair_fk_targets(conn: sqlite3.Connection) -> None:
    """Repair legacy DBs whose FK constraints reference the transient "memories_old" table."""
    refs_sql = _table_sql(conn, "memory_refs")
    ev_sql = _table_sql(conn, "memory_events")
    if "memories_old" not in (refs_sql + ev_sql):
        return
    _rebuild_child_tables(conn)


def _rebuild_child_tables(conn: sqlite3.Connection) -> None:
    """Recreate child tables so their foreign keys reference the current `memories` table."""
    needs_txn = not conn.in_transaction
    conn.execute("PRAGMA foreign_keys = OFF")
    if needs_txn:
        conn.execute("BEGIN")
    try:
        conn.execute("DROP INDEX IF EXISTS idx_memory_refs_memory_id")
        conn.execute("DROP INDEX IF EXISTS idx_memory_refs_target")
        conn.execute("DROP INDEX IF EXISTS idx_memory_events_type_time")

        conn.execute("ALTER TABLE memory_refs RENAME TO memory_refs_old")
        conn.execute("ALTER TABLE memory_events RENAME TO memory_events_old")

        conn.execute(
            """
            CREATE TABLE memory_refs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              memory_id TEXT NOT NULL,
              ref_type TEXT NOT NULL,
              target TEXT NOT NULL,
              note TEXT,
              FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE memory_events (
              event_id TEXT PRIMARY KEY,
              event_type TEXT NOT NULL,
              event_time TEXT NOT NULL,
              memory_id TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
            )
            """
        )

        # Preserve existing ids / event ids.
        conn.execute(
            """
            INSERT INTO memory_refs(id, memory_id, ref_type, target, note)
            SELECT id, memory_id, ref_type, target, note FROM memory_refs_old
            """
        )
        conn.execute(
            """
            INSERT INTO memory_events(event_id, event_type, event_time, memory_id, payload_json)
            SELECT event_id, event_type, event_time, memory_id, payload_json FROM memory_events_old
            """
        )

        conn.execute("DROP TABLE memory_refs_old")
        conn.execute("DROP TABLE memory_events_old")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_refs_memory_id ON memory_refs(memory_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_refs_target ON memory_refs(target)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_type_time ON memory_events(event_type, event_time)")
        if needs_txn:
            conn.execute("COMMIT")
    except Exception:
        if needs_txn:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _rebuild_memories_table(conn: sqlite3.Connection) -> None:
    # Keep this DDL in sync with db/schema.sql columns and indexes.
    kinds = ", ".join([f"'{k}'" for k in sorted(KIND_SET)])
    layers = ", ".join([f"'{l}'" for l in sorted(LAYER_SET)])
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN")
    try:
        conn.execute("DROP TRIGGER IF EXISTS memories_ai")
        conn.execute("DROP TRIGGER IF EXISTS memories_ad")
        conn.execute("DROP TRIGGER IF EXISTS memories_au")
        conn.execute("DROP INDEX IF EXISTS idx_memories_layer")
        conn.execute("DROP INDEX IF EXISTS idx_memories_kind")
        conn.execute("DROP INDEX IF EXISTS idx_memories_updated_at")
        conn.execute("DROP INDEX IF EXISTS idx_memories_importance")
        conn.execute("DROP INDEX IF EXISTS idx_memories_reuse_count")

        conn.execute("ALTER TABLE memories RENAME TO memories_old")
        conn.execute(
            f"""
            CREATE TABLE memories (
              id TEXT PRIMARY KEY,
              schema_version TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              layer TEXT NOT NULL CHECK (layer IN ({layers})),
              kind TEXT NOT NULL CHECK (kind IN ({kinds})),
              summary TEXT NOT NULL,
              body_md_path TEXT NOT NULL,
              body_text TEXT NOT NULL DEFAULT '',
              tags_json TEXT NOT NULL DEFAULT '[]',
              importance_score REAL NOT NULL DEFAULT 0.5 CHECK (importance_score >= 0 AND importance_score <= 1),
              confidence_score REAL NOT NULL DEFAULT 0.5 CHECK (confidence_score >= 0 AND confidence_score <= 1),
              stability_score REAL NOT NULL DEFAULT 0.5 CHECK (stability_score >= 0 AND stability_score <= 1),
              reuse_count INTEGER NOT NULL DEFAULT 0 CHECK (reuse_count >= 0),
              volatility_score REAL NOT NULL DEFAULT 0.5 CHECK (volatility_score >= 0 AND volatility_score <= 1),
              cred_refs_json TEXT NOT NULL DEFAULT '[]',
              source_json TEXT NOT NULL,
              scope_json TEXT NOT NULL,
              integrity_json TEXT NOT NULL
            )
            """
        )
        cols = (
            "id,schema_version,created_at,updated_at,layer,kind,summary,body_md_path,body_text,"
            "tags_json,importance_score,confidence_score,stability_score,reuse_count,volatility_score,"
            "cred_refs_json,source_json,scope_json,integrity_json"
        )
        conn.execute(f"INSERT INTO memories({cols}) SELECT {cols} FROM memories_old")
        # memory_refs/memory_events foreign keys are rewritten by SQLite to reference memories_old
        # after the rename; rebuild them so they reference the new `memories` table.
        _rebuild_child_tables(conn)
        conn.execute("DROP TABLE memories_old")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_layer ON memories(layer)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories(updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance_score)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_reuse_count ON memories(reuse_count)")

        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories
            BEGIN
              INSERT INTO memories_fts(id, summary, body_text, tags)
              VALUES (new.id, new.summary, new.body_text, new.tags_json);
            END;
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories
            BEGIN
              DELETE FROM memories_fts WHERE id = old.id;
            END;
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories
            BEGIN
              DELETE FROM memories_fts WHERE id = old.id;
              INSERT INTO memories_fts(id, summary, body_text, tags)
              VALUES (new.id, new.summary, new.body_text, new.tags_json);
            END;
            """
        )
        # Rebuild FTS table to be safe.
        conn.execute("DELETE FROM memories_fts")
        conn.execute(
            "INSERT INTO memories_fts(id, summary, body_text, tags) SELECT id, summary, body_text, tags_json FROM memories"
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


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


def bump_reuse_counts(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    ids: list[str],
    delta: int = 1,
    tool: str = "omnimem",
    session_id: str = "session-local",
    project_id: str = "",
) -> dict[str, Any]:
    """Increment reuse_count for a set of memories.

    Intended to be called when memories are retrieved/used, so governance has a concrete reuse signal.
    """
    ensure_storage(paths, schema_sql_path)
    if not ids:
        return {"ok": True, "updated": 0}
    delta = int(delta)
    if delta <= 0:
        return {"ok": True, "updated": 0}
    when = utc_now()
    try:
        with sqlite3.connect(paths.sqlite_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            n = 0
            for mid in ids:
                # Reuse should gently increase stability/confidence and reduce volatility.
                cur = conn.execute(
                    """
                    UPDATE memories
                    SET reuse_count = reuse_count + ?,
                        stability_score = min(1.0, stability_score + (0.03 * ?)),
                        confidence_score = min(1.0, confidence_score + (0.01 * ?)),
                        volatility_score = max(0.0, volatility_score - (0.02 * ?)),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (delta, delta, delta, delta, when, mid),
                )
                n += int(cur.rowcount or 0)
            conn.commit()
        log_system_event(
            paths,
            schema_sql_path,
            "memory.reuse",
            {"tool": tool, "session_id": session_id, "project_id": project_id, "delta": delta, "count": n},
        )
        return {"ok": True, "updated": n}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc), "updated": 0}


def apply_decay(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    days: int = 14,
    limit: int = 200,
    project_id: str = "",
    layers: list[str] | None = None,
    dry_run: bool = True,
    tool: str = "omnimem",
    session_id: str = "system",
) -> dict[str, Any]:
    """Apply time-based signal decay for stale memories.

    Decay targets "recent working sets" more than cold archive, and is dampened by reuse_count.
    We avoid changing updated_at; instead we store last_decay_at in integrity_json to prevent
    repeated decay in short intervals.
    """
    ensure_storage(paths, schema_sql_path)
    days = max(1, int(days))
    limit = max(1, min(2000, int(limit)))
    if layers is None:
        layers = ["instant", "short", "long"]
    layers = [x for x in (str(l).strip() for l in layers) if x]
    for l in layers:
        if l not in LAYER_SET:
            raise ValueError(f"invalid layer: {l}")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    cutoff = (now - timedelta(days=days)).isoformat()
    placeholders = ",".join(["?"] * len(layers))

    with sqlite3.connect(paths.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT id, layer, kind, summary, updated_at,
                   importance_score, confidence_score, stability_score, reuse_count, volatility_score,
                   integrity_json,
                   COALESCE(json_extract(scope_json, '$.project_id'), '') AS project_id
            FROM memories
            WHERE layer IN ({placeholders})
              AND (json_extract(scope_json, '$.project_id') = ? OR ? = '')
              AND COALESCE(json_extract(integrity_json, '$.last_decay_at'), updated_at) < ?
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (*layers, project_id, project_id, cutoff, limit),
        ).fetchall()

        changes: list[dict[str, Any]] = []
        moved = 0
        for r in rows:
            try:
                updated_at = datetime.fromisoformat(str(r["updated_at"]))
            except Exception:
                continue
            age_days = max(0, int((now - updated_at).total_seconds() // 86400))
            if age_days < days:
                continue
            reuse = int(r["reuse_count"] or 0)
            # Decay strength increases with age, but dampens with reuse.
            age_factor = min(1.0, (age_days - days) / 30.0)
            damp = 1.0 / (1.0 + (reuse / 6.0))
            strength = age_factor * damp

            old = {
                "confidence": float(r["confidence_score"]),
                "stability": float(r["stability_score"]),
                "volatility": float(r["volatility_score"]),
            }
            new_conf = max(0.0, min(1.0, old["confidence"] - (0.02 * strength)))
            new_stab = max(0.0, min(1.0, old["stability"] - (0.03 * strength)))
            new_vol = max(0.0, min(1.0, old["volatility"] + (0.02 * strength)))

            if (
                abs(new_conf - old["confidence"]) < 1e-6
                and abs(new_stab - old["stability"]) < 1e-6
                and abs(new_vol - old["volatility"]) < 1e-6
            ):
                continue

            integrity = {}
            try:
                integrity = json.loads(r["integrity_json"] or "{}")
            except Exception:
                integrity = {}
            integrity["last_decay_at"] = now.isoformat()

            change = {
                "id": r["id"],
                "layer": r["layer"],
                "kind": r["kind"],
                "project_id": r["project_id"],
                "updated_at": r["updated_at"],
                "age_days": age_days,
                "reuse_count": reuse,
                "old": old,
                "new": {"confidence": new_conf, "stability": new_stab, "volatility": new_vol},
            }
            changes.append(change)

            if not dry_run:
                conn.execute(
                    """
                    UPDATE memories
                    SET confidence_score = ?,
                        stability_score = ?,
                        volatility_score = ?,
                        integrity_json = ?
                    WHERE id = ?
                    """,
                    (new_conf, new_stab, new_vol, json.dumps(integrity, ensure_ascii=False), r["id"]),
                )
                moved += 1

        if not dry_run:
            conn.commit()

    if not dry_run and changes:
        log_system_event(
            paths,
            schema_sql_path,
            "memory.decay",
            {
                "tool": tool,
                "session_id": session_id,
                "project_id": project_id,
                "days": days,
                "layers": layers,
                "changed": len(changes),
                "applied": moved,
                "sample": changes[:20],
            },
        )

    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "project_id": project_id,
        "days": days,
        "layers": layers,
        "count": len(changes),
        "items": changes,
    }


def insert_event(conn: sqlite3.Connection, evt: dict[str, Any]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO memory_events(event_id, event_type, event_time, memory_id, payload_json) VALUES (?, ?, ?, ?, ?)",
        (evt["event_id"], evt["event_type"], evt["event_time"], evt["memory_id"], json.dumps(evt["payload"], ensure_ascii=False)),
    )


def log_system_event(
    paths: MemoryPaths,
    schema_sql_path: Path,
    event_type: str,
    payload: dict[str, Any],
    *,
    portable: bool = True,
) -> None:
    with repo_lock(paths.root, timeout_s=30.0):
        system_id = ensure_system_memory(paths, schema_sql_path)
        evt = {
            "event_id": make_id(),
            "event_type": event_type,
            "event_time": utc_now(),
            "memory_id": system_id,
            "payload": payload,
        }
        # Most events are portable and are stored in JSONL so a device can rebuild its index from Git.
        # Some operational events (notably sync) are device-local and create unnecessary Git churn/conflicts.
        if portable:
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
    if event_type not in EVENT_SET:
        raise ValueError(f"invalid event_type: {event_type}")

    with repo_lock(paths.root, timeout_s=30.0):
        ensure_storage(paths, schema_sql_path)
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


def move_memory_layer(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    memory_id: str,
    new_layer: str,
    tool: str = "cli",
    account: str = "default",
    device: str = "local",
    session_id: str = "session-local",
    event_type: str = "memory.promote",
) -> dict[str, Any]:
    """
    Promote/demote an existing memory by moving it to a different layer.

    This updates:
    - Markdown path (moves file to the new layer directory)
    - SQLite row (layer, updated_at, body_md_path)
    - JSONL + SQLite event log (memory.promote)
    """
    if new_layer not in LAYER_SET:
        raise ValueError(f"invalid layer: {new_layer}")
    if event_type not in EVENT_SET:
        raise ValueError(f"invalid event_type: {event_type}")

    with repo_lock(paths.root, timeout_s=30.0):
        ensure_storage(paths, schema_sql_path)
        when_dt = datetime.now(timezone.utc)
        when_iso = when_dt.replace(microsecond=0).isoformat()

        with sqlite3.connect(paths.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            row = conn.execute(
                """
                SELECT id, schema_version, created_at, updated_at, layer, kind, summary, body_md_path, body_text,
                       tags_json, importance_score, confidence_score, stability_score, reuse_count, volatility_score,
                       cred_refs_json, source_json, scope_json, integrity_json
                FROM memories
                WHERE id = ?
                """,
                (memory_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"memory not found: {memory_id}")

            old_layer = str(row["layer"])
            if old_layer == new_layer:
                return {"ok": True, "memory_id": memory_id, "from_layer": old_layer, "to_layer": new_layer, "changed": False}

            old_rel = str(row["body_md_path"])
            old_md = paths.markdown_root / old_rel
            if not old_md.exists():
                raise FileNotFoundError(f"markdown not found: {old_rel}")

            body_md = old_md.read_text(encoding="utf-8")
            new_rel = md_rel_path(new_layer, memory_id, when_dt)
            new_md = paths.markdown_root / new_rel
            new_md.parent.mkdir(parents=True, exist_ok=True)
            new_md.write_text(body_md, encoding="utf-8")
            old_md.unlink(missing_ok=True)

            # Keep created_at stable; only update updated_at, layer, and path.
            conn.execute(
                "UPDATE memories SET layer = ?, updated_at = ?, body_md_path = ? WHERE id = ?",
                (new_layer, when_iso, new_rel, memory_id),
            )

            refs = conn.execute(
                "SELECT ref_type, target, note FROM memory_refs WHERE memory_id = ? ORDER BY id",
                (memory_id,),
            ).fetchall()

            tags = json.loads(row["tags_json"] or "[]")
            cred_refs = json.loads(row["cred_refs_json"] or "[]")
            scope = json.loads(row["scope_json"] or "{}")
            integrity = json.loads(row["integrity_json"] or "{}")
            # Recompute hash after move to be defensive (content should be identical).
            integrity["content_sha256"] = sha256_text(body_md)

            env = {
                "id": memory_id,
                "schema_version": str(row["schema_version"]),
                "created_at": str(row["created_at"]),
                "updated_at": when_iso,
                "layer": new_layer,
                "kind": str(row["kind"]),
                "summary": str(row["summary"]),
                "body_md_path": new_rel,
                "tags": tags,
                "refs": [{"type": r["ref_type"], "target": r["target"], "note": r["note"]} for r in refs],
                "signals": {
                    "importance_score": float(row["importance_score"]),
                    "confidence_score": float(row["confidence_score"]),
                    "stability_score": float(row["stability_score"]),
                    "reuse_count": int(row["reuse_count"]),
                    "volatility_score": float(row["volatility_score"]),
                },
                "cred_refs": cred_refs,
                # Preserve scope; source points to the actor performing the move.
                "source": {
                    "tool": tool,
                    "account": account,
                    "device": device,
                    "session_id": session_id,
                },
                "scope": scope,
                "integrity": integrity,
            }

            evt = {
                "event_id": make_id(),
                "event_type": event_type,
                "event_time": when_iso,
                "memory_id": memory_id,
                "payload": {
                    "from_layer": old_layer,
                    "to_layer": new_layer,
                    "old_body_md_path": old_rel,
                    "new_body_md_path": new_rel,
                    "envelope": env,
                },
            }

            append_jsonl(event_file_path(paths, when_dt), evt)
            insert_event(conn, evt)
            conn.commit()

    return {
        "ok": True,
        "memory_id": memory_id,
        "from_layer": old_layer,
        "to_layer": new_layer,
        "old_body_md_path": old_rel,
        "new_body_md_path": new_rel,
        "changed": True,
    }


def update_memory_content(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    memory_id: str,
    summary: str,
    body: str,
    tags: list[str] | None = None,
    tool: str = "cli",
    account: str = "default",
    device: str = "local",
    session_id: str = "session-local",
    event_type: str = "memory.update",
) -> dict[str, Any]:
    """
    Edit an existing memory in-place.

    This updates:
    - Markdown body (rewritten as `# {summary}\n\n{body}\n`)
    - SQLite row (summary, updated_at, body_text, tags_json, integrity_json)
    - JSONL + SQLite event log (memory.update)

    It intentionally preserves `created_at`, `layer`, `kind`, and the original `source_json`/`scope_json`
    to keep provenance stable; the actor performing the edit is recorded in the update event payload.
    """
    if event_type not in EVENT_SET:
        raise ValueError(f"invalid event_type: {event_type}")

    with repo_lock(paths.root, timeout_s=30.0):
        ensure_storage(paths, schema_sql_path)
        when_dt = datetime.now(timezone.utc)
        when_iso = when_dt.replace(microsecond=0).isoformat()
        summary = str(summary or "").strip()
        if not summary:
            raise ValueError("summary must be non-empty")
        body = str(body or "").strip()
        tags = [str(x).strip() for x in (tags or []) if str(x).strip()]

        with sqlite3.connect(paths.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            row = conn.execute(
                """
                SELECT id, schema_version, created_at, updated_at, layer, kind, summary, body_md_path, body_text,
                       tags_json, importance_score, confidence_score, stability_score, reuse_count, volatility_score,
                       cred_refs_json, source_json, scope_json, integrity_json
                FROM memories
                WHERE id = ?
                """,
                (memory_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"memory not found: {memory_id}")

            rel = str(row["body_md_path"])
            md_path = paths.markdown_root / rel
            if not md_path.exists():
                raise FileNotFoundError(f"markdown not found: {rel}")

            body_md = f"# {summary}\n\n{body}\n"
            md_path.write_text(body_md, encoding="utf-8")

            integrity = json.loads(row["integrity_json"] or "{}")
            integrity["content_sha256"] = sha256_text(body_md)
            integrity["last_edit_at"] = when_iso

            conn.execute(
                """
                UPDATE memories
                SET summary = ?,
                    updated_at = ?,
                    body_text = ?,
                    tags_json = ?,
                    integrity_json = ?
                WHERE id = ?
                """,
                (
                    summary,
                    when_iso,
                    body_md,
                    json.dumps(tags, ensure_ascii=False),
                    json.dumps(integrity, ensure_ascii=False),
                    memory_id,
                ),
            )

            refs = conn.execute(
                "SELECT ref_type, target, note FROM memory_refs WHERE memory_id = ? ORDER BY id",
                (memory_id,),
            ).fetchall()

            cred_refs = json.loads(row["cred_refs_json"] or "[]")
            scope = json.loads(row["scope_json"] or "{}")
            source = json.loads(row["source_json"] or "{}")

            env = {
                "id": memory_id,
                "schema_version": str(row["schema_version"]),
                "created_at": str(row["created_at"]),
                "updated_at": when_iso,
                "layer": str(row["layer"]),
                "kind": str(row["kind"]),
                "summary": summary,
                "body_md_path": rel,
                "tags": tags,
                "refs": [{"type": r["ref_type"], "target": r["target"], "note": r["note"]} for r in refs],
                "signals": {
                    "importance_score": float(row["importance_score"]),
                    "confidence_score": float(row["confidence_score"]),
                    "stability_score": float(row["stability_score"]),
                    "reuse_count": int(row["reuse_count"]),
                    "volatility_score": float(row["volatility_score"]),
                },
                "cred_refs": cred_refs,
                "source": source,
                "scope": scope,
                "integrity": integrity,
            }

            evt = {
                "event_id": make_id(),
                "event_type": event_type,
                "event_time": when_iso,
                "memory_id": memory_id,
                "payload": {
                    "summary": summary,
                    "tags": tags,
                    "body_md_path": rel,
                    "actor": {"tool": tool, "account": account, "device": device, "session_id": session_id},
                    "envelope": env,
                },
            }

            append_jsonl(event_file_path(paths, when_dt), evt)
            insert_event(conn, evt)
            conn.commit()

        return {"ok": True, "memory_id": memory_id, "updated_at": when_iso, "body_md_path": rel}


def find_memories(
    paths: MemoryPaths,
    schema_sql_path: Path,
    query: str,
    layer: str | None,
    limit: int,
    project_id: str = "",
    session_id: str = "",
) -> list[dict[str, Any]]:
    res = find_memories_ex(
        paths=paths,
        schema_sql_path=schema_sql_path,
        query=query,
        layer=layer,
        limit=limit,
        project_id=project_id,
        session_id=session_id,
    )
    return list(res.get("items") or [])


def _normalize_fts_query(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    # Replace punctuation (including dots in versions) with spaces so FTS doesn't error.
    s = re.sub(r"[^\w\u4e00-\u9fff]+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _query_tokens(raw: str, *, max_tokens: int = 12) -> list[str]:
    s = str(raw or "")
    toks = re.findall(r"[\w]+|[\u4e00-\u9fff]+", s, flags=re.UNICODE)
    out: list[str] = []
    for t in toks:
        tt = t.strip()
        if not tt:
            continue
        if tt.upper() in {"AND", "OR", "NOT"}:
            continue
        out.append(tt)
        if len(out) >= max_tokens:
            break
    return out


def _signals_from_row(d: dict[str, Any]) -> dict[str, Any]:
    d["signals"] = {
        "importance_score": float(d.pop("importance_score", 0.0) or 0.0),
        "confidence_score": float(d.pop("confidence_score", 0.0) or 0.0),
        "stability_score": float(d.pop("stability_score", 0.0) or 0.0),
        "reuse_count": int(d.pop("reuse_count", 0) or 0),
        "volatility_score": float(d.pop("volatility_score", 0.0) or 0.0),
    }
    return d


def _fts_rows(
    conn: sqlite3.Connection,
    *,
    match_query: str,
    layer: str | None,
    limit: int,
    project_id: str,
    session_id: str,
) -> list[sqlite3.Row]:
    if layer:
        return conn.execute(
            """
            SELECT m.id, m.layer, m.kind, m.summary, m.updated_at, m.body_md_path,
                   COALESCE(json_extract(m.scope_json, '$.project_id'), '') AS project_id,
                   COALESCE(json_extract(m.source_json, '$.session_id'), '') AS session_id,
                   m.importance_score, m.confidence_score, m.stability_score, m.reuse_count, m.volatility_score
            FROM memories_fts f
            JOIN memories m ON m.id = f.id
            WHERE f.memories_fts MATCH ? AND m.layer = ?
              AND (json_extract(m.scope_json, '$.project_id') = ? OR ? = '')
              AND (COALESCE(json_extract(m.source_json, '$.session_id'), '') = ? OR ? = '')
            ORDER BY bm25(memories_fts), m.updated_at DESC
            LIMIT ?
            """,
            (match_query, layer, project_id, project_id, session_id, session_id, limit),
        ).fetchall()
    return conn.execute(
        """
        SELECT m.id, m.layer, m.kind, m.summary, m.updated_at, m.body_md_path,
               COALESCE(json_extract(m.scope_json, '$.project_id'), '') AS project_id,
               COALESCE(json_extract(m.source_json, '$.session_id'), '') AS session_id,
               m.importance_score, m.confidence_score, m.stability_score, m.reuse_count, m.volatility_score
        FROM memories_fts f
        JOIN memories m ON m.id = f.id
        WHERE f.memories_fts MATCH ?
          AND (json_extract(m.scope_json, '$.project_id') = ? OR ? = '')
          AND (COALESCE(json_extract(m.source_json, '$.session_id'), '') = ? OR ? = '')
        ORDER BY bm25(memories_fts), m.updated_at DESC
        LIMIT ?
        """,
        (match_query, project_id, project_id, session_id, session_id, limit),
    ).fetchall()


def _like_rows(
    conn: sqlite3.Connection,
    *,
    tokens: list[str],
    layer: str | None,
    limit: int,
    project_id: str,
    session_id: str,
) -> list[sqlite3.Row]:
    if not tokens:
        return []
    clauses: list[str] = []
    args: list[Any] = []
    for t in tokens[:12]:
        clauses.append("(summary LIKE ? OR body_text LIKE ?)")
        pat = f"%{t}%"
        args.extend([pat, pat])
    where_tokens = " OR ".join(clauses)
    sql = f"""
        SELECT id, layer, kind, summary, updated_at, body_md_path,
               COALESCE(json_extract(scope_json, '$.project_id'), '') AS project_id,
               COALESCE(json_extract(source_json, '$.session_id'), '') AS session_id,
               importance_score, confidence_score, stability_score, reuse_count, volatility_score
        FROM memories
        WHERE ({where_tokens})
          AND (json_extract(scope_json, '$.project_id') = ? OR ? = '')
          AND (COALESCE(json_extract(source_json, '$.session_id'), '') = ? OR ? = '')
    """
    args.extend([project_id, project_id, session_id, session_id])
    if layer:
        sql += " AND layer = ?"
        args.append(layer)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    args.append(limit)
    return conn.execute(sql, tuple(args)).fetchall()


def find_memories_ex(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    query: str,
    layer: str | None,
    limit: int,
    project_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    ensure_storage(paths, schema_sql_path)
    query = str(query or "").strip()
    limit = max(1, min(200, int(limit)))
    tried: list[dict[str, str]] = []

    with sqlite3.connect(paths.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row

        if not query:
            if layer:
                rows = conn.execute(
                    """
                    SELECT id, layer, kind, summary, updated_at, body_md_path,
                           COALESCE(json_extract(scope_json, '$.project_id'), '') AS project_id,
                           COALESCE(json_extract(source_json, '$.session_id'), '') AS session_id,
                           importance_score, confidence_score, stability_score, reuse_count, volatility_score
                    FROM memories
                    WHERE layer = ? AND (json_extract(scope_json, '$.project_id') = ? OR ? = '')
                      AND (COALESCE(json_extract(source_json, '$.session_id'), '') = ? OR ? = '')
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (layer, project_id, project_id, session_id, session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, layer, kind, summary, updated_at, body_md_path,
                           COALESCE(json_extract(scope_json, '$.project_id'), '') AS project_id,
                           COALESCE(json_extract(source_json, '$.session_id'), '') AS session_id,
                           importance_score, confidence_score, stability_score, reuse_count, volatility_score
                    FROM memories
                    WHERE (json_extract(scope_json, '$.project_id') = ? OR ? = '')
                      AND (COALESCE(json_extract(source_json, '$.session_id'), '') = ? OR ? = '')
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (project_id, project_id, session_id, session_id, limit),
                ).fetchall()
            items = [_signals_from_row(dict(r)) for r in rows]
            return {"ok": True, "strategy": "recent", "query_used": "", "tried": tried, "items": items}

        tokens = _query_tokens(query)
        normalized = _normalize_fts_query(query)
        candidates: list[tuple[str, str]] = [("fts_raw", query)]
        if normalized and normalized != query:
            candidates.append(("fts_normalized", normalized))
        if tokens:
            candidates.append(("fts_or", " OR ".join(tokens)))
            pref = [t + "*" for t in tokens if len(t) >= 3]
            if pref:
                candidates.append(("fts_or_prefix", " OR ".join(pref)))

        for strat, q in candidates:
            qq = str(q or "").strip()
            if not qq:
                continue
            tried.append({"strategy": strat, "query_used": qq})
            try:
                rows = _fts_rows(conn, match_query=qq, layer=layer, limit=limit, project_id=project_id, session_id=session_id)
            except sqlite3.OperationalError:
                continue
            if rows:
                items = [_signals_from_row(dict(r)) for r in rows]
                return {"ok": True, "strategy": strat, "query_used": qq, "tried": tried, "items": items}

        # Resilient fallback.
        ltoks = tokens or _query_tokens(normalized)
        tried.append({"strategy": "like_fallback", "query_used": " OR ".join(ltoks)})
        rows2 = _like_rows(conn, tokens=ltoks, layer=layer, limit=limit, project_id=project_id, session_id=session_id)
        items2 = [_signals_from_row(dict(r)) for r in rows2]
        return {"ok": True, "strategy": "like_fallback", "query_used": " OR ".join(ltoks), "tried": tried, "items": items2}


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


def _run_git(
    paths: MemoryPaths,
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(paths.root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        cmd = "git -C " + str(paths.root) + " " + " ".join(args)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        msg = f"{cmd} failed (exit {proc.returncode})"
        if out:
            msg += f"\nstdout:\n{out}"
        if err:
            msg += f"\nstderr:\n{err}"
        raise RuntimeError(msg)
    return proc


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


def _git_has_head(paths: MemoryPaths) -> bool:
    proc = _run_git(paths, ["rev-parse", "--verify", "HEAD"], check=False)
    return proc.returncode == 0


def _git_unmerged_paths(paths: MemoryPaths) -> list[str]:
    proc = _run_git(paths, ["diff", "--name-only", "--diff-filter=U"], check=False)
    items = [x.strip() for x in (proc.stdout or "").splitlines() if x.strip()]
    return items


def _git_rebase_in_progress(paths: MemoryPaths) -> bool:
    git_dir = paths.root / ".git"
    return (git_dir / "rebase-apply").exists() or (git_dir / "rebase-merge").exists()


def _git_merge_in_progress(paths: MemoryPaths) -> bool:
    proc = _run_git(paths, ["rev-parse", "-q", "--verify", "MERGE_HEAD"], check=False)
    return proc.returncode == 0


def _ensure_sync_gitignore(paths: MemoryPaths) -> None:
    """Keep the memory Git repo focused on shareable memory artifacts, not runtime/install files."""
    ignore_path = paths.root / ".gitignore"
    start = "# OMNIMEM:SYNC:START"
    end = "# OMNIMEM:SYNC:END"
    block_lines = [
        start,
        "# Runtime / install artifacts (syncing these causes frequent conflicts).",
        "runtime/",
        "bin/",
        "lib/",
        "docs/",
        "spec/",
        "templates/",
        "db/",
        "__pycache__/",
        "*.pyc",
        "",
        "# Local SQLite (use JSONL/Markdown as the portable source of truth).",
        "data/omnimem.db",
        "data/omnimem.db-*",
        "data/omnimem.db-shm",
        "data/omnimem.db-wal",
        "data/omnimemory.db",
        "data/omnimemory.db-*",
        "data/omnimemory.db-shm",
        "data/omnimemory.db-wal",
        end,
        "",
    ]

    if ignore_path.exists():
        txt = ignore_path.read_text(encoding="utf-8", errors="ignore")
    else:
        txt = ""

    if start in txt and end in txt:
        a = txt.index(start)
        b = txt.index(end) + len(end)
        new_txt = (txt[:a] + "\n".join(block_lines).rstrip("\n") + txt[b:]).strip() + "\n"
    else:
        new_txt = (txt.rstrip("\n") + ("\n" if txt.strip() else "")) + "\n".join(block_lines)

    if new_txt != (txt if txt.endswith("\n") else txt + "\n"):
        ignore_path.write_text(new_txt, encoding="utf-8")


def _untrack_sync_ignored(paths: MemoryPaths) -> None:
    # If these were previously committed, .gitignore won't help; drop from index but keep local files.
    _run_git(paths, ["rm", "-r", "--cached", "--ignore-unmatch", "runtime"], check=False)
    for name in ["bin", "lib", "docs", "spec", "templates", "db", "__pycache__"]:
        _run_git(paths, ["rm", "-r", "--cached", "--ignore-unmatch", name], check=False)
    for name in ["data/omnimem.db", "data/omnimem.db-wal", "data/omnimem.db-shm"]:
        _run_git(paths, ["rm", "--cached", "--ignore-unmatch", name], check=False)
    for name in ["data/omnimemory.db", "data/omnimemory.db-wal", "data/omnimemory.db-shm"]:
        _run_git(paths, ["rm", "--cached", "--ignore-unmatch", name], check=False)


def _parse_jsonl_union(stage2: str, stage3: str) -> str:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for blob in (stage2, stage3):
        for line in (blob or "").splitlines():
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError:
                continue
            eid = str(obj.get("event_id") or "")
            if not eid:
                eid = sha256_text(s)
            if eid in seen:
                continue
            seen.add(eid)
            rows.append(obj)
    rows.sort(key=lambda o: (str(o.get("event_time") or ""), str(o.get("event_id") or "")))
    return "\n".join(json.dumps(o, ensure_ascii=False) for o in rows) + ("\n" if rows else "")


def _auto_resolve_jsonl_conflicts(paths: MemoryPaths) -> bool:
    unmerged = _git_unmerged_paths(paths)
    if not unmerged:
        return False
    if not all(p.startswith("data/jsonl/") and Path(p).name.startswith("events-") and p.endswith(".jsonl") for p in unmerged):
        return False

    for rel in unmerged:
        # Stage 2 = ours, stage 3 = theirs.
        s2 = _run_git(paths, ["show", f":2:{rel}"], check=False).stdout or ""
        s3 = _run_git(paths, ["show", f":3:{rel}"], check=False).stdout or ""
        merged = _parse_jsonl_union(s2, s3)
        fp = paths.root / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(merged, encoding="utf-8")
        _run_git(paths, ["add", rel])
    return True


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

    # Git operations and storage mutations must not interleave across processes.
    lock_ctx = repo_lock(paths.root, timeout_s=30.0) if mode in {"git", "github-status", "github-push", "github-pull", "github-bootstrap"} else nullcontext()
    with lock_ctx:
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
                _ensure_sync_gitignore(paths)
                _untrack_sync_ignored(paths)
                if _git_rebase_in_progress(paths) or _git_merge_in_progress(paths) or _git_unmerged_paths(paths):
                    st = _run_git(paths, ["status", "--short"], check=False).stdout.strip()
                    raise RuntimeError(f"git repo has an in-progress merge/rebase or unmerged files; resolve first\n{st}")

                _run_git(paths, ["add", "-A"])
                commit_proc = _run_git(paths, ["commit", "-m", commit_message], check=False)
                if commit_proc.returncode != 0 and "nothing to commit" not in (commit_proc.stdout or "") + (commit_proc.stderr or ""):
                    raise RuntimeError((commit_proc.stderr or "").strip() or (commit_proc.stdout or "").strip() or "git commit failed")
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
                detail = _run_git(paths, ["status", "--short"], check=False).stdout.strip()
        elif mode == "github-pull":
            try:
                _ensure_git_repo(paths)
                _ensure_remote(paths, remote_name, remote_url)
                _ensure_sync_gitignore(paths)
                _untrack_sync_ignored(paths)

                _run_git(paths, ["fetch", remote_name, branch])
                remote_ref = f"{remote_name}/{branch}"
                remote_ok = _run_git(
                    paths,
                    ["show-ref", "--verify", "--quiet", f"refs/remotes/{remote_name}/{branch}"],
                    check=False,
                ).returncode == 0
                if not remote_ok:
                    raise RuntimeError(f"remote branch not found after fetch: {remote_ref}")

                # If repo has no commits yet, create a snapshot commit first (if needed),
                # then merge remote (handles unrelated histories / root commits robustly).
                if not _git_has_head(paths):
                    st = _run_git(paths, ["status", "--porcelain"], check=False).stdout or ""
                    if st.strip():
                        _run_git(paths, ["add", "-A"])
                        cp = _run_git(paths, ["commit", "-m", "chore(memory): local snapshot (pre-pull)"], check=False)
                        if cp.returncode != 0 and "nothing to commit" not in (cp.stdout or "") + (cp.stderr or ""):
                            raise RuntimeError((cp.stderr or "").strip() or (cp.stdout or "").strip() or "git commit failed")
                        _run_git(paths, ["merge", "--no-ff", "--allow-unrelated-histories", remote_ref])
                    else:
                        _run_git(paths, ["checkout", "-B", branch, remote_ref])
                else:
                    # Prefer rebase, but fall back to a merge when histories are unrelated.
                    rebase_proc = _run_git(paths, ["rebase", "--autostash", remote_ref], check=False)
                    if rebase_proc.returncode != 0:
                        err_text = (rebase_proc.stdout or "") + "\n" + (rebase_proc.stderr or "")
                        if "unrelated histories" in err_text.lower() or "no common commits" in err_text.lower():
                            _run_git(paths, ["rebase", "--abort"], check=False)
                            _run_git(paths, ["merge", "--no-ff", "--allow-unrelated-histories", remote_ref])
                        else:
                            # Attempt safe auto-resolution for JSONL conflicts only.
                            for _ in range(20):
                                if not _git_unmerged_paths(paths):
                                    break
                                if not _auto_resolve_jsonl_conflicts(paths):
                                    break
                                if _git_rebase_in_progress(paths):
                                    cont = _run_git(paths, ["rebase", "--continue"], check=False)
                                    if cont.returncode != 0:
                                        break
                            if _git_unmerged_paths(paths) or _git_rebase_in_progress(paths):
                                st2 = _run_git(paths, ["status", "--short"], check=False).stdout.strip()
                                raise RuntimeError(f"git pull/rebase has conflicts; manual resolution required\n{st2}")

                message = "github pull ok"
                ok = True
                detail = _run_git(paths, ["status", "--short"]).stdout.strip()
            except Exception as exc:  # pragma: no cover
                message = f"github pull failed ({exc})"
                ok = False
                detail = _run_git(paths, ["status", "--short"], check=False).stdout.strip()
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
            portable=False,
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
    log_system_event(paths, schema_sql_path, "memory.sync", {"daemon": result}, portable=False)
    return result
