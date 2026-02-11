from __future__ import annotations

from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
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
    "memory.link",
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
_SCHEMA_SQL_TEXT_CACHE: dict[str, str] = {}
_SYSTEM_MEMORY_READY: set[str] = set()

# Per-home guard for best-effort auto-weave triggers.
_AUTO_WEAVE_LAST_TRY: dict[str, float] = {}

@contextmanager
def _sqlite_connect(db_path: Path, *, timeout: float | None = None):
    kwargs: dict[str, Any] = {}
    if timeout is not None:
        kwargs["timeout"] = float(timeout)
    conn = sqlite3.connect(db_path, **kwargs)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


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
    data = (json.dumps(cfg, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    # Atomic write: avoid leaving a truncated config if the process is interrupted mid-write.
    tmp_fp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=str(path.parent),
            prefix=path.name + ".tmp.",
        ) as f:
            tmp_fp = Path(f.name)
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(str(tmp_fp), str(path))
        try:
            os.chmod(str(path), 0o600)
        except Exception:
            pass
    finally:
        if tmp_fp is not None and tmp_fp.exists():
            try:
                tmp_fp.unlink()
            except Exception:
                pass


def resolve_paths(cfg: dict[str, Any]) -> MemoryPaths:
    home = Path(cfg.get("home", Path.cwd())).expanduser().resolve()
    storage = cfg.get("storage", {})
    markdown_root = Path(storage.get("markdown", home / "data" / "markdown")).expanduser().resolve()
    jsonl_root = Path(storage.get("jsonl", home / "data" / "jsonl")).expanduser().resolve()
    sqlite_path = Path(storage.get("sqlite", home / "data" / "omnimem.db")).expanduser().resolve()
    return MemoryPaths(root=home, markdown_root=markdown_root, jsonl_root=jsonl_root, sqlite_path=sqlite_path)


def _cache_key_for_paths(paths: MemoryPaths) -> str:
    return str(paths.sqlite_path.expanduser().resolve())


def _schema_sql_text(schema_sql_path: Path) -> str:
    key = str(schema_sql_path.expanduser().resolve())
    txt = _SCHEMA_SQL_TEXT_CACHE.get(key)
    if txt is not None:
        return txt
    txt = schema_sql_path.read_text(encoding="utf-8")
    _SCHEMA_SQL_TEXT_CACHE[key] = txt
    return txt


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

    schema_sql = _schema_sql_text(schema_sql_path)
    # Avoid re-applying DDL on every call. This also reduces cross-process startup races
    # when WebUI and CLI hit ensure_storage concurrently.
    for attempt in range(2):
        try:
            with _sqlite_connect(paths.sqlite_path, timeout=2.0) as conn:
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

    with _sqlite_connect(paths.sqlite_path, timeout=2.0) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 1500")
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            pass
        _maybe_migrate_memories_table(conn)
        _maybe_repair_fk_targets(conn)
        _maybe_create_memory_links_table(conn)


def _maybe_create_memory_links_table(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_links'"
    ).fetchone()
    if row:
        return
    conn.executescript(
        """
        CREATE TABLE memory_links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL,
          src_id TEXT NOT NULL,
          dst_id TEXT NOT NULL,
          link_type TEXT NOT NULL,
          weight REAL NOT NULL DEFAULT 0.5 CHECK (weight >= 0 AND weight <= 1),
          reason TEXT,
          FOREIGN KEY (src_id) REFERENCES memories(id) ON DELETE CASCADE,
          FOREIGN KEY (dst_id) REFERENCES memories(id) ON DELETE CASCADE,
          UNIQUE (src_id, dst_id, link_type)
        );
        CREATE INDEX idx_memory_links_src ON memory_links(src_id);
        CREATE INDEX idx_memory_links_dst ON memory_links(dst_id);
        CREATE INDEX idx_memory_links_type ON memory_links(link_type);
        CREATE INDEX idx_memory_links_weight ON memory_links(weight);
        """
    )


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
    key = _cache_key_for_paths(paths)
    system_id = "system000"
    if key in _SYSTEM_MEMORY_READY:
        return system_id
    ensure_storage(paths, schema_sql_path)
    rel_path = "archive/system/system000.md"
    md_path = paths.markdown_root / rel_path
    if not md_path.exists():
        md_path.parent.mkdir(parents=True, exist_ok=True)
        body = "# system\n\nreserved memory for system audit events\n"
        md_path.write_text(body, encoding="utf-8")
    else:
        body = md_path.read_text(encoding="utf-8")

    with _sqlite_connect(paths.sqlite_path) as conn:
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

    _SYSTEM_MEMORY_READY.add(key)
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
        with _sqlite_connect(paths.sqlite_path) as conn:
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

    with _sqlite_connect(paths.sqlite_path) as conn:
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


def _quantile(sorted_vals: list[float], q: float, default: float) -> float:
    if not sorted_vals:
        return float(default)
    qq = max(0.0, min(1.0, float(q)))
    idx = int(round((len(sorted_vals) - 1) * qq))
    idx = max(0, min(len(sorted_vals) - 1, idx))
    return float(sorted_vals[idx])


def infer_adaptive_governance_thresholds(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    project_id: str = "",
    session_id: str = "",
    days: int = 14,
    q_promote_imp: float = 0.68,
    q_promote_conf: float = 0.60,
    q_promote_stab: float = 0.62,
    q_promote_vol: float = 0.42,
    q_demote_vol: float = 0.78,
    q_demote_stab: float = 0.28,
    q_demote_reuse: float = 0.30,
) -> dict[str, Any]:
    """Infer consolidation thresholds from recent signal distributions."""
    ensure_storage(paths, schema_sql_path)
    days = max(1, min(180, int(days)))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    sid_where = ""
    sid_args: list[Any] = []
    if session_id:
        sid_where = "AND COALESCE(json_extract(source_json, '$.session_id'), '') = ?"
        sid_args.append(session_id)

    with _sqlite_connect(paths.sqlite_path, timeout=6.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT layer, importance_score, confidence_score, stability_score, reuse_count, volatility_score
            FROM memories
            WHERE (json_extract(scope_json, '$.project_id') = ? OR ? = '')
              {sid_where}
              AND updated_at >= ?
              AND kind NOT IN ('retrieve')
            ORDER BY updated_at DESC
            LIMIT 3000
            """,
            (project_id, project_id, *sid_args, cutoff),
        ).fetchall()

    all_imp = sorted(float(r["importance_score"] or 0.0) for r in rows)
    all_conf = sorted(float(r["confidence_score"] or 0.0) for r in rows)
    all_stab = sorted(float(r["stability_score"] or 0.0) for r in rows)
    all_vol = sorted(float(r["volatility_score"] or 0.0) for r in rows)
    all_reuse = sorted(int(r["reuse_count"] or 0) for r in rows)

    p_imp = max(0.55, min(0.92, _quantile(all_imp, q_promote_imp, 0.75)))
    p_conf = max(0.50, min(0.90, _quantile(all_conf, q_promote_conf, 0.65)))
    p_stab = max(0.50, min(0.95, _quantile(all_stab, q_promote_stab, 0.65)))
    p_vol = max(0.25, min(0.80, _quantile(all_vol, q_promote_vol, 0.65)))
    d_vol = max(0.55, min(0.98, _quantile(all_vol, q_demote_vol, 0.75)))
    d_stab = max(0.10, min(0.70, _quantile(all_stab, q_demote_stab, 0.45)))
    d_reuse = max(0, min(8, int(_quantile([float(x) for x in all_reuse], q_demote_reuse, 1.0))))

    return {
        "ok": True,
        "project_id": project_id,
        "session_id": session_id,
        "days": days,
        "sample_size": len(rows),
        "thresholds": {
            "p_imp": float(round(p_imp, 3)),
            "p_conf": float(round(p_conf, 3)),
            "p_stab": float(round(p_stab, 3)),
            "p_vol": float(round(p_vol, 3)),
            "d_vol": float(round(d_vol, 3)),
            "d_stab": float(round(d_stab, 3)),
            "d_reuse": int(d_reuse),
        },
        "quantiles": {
            "q_promote_imp": float(q_promote_imp),
            "q_promote_conf": float(q_promote_conf),
            "q_promote_stab": float(q_promote_stab),
            "q_promote_vol": float(q_promote_vol),
            "q_demote_vol": float(q_demote_vol),
            "q_demote_stab": float(q_demote_stab),
            "q_demote_reuse": float(q_demote_reuse),
        },
    }


def consolidate_memories(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    project_id: str = "",
    session_id: str = "",
    limit: int = 80,
    dry_run: bool = True,
    p_imp: float = 0.75,
    p_conf: float = 0.65,
    p_stab: float = 0.65,
    p_vol: float = 0.65,
    d_vol: float = 0.75,
    d_stab: float = 0.45,
    d_reuse: int = 1,
    adaptive: bool = False,
    adaptive_days: int = 14,
    adaptive_q_promote_imp: float = 0.68,
    adaptive_q_promote_conf: float = 0.60,
    adaptive_q_promote_stab: float = 0.62,
    adaptive_q_promote_vol: float = 0.42,
    adaptive_q_demote_vol: float = 0.78,
    adaptive_q_demote_stab: float = 0.28,
    adaptive_q_demote_reuse: float = 0.30,
    tool: str = "omnimem",
    actor_session_id: str = "system",
) -> dict[str, Any]:
    """Adaptive consolidation pass: promote stable/high-value memories and demote noisy stale ones."""
    ensure_storage(paths, schema_sql_path)
    limit = max(1, min(500, int(limit)))
    sid_where = ""
    sid_args: list[Any] = []
    if session_id:
        sid_where = "AND COALESCE(json_extract(source_json, '$.session_id'), '') = ?"
        sid_args.append(session_id)
    learned: dict[str, Any] = {}
    if adaptive:
        learned = infer_adaptive_governance_thresholds(
            paths=paths,
            schema_sql_path=schema_sql_path,
            project_id=project_id,
            session_id=session_id,
            days=adaptive_days,
            q_promote_imp=adaptive_q_promote_imp,
            q_promote_conf=adaptive_q_promote_conf,
            q_promote_stab=adaptive_q_promote_stab,
            q_promote_vol=adaptive_q_promote_vol,
            q_demote_vol=adaptive_q_demote_vol,
            q_demote_stab=adaptive_q_demote_stab,
            q_demote_reuse=adaptive_q_demote_reuse,
        )
        th = dict(learned.get("thresholds") or {})
        p_imp = float(th.get("p_imp", p_imp))
        p_conf = float(th.get("p_conf", p_conf))
        p_stab = float(th.get("p_stab", p_stab))
        p_vol = float(th.get("p_vol", p_vol))
        d_vol = float(th.get("d_vol", d_vol))
        d_stab = float(th.get("d_stab", d_stab))
        d_reuse = int(th.get("d_reuse", d_reuse))

    with _sqlite_connect(paths.sqlite_path, timeout=6.0) as conn:
        conn.row_factory = sqlite3.Row
        promote = conn.execute(
            f"""
            SELECT id, layer, kind, summary, updated_at,
                   importance_score, confidence_score, stability_score, reuse_count, volatility_score
            FROM memories
            WHERE layer IN ('instant','short')
              AND (json_extract(scope_json, '$.project_id') = ? OR ? = '')
              {sid_where}
              AND importance_score >= ?
              AND confidence_score >= ?
              AND stability_score >= ?
              AND volatility_score <= ?
            ORDER BY importance_score DESC, stability_score DESC, updated_at DESC
            LIMIT ?
            """,
            (project_id, project_id, *sid_args, p_imp, p_conf, p_stab, p_vol, limit),
        ).fetchall()
        demote = conn.execute(
            f"""
            SELECT id, layer, kind, summary, updated_at,
                   importance_score, confidence_score, stability_score, reuse_count, volatility_score
            FROM memories
            WHERE layer IN ('long')
              AND (json_extract(scope_json, '$.project_id') = ? OR ? = '')
              {sid_where}
              AND (volatility_score >= ? OR stability_score <= ?)
              AND reuse_count <= ?
            ORDER BY volatility_score DESC, stability_score ASC, updated_at ASC
            LIMIT ?
            """,
            (project_id, project_id, *sid_args, d_vol, d_stab, int(d_reuse), limit),
        ).fetchall()

    pro_items = [dict(r) for r in promote]
    de_items = [dict(r) for r in demote]
    applied_promote: list[dict[str, Any]] = []
    applied_demote: list[dict[str, Any]] = []
    errors: list[str] = []

    if not dry_run:
        for r in pro_items:
            mid = str(r.get("id") or "")
            layer = str(r.get("layer") or "")
            to_layer = "short" if layer == "instant" else "long"
            try:
                out = move_memory_layer(
                    paths=paths,
                    schema_sql_path=schema_sql_path,
                    memory_id=mid,
                    new_layer=to_layer,
                    tool=tool,
                    session_id=actor_session_id,
                    event_type="memory.promote",
                )
                if out.get("ok") and out.get("changed"):
                    applied_promote.append({"id": mid, "from_layer": layer, "to_layer": to_layer})
            except Exception as exc:
                errors.append(f"promote:{mid}:{exc}")

        for r in de_items:
            mid = str(r.get("id") or "")
            layer = str(r.get("layer") or "")
            to_layer = "short"
            try:
                out = move_memory_layer(
                    paths=paths,
                    schema_sql_path=schema_sql_path,
                    memory_id=mid,
                    new_layer=to_layer,
                    tool=tool,
                    session_id=actor_session_id,
                    event_type="memory.promote",
                )
                if out.get("ok") and out.get("changed"):
                    applied_demote.append({"id": mid, "from_layer": layer, "to_layer": to_layer})
            except Exception as exc:
                errors.append(f"demote:{mid}:{exc}")

        log_system_event(
            paths,
            schema_sql_path,
            "memory.update",
            {
                "action": "consolidate",
                "project_id": project_id,
                "session_id": session_id,
                "promote_candidates": len(pro_items),
                "demote_candidates": len(de_items),
                "promoted": len(applied_promote),
                "demoted": len(applied_demote),
                "adaptive": bool(adaptive),
                "thresholds": {
                    "p_imp": p_imp,
                    "p_conf": p_conf,
                    "p_stab": p_stab,
                    "p_vol": p_vol,
                    "d_vol": d_vol,
                    "d_stab": d_stab,
                    "d_reuse": int(d_reuse),
                },
                "errors": errors[:30],
            },
            portable=False,
        )

    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "project_id": project_id,
        "session_id": session_id,
        "promote": pro_items[:limit],
        "demote": de_items[:limit],
        "promoted": applied_promote,
        "demoted": applied_demote,
        "errors": errors,
        "adaptive": bool(adaptive),
        "adaptive_info": learned,
        "thresholds": {
            "p_imp": p_imp,
            "p_conf": p_conf,
            "p_stab": p_stab,
            "p_vol": p_vol,
            "d_vol": d_vol,
            "d_stab": d_stab,
            "d_reuse": int(d_reuse),
        },
    }


def compress_session_context(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    project_id: str = "",
    session_id: str,
    limit: int = 120,
    min_items: int = 8,
    target_layer: str = "short",
    dry_run: bool = True,
    tool: str = "omnimem",
    actor_session_id: str = "system",
) -> dict[str, Any]:
    """Create a compact, reusable session memory summary (ICAE-style context compression, deterministic)."""
    ensure_storage(paths, schema_sql_path)
    if target_layer not in LAYER_SET:
        raise ValueError(f"invalid target_layer: {target_layer}")
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("session_id is required")
    limit = max(10, min(500, int(limit)))
    min_items = max(2, min(200, int(min_items)))

    with _sqlite_connect(paths.sqlite_path, timeout=6.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, layer, kind, summary, updated_at, tags_json
            FROM memories
            WHERE (json_extract(scope_json, '$.project_id') = ? OR ? = '')
              AND COALESCE(json_extract(source_json, '$.session_id'), '') = ?
              AND kind NOT IN ('retrieve')
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (project_id, project_id, sid, limit),
        ).fetchall()

    items = [dict(r) for r in rows]
    if len(items) < min_items:
        return {
            "ok": True,
            "dry_run": bool(dry_run),
            "session_id": sid,
            "project_id": project_id,
            "compressed": False,
            "reason": f"insufficient items ({len(items)} < {min_items})",
            "items": items,
        }

    layer_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    for x in items:
        layer = str(x.get("layer") or "")
        kind = str(x.get("kind") or "")
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        try:
            tags = json.loads(x.get("tags_json") or "[]")
        except Exception:
            tags = []
        for t in tags[:10]:
            tt = str(t).strip()
            if not tt:
                continue
            tag_counts[tt] = tag_counts.get(tt, 0) + 1

    top_tags = [k for k, _ in sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]]
    top_kinds = [f"{k}:{v}" for k, v in sorted(kind_counts.items(), key=lambda kv: kv[1], reverse=True)]
    top_layers = [f"{k}:{v}" for k, v in sorted(layer_counts.items(), key=lambda kv: kv[1], reverse=True)]
    highlights = items[: min(12, len(items))]

    summary = f"Session digest: {sid[:12]}… ({len(items)} memories)"
    lines = [
        "## Session Compression Digest",
        "",
        f"- project_id: {project_id or '(all)'}",
        f"- session_id: {sid}",
        f"- source_items: {len(items)}",
        f"- layers: {', '.join(top_layers) if top_layers else '(none)'}",
        f"- kinds: {', '.join(top_kinds) if top_kinds else '(none)'}",
        f"- top_tags: {', '.join(top_tags) if top_tags else '(none)'}",
        "",
        "### Highlights",
    ]
    for x in highlights:
        lines.append(f"- [{x.get('updated_at','')}] ({x.get('layer','')}/{x.get('kind','')}) {x.get('summary','')}")
    body = "\n".join(lines).strip() + "\n"

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "session_id": sid,
            "project_id": project_id,
            "compressed": False,
            "summary_preview": summary,
            "body_preview": body,
            "source_count": len(items),
        }

    out = write_memory(
        paths=paths,
        schema_sql_path=schema_sql_path,
        layer=target_layer,
        kind="summary",
        summary=summary,
        body=body,
        tags=[
            "auto:session-compress",
            f"session:{sid}",
            *(["project:" + project_id] if project_id else []),
        ],
        refs=[],
        cred_refs=[],
        tool=tool,
        account="default",
        device="local",
        session_id=actor_session_id,
        project_id=project_id or "global",
        workspace=str(paths.root),
        importance=0.76,
        confidence=0.72,
        stability=0.78,
        reuse_count=0,
        volatility=0.22,
        event_type="memory.write",
    )
    return {
        "ok": True,
        "dry_run": False,
        "session_id": sid,
        "project_id": project_id,
        "compressed": True,
        "memory_id": out["memory"]["id"],
        "body_md_path": out["memory"]["body_md_path"],
        "source_count": len(items),
    }


def compress_hot_sessions(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    project_id: str = "",
    max_sessions: int = 2,
    per_session_limit: int = 120,
    min_items: int = 8,
    dry_run: bool = True,
    tool: str = "omnimem",
    actor_session_id: str = "system",
) -> dict[str, Any]:
    ensure_storage(paths, schema_sql_path)
    max_sessions = max(1, min(10, int(max_sessions)))
    with _sqlite_connect(paths.sqlite_path, timeout=6.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT COALESCE(json_extract(source_json, '$.session_id'), '') AS sid, COUNT(*) AS c
            FROM memories
            WHERE (json_extract(scope_json, '$.project_id') = ? OR ? = '')
              AND COALESCE(json_extract(source_json, '$.session_id'), '') != ''
              AND kind NOT IN ('retrieve')
            GROUP BY sid
            ORDER BY c DESC
            LIMIT ?
            """,
            (project_id, project_id, max_sessions * 3),
        ).fetchall()

    sessions = [str(r["sid"]) for r in rows if str(r["sid"]).strip() and str(r["sid"]) not in {"system", "webui-session"}][:max_sessions]
    items: list[dict[str, Any]] = []
    for sid in sessions:
        try:
            out = compress_session_context(
                paths=paths,
                schema_sql_path=schema_sql_path,
                project_id=project_id,
                session_id=sid,
                limit=per_session_limit,
                min_items=min_items,
                dry_run=dry_run,
                tool=tool,
                actor_session_id=actor_session_id,
            )
            items.append(out)
        except Exception as exc:
            items.append({"ok": False, "session_id": sid, "error": str(exc)})
    return {"ok": True, "project_id": project_id, "sessions": sessions, "items": items}


def build_temporal_memory_tree(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    project_id: str = "",
    days: int = 30,
    max_sessions: int = 20,
    per_session_limit: int = 120,
    dry_run: bool = True,
    tool: str = "omnimem",
    actor_session_id: str = "system",
) -> dict[str, Any]:
    """Build temporal/hierarchical links to support low-cost episodic traversal.

    - temporal_next: ordered links within each session
    - distill_of: latest distill summaries linked to recent source memories
    """
    ensure_storage(paths, schema_sql_path)
    days = max(1, min(180, int(days)))
    max_sessions = max(1, min(100, int(max_sessions)))
    per_session_limit = max(20, min(500, int(per_session_limit)))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    when = utc_now()

    with _sqlite_connect(paths.sqlite_path, timeout=6.0) as conn:
        conn.row_factory = sqlite3.Row
        srows = conn.execute(
            """
            SELECT COALESCE(json_extract(source_json, '$.session_id'), '') AS sid, COUNT(*) AS c
            FROM memories
            WHERE updated_at >= ?
              AND (json_extract(scope_json, '$.project_id') = ? OR ? = '')
              AND COALESCE(json_extract(source_json, '$.session_id'), '') != ''
              AND kind NOT IN ('retrieve')
            GROUP BY sid
            ORDER BY c DESC
            LIMIT ?
            """,
            (cutoff, project_id, project_id, max_sessions * 2),
        ).fetchall()

        sessions = [str(r["sid"]).strip() for r in srows if str(r["sid"]).strip() and str(r["sid"]) not in {"system", "webui-session"}][:max_sessions]
        temporal_links: list[dict[str, Any]] = []
        distill_links: list[dict[str, Any]] = []

        for sid in sessions:
            rows = conn.execute(
                """
                SELECT id, updated_at, tags_json
                FROM memories
                WHERE updated_at >= ?
                  AND (json_extract(scope_json, '$.project_id') = ? OR ? = '')
                  AND COALESCE(json_extract(source_json, '$.session_id'), '') = ?
                  AND kind NOT IN ('retrieve')
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (cutoff, project_id, project_id, sid, per_session_limit),
            ).fetchall()
            ids = [str(r["id"]) for r in rows if str(r["id"]).strip()]
            for i in range(len(ids) - 1):
                temporal_links.append(
                    {
                        "created_at": when,
                        "src_id": ids[i],
                        "dst_id": ids[i + 1],
                        "link_type": "temporal_next",
                        "weight": 1.0,
                        "reason": f"session:{sid}",
                    }
                )

            drows = conn.execute(
                """
                SELECT id, tags_json
                FROM memories
                WHERE updated_at >= ?
                  AND kind='summary'
                  AND (json_extract(scope_json, '$.project_id') = ? OR ? = '')
                  AND EXISTS (SELECT 1 FROM json_each(memories.tags_json) WHERE value='auto:distill')
                  AND EXISTS (SELECT 1 FROM json_each(memories.tags_json) WHERE value=?)
                ORDER BY updated_at DESC
                LIMIT 2
                """,
                (cutoff, project_id, project_id, f"session:{sid}"),
            ).fetchall()
            dids = [str(r["id"]) for r in drows if str(r["id"]).strip()]
            for did in dids:
                for mid in ids[-20:]:
                    distill_links.append(
                        {
                            "created_at": when,
                            "src_id": did,
                            "dst_id": mid,
                            "link_type": "distill_of",
                            "weight": 0.86,
                            "reason": f"session:{sid}",
                        }
                    )

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "project_id": project_id,
                "days": days,
                "sessions": sessions,
                "temporal_links": len(temporal_links),
                "distill_links": len(distill_links),
            }

        made = 0
        for lk in temporal_links + distill_links:
            insert_link(conn, lk)
            made += 1
        conn.commit()

    try:
        log_system_event(
            paths,
            schema_sql_path,
            "memory.update",
            {
                "action": "temporal-tree",
                "project_id": project_id,
                "days": days,
                "sessions": len(sessions),
                "made": made,
                "temporal_links": len(temporal_links),
                "distill_links": len(distill_links),
                "tool": tool,
                "actor_session_id": actor_session_id,
            },
            portable=False,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "dry_run": False,
        "project_id": project_id,
        "days": days,
        "sessions": sessions,
        "made": made,
        "temporal_links": len(temporal_links),
        "distill_links": len(distill_links),
    }


def distill_session_memory(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    project_id: str = "",
    session_id: str,
    limit: int = 140,
    min_items: int = 10,
    dry_run: bool = True,
    semantic_layer: str = "long",
    procedural_layer: str = "short",
    tool: str = "omnimem",
    actor_session_id: str = "system",
) -> dict[str, Any]:
    """Distill session traces into compact semantic + procedural memories.

    Deterministic (no model call): extract high-signal facts/steps from summaries and tags.
    """
    ensure_storage(paths, schema_sql_path)
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("session_id is required")
    if semantic_layer not in LAYER_SET or procedural_layer not in LAYER_SET:
        raise ValueError("invalid target layers")
    limit = max(20, min(600, int(limit)))
    min_items = max(3, min(200, int(min_items)))

    with _sqlite_connect(paths.sqlite_path, timeout=6.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, layer, kind, summary, updated_at, tags_json
            FROM memories
            WHERE (json_extract(scope_json, '$.project_id') = ? OR ? = '')
              AND COALESCE(json_extract(source_json, '$.session_id'), '') = ?
              AND kind NOT IN ('retrieve')
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (project_id, project_id, sid, limit),
        ).fetchall()

    items = [dict(r) for r in rows]
    if len(items) < min_items:
        return {
            "ok": True,
            "dry_run": bool(dry_run),
            "project_id": project_id,
            "session_id": sid,
            "distilled": False,
            "reason": f"insufficient items ({len(items)} < {min_items})",
        }

    fact_kw = ("decision", "rule", "constraint", "must", "final", "结论", "规则", "约束")
    step_kw = ("how", "step", "run", "command", "fix", "script", "流程", "步骤", "命令", "修复")
    facts: list[str] = []
    steps: list[str] = []
    seen_fact: set[str] = set()
    seen_step: set[str] = set()

    for x in items:
        sm = str(x.get("summary") or "").strip()
        if not sm:
            continue
        low = sm.lower()
        is_fact = (str(x.get("kind") or "") in {"decision", "evidence", "summary"}) or any(k in low for k in fact_kw)
        is_step = any(k in low for k in step_kw)
        if is_fact and sm not in seen_fact:
            seen_fact.add(sm)
            facts.append(sm)
        if is_step and sm not in seen_step:
            seen_step.add(sm)
            steps.append(sm)
        if len(facts) >= 14 and len(steps) >= 14:
            break

    if not facts:
        facts = [str(x.get("summary") or "").strip() for x in items[:8] if str(x.get("summary") or "").strip()]
    if not steps:
        steps = [str(x.get("summary") or "").strip() for x in items[:8] if str(x.get("summary") or "").strip()]
    facts = facts[:14]
    steps = steps[:14]

    source_ids = [str(x.get("id") or "").strip() for x in items if str(x.get("id") or "").strip()][:40]
    refs = [{"type": "memory", "target": mid, "note": "distill-source"} for mid in source_ids]

    sem_summary = f"Semantic distill: {sid[:12]}…"
    sem_body = "## Semantic Memory Distillation\n\n"
    sem_body += f"- project_id: {project_id or '(all)'}\n- session_id: {sid}\n- source_items: {len(items)}\n\n### Stable facts\n"
    for f in facts:
        sem_body += f"- {f}\n"
    sem_body += "\n### Source memory ids\n"
    for mid in source_ids[:30]:
        sem_body += f"- {mid}\n"

    proc_summary = f"Procedural distill: {sid[:12]}…"
    proc_body = "## Procedural Memory Distillation\n\n"
    proc_body += f"- project_id: {project_id or '(all)'}\n- session_id: {sid}\n- source_items: {len(items)}\n\n### Reusable steps\n"
    for s in steps:
        proc_body += f"- {s}\n"
    proc_body += "\n### Source memory ids\n"
    for mid in source_ids[:30]:
        proc_body += f"- {mid}\n"

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "project_id": project_id,
            "session_id": sid,
            "distilled": False,
            "semantic_preview": {"summary": sem_summary, "body": sem_body},
            "procedural_preview": {"summary": proc_summary, "body": proc_body},
            "source_count": len(items),
        }

    sem_out = write_memory(
        paths=paths,
        schema_sql_path=schema_sql_path,
        layer=semantic_layer,
        kind="summary",
        summary=sem_summary,
        body=sem_body,
        tags=["auto:distill", "mem:semantic", f"session:{sid}", *(["project:" + project_id] if project_id else [])],
        refs=refs,
        cred_refs=[],
        tool=tool,
        account="default",
        device="local",
        session_id=actor_session_id,
        project_id=project_id or "global",
        workspace=str(paths.root),
        importance=0.82,
        confidence=0.72,
        stability=0.84,
        reuse_count=0,
        volatility=0.20,
        event_type="memory.write",
    )
    proc_out = write_memory(
        paths=paths,
        schema_sql_path=schema_sql_path,
        layer=procedural_layer,
        kind="summary",
        summary=proc_summary,
        body=proc_body,
        tags=["auto:distill", "mem:procedural", f"session:{sid}", *(["project:" + project_id] if project_id else [])],
        refs=refs,
        cred_refs=[],
        tool=tool,
        account="default",
        device="local",
        session_id=actor_session_id,
        project_id=project_id or "global",
        workspace=str(paths.root),
        importance=0.80,
        confidence=0.70,
        stability=0.78,
        reuse_count=0,
        volatility=0.26,
        event_type="memory.write",
    )

    return {
        "ok": True,
        "dry_run": False,
        "project_id": project_id,
        "session_id": sid,
        "distilled": True,
        "source_count": len(items),
        "source_ids": source_ids,
        "semantic_memory_id": str((sem_out.get("memory") or {}).get("id") or ""),
        "procedural_memory_id": str((proc_out.get("memory") or {}).get("id") or ""),
    }


def insert_event(conn: sqlite3.Connection, evt: dict[str, Any]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO memory_events(event_id, event_type, event_time, memory_id, payload_json) VALUES (?, ?, ?, ?, ?)",
        (evt["event_id"], evt["event_type"], evt["event_time"], evt["memory_id"], json.dumps(evt["payload"], ensure_ascii=False)),
    )


def insert_link(conn: sqlite3.Connection, link: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO memory_links(created_at, src_id, dst_id, link_type, weight, reason)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(link.get("created_at") or utc_now()),
            str(link.get("src_id") or ""),
            str(link.get("dst_id") or ""),
            str(link.get("link_type") or "similar"),
            float(link.get("weight") or 0.5),
            str(link.get("reason") or ""),
        ),
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
        key = _cache_key_for_paths(paths)
        system_id = "system000"
        if key not in _SYSTEM_MEMORY_READY:
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
        with _sqlite_connect(paths.sqlite_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                insert_event(conn, evt)
            except sqlite3.IntegrityError:
                # If system memory was externally reset/reindexed while process cache says "ready",
                # recover once by recreating system memory and retrying this event.
                _SYSTEM_MEMORY_READY.discard(key)
                evt["memory_id"] = ensure_system_memory(paths, schema_sql_path)
                insert_event(conn, evt)
            conn.commit()


def reindex_from_jsonl(paths: MemoryPaths, schema_sql_path: Path, reset: bool = True) -> dict[str, Any]:
    ensure_storage(paths, schema_sql_path)
    system_id = ensure_system_memory(paths, schema_sql_path)
    files = sorted(paths.jsonl_root.glob("events-*.jsonl"))
    parsed_events = 0
    indexed_memories = 0
    skipped_events = 0

    with _sqlite_connect(paths.sqlite_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        if reset:
            conn.execute("DELETE FROM memory_events")
            conn.execute("DELETE FROM memory_refs")
            conn.execute("DELETE FROM memory_links")
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

                # Rebuild graph edges from portable events.
                if evt.get("event_type") == "memory.link":
                    try:
                        src_id = str(payload.get("src_id") or "")
                        dst_id = str(payload.get("dst_id") or "")
                        if src_id and dst_id:
                            insert_link(
                                conn,
                                {
                                    "created_at": evt.get("event_time") or utc_now(),
                                    "src_id": src_id,
                                    "dst_id": dst_id,
                                    "link_type": str(payload.get("link_type") or "similar"),
                                    "weight": float(payload.get("weight") or 0.5),
                                    "reason": str(payload.get("reason") or ""),
                                },
                            )
                    except Exception:
                        # Don't fail reindex if a link line is malformed.
                        pass

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

        with _sqlite_connect(paths.sqlite_path) as conn:
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

        with _sqlite_connect(paths.sqlite_path) as conn:
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

        with _sqlite_connect(paths.sqlite_path) as conn:
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


def _parse_iso_dt(raw: str) -> datetime:
    s = str(raw or "").strip()
    if not s:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _recency_score(updated_at: str, now_dt: datetime, *, half_life_days: float = 14.0) -> float:
    try:
        age_days = max(0.0, (now_dt - _parse_iso_dt(updated_at)).total_seconds() / 86400.0)
    except Exception:
        age_days = 3650.0
    # Ebbinghaus-inspired forgetting curve: score halves every `half_life_days`.
    v = 2.0 ** (-(age_days / max(1e-6, half_life_days)))
    return max(0.0, min(1.0, float(v)))


def _reuse_norm(reuse_count: int) -> float:
    # Saturating normalization so early reuse increments matter most.
    rc = max(0, int(reuse_count or 0))
    v = 1.0 - (2.718281828459045 ** (-rc / 4.0))
    return max(0.0, min(1.0, float(v)))


def _fts_rank_to_relevance(fts_rank: Any) -> float:
    if fts_rank is None:
        return 0.0
    try:
        r = float(fts_rank)
    except Exception:
        return 0.0
    # SQLite FTS bm25: lower is better, often near zero and can be negative.
    # Convert to [0,1] with a smooth inverse mapping.
    z = max(0.0, r)
    v = 1.0 / (1.0 + z)
    return max(0.0, min(1.0, float(v)))


def _token_overlap_score(summary: str, query_tokens: list[str]) -> float:
    if not query_tokens:
        return 0.0
    qt = set(t.lower() for t in query_tokens if t.strip())
    if not qt:
        return 0.0
    st = _mem_text_tokens(summary or "")
    if not st:
        return 0.0
    return _jaccard(qt, st)


def _attach_cognitive_retrieval(
    items: list[dict[str, Any]],
    *,
    strategy: str,
    query_tokens: list[str],
) -> list[dict[str, Any]]:
    now_dt = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for it in items:
        sig = it.get("signals") or {}
        importance = max(0.0, min(1.0, float(sig.get("importance_score", 0.0) or 0.0)))
        confidence = max(0.0, min(1.0, float(sig.get("confidence_score", 0.0) or 0.0)))
        stability = max(0.0, min(1.0, float(sig.get("stability_score", 0.0) or 0.0)))
        volatility = max(0.0, min(1.0, float(sig.get("volatility_score", 0.0) or 0.0)))
        reuse = _reuse_norm(int(sig.get("reuse_count", 0) or 0))
        recency = _recency_score(str(it.get("updated_at", "")), now_dt)
        lexical = _token_overlap_score(str(it.get("summary", "")), query_tokens)
        fts_rel = _fts_rank_to_relevance(it.pop("fts_rank", None))
        relevance = max(lexical, fts_rel)

        # Inspired by generative-memory retrieval (relevance + recency + importance)
        # and long-term-memory stabilization signals used by OmniMem.
        score = (
            0.38 * relevance
            + 0.18 * importance
            + 0.12 * recency
            + 0.11 * stability
            + 0.08 * confidence
            + 0.08 * reuse
            - 0.05 * volatility
        )
        score = max(0.0, min(1.0, float(score)))
        it["retrieval"] = {
            "strategy": strategy,
            "score": score,
            "components": {
                "relevance": relevance,
                "lexical_overlap": lexical,
                "fts_relevance": fts_rel,
                "recency": recency,
                "importance": importance,
                "confidence": confidence,
                "stability": stability,
                "reuse": reuse,
                "volatility_penalty": volatility,
            },
        }
        out.append(it)

    out.sort(key=lambda x: (float((x.get("retrieval") or {}).get("score", 0.0)), str(x.get("updated_at", ""))), reverse=True)
    return out


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
                   m.importance_score, m.confidence_score, m.stability_score, m.reuse_count, m.volatility_score,
                   bm25(memories_fts) AS fts_rank
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
               m.importance_score, m.confidence_score, m.stability_score, m.reuse_count, m.volatility_score,
               bm25(memories_fts) AS fts_rank
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

    with _sqlite_connect(paths.sqlite_path) as conn:
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
                reranked = _attach_cognitive_retrieval(items, strategy=strat, query_tokens=tokens)
                return {"ok": True, "strategy": strat, "query_used": qq, "tried": tried, "items": reranked}

        # Resilient fallback.
        ltoks = tokens or _query_tokens(normalized)
        tried.append({"strategy": "like_fallback", "query_used": " OR ".join(ltoks)})
        rows2 = _like_rows(conn, tokens=ltoks, layer=layer, limit=limit, project_id=project_id, session_id=session_id)
        items2 = [_signals_from_row(dict(r)) for r in rows2]
        reranked2 = _attach_cognitive_retrieval(items2, strategy="like_fallback", query_tokens=ltoks)
        return {"ok": True, "strategy": "like_fallback", "query_used": " OR ".join(ltoks), "tried": tried, "items": reranked2}


def _mem_text_tokens(text: str) -> set[str]:
    s = str(text or "").lower()
    toks = re.findall(r"[\w]+|[\u4e00-\u9fff]+", s, flags=re.UNICODE)
    out: set[str] = set()
    for t in toks:
        tt = t.strip()
        if not tt:
            continue
        if len(tt) == 1 and tt.isascii():
            continue
        out.add(tt)
        if len(out) >= 80:
            break
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    if inter <= 0:
        return 0.0
    union = len(a.union(b))
    return inter / max(1, union)


def weave_links(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    project_id: str = "",
    limit: int = 120,
    min_weight: float = 0.18,
    max_per_src: int = 6,
    include_archive: bool = True,
    portable: bool = False,
    max_wait_s: float = 20.0,
    tool: str = "cli",
    session_id: str = "system",
) -> dict[str, Any]:
    """Build/refresh a lightweight memory relationship graph.

    Current implementation is heuristic:
    - token overlap (summary + tags + a slice of body_text) using Jaccard similarity
    - bidirectional 'similar' links for weights above threshold
    """
    with repo_lock(paths.root, timeout_s=30.0):
        ensure_storage(paths, schema_sql_path)
        when = utc_now()
        limit = max(10, min(800, int(limit)))
        min_weight = max(0.0, min(1.0, float(min_weight)))
        max_per_src = max(1, min(50, int(max_per_src)))
        max_wait_s = max(0.0, float(max_wait_s))

        # Read phase (can run even if link writes are busy).
        items = []
        try:
            with _sqlite_connect(paths.sqlite_path, timeout=6.0) as conn_r:
                conn_r.row_factory = sqlite3.Row
                conn_r.execute("PRAGMA foreign_keys = ON")
                conn_r.execute("PRAGMA busy_timeout = 6000")
                layers = ["instant", "short", "long"] + (["archive"] if include_archive else [])
                placeholders = ",".join(["?"] * len(layers))
                rows = conn_r.execute(
                    f"""
                    SELECT id, layer, kind, summary, body_text, tags_json, updated_at,
                           COALESCE(json_extract(scope_json, '$.project_id'), '') AS project_id
                    FROM memories
                    WHERE layer IN ({placeholders})
                      AND kind NOT IN ('retrieve','summary')
                      AND (json_extract(scope_json, '$.project_id') = ? OR ? = '')
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (*layers, project_id, project_id, limit),
                ).fetchall()

                for r in rows:
                    tags = []
                    try:
                        tags = json.loads(r["tags_json"] or "[]")
                    except Exception:
                        tags = []
                    blob = " ".join(
                        [
                            str(r["summary"] or ""),
                            " ".join([str(t) for t in (tags or [])]),
                            str(r["body_text"] or "")[:800],
                        ]
                    )
                    items.append(
                        {
                            "id": str(r["id"]),
                            "layer": str(r["layer"]),
                            "updated_at": str(r["updated_at"]),
                            "tokens": _mem_text_tokens(blob),
                        }
                    )
        except sqlite3.OperationalError as exc:
            return {"ok": False, "error": str(exc)}

        # Compute phase (no DB).
        proposed: list[dict[str, Any]] = []
        considered = 0
        for i, src in enumerate(items):
            scored: list[tuple[float, str]] = []
            for j, dst in enumerate(items):
                if i == j:
                    continue
                considered += 1
                w = _jaccard(src["tokens"], dst["tokens"])
                if w >= min_weight:
                    scored.append((w, dst["id"]))
            scored.sort(reverse=True, key=lambda x: x[0])
            for w, dst_id in scored[:max_per_src]:
                proposed.append(
                    {
                        "created_at": when,
                        "src_id": src["id"],
                        "dst_id": dst_id,
                        "link_type": "similar",
                        "weight": float(round(w, 4)),
                        "reason": "token-jaccard(summary,tags,body_slice)",
                    }
                )

        # Write phase with retry (handles a busy WebUI/daemon without requiring kill).
        start = time.time()
        backoff = 0.2
        attempt = 0
        while True:
            attempt += 1
            try:
                with _sqlite_connect(paths.sqlite_path, timeout=8.0) as conn_w:
                    conn_w.row_factory = sqlite3.Row
                    conn_w.execute("PRAGMA foreign_keys = ON")
                    conn_w.execute("PRAGMA busy_timeout = 8000")
                    made = 0
                    system_id = ensure_system_memory(paths, schema_sql_path)
                    for link in proposed:
                        insert_link(conn_w, link)
                        evt = {
                            "event_id": make_id(),
                            "event_type": "memory.link",
                            "event_time": when,
                            "memory_id": system_id,
                            "payload": {
                                "src_id": link["src_id"],
                                "dst_id": link["dst_id"],
                                "link_type": link["link_type"],
                                "weight": link["weight"],
                                "reason": link.get("reason", ""),
                            },
                        }
                        # By default links are derived/heuristic: keep them device-local to avoid Git churn.
                        if portable:
                            append_jsonl(event_file_path(paths, datetime.now(timezone.utc)), evt)
                        insert_event(conn_w, evt)
                        made += 1
                    conn_w.commit()
                return {
                    "ok": True,
                    "project_id": project_id,
                    "made": made,
                    "considered": considered,
                    "min_weight": min_weight,
                    "limit": limit,
                    "portable": bool(portable),
                    "attempts": attempt,
                }
            except sqlite3.OperationalError as exc:
                msg = str(exc).lower()
                if "database is locked" not in msg and "database is busy" not in msg:
                    return {"ok": False, "error": str(exc)}
                if (time.time() - start) >= max_wait_s:
                    return {
                        "ok": False,
                        "error": f"database is locked (waited {max_wait_s:.1f}s); stop other omnimem processes (webui/daemon/codex wrapper) and retry",
                    }
                time.sleep(backoff)
                backoff = min(1.6, backoff * 1.6)


def retrieve_thread(
    *,
    paths: MemoryPaths,
    schema_sql_path: Path,
    query: str,
    project_id: str = "",
    session_id: str = "",
    seed_limit: int = 8,
    depth: int = 2,
    per_hop: int = 6,
    min_weight: float = 0.18,
    auto_weave: bool = True,
    auto_weave_limit: int = 220,
    auto_weave_max_wait_s: float = 2.5,
    ranking_mode: str = "hybrid",
    ppr_alpha: float = 0.85,
    ppr_iters: int = 16,
) -> dict[str, Any]:
    """Progressive, graph-aware retrieval.

    1) Seed from shallow layers (instant/short) with fuzzy matching.
    2) Expand outward along memory_links (both directions), preferring deeper layers.
    """
    ensure_storage(paths, schema_sql_path)
    seed_limit = max(1, min(30, int(seed_limit)))
    depth = max(0, min(4, int(depth)))
    per_hop = max(1, min(30, int(per_hop)))
    min_weight = max(0.0, min(1.0, float(min_weight)))
    auto_weave = bool(auto_weave)
    ranking_mode = str(ranking_mode or "hybrid").strip().lower()
    if ranking_mode not in {"path", "ppr", "hybrid"}:
        ranking_mode = "hybrid"
    ppr_alpha = max(0.10, min(0.98, float(ppr_alpha)))
    ppr_iters = max(4, min(64, int(ppr_iters)))

    # Best-effort: keep the link graph from being perpetually empty when running without a daemon.
    # Guard per home so repeated retrieves don't constantly try to weave while DB is busy.
    if auto_weave and depth > 0:
        key = str(paths.root)
        last_try = _AUTO_WEAVE_LAST_TRY.get(key, 0.0)
        if (time.time() - last_try) >= 45.0:
            _AUTO_WEAVE_LAST_TRY[key] = time.time()
            try:
                with _sqlite_connect(paths.sqlite_path, timeout=1.5) as conn0:
                    conn0.execute("PRAGMA busy_timeout = 1500")
                    n = int(conn0.execute("SELECT COUNT(*) FROM memory_links").fetchone()[0] or 0)
                if n == 0:
                    weave_links(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        project_id=project_id,
                        limit=int(auto_weave_limit),
                        min_weight=min_weight,
                        max_per_src=6,
                        include_archive=False,
                        portable=False,
                        max_wait_s=float(auto_weave_max_wait_s),
                        tool="omnimem",
                        session_id=session_id or "system",
                    )
            except Exception:
                pass

    seeds: list[dict[str, Any]] = []
    for l in ["instant", "short", "long", "archive"]:
        if len(seeds) >= seed_limit:
            break
        out = find_memories_ex(
            paths=paths,
            schema_sql_path=schema_sql_path,
            query=query,
            layer=l,
            limit=seed_limit,
            project_id=project_id,
            session_id=session_id,
        )
        for it in (out.get("items") or []):
            if len(seeds) >= seed_limit:
                break
            if not any(x.get("id") == it.get("id") for x in seeds):
                it2 = dict(it)
                it2["_seed_layer"] = l
                seeds.append(it2)

    layer_bonus = {"instant": 0.95, "short": 1.0, "long": 1.12, "archive": 1.08}

    visited: set[str] = set()
    scored: dict[str, float] = {}
    paths_explain: dict[str, list[dict[str, Any]]] = {}
    frontier: list[str] = []
    graph_edges: list[tuple[str, str, float]] = []
    for i, s in enumerate(seeds):
        mid = str(s.get("id") or "")
        if not mid:
            continue
        visited.add(mid)
        scored[mid] = max(scored.get(mid, 0.0), 1.0 - (i * 0.03))
        paths_explain[mid] = [{"hop": 0, "via": "seed", "id": mid}]
        frontier.append(mid)

    with _sqlite_connect(paths.sqlite_path, timeout=6.0) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 6000")
        for hop in range(1, depth + 1):
            if not frontier:
                break
            next_frontier: list[str] = []
            # Expand both directions: src->dst and dst->src
            placeholders = ",".join(["?"] * len(frontier))
            rows = conn.execute(
                f"""
                SELECT created_at, src_id, dst_id, link_type, weight, reason
                FROM memory_links
                WHERE (src_id IN ({placeholders}) OR dst_id IN ({placeholders}))
                  AND weight >= ?
                ORDER BY weight DESC
                """,
                (*frontier, *frontier, min_weight),
            ).fetchall()

            # Score candidates, keep best per hop.
            cand: dict[str, tuple[float, dict[str, Any]]] = {}
            for r in rows:
                w = float(r["weight"] or 0.0)
                src_id = str(r["src_id"] or "")
                dst_id = str(r["dst_id"] or "")
                if src_id and dst_id:
                    graph_edges.append((src_id, dst_id, w))
                a = src_id
                b = dst_id
                if a in frontier:
                    from_id, to_id = a, b
                elif b in frontier:
                    from_id, to_id = b, a
                else:
                    continue
                if not to_id or to_id in visited:
                    continue
                to_layer = conn.execute("SELECT layer FROM memories WHERE id = ?", (to_id,)).fetchone()
                lb = layer_bonus.get(str(to_layer[0]) if to_layer else "short", 1.0)
                base = scored.get(from_id, 0.4)
                score = base * w * lb
                cur = cand.get(to_id)
                if cur is None or score > cur[0]:
                    cand[to_id] = (
                        score,
                        {
                            "hop": hop,
                            "from_id": from_id,
                            "to_id": to_id,
                            "link_type": str(r["link_type"] or ""),
                            "weight": w,
                            "reason": str(r["reason"] or ""),
                        },
                    )

            top = sorted(cand.items(), key=lambda kv: kv[1][0], reverse=True)[: per_hop * max(1, len(frontier))]
            for to_id, (score, edge) in top[: per_hop]:
                visited.add(to_id)
                scored[to_id] = score
                paths_explain[to_id] = (paths_explain.get(edge["from_id"], []) + [edge])[-8:]
                next_frontier.append(to_id)
            frontier = next_frontier

        # HippoRAG-style graph propagation over the observed subgraph.
        if seeds and graph_edges and ranking_mode in {"ppr", "hybrid"}:
            seed_ids = [str(s.get("id") or "") for s in seeds if str(s.get("id") or "")]
            tp: dict[str, float] = {}
            for i, sid in enumerate(seed_ids):
                tp[sid] = tp.get(sid, 0.0) + max(0.0, 1.0 - (i * 0.03))
            z = sum(tp.values()) or 1.0
            for k in list(tp.keys()):
                tp[k] = tp[k] / z

            adj: dict[str, list[tuple[str, float]]] = {}
            out_sum: dict[str, float] = {}
            for a, b, w in graph_edges:
                ww = max(0.0, float(w))
                if ww <= 0.0:
                    continue
                adj.setdefault(a, []).append((b, ww))
                adj.setdefault(b, []).append((a, ww))
                out_sum[a] = out_sum.get(a, 0.0) + ww
                out_sum[b] = out_sum.get(b, 0.0) + ww

            p = dict(tp)
            for _ in range(ppr_iters):
                nxt: dict[str, float] = {k: (1.0 - ppr_alpha) * v for k, v in tp.items()}
                for src, outs in adj.items():
                    ps = p.get(src, 0.0)
                    if ps <= 0.0:
                        continue
                    denom = out_sum.get(src, 0.0) or 1.0
                    for dst, w in outs:
                        nxt[dst] = nxt.get(dst, 0.0) + (ppr_alpha * ps * (w / denom))
                p = nxt

            max_p = max([float(v) for v in p.values()] + [1e-9])
            for mid, pv in p.items():
                ppr = float(pv) / max_p
                base = float(scored.get(mid, 0.0))
                if ranking_mode == "ppr":
                    scored[mid] = ppr
                elif ranking_mode == "hybrid":
                    scored[mid] = (0.62 * base) + (0.38 * ppr)

        # Materialize items.
        ids = sorted(scored.keys(), key=lambda k: scored[k], reverse=True)[: max(seed_limit, 12)]
        if not ids:
            return {"ok": True, "query": query, "items": [], "explain": {"seeds": seeds, "paths": {}}}
        placeholders = ",".join(["?"] * len(ids))
        rows2 = conn.execute(
            f"""
            SELECT id, layer, kind, summary, updated_at, body_md_path,
                   COALESCE(json_extract(scope_json, '$.project_id'), '') AS project_id,
                   COALESCE(json_extract(source_json, '$.session_id'), '') AS session_id,
                   importance_score, confidence_score, stability_score, reuse_count, volatility_score
            FROM memories
            WHERE id IN ({placeholders})
            """,
            tuple(ids),
        ).fetchall()
        out_items = []
        for r in rows2:
            d = _signals_from_row(dict(r))
            d["score"] = float(round(scored.get(str(d.get("id")), 0.0), 6))
            out_items.append(d)
        out_items.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

    return {
        "ok": True,
        "query": query,
        "items": out_items,
        "explain": {
            "ranking_mode": ranking_mode,
            "ppr_alpha": ppr_alpha,
            "ppr_iters": ppr_iters,
            "seeds": seeds,
            "paths": {k: v for k, v in paths_explain.items() if k in {x.get("id") for x in out_items}},
        },
    }


def build_brief(paths: MemoryPaths, schema_sql_path: Path, project_id: str, limit: int) -> dict[str, Any]:
    ensure_storage(paths, schema_sql_path)
    with _sqlite_connect(paths.sqlite_path) as conn:
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

    with _sqlite_connect(paths.sqlite_path) as conn:
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
    maintenance_consolidate_limit: int = 80,
    maintenance_compress_sessions: int = 2,
    maintenance_compress_min_items: int = 8,
    maintenance_distill_enabled: bool = True,
    maintenance_distill_sessions: int = 1,
    maintenance_distill_min_items: int = 12,
    maintenance_temporal_tree_enabled: bool = True,
    maintenance_temporal_tree_days: int = 30,
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
                last_maintenance_result = {
                    "ok": bool(decay_out.get("ok") and cons_out.get("ok") and comp_out.get("ok")),
                    "decay": decay_out,
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
    }
    log_system_event(paths, schema_sql_path, "memory.sync", {"daemon": result}, portable=False)
    return result
