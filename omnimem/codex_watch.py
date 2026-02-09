from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import load_config, resolve_paths, sha256_text, write_memory


_SENSITIVE_RE = re.compile(
    r"(?i)("
    r"BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY"
    r"|AKIA[0-9A-Z]{16}"
    r"|ASIA[0-9A-Z]{16}"
    r"|sk-[A-Za-z0-9]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|authorization:\\s*bearer\\s+[A-Za-z0-9._-]{10,}"
    r"|api[_-]?key\\s*[:=]\\s*[A-Za-z0-9._-]{8,}"
    r"|secret\\s*[:=]\\s*[A-Za-z0-9._-]{8,}"
    r"|password\\s*[:=]\\s*.+"
    r")"
)


def _looks_sensitive(text: str) -> bool:
    return bool(_SENSITIVE_RE.search(text or ""))


def _extract_text(msg: dict[str, Any], *, allow_types: set[str]) -> str:
    out = []
    for c in msg.get("content") or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") in allow_types:
            out.append(str(c.get("text", "")))
    return "".join(out).strip()


def _schema_sql_path() -> Path:
    # Local helper to avoid importing omnimem.cli (which is heavy and CLI-specific).
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


@dataclass
class WatchOptions:
    project_id: str
    tool: str = "codex"
    workspace: str = ""
    # Only store assistant messages longer than this (helps avoid storing progress chatter).
    min_chars: int = 280
    # Upper bound on stored body size (protects DB/FTS from huge transcripts).
    max_body_chars: int = 12000
    # Poll interval for session file discovery/read.
    poll_s: float = 0.5


def watch_codex_sessions_and_write(
    *,
    stop: threading.Event,
    started_at: datetime,
    opts: WatchOptions,
    cfg_path: Path | None = None,
) -> None:
    """
    Best-effort background writer:
    - watches ~/.codex/sessions/**.jsonl created/updated after started_at
    - matches sessions by cwd == opts.workspace when provided
    - on assistant messages, writes a short memory (unless it looks sensitive)

    This does NOT inject memory back into Codex; it only improves write-side capture while keeping native UX.
    """
    sessions_root = Path.home() / ".codex" / "sessions"
    if not sessions_root.exists():
        return

    started_ts = started_at.replace(tzinfo=timezone.utc).timestamp()
    cfg = load_config(cfg_path)
    paths = resolve_paths(cfg)
    schema = _schema_sql_path()

    # Track per-file read offsets so we can tail multiple session logs.
    offsets: dict[str, int] = {}
    # Track accepted files (match cwd) -> codex session id, last user message, last assistant sha.
    state: dict[str, dict[str, Any]] = {}

    def iter_candidate_files() -> list[Path]:
        # Restrict scan to last 2 days to keep polling cheap.
        # Structure: ~/.codex/sessions/YYYY/MM/DD/*.jsonl
        out: list[Path] = []
        # Compute date folders explicitly to avoid DST/local time surprises.
        for delta_days in range(0, 2):
            day = datetime.now(timezone.utc).date().toordinal() - delta_days
            dt = datetime.fromordinal(day).replace(tzinfo=timezone.utc)
            y = f"{dt.year:04d}"
            m = f"{dt.month:02d}"
            dd = f"{dt.day:02d}"
            folder = sessions_root / y / m / dd
            if not folder.exists():
                continue
            out.extend(folder.glob("*.jsonl"))
        out.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return out[:200]

    while not stop.is_set():
        try:
            for fp in iter_candidate_files():
                try:
                    st = fp.stat()
                except FileNotFoundError:
                    continue
                if st.st_mtime < started_ts - 2:
                    continue

                key = str(fp)
                off = offsets.get(key, 0)
                try:
                    with fp.open("r", encoding="utf-8") as f:
                        if off:
                            f.seek(off)
                        for line in f:
                            off = f.tell()
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except Exception:
                                continue

                            typ = obj.get("type")
                            payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}

                            # Discover session meta (cwd + id)
                            if typ == "session_meta":
                                pl = payload if isinstance(payload, dict) else {}
                                sid = str((pl.get("id") or "")).strip()
                                cwd = str((pl.get("cwd") or "")).strip()
                                if not sid:
                                    continue
                                if opts.workspace and cwd and Path(cwd).resolve() != Path(opts.workspace).resolve():
                                    # This file isn't for the session we care about.
                                    state[key] = {"ignore": True}
                                    continue
                                state.setdefault(key, {})
                                state[key]["session_id"] = sid
                                state[key]["cwd"] = cwd
                                continue

                            # Skip non-matching files as early as possible.
                            if state.get(key, {}).get("ignore"):
                                continue

                            if typ != "response_item":
                                continue
                            msg = payload if isinstance(payload, dict) else {}
                            if msg.get("type") != "message":
                                continue

                            role = str(msg.get("role") or "").strip()
                            if role == "user":
                                txt = _extract_text(msg, allow_types={"input_text", "output_text"})
                                if txt:
                                    state.setdefault(key, {})
                                    state[key]["last_user"] = txt
                                continue

                            if role != "assistant":
                                continue

                            sid = str(state.get(key, {}).get("session_id") or "").strip() or "session-unknown"
                            user_txt = str(state.get(key, {}).get("last_user") or "").strip()
                            asst_txt = _extract_text(msg, allow_types={"output_text"})
                            if not asst_txt or len(asst_txt) < int(opts.min_chars):
                                continue
                            if _looks_sensitive(user_txt) or _looks_sensitive(asst_txt):
                                continue

                            # Dedup: content hash.
                            h = sha256_text(asst_txt)
                            if h == state.get(key, {}).get("last_asst_sha"):
                                continue
                            state.setdefault(key, {})
                            state[key]["last_asst_sha"] = h

                            # Construct memory payload.
                            summary = (user_txt.strip().splitlines()[0] if user_txt else "codex turn")[:120]
                            body = (
                                "Auto-captured Codex turn.\n\n"
                                f"- codex_session_id: {sid}\n"
                                f"- workspace: {opts.workspace}\n\n"
                                f"## User\n{user_txt}\n\n"
                                f"## Assistant\n{asst_txt}\n"
                            )
                            if len(body) > int(opts.max_body_chars):
                                body = body[: int(opts.max_body_chars)] + "\n\n(truncated)\n"

                            write_memory(
                                paths=paths,
                                schema_sql_path=schema,
                                layer="short",
                                kind="summary",
                                summary=f"Codex: {summary}",
                                body=body,
                                tags=[f"project:{opts.project_id}", "auto:codex-watch", "tool:codex"],
                                refs=[],
                                cred_refs=[],
                                tool="codex",
                                account="default",
                                device="local",
                                session_id=sid,
                                project_id=opts.project_id,
                                workspace=opts.workspace or "",
                                importance=0.55,
                                confidence=0.6,
                                stability=0.45,
                                reuse_count=0,
                                volatility=0.55,
                                event_type="memory.write",
                            )

                finally:
                    offsets[key] = off
        except Exception:
            # Best-effort background job: never crash the parent process.
            pass

        stop.wait(timeout=max(0.1, float(opts.poll_s)))


def _parse_iso_utc(s: str) -> datetime:
    # Accepts "2026-02-09T11:14:54Z" or "+00:00" forms.
    v = (s or "").strip()
    if not v:
        return datetime.now(timezone.utc)
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except Exception:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m omnimem.codex_watch")
    p.add_argument("--project-id", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--parent-pid", type=int, required=True)
    p.add_argument("--started-at", default="")
    p.add_argument("--config")
    p.add_argument("--poll-s", type=float, default=0.5)
    p.add_argument("--min-chars", type=int, default=280)
    p.add_argument("--max-body-chars", type=int, default=12000)
    args = p.parse_args(list(argv) if argv is not None else None)

    started_at = _parse_iso_utc(args.started_at)
    cfg_path = Path(args.config).expanduser().resolve() if args.config else None

    stop = threading.Event()

    def parent_watch() -> None:
        # Stop when the parent (which becomes codex via exec) exits.
        while not stop.is_set():
            try:
                os.kill(int(args.parent_pid), 0)
            except Exception:
                stop.set()
                break
            time.sleep(0.8)

    threading.Thread(target=parent_watch, name="omnimem-codex-watch-parent", daemon=True).start()
    watch_codex_sessions_and_write(
        stop=stop,
        started_at=started_at,
        opts=WatchOptions(
            project_id=str(args.project_id),
            tool="codex",
            workspace=str(args.workspace),
            min_chars=int(args.min_chars),
            max_body_chars=int(args.max_body_chars),
            poll_s=float(args.poll_s),
        ),
        cfg_path=cfg_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
