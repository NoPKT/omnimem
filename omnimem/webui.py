from __future__ import annotations

from contextlib import contextmanager
import json
import os
import re
try:
    import resource
except ImportError:
    resource = None  # type: ignore[assignment]
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import traceback
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
import urllib.error
import urllib.request

from . import __version__ as OMNIMEM_VERSION
from .core import (
    LAYER_SET,
    analyze_profile_drift,
    apply_decay,
    apply_memory_feedback,
    build_user_profile,
    compress_hot_sessions,
    compress_session_context,
    consolidate_memories,
    ensure_storage,
    find_memories,
    get_core_block,
    infer_adaptive_governance_thresholds,
    list_core_blocks,
    move_memory_layer,
    retrieve_thread,
    upsert_core_block,
    update_memory_content,
    resolve_paths,
    save_config,
    sync_error_hint,
    utc_now,
    write_memory,
)


def _load_html_page() -> str:
    """Load the WebUI HTML from a static file with safe fallbacks."""
    candidates: list[Path] = []

    # PyInstaller bundle paths.
    base = getattr(sys, "_MEIPASS", None)
    if base:
        bundle_root = Path(base)
        candidates.append(bundle_root / "omnimem" / "static" / "index.html")
        candidates.append(bundle_root / "static" / "index.html")

    # Source / wheel package path.
    candidates.append(Path(__file__).resolve().parent / "static" / "index.html")

    for p in candidates:
        try:
            if p.exists():
                return p.read_text(encoding="utf-8")
        except Exception:
            continue

    # Keep CLI importable even if static assets are unavailable.
    return (
        "<!doctype html><html><head><meta charset='utf-8'/>"
        "<title>OmniMem WebUI</title></head>"
        "<body><h1>OmniMem WebUI</h1><p>WebUI static assets not found.</p></body></html>"
    )


HTML_PAGE = _load_html_page()


def _cfg_to_ui(cfg: dict[str, Any], cfg_path: Path) -> dict[str, Any]:
    storage = cfg.get("storage", {})
    gh = cfg.get("sync", {}).get("github", {})
    dm = cfg.get("daemon", {})
    wu = cfg.get("webui", {})
    return {
        "ok": True,
        "initialized": cfg_path.exists(),
        "config_path": str(cfg_path),
        "home": cfg.get("home", ""),
        "markdown": storage.get("markdown", ""),
        "jsonl": storage.get("jsonl", ""),
        "sqlite": storage.get("sqlite", ""),
        "remote_name": gh.get("remote_name", "origin"),
        "remote_url": gh.get("remote_url", ""),
        "branch": gh.get("branch", "main"),
        "gh_oauth_client_id": gh.get("oauth", {}).get("client_id", "") if isinstance(gh.get("oauth"), dict) else "",
        "gh_oauth_broker_url": gh.get("oauth", {}).get("broker_url", "") if isinstance(gh.get("oauth"), dict) else "",
        "sync_include_layers": ",".join([str(x).strip() for x in (gh.get("include_layers") or []) if str(x).strip()]),
        "sync_include_jsonl": bool(gh.get("include_jsonl", True)),
        "daemon_scan_interval": dm.get("scan_interval", 8),
        "daemon_pull_interval": dm.get("pull_interval", 30),
        "daemon_retry_max_attempts": dm.get("retry_max_attempts", 3),
        "daemon_retry_initial_backoff": dm.get("retry_initial_backoff", 1),
        "daemon_retry_max_backoff": dm.get("retry_max_backoff", 8),
        "daemon_maintenance_enabled": dm.get("maintenance_enabled", True),
        "daemon_maintenance_interval": dm.get("maintenance_interval", 300),
        "daemon_maintenance_decay_days": dm.get("maintenance_decay_days", 14),
        "daemon_maintenance_decay_limit": dm.get("maintenance_decay_limit", 120),
        "daemon_maintenance_prune_enabled": dm.get("maintenance_prune_enabled", False),
        "daemon_maintenance_prune_days": dm.get("maintenance_prune_days", 45),
        "daemon_maintenance_prune_limit": dm.get("maintenance_prune_limit", 300),
        "daemon_maintenance_prune_layers": ",".join(
            [str(x).strip() for x in (dm.get("maintenance_prune_layers") or ["instant", "short"]) if str(x).strip()]
        ),
        "daemon_maintenance_prune_keep_kinds": ",".join(
            [str(x).strip() for x in (dm.get("maintenance_prune_keep_kinds") or ["decision", "checkpoint"]) if str(x).strip()]
        ),
        "daemon_maintenance_consolidate_limit": dm.get("maintenance_consolidate_limit", 80),
        "daemon_maintenance_compress_sessions": dm.get("maintenance_compress_sessions", 2),
        "daemon_maintenance_compress_min_items": dm.get("maintenance_compress_min_items", 8),
        "daemon_maintenance_temporal_tree_enabled": dm.get("maintenance_temporal_tree_enabled", True),
        "daemon_maintenance_temporal_tree_days": dm.get("maintenance_temporal_tree_days", 30),
        "daemon_maintenance_rehearsal_enabled": dm.get("maintenance_rehearsal_enabled", True),
        "daemon_maintenance_rehearsal_days": dm.get("maintenance_rehearsal_days", 45),
        "daemon_maintenance_rehearsal_limit": dm.get("maintenance_rehearsal_limit", 16),
        "daemon_maintenance_reflection_enabled": dm.get("maintenance_reflection_enabled", True),
        "daemon_maintenance_reflection_days": dm.get("maintenance_reflection_days", 14),
        "daemon_maintenance_reflection_limit": dm.get("maintenance_reflection_limit", 4),
        "daemon_maintenance_reflection_min_repeats": dm.get("maintenance_reflection_min_repeats", 2),
        "daemon_maintenance_reflection_max_avg_retrieved": dm.get("maintenance_reflection_max_avg_retrieved", 2.0),
        "webui_approval_required": bool(wu.get("approval_required", False)),
        "webui_maintenance_preview_only_until": str(wu.get("maintenance_preview_only_until", "")),
    }


def _normalize_github_full_name(owner: str, repo: str, full_name: str) -> str:
    f = str(full_name or "").strip().strip("/")
    if f:
        if "/" not in f:
            raise ValueError("full_name must be in owner/repo format")
        a, b = [x.strip() for x in f.split("/", 1)]
        if not a or not b:
            raise ValueError("full_name must be in owner/repo format")
        return f"{a}/{b}"
    a = str(owner or "").strip().strip("/")
    b = str(repo or "").strip().strip("/")
    if not a or not b:
        raise ValueError("owner and repo are required")
    return f"{a}/{b}"


def _build_github_remote_url(full_name: str, protocol: str) -> str:
    proto = str(protocol or "ssh").strip().lower()
    if proto == "https":
        return f"https://github.com/{full_name}.git"
    return f"git@github.com:{full_name}.git"


def _github_home_dir(cfg: dict[str, Any]) -> Path:
    raw = str(cfg.get("home", "")).strip()
    if raw:
        return Path(raw).expanduser()
    return (Path.home() / ".omnimem").expanduser()


def _github_oauth_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    sync = cfg.setdefault("sync", {})
    if not isinstance(sync, dict):
        sync = {}
        cfg["sync"] = sync
    gh = sync.setdefault("github", {})
    if not isinstance(gh, dict):
        gh = {}
        sync["github"] = gh
    oauth = gh.setdefault("oauth", {})
    if not isinstance(oauth, dict):
        oauth = {}
        gh["oauth"] = oauth
    return oauth


def _github_oauth_client_id(cfg: dict[str, Any], client_id: str = "") -> str:
    c = str(client_id or "").strip()
    if c:
        return c
    env_c = str(os.environ.get("OMNIMEM_GITHUB_OAUTH_CLIENT_ID", "")).strip()
    if env_c:
        return env_c
    return str(cfg.get("sync", {}).get("github", {}).get("oauth", {}).get("client_id", "")).strip()


def _normalize_broker_url(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "https://" + s
    try:
        p = urlparse(s)
    except Exception:
        return ""
    if p.scheme not in {"http", "https"} or not p.netloc:
        return ""
    return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")


def _github_oauth_broker_url(cfg: dict[str, Any], broker_url: str = "") -> str:
    b = _normalize_broker_url(broker_url)
    if b:
        return b
    env_b = _normalize_broker_url(str(os.environ.get("OMNIMEM_GITHUB_OAUTH_BROKER_URL", "")).strip())
    if env_b:
        return env_b
    return _normalize_broker_url(str(cfg.get("sync", {}).get("github", {}).get("oauth", {}).get("broker_url", "")).strip())


def _github_oauth_token_file(cfg: dict[str, Any]) -> Path:
    oauth = cfg.get("sync", {}).get("github", {}).get("oauth", {})
    raw = str((oauth or {}).get("token_file", "")).strip() if isinstance(oauth, dict) else ""
    if raw:
        return Path(raw).expanduser()
    return _github_home_dir(cfg) / "runtime" / "github_oauth_token.json"


def _read_github_oauth_token(cfg: dict[str, Any]) -> dict[str, Any]:
    fp = _github_oauth_token_file(cfg)
    if not fp.exists():
        return {}
    try:
        obj = json.loads(fp.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return {}
        return obj
    except Exception:
        return {}


def _write_github_oauth_token(cfg: dict[str, Any], payload: dict[str, Any]) -> Path:
    fp = _github_oauth_token_file(cfg)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(fp, 0o600)
    except Exception:
        pass
    return fp


def _github_api_request(
    *,
    method: str,
    url: str,
    token: str = "",
    form: dict[str, Any] | None = None,
    json_payload: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "omnimem-webui",
    }
    data: bytes | None = None
    if str(token or "").strip():
        headers["Authorization"] = f"Bearer {str(token).strip()}"
    if form is not None:
        data = urlencode({k: str(v) for k, v in form.items()}).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif json_payload is not None:
        data = json.dumps(json_payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            raw = json.loads(body) if body.strip() else {}
            return {"ok": True, "status": int(resp.status), "json": raw}
    except urllib.error.HTTPError as exc:
        body = (exc.read() or b"").decode("utf-8", errors="ignore")
        try:
            raw = json.loads(body) if body.strip() else {}
        except Exception:
            raw = {"message": body[:1200]}
        return {"ok": False, "status": int(exc.code), "json": raw, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "status": 0, "json": {}, "error": str(exc)}


def _github_oauth_broker_request(
    *,
    broker_url: str,
    action: str,
    payload: dict[str, Any],
    timeout: float = 15.0,
) -> dict[str, Any]:
    base = _normalize_broker_url(broker_url)
    if not base:
        return {"ok": False, "status": 0, "json": {}, "error": "invalid broker_url"}
    path = "/v1/github/device/start" if action == "start" else "/v1/github/device/poll"
    return _github_api_request(
        method="POST",
        url=f"{base}{path}",
        json_payload=payload,
        timeout=timeout,
    )


def _github_oauth_status(cfg: dict[str, Any]) -> dict[str, Any]:
    oauth = cfg.get("sync", {}).get("github", {}).get("oauth", {})
    token_obj = _read_github_oauth_token(cfg)
    token = str(token_obj.get("access_token") or "").strip()
    pending = bool(str((oauth or {}).get("device_code", "")).strip()) if isinstance(oauth, dict) else False
    broker_url = _github_oauth_broker_url(cfg)
    client_id = _github_oauth_client_id(cfg)
    return {
        "configured": bool(client_id or broker_url),
        "authenticated": bool(token),
        "pending": pending and not bool(token),
        "token_file": str(_github_oauth_token_file(cfg)),
        "scope": str(token_obj.get("scope") or ""),
        "updated_at": str(token_obj.get("updated_at") or ""),
        "broker_url": broker_url,
        "mode": "broker" if broker_url else ("direct" if client_id else "none"),
    }


def _github_status(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    gh = shutil.which("gh")
    oauth_info = _github_oauth_status(cfg or {}) if isinstance(cfg, dict) else {
        "configured": False,
        "authenticated": False,
        "pending": False,
        "token_file": "",
        "scope": "",
        "updated_at": "",
    }
    if not gh:
        return {
            "ok": True,
            "installed": False,
            "authenticated": bool(oauth_info.get("authenticated", False)),
            "auth_source": "oauth-device" if bool(oauth_info.get("authenticated", False)) else "none",
            "oauth": oauth_info,
        }
    try:
        cp = subprocess.run(
            [gh, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        txt = (cp.stdout or "") + "\n" + (cp.stderr or "")
        gh_auth = bool(cp.returncode == 0)
        oauth_auth = bool(oauth_info.get("authenticated", False))
        return {
            "ok": True,
            "installed": True,
            "authenticated": bool(gh_auth or oauth_auth),
            "auth_source": "gh" if gh_auth else ("oauth-device" if oauth_auth else "none"),
            "gh_authenticated": gh_auth,
            "details": txt.strip()[:1200],
            "oauth": oauth_info,
        }
    except Exception as exc:
        return {
            "ok": True,
            "installed": True,
            "authenticated": bool(oauth_info.get("authenticated", False)),
            "auth_source": "oauth-device" if bool(oauth_info.get("authenticated", False)) else "none",
            "error": str(exc),
            "oauth": oauth_info,
        }


def _github_repo_list(*, cfg: dict[str, Any] | None = None, query: str = "", limit: int = 50) -> dict[str, Any]:
    if isinstance(cfg, dict):
        tok = str(_read_github_oauth_token(cfg).get("access_token") or "").strip()
    else:
        tok = ""
    n = max(1, min(200, int(limit)))
    if tok:
        url = f"https://api.github.com/user/repos?per_page={min(100, n)}&sort=updated&direction=desc"
        resp = _github_api_request(method="GET", url=url, token=tok, timeout=20)
        if not bool(resp.get("ok")):
            return {
                "ok": True,
                "installed": False,
                "authenticated": False,
                "items": [],
                "source": "oauth-device",
                "error": str((resp.get("json") or {}).get("message") or resp.get("error") or "oauth api failed")[:1200],
            }
        raw_items = resp.get("json") if isinstance(resp.get("json"), list) else []
        q = str(query or "").strip().lower()
        items: list[dict[str, Any]] = []
        for it in raw_items:
            if not isinstance(it, dict):
                continue
            name = str(it.get("full_name") or "").strip()
            if not name:
                continue
            if q and q not in name.lower():
                continue
            items.append(
                {
                    "full_name": name,
                    "private": bool(it.get("private", False)),
                    "permission": str((it.get("permissions") or {}).get("admin", False)),
                    "url": str(it.get("html_url") or ""),
                }
            )
        return {
            "ok": True,
            "installed": False,
            "authenticated": True,
            "count": len(items),
            "items": items[:n],
            "source": "oauth-device",
        }

    gh = shutil.which("gh")
    if not gh:
        return {"ok": True, "installed": False, "authenticated": False, "items": []}
    try:
        cp = subprocess.run(
            [gh, "repo", "list", "--limit", str(n), "--json", "nameWithOwner,isPrivate,viewerPermission,url"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if int(cp.returncode) != 0:
            txt = ((cp.stderr or "") + "\n" + (cp.stdout or "")).strip()
            return {
                "ok": True,
                "installed": True,
                "authenticated": False,
                "items": [],
                "error": txt[:1200],
            }
        raw_items = json.loads(cp.stdout or "[]")
        q = str(query or "").strip().lower()
        items: list[dict[str, Any]] = []
        for it in raw_items if isinstance(raw_items, list) else []:
            name = str((it or {}).get("nameWithOwner") or "").strip()
            if not name:
                continue
            if q and q not in name.lower():
                continue
            items.append(
                {
                    "full_name": name,
                    "private": bool((it or {}).get("isPrivate", False)),
                    "permission": str((it or {}).get("viewerPermission") or ""),
                    "url": str((it or {}).get("url") or ""),
                }
            )
        items.sort(key=lambda x: str(x.get("full_name") or "").lower())
        return {
            "ok": True,
            "installed": True,
            "authenticated": True,
            "count": len(items),
            "items": items[:n],
            "source": "gh",
        }
    except Exception as exc:
        return {"ok": True, "installed": True, "authenticated": False, "items": [], "error": str(exc)}


def _github_setup_plan(*, cfg: dict[str, Any], initialized: bool) -> dict[str, Any]:
    gh = cfg.get("sync", {}).get("github", {}) if isinstance(cfg, dict) else {}
    oauth = gh.get("oauth", {}) if isinstance(gh, dict) else {}
    status = _github_status(cfg)
    oauth_status = status.get("oauth", {}) if isinstance(status.get("oauth"), dict) else {}
    has_remote = bool(str(gh.get("remote_url", "") or "").strip()) if isinstance(gh, dict) else False
    has_client_id = bool(str(oauth.get("client_id", "") or "").strip()) if isinstance(oauth, dict) else False
    has_broker = bool(str(oauth.get("broker_url", "") or "").strip()) if isinstance(oauth, dict) else False
    pending = bool(oauth_status.get("pending", False))
    authenticated = bool(status.get("authenticated", False))
    full_name_hint = str(gh.get("remote_url", "") or "").strip()
    migration_recommended = bool(initialized and has_remote and not authenticated and not has_client_id and not has_broker)

    if not initialized:
        return {
            "ok": True,
            "next_action": "save_config",
            "next_hint": "Save configuration first to initialize this install.",
            "migration_recommended": False,
            "status": {
                "initialized": False,
                "authenticated": authenticated,
                "remote_configured": has_remote,
                "broker_configured": has_broker,
                "client_id_configured": has_client_id,
                "oauth_pending": pending,
                "remote_url": full_name_hint,
            },
        }
    if pending:
        return {
            "ok": True,
            "next_action": "oauth_poll",
            "next_hint": "Complete OAuth polling to finish authentication.",
            "migration_recommended": migration_recommended,
            "status": {
                "initialized": True,
                "authenticated": authenticated,
                "remote_configured": has_remote,
                "broker_configured": has_broker,
                "client_id_configured": has_client_id,
                "oauth_pending": True,
                "remote_url": full_name_hint,
            },
        }
    if not authenticated:
        return {
            "ok": True,
            "next_action": "oauth_start",
            "next_hint": "Sign in with GitHub OAuth next.",
            "migration_recommended": migration_recommended,
            "status": {
                "initialized": True,
                "authenticated": False,
                "remote_configured": has_remote,
                "broker_configured": has_broker,
                "client_id_configured": has_client_id,
                "oauth_pending": False,
                "remote_url": full_name_hint,
            },
        }
    if not has_remote:
        return {
            "ok": True,
            "next_action": "repos_load",
            "next_hint": "Load repo list and select a repository next.",
            "migration_recommended": False,
            "status": {
                "initialized": True,
                "authenticated": True,
                "remote_configured": False,
                "broker_configured": has_broker,
                "client_id_configured": has_client_id,
                "oauth_pending": False,
                "remote_url": "",
            },
        }
    return {
        "ok": True,
        "next_action": "done",
        "next_hint": "GitHub setup is complete.",
        "migration_recommended": False,
        "status": {
            "initialized": True,
            "authenticated": True,
            "remote_configured": True,
            "broker_configured": has_broker,
            "client_id_configured": has_client_id,
            "oauth_pending": False,
            "remote_url": full_name_hint,
        },
    }


def _github_oauth_start(
    *,
    cfg: dict[str, Any],
    cfg_path: Path,
    client_id: str = "",
    broker_url: str = "",
    scope: str = "repo",
) -> dict[str, Any]:
    b_url = _github_oauth_broker_url(cfg, broker_url=broker_url)
    if b_url:
        req = _github_oauth_broker_request(
            broker_url=b_url,
            action="start",
            payload={"scope": str(scope or "repo"), "client_id": str(client_id or "").strip()},
            timeout=12,
        )
        if not bool(req.get("ok")):
            msg = str((req.get("json") or {}).get("error") or (req.get("json") or {}).get("message") or req.get("error") or "broker start failed")
            return {"ok": False, "error": msg[:1200]}
        data = req.get("json") if isinstance(req.get("json"), dict) else {}
        device_code = str(data.get("device_code") or "").strip()
        user_code = str(data.get("user_code") or "").strip()
        if not device_code or not user_code:
            return {"ok": False, "error": "broker start missing device_code/user_code"}
        interval = max(2, int(data.get("interval", 5) or 5))
        expires_in = max(interval, int(data.get("expires_in", 900) or 900))
        oauth = _github_oauth_cfg(cfg)
        if str(data.get("client_id") or "").strip():
            oauth["client_id"] = str(data.get("client_id") or "").strip()
        oauth["broker_url"] = b_url
        oauth["scope"] = str(scope or "repo").strip() or "repo"
        oauth["device_code"] = device_code
        oauth["user_code"] = user_code
        oauth["verification_uri"] = str(data.get("verification_uri") or "https://github.com/login/device")
        oauth["verification_uri_complete"] = str(data.get("verification_uri_complete") or "")
        oauth["interval"] = int(interval)
        oauth["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).replace(microsecond=0).isoformat()
        save_config(cfg_path, cfg)
        return {
            "ok": True,
            "started": True,
            "auth_method": "oauth-device",
            "oauth_source": "broker",
            "user_code": oauth["user_code"],
            "verification_uri": oauth["verification_uri"],
            "verification_uri_complete": oauth.get("verification_uri_complete", ""),
            "interval": oauth["interval"],
            "expires_at": oauth["expires_at"],
            "hint": "Open verification_uri, authorize app, then click Complete OAuth Login.",
        }

    cid = _github_oauth_client_id(cfg, client_id=client_id)
    if not cid:
        return {
            "ok": False,
            "error": "missing GitHub OAuth client_id (set in WebUI field or OMNIMEM_GITHUB_OAUTH_CLIENT_ID)",
        }
    req = _github_api_request(
        method="POST",
        url="https://github.com/login/device/code",
        form={"client_id": cid, "scope": str(scope or "repo")},
        timeout=12,
    )
    if not bool(req.get("ok")):
        msg = str((req.get("json") or {}).get("error_description") or (req.get("json") or {}).get("message") or req.get("error") or "oauth start failed")
        return {"ok": False, "error": msg[:1200]}
    data = req.get("json") if isinstance(req.get("json"), dict) else {}
    device_code = str(data.get("device_code") or "").strip()
    user_code = str(data.get("user_code") or "").strip()
    if not device_code or not user_code:
        return {"ok": False, "error": "oauth device flow did not return expected device_code/user_code"}
    interval = max(2, int(data.get("interval", 5) or 5))
    expires_in = max(interval, int(data.get("expires_in", 900) or 900))
    oauth = _github_oauth_cfg(cfg)
    oauth["client_id"] = cid
    oauth["broker_url"] = ""
    oauth["scope"] = str(scope or "repo").strip() or "repo"
    oauth["device_code"] = device_code
    oauth["user_code"] = user_code
    oauth["verification_uri"] = str(data.get("verification_uri") or "https://github.com/login/device")
    oauth["verification_uri_complete"] = str(data.get("verification_uri_complete") or "")
    oauth["interval"] = int(interval)
    oauth["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    ).replace(microsecond=0).isoformat()
    save_config(cfg_path, cfg)
    return {
        "ok": True,
        "started": True,
        "auth_method": "oauth-device",
        "oauth_source": "direct",
        "user_code": oauth["user_code"],
        "verification_uri": oauth["verification_uri"],
        "verification_uri_complete": oauth.get("verification_uri_complete", ""),
        "interval": oauth["interval"],
        "expires_at": oauth["expires_at"],
        "hint": "Open verification_uri, authorize app, then click Complete OAuth Login.",
    }


def _github_oauth_poll(*, cfg: dict[str, Any], cfg_path: Path) -> dict[str, Any]:
    oauth = _github_oauth_cfg(cfg)
    cid = _github_oauth_client_id(cfg, client_id=str(oauth.get("client_id", "")))
    dcode = str(oauth.get("device_code") or "").strip()
    b_url = _github_oauth_broker_url(cfg, broker_url=str(oauth.get("broker_url", "")))
    retry_after = max(2, int(oauth.get("interval", 5) or 5))
    if not dcode:
        return {"ok": False, "error": "oauth device flow is not started"}
    if b_url:
        req = _github_oauth_broker_request(
            broker_url=b_url,
            action="poll",
            payload={"device_code": dcode, "client_id": cid},
            timeout=15,
        )
    else:
        if not cid:
            return {"ok": False, "error": "missing oauth client_id for direct poll"}
        req = _github_api_request(
            method="POST",
            url="https://github.com/login/oauth/access_token",
            form={
                "client_id": cid,
                "device_code": dcode,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=15,
        )
    data = req.get("json") if isinstance(req.get("json"), dict) else {}
    access_token = str((data or {}).get("access_token") or "").strip()
    if not access_token:
        err = str((data or {}).get("error") or "authorization_pending").strip()
        desc = str((data or {}).get("error_description") or err).strip()
        if err in {"authorization_pending", "slow_down"}:
            if err == "slow_down":
                retry_after = max(retry_after, 7)
            return {"ok": True, "pending": True, "error": desc[:800], "retry_after": int(retry_after)}
        return {"ok": False, "error": desc[:1200]}
    token_payload = {
        "provider": "github",
        "access_token": access_token,
        "token_type": str((data or {}).get("token_type") or "bearer"),
        "scope": str((data or {}).get("scope") or oauth.get("scope") or ""),
        "updated_at": utc_now(),
    }
    token_path = _write_github_oauth_token(cfg, token_payload)
    oauth["token_file"] = str(token_path)
    oauth["client_id"] = cid
    oauth["authenticated_at"] = utc_now()
    oauth.pop("device_code", None)
    oauth.pop("user_code", None)
    oauth.pop("verification_uri", None)
    oauth.pop("verification_uri_complete", None)
    oauth.pop("interval", None)
    oauth.pop("expires_at", None)
    save_config(cfg_path, cfg)
    return {
        "ok": True,
        "authenticated": True,
        "auth_method": "oauth-device",
        "oauth_source": "broker" if b_url else "direct",
        "token_file": str(token_path),
        "scope": str(token_payload.get("scope") or ""),
    }


def _github_auth_start(
    *,
    cfg: dict[str, Any],
    cfg_path: Path,
    protocol: str = "https",
    client_id: str = "",
    broker_url: str = "",
) -> dict[str, Any]:
    b_url = _github_oauth_broker_url(cfg, broker_url=broker_url)
    cid = _github_oauth_client_id(cfg, client_id=client_id)
    if cid or b_url:
        return _github_oauth_start(cfg=cfg, cfg_path=cfg_path, client_id=cid, broker_url=b_url, scope="repo")
    gh = shutil.which("gh")
    if not gh:
        return {"ok": False, "error": "gh CLI is not installed and neither OAuth client_id nor broker_url is configured"}
    proto = str(protocol or "https").strip().lower()
    if proto not in {"https", "ssh"}:
        proto = "https"
    status = _github_status(cfg)
    if bool(status.get("authenticated", False)):
        return {"ok": True, "already_authenticated": True}
    cmd = [gh, "auth", "login", "--hostname", "github.com", "--git-protocol", proto, "--web"]
    if proto == "ssh":
        cmd.append("--skip-ssh-key")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {
            "ok": True,
            "started": True,
            "auth_method": "gh",
            "pid": int(proc.pid),
            "protocol": proto,
            "hint": "Complete authentication in browser, then click Check GitHub Auth.",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _github_quick_setup(
    *,
    cfg: dict[str, Any],
    cfg_path: Path,
    owner: str,
    repo: str,
    full_name: str,
    protocol: str,
    remote_name: str,
    branch: str,
    create_if_missing: bool,
    private_repo: bool,
) -> dict[str, Any]:
    full = _normalize_github_full_name(owner=owner, repo=repo, full_name=full_name)
    remote_url = _build_github_remote_url(full, protocol)

    created = False
    if bool(create_if_missing):
        gh = shutil.which("gh")
        if gh:
            view = subprocess.run([gh, "repo", "view", full], capture_output=True, text=True, timeout=12, check=False)
            if int(view.returncode) != 0:
                vis_flag = "--private" if bool(private_repo) else "--public"
                crt = subprocess.run(
                    [gh, "repo", "create", full, vis_flag, "--disable-wiki"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                if int(crt.returncode) != 0:
                    msg = ((crt.stderr or "") + "\n" + (crt.stdout or "")).strip()
                    raise RuntimeError(f"failed to create GitHub repo: {msg[:800]}")
                created = True
        else:
            tok = str(_read_github_oauth_token(cfg).get("access_token") or "").strip()
            if not tok:
                raise RuntimeError("cannot auto-create repository: no gh auth and no OAuth token")
            owner, repo_name = full.split("/", 1)
            chk = _github_api_request(method="GET", url=f"https://api.github.com/repos/{full}", token=tok, timeout=15)
            if int(chk.get("status", 0)) == 404:
                me = _github_api_request(method="GET", url="https://api.github.com/user", token=tok, timeout=12)
                login = str((me.get("json") or {}).get("login") or "").strip()
                if owner == login:
                    crt = _github_api_request(
                        method="POST",
                        url="https://api.github.com/user/repos",
                        token=tok,
                        json_payload={"name": repo_name, "private": bool(private_repo)},
                        timeout=20,
                    )
                else:
                    crt = _github_api_request(
                        method="POST",
                        url=f"https://api.github.com/orgs/{owner}/repos",
                        token=tok,
                        json_payload={"name": repo_name, "private": bool(private_repo)},
                        timeout=20,
                    )
                if not bool(crt.get("ok")):
                    msg = str((crt.get("json") or {}).get("message") or crt.get("error") or "repo create failed")
                    raise RuntimeError(f"failed to create GitHub repo: {msg[:800]}")
                created = True

    cfg.setdefault("sync", {}).setdefault("github", {})
    cfg["sync"]["github"]["remote_name"] = str(remote_name or "origin").strip() or "origin"
    cfg["sync"]["github"]["remote_url"] = remote_url
    cfg["sync"]["github"]["branch"] = str(branch or "main").strip() or "main"
    save_config(cfg_path, cfg)
    return {
        "ok": True,
        "created": bool(created),
        "full_name": full,
        "remote_url": remote_url,
        "remote_name": str(cfg["sync"]["github"]["remote_name"]),
        "branch": str(cfg["sync"]["github"]["branch"]),
        "protocol": str(protocol or "ssh").strip().lower(),
    }


def _sync_options_from_cfg(cfg: dict[str, Any]) -> tuple[list[str], bool]:
    gh = cfg.get("sync", {}).get("github", {})
    raw_layers = gh.get("include_layers")
    if isinstance(raw_layers, list):
        layers = [str(x).strip() for x in raw_layers if str(x).strip()]
    else:
        layers = [x.strip() for x in str(raw_layers or "").split(",") if x.strip()]
    include_jsonl = bool(gh.get("include_jsonl", True))
    return layers, include_jsonl


def _sync_oauth_token_file_from_cfg(cfg: dict[str, Any]) -> str:
    gh = cfg.get("sync", {}).get("github", {})
    oauth = gh.get("oauth", {}) if isinstance(gh, dict) else {}
    if isinstance(oauth, dict):
        return str(oauth.get("token_file", "") or "").strip()
    return ""


def _projects_registry_path(home: str) -> Path:
    base = Path(home).expanduser().resolve() if home else (Path.home() / ".omnimem")
    return base / "projects.local.json"


def _load_projects_registry(home: str) -> list[dict[str, Any]]:
    fp = _projects_registry_path(home)
    if not fp.exists():
        return []
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        return []
    return []


def _save_projects_registry(home: str, items: list[dict[str, Any]]) -> None:
    fp = _projects_registry_path(home)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _register_project(home: str, project_id: str, project_path: str) -> None:
    now = utc_now()
    target = str(Path(project_path).expanduser().resolve())
    items = _load_projects_registry(home)
    for it in items:
        if str(it.get("project_path", "")) == target:
            it["project_id"] = project_id
            it["updated_at"] = now
            _save_projects_registry(home, items)
            return
    items.append(
        {
            "project_id": project_id,
            "project_path": target,
            "attached_at": now,
            "updated_at": now,
        }
    )
    _save_projects_registry(home, items)


def _unregister_project(home: str, project_path: str) -> None:
    target = str(Path(project_path).expanduser().resolve())
    items = _load_projects_registry(home)
    kept = [x for x in items if str(x.get("project_path", "")) != target]
    _save_projects_registry(home, kept)


def _upsert_managed_block(path: Path, block: str) -> None:
    start = "<!-- OMNIMEM:START -->"
    end = "<!-- OMNIMEM:END -->"
    managed = f"{start}\n{block.rstrip()}\n{end}\n"
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if start in old and end in old:
            left = old.split(start, 1)[0].rstrip()
            right = old.split(end, 1)[1].lstrip()
            new_text = f"{left}\n\n{managed}"
            if right:
                new_text += f"\n{right}"
            path.write_text(new_text, encoding="utf-8")
            return
        sep = "\n\n" if old and not old.endswith("\n\n") else ""
        path.write_text(old + sep + managed, encoding="utf-8")
        return
    path.write_text(managed, encoding="utf-8")


def _agent_protocol_block(project_id: str) -> str:
    return (
        "# OmniMem Memory Protocol\n"
        "\n"
        f"- Project ID: `{project_id}`\n"
        "- Session start: run `omnimem brief --project-id <PROJECT_ID> --limit 8` and use it as active context.\n"
        "- During task: when a stable decision/fact appears, run `omnimem write` with concise summary + evidence.\n"
        "- Phase end: run `omnimem checkpoint` with goal/result/next-step/risks.\n"
        "- If confidence is low or info is temporary, store in `instant`/`short`; promote to `long` only when repeated and stable.\n"
        "- Never write raw secrets. Use credential references only (for example `op://...` or `env://...`).\n"
    )


def _attach_project_in_webui(project_path: str, project_id: str, cfg_home: str) -> dict[str, Any]:
    if not project_path:
        return {"ok": False, "error": "project_path is required"}
    project = Path(project_path).expanduser().resolve()
    if not project.exists() or not project.is_dir():
        return {"ok": False, "error": f"project path not found: {project}"}
    if not project_id:
        project_id = project.name

    repo_root = Path(__file__).resolve().parent.parent
    tpl = repo_root / "templates" / "project-minimal"
    created: list[str] = []
    updated: list[str] = []

    files = [
        (tpl / ".omnimem.json", project / ".omnimem.json"),
        (tpl / ".omnimem-session.md", project / ".omnimem-session.md"),
        (tpl / ".omnimem-ignore", project / ".omnimem-ignore"),
    ]
    for src, dst in files:
        text = src.read_text(encoding="utf-8")
        text = text.replace("replace-with-project-id", project_id)
        text = text.replace("~/.omnimem", cfg_home or "~/.omnimem")
        exists = dst.exists()
        dst.write_text(text, encoding="utf-8")
        (updated if exists else created).append(str(dst))

    block = _agent_protocol_block(project_id=project_id)
    managed_targets = [
        project / "AGENTS.md",
        project / "CLAUDE.md",
        project / ".cursorrules",
    ]
    for fp in managed_targets:
        exists = fp.exists()
        _upsert_managed_block(fp, block)
        (updated if exists else created).append(str(fp))

    cursor_rule = project / ".cursor" / "rules" / "omnimem.mdc"
    cursor_exists = cursor_rule.exists()
    cursor_rule.parent.mkdir(parents=True, exist_ok=True)
    cursor_rule.write_text(
        (
            "---\n"
            "description: OmniMem project memory protocol\n"
            "alwaysApply: true\n"
            "---\n\n"
            + block
        ),
        encoding="utf-8",
    )
    (updated if cursor_exists else created).append(str(cursor_rule))

    return {
        "ok": True,
        "project_path": str(project),
        "project_id": project_id,
        "created": created,
        "updated": updated,
    }


def _detach_project_in_webui(project_path: str) -> dict[str, Any]:
    if not project_path:
        return {"ok": False, "error": "project_path is required"}
    project = Path(project_path).expanduser().resolve()
    if not project.exists() or not project.is_dir():
        return {"ok": False, "error": f"project path not found: {project}"}

    removed: list[str] = []
    for name in [
        ".omnimem.json",
        ".omnimem-session.md",
        ".omnimem-ignore",
        ".cursorrules",
        "CLAUDE.md",
        "AGENTS.md",
        ".cursor/rules/omnimem.mdc",
    ]:
        fp = project / name
        if fp.exists():
            txt = fp.read_text(encoding="utf-8", errors="ignore")
            if "<!-- OMNIMEM:START -->" in txt and "<!-- OMNIMEM:END -->" in txt:
                start = txt.index("<!-- OMNIMEM:START -->")
                end = txt.index("<!-- OMNIMEM:END -->") + len("<!-- OMNIMEM:END -->")
                new_txt = (txt[:start] + txt[end:]).strip()
                if new_txt:
                    fp.write_text(new_txt + "\n", encoding="utf-8")
                else:
                    fp.unlink()
                removed.append(str(fp))
                continue
            if fp.name in {".omnimem.json", ".omnimem-session.md", ".omnimem-ignore", "omnimem.mdc"}:
                fp.unlink()
                removed.append(str(fp))
    return {"ok": True, "project_path": str(project), "removed": removed}


def _safe_open_fd_count() -> int | None:
    # /dev/fd is available on macOS/Linux and gives a cheap FD usage snapshot.
    try:
        return max(0, len(os.listdir("/dev/fd")) - 1)
    except Exception:
        return None


def _safe_fd_limits() -> tuple[int | None, int | None]:
    if resource is None:
        return None, None
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        return int(soft), int(hard)
    except Exception:
        return None, None


def _evaluate_governance_action(
    *,
    layer: str,
    signals: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    imp = float(signals.get("importance_score", 0.0) or 0.0)
    conf = float(signals.get("confidence_score", 0.0) or 0.0)
    stab = float(signals.get("stability_score", 0.0) or 0.0)
    vol = float(signals.get("volatility_score", 0.0) or 0.0)
    reuse = int(signals.get("reuse_count", 0) or 0)

    p_imp = float(thresholds.get("p_imp", 0.75))
    p_conf = float(thresholds.get("p_conf", 0.65))
    p_stab = float(thresholds.get("p_stab", 0.65))
    p_vol = float(thresholds.get("p_vol", 0.65))
    d_vol = float(thresholds.get("d_vol", 0.75))
    d_stab = float(thresholds.get("d_stab", 0.45))
    d_reuse = int(thresholds.get("d_reuse", 1))

    checks = {
        "promote": {
            "layer_ok": layer in {"instant", "short"},
            "importance_ok": imp >= p_imp,
            "confidence_ok": conf >= p_conf,
            "stability_ok": stab >= p_stab,
            "volatility_ok": vol <= p_vol,
        },
        "demote": {
            "layer_ok": layer == "long",
            "volatility_or_stability_ok": (vol >= d_vol) or (stab <= d_stab),
            "reuse_ok": reuse <= d_reuse,
        },
    }
    promote_ok = all(bool(v) for v in checks["promote"].values())
    demote_ok = all(bool(v) for v in checks["demote"].values())

    action = "keep"
    reason = "Signals do not cross promote/demote thresholds."
    if promote_ok:
        action = "promote"
        reason = "Meets all promote thresholds."
    elif demote_ok:
        action = "demote"
        reason = "Meets demote thresholds (high volatility/low stability + low reuse)."
    elif layer != "archive" and stab >= 0.90 and reuse >= 3 and vol <= 0.30:
        action = "archive_hint"
        reason = "Highly stable and reused with low volatility; archive snapshot may help curation."

    return {
        "action": action,
        "reason": reason,
        "checks": checks,
        "thresholds": {
            "p_imp": p_imp,
            "p_conf": p_conf,
            "p_stab": p_stab,
            "p_vol": p_vol,
            "d_vol": d_vol,
            "d_stab": d_stab,
            "d_reuse": d_reuse,
        },
        "signals": {
            "importance_score": imp,
            "confidence_score": conf,
            "stability_score": stab,
            "volatility_score": vol,
            "reuse_count": reuse,
        },
    }


def _normalize_memory_route(route: str) -> str:
    r = str(route or "").strip().lower()
    if r in {"episodic", "semantic", "procedural", "auto", "general"}:
        return r
    return "auto"


def _infer_memory_route(query: str) -> str:
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


def _route_tag(route: str) -> str:
    return f"mem:{route}"


def _normalize_route_templates(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for x in raw:
        if not isinstance(x, dict):
            continue
        name = str(x.get("name", "")).strip()
        route = str(x.get("route", "")).strip().lower()
        if not name or route not in {"episodic", "semantic", "procedural"}:
            continue
        out.append({"name": name, "route": route})
    # de-dup by name, keep first
    seen: set[str] = set()
    uniq: list[dict[str, str]] = []
    for x in out:
        key = x["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(x)
    return uniq[:80]


def _filter_items_by_route(paths, items: list[dict[str, Any]], route: str) -> list[dict[str, Any]]:
    if route not in {"episodic", "semantic", "procedural"}:
        return items
    ids = [str(x.get("id", "")).strip() for x in items if str(x.get("id", "")).strip()]
    if not ids:
        return items
    tag = _route_tag(route)
    keep: set[str] = set()
    placeholders = ",".join(["?"] * len(ids))
    with sqlite3.connect(paths.sqlite_path, timeout=2.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT id, tags_json FROM memories WHERE id IN ({placeholders})",
            tuple(ids),
        ).fetchall()
        for r in rows:
            try:
                tags = [str(t).strip().lower() for t in (json.loads(r["tags_json"] or "[]") or [])]
            except Exception:
                tags = []
            if tag in tags:
                keep.add(str(r["id"]))
    return [x for x in items if str(x.get("id", "")) in keep]


def _parse_updated_at_utc(raw: str) -> datetime | None:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _apply_memory_filters(
    items: list[dict[str, Any]],
    *,
    kind_filter: str,
    tag_filter: str,
    since_days: int,
) -> list[dict[str, Any]]:
    out = list(items or [])
    if kind_filter:
        out = [x for x in out if str(x.get("kind") or "").strip().lower() == kind_filter]
    if tag_filter:
        out = [
            x
            for x in out
            if any(str(t).strip().lower() == tag_filter for t in (x.get("tags") or []))
        ]
    if since_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        keep: list[dict[str, Any]] = []
        for x in out:
            dt = _parse_updated_at_utc(str(x.get("updated_at") or ""))
            if dt is not None and dt >= cutoff:
                keep.append(x)
        out = keep
    return out


def _normalize_dedup_mode(raw: str) -> str:
    s = str(raw or "").strip().lower()
    return s if s in {"off", "summary_kind"} else "off"




def _context_runtime_summary(*, paths_root: Path, project_id: str = "", tool: str = "", window: int = 12) -> dict[str, Any]:
    runtime_fp = Path(paths_root) / "runtime" / "context_strategy_stats.json"

    def _empty() -> dict[str, Any]:
        return {
            "ok": True,
            "count": 0,
            "avg_context_utilization": 0.0,
            "p95_context_utilization": 0.0,
            "transient_failures_sum": 0,
            "attempts_sum": 0,
            "avg_output_tokens": 0.0,
            "p95_output_tokens": 0.0,
            "risk_level": "none",
            "recommended_quota_mode": "normal",
            "recommended_context_profile": "balanced",
            "by_tool": [],
        }

    if not runtime_fp.exists():
        return _empty()

    try:
        obj = json.loads(runtime_fp.read_text(encoding="utf-8"))
    except Exception:
        obj = {}
    items = obj.get("items") if isinstance(obj, dict) else []
    if not isinstance(items, list):
        items = []

    p_filter = str(project_id or "").strip()
    t_filter = str(tool or "").strip().lower()
    rows: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        key = str(it.get("key", "") or "")
        if "|" not in key:
            continue
        k_tool, k_project = key.split("|", 1)
        if p_filter and k_project != p_filter:
            continue
        if t_filter and str(k_tool).lower() != t_filter:
            continue
        rows.append(it)

    w = max(1, min(120, int(window or 12)))
    rows = rows[-w:]
    count = len(rows)
    if count <= 0:
        return _empty()

    tf_sum = 0
    at_sum = 0
    util_vals: list[float] = []
    out_vals: list[float] = []
    by_tool: dict[str, dict[str, Any]] = {}

    for r in rows:
        key = str(r.get("key", "") or "")
        k_tool = key.split("|", 1)[0] if "|" in key else ""
        tf = max(0, int(r.get("transient_failures", 0) or 0))
        at = max(0, int(r.get("attempts", 0) or 0))
        util = max(0.0, min(1.2, float(r.get("context_utilization", 0.0) or 0.0)))
        out_t = max(0.0, float(r.get("output_tokens", 0) or 0))

        tf_sum += tf
        at_sum += at
        util_vals.append(util)
        out_vals.append(out_t)

        slot = by_tool.setdefault(
            k_tool,
            {
                "tool": k_tool,
                "count": 0,
                "avg_context_utilization": 0.0,
                "avg_output_tokens": 0.0,
            },
        )
        slot["count"] = int(slot.get("count", 0)) + 1
        slot["avg_context_utilization"] = float(slot.get("avg_context_utilization", 0.0)) + util
        slot["avg_output_tokens"] = float(slot.get("avg_output_tokens", 0.0)) + out_t

    util_vals.sort()
    out_vals.sort()

    def _p95(vals: list[float]) -> float:
        if not vals:
            return 0.0
        idx = max(0, min(len(vals) - 1, int(round((len(vals) - 1) * 0.95))))
        return float(vals[idx])

    avg_util = sum(util_vals) / float(count)
    p95_util = _p95(util_vals)
    avg_out = sum(out_vals) / float(count)
    p95_out = _p95(out_vals)

    risk_level = "balanced"
    if p95_util >= 0.98 or tf_sum >= max(3, count // 2):
        risk_level = "critical"
    elif p95_util >= 0.90 or avg_util >= 0.82 or tf_sum >= 2:
        risk_level = "high"

    recommended_quota_mode = "normal"
    recommended_context_profile = "balanced"
    if risk_level == "critical":
        recommended_quota_mode = "critical"
        recommended_context_profile = "low_quota"
    elif risk_level == "high":
        recommended_quota_mode = "low"
        recommended_context_profile = "balanced"
    elif avg_util <= 0.45 and tf_sum == 0:
        recommended_quota_mode = "normal"
        recommended_context_profile = "deep_research"

    by_tool_items: list[dict[str, Any]] = []
    for v in by_tool.values():
        c = max(1, int(v.get("count", 0) or 0))
        by_tool_items.append(
            {
                "tool": str(v.get("tool", "") or ""),
                "count": c,
                "avg_context_utilization": float(v.get("avg_context_utilization", 0.0)) / float(c),
                "avg_output_tokens": float(v.get("avg_output_tokens", 0.0)) / float(c),
            }
        )
    by_tool_items.sort(key=lambda x: str(x.get("tool", "")))

    return {
        "ok": True,
        "count": count,
        "avg_context_utilization": avg_util,
        "p95_context_utilization": p95_util,
        "transient_failures_sum": tf_sum,
        "attempts_sum": at_sum,
        "avg_output_tokens": avg_out,
        "p95_output_tokens": p95_out,
        "risk_level": risk_level,
        "recommended_quota_mode": recommended_quota_mode,
        "recommended_context_profile": recommended_context_profile,
        "by_tool": by_tool_items,
    }

def _parse_int_param(raw: Any, *, default: int, lo: int, hi: int) -> int:
    try:
        v = int(float(raw))
    except Exception:
        v = int(default)
    return max(int(lo), min(int(hi), v))


def _parse_float_param(raw: Any, *, default: float, lo: float, hi: float) -> float:
    try:
        v = float(raw)
    except Exception:
        v = float(default)
    return max(float(lo), min(float(hi), v))


def _parse_bool_param(raw: Any, *, default: bool = False) -> bool:
    s = str(raw if raw is not None else "").strip().lower()
    if not s:
        return bool(default)
    if s in {"1", "true", "on", "yes", "y"}:
        return True
    if s in {"0", "false", "off", "no", "n"}:
        return False
    return bool(default)


def _parse_retrieve_core_options(q: dict[str, list[str]]) -> tuple[bool, int, bool]:
    include_core_blocks = _parse_bool_param(q.get("include_core_blocks", ["1"])[0], default=True)
    core_block_limit = _parse_int_param(q.get("core_block_limit", ["2"])[0], default=2, lo=0, hi=6)
    core_merge_by_topic = _parse_bool_param(q.get("core_merge_by_topic", ["1"])[0], default=True)
    return bool(include_core_blocks), int(core_block_limit), bool(core_merge_by_topic)


def _parse_retrieve_drift_options(q: dict[str, list[str]]) -> tuple[bool, int, int, float]:
    drift_aware = _parse_bool_param(q.get("drift_aware", ["1"])[0], default=True)
    drift_recent_days = _parse_int_param(q.get("drift_recent_days", ["14"])[0], default=14, lo=1, hi=60)
    drift_baseline_days = _parse_int_param(q.get("drift_baseline_days", ["120"])[0], default=120, lo=2, hi=720)
    drift_weight = _parse_float_param(q.get("drift_weight", ["0.35"])[0], default=0.35, lo=0.0, hi=1.0)
    return bool(drift_aware), int(drift_recent_days), int(drift_baseline_days), float(drift_weight)


def _parse_memories_request(q: dict[str, list[str]]) -> dict[str, Any]:
    query = q.get("query", [""])[0].strip()
    route_raw = _normalize_memory_route(q.get("route", ["auto"])[0].strip())
    route = _infer_memory_route(query) if route_raw == "auto" else route_raw
    include_core_blocks, core_block_limit, core_merge_by_topic = _parse_retrieve_core_options(q)
    drift_aware, drift_recent_days, drift_baseline_days, drift_weight = _parse_retrieve_drift_options(q)
    sort_mode = str(q.get("sort_mode", ["server"])[0] or "").strip().lower()
    if sort_mode not in {"server", "updated_desc", "updated_asc", "score_desc"}:
        sort_mode = "server"
    return {
        "limit": _parse_int_param(q.get("limit", ["20"])[0], default=20, lo=1, hi=200),
        "offset": _parse_int_param(q.get("offset", ["0"])[0], default=0, lo=0, hi=10000),
        "project_id": q.get("project_id", [""])[0].strip(),
        "session_id": q.get("session_id", [""])[0].strip(),
        "layer": q.get("layer", [""])[0].strip() or None,
        "query": query,
        "kind_filter": q.get("kind", [""])[0].strip().lower(),
        "tag_filter": q.get("tag", [""])[0].strip().lower(),
        "since_days": _parse_int_param(q.get("since_days", ["0"])[0], default=0, lo=0, hi=365),
        "mode": q.get("mode", ["basic"])[0].strip().lower() or "basic",
        "route": route,
        "depth": _parse_int_param(q.get("depth", ["2"])[0], default=2, lo=1, hi=4),
        "per_hop": _parse_int_param(q.get("per_hop", ["6"])[0], default=6, lo=1, hi=30),
        "ranking_mode": q.get("ranking_mode", ["hybrid"])[0].strip().lower() or "hybrid",
        "diversify": _parse_bool_param(q.get("diversify", ["1"])[0], default=True),
        "profile_aware": _parse_bool_param(q.get("profile_aware", ["1"])[0], default=True),
        "profile_weight": _parse_float_param(q.get("profile_weight", ["0.35"])[0], default=0.35, lo=0.0, hi=1.0),
        "include_core_blocks": include_core_blocks,
        "core_block_limit": core_block_limit,
        "core_merge_by_topic": core_merge_by_topic,
        "drift_aware": drift_aware,
        "drift_recent_days": drift_recent_days,
        "drift_baseline_days": drift_baseline_days,
        "drift_weight": drift_weight,
        "dedup_mode": _normalize_dedup_mode(q.get("dedup", ["off"])[0]),
        "mmr_lambda": _parse_float_param(q.get("mmr_lambda", ["0.72"])[0], default=0.72, lo=0.05, hi=0.95),
        "include_preview": _parse_bool_param(q.get("include_preview", ["1"])[0], default=True),
        "sort_mode": sort_mode,
    }


def _resolve_memories_scan_limit(*, req_limit: int, req_offset: int, sort_mode: str, mode: str) -> int:
    base = max(1, int(req_limit)) + max(0, int(req_offset))
    mode_s = str(mode or "basic").strip().lower()
    if mode_s == "smart":
        return max(8, min(1000, base + 120))
    if str(sort_mode or "server").strip().lower() != "server":
        base = max(base, 400)
    return max(50, min(2000, base))


def _build_smart_memories_cache_key(req: dict[str, Any]) -> tuple[Any, ...]:
    depth_i = int(req["depth"])
    hop_i = int(req["per_hop"])
    rank_i = str(req.get("ranking_mode") or "").lower().strip()
    rank_i = rank_i if rank_i in {"path", "ppr", "hybrid"} else "hybrid"
    req_limit = max(1, min(200, int(req.get("limit", 20))))
    req_offset = max(0, min(10000, int(req.get("offset", 0))))
    limit_i = max(8, min(200, req_limit))
    scan_limit = _resolve_memories_scan_limit(
        req_limit=req_limit,
        req_offset=req_offset,
        sort_mode=str(req.get("sort_mode", "server")),
        mode="smart",
    )
    return (
        str(req.get("project_id") or ""),
        str(req.get("session_id") or ""),
        str(req.get("query") or ""),
        depth_i,
        hop_i,
        rank_i,
        bool(req.get("diversify", True)),
        float(req.get("mmr_lambda", 0.72)),
        limit_i,
        bool(req.get("profile_aware", True)),
        float(req.get("profile_weight", 0.35)),
        bool(req.get("include_core_blocks", True)),
        int(req.get("core_block_limit", 2)),
        bool(req.get("core_merge_by_topic", True)),
        bool(req.get("drift_aware", True)),
        int(req.get("drift_recent_days", 14)),
        int(req.get("drift_baseline_days", 120)),
        float(req.get("drift_weight", 0.35)),
        scan_limit,
    )


def _process_memories_items(
    *,
    paths: Any,
    items: list[dict[str, Any]],
    route: str,
    kind_filter: str,
    tag_filter: str,
    since_days: int,
    dedup_mode: str,
) -> tuple[list[dict[str, Any]], int]:
    out = _filter_items_by_route(paths, items, route)
    out = _apply_memory_filters(
        out,
        kind_filter=kind_filter,
        tag_filter=tag_filter,
        since_days=since_days,
    )
    before_dedup = len(out)
    out = _dedup_memory_items(out, mode=dedup_mode)
    return out, before_dedup


def _sort_memory_items(items: list[dict[str, Any]], *, sort_mode: str) -> list[dict[str, Any]]:
    mode = str(sort_mode or "server").strip().lower()
    if mode == "updated_desc":
        return sorted(items, key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    if mode == "updated_asc":
        return sorted(items, key=lambda x: str(x.get("updated_at") or ""))
    if mode == "score_desc":
        return sorted(items, key=lambda x: float((x.get("retrieval") or {}).get("score", 0.0)), reverse=True)
    return items


def _read_memory_body_preview(paths: Any, body_md_path: str, *, max_chars: int = 260) -> str:
    rel = str(body_md_path or "").strip()
    if not rel:
        return ""
    try:
        root = Path(str(paths.markdown_root)).resolve()
        fp = (root / rel).resolve()
        if root not in fp.parents and fp != root:
            return ""
        if not fp.exists() or not fp.is_file():
            return ""
        txt = fp.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    txt = re.sub(r"^# .*?\n\n", "", txt, count=1, flags=re.DOTALL)
    txt = re.sub(r"\s+", " ", txt).strip()
    if not txt:
        return ""
    max_chars = max(60, min(1200, int(max_chars)))
    if len(txt) <= max_chars:
        return txt
    return txt[: max_chars - 1].rstrip() + "…"


def _attach_memory_previews(paths: Any, items: list[dict[str, Any]], *, max_chars: int = 260, max_items: int = 120) -> list[dict[str, Any]]:
    if not items:
        return items
    cap = max(1, min(int(max_items), len(items)))
    for idx, item in enumerate(items):
        if idx >= cap:
            break
        rel = str((item or {}).get("body_md_path") or "").strip()
        if not rel:
            continue
        item["body_preview"] = _read_memory_body_preview(paths, rel, max_chars=max_chars)
    return items


def _parse_governance_request(q: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "project_id": q.get("project_id", [""])[0].strip(),
        "session_id": q.get("session_id", [""])[0].strip(),
        "limit": _parse_int_param(q.get("limit", ["6"])[0], default=6, lo=1, hi=200),
        "thresholds": {
            "p_imp": _parse_float_param(q.get("p_imp", ["0.75"])[0], default=0.75, lo=0.0, hi=1.0),
            "p_conf": _parse_float_param(q.get("p_conf", ["0.65"])[0], default=0.65, lo=0.0, hi=1.0),
            "p_stab": _parse_float_param(q.get("p_stab", ["0.65"])[0], default=0.65, lo=0.0, hi=1.0),
            "p_vol": _parse_float_param(q.get("p_vol", ["0.65"])[0], default=0.65, lo=0.0, hi=1.0),
            "d_vol": _parse_float_param(q.get("d_vol", ["0.75"])[0], default=0.75, lo=0.0, hi=1.0),
            "d_stab": _parse_float_param(q.get("d_stab", ["0.45"])[0], default=0.45, lo=0.0, hi=1.0),
            "d_reuse": _parse_int_param(q.get("d_reuse", ["1"])[0], default=1, lo=0, hi=100000),
        },
    }


def _governance_scope_filters(project_id: str, session_id: str) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if project_id:
        clauses.append("json_extract(scope_json, '$.project_id') = ?")
        args.append(project_id)
    if session_id:
        clauses.append("COALESCE(json_extract(source_json, '$.session_id'), '') = ?")
        args.append(session_id)
    if not clauses:
        return "", args
    return " AND " + " AND ".join(clauses), args


def _pack_governance_rows(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "layer": r["layer"],
                "kind": r["kind"],
                "summary": r["summary"],
                "updated_at": r["updated_at"],
                "signals": {
                    "importance_score": float(r["importance_score"]),
                    "confidence_score": float(r["confidence_score"]),
                    "stability_score": float(r["stability_score"]),
                    "reuse_count": int(r["reuse_count"]),
                    "volatility_score": float(r["volatility_score"]),
                },
            }
        )
    return out


def _infer_governance_thresholds(
    *,
    paths: Any,
    schema_sql_path: Path,
    cfg: dict[str, Any],
    project_id: str,
    session_id: str,
    days: int,
) -> dict[str, Any]:
    dm = dict(cfg.get("daemon", {}) or {})
    return infer_adaptive_governance_thresholds(
        paths=paths,
        schema_sql_path=schema_sql_path,
        project_id=project_id,
        session_id=session_id,
        days=int(days),
        q_promote_imp=float(dm.get("adaptive_q_promote_imp", 0.68)),
        q_promote_conf=float(dm.get("adaptive_q_promote_conf", 0.60)),
        q_promote_stab=float(dm.get("adaptive_q_promote_stab", 0.62)),
        q_promote_vol=float(dm.get("adaptive_q_promote_vol", 0.42)),
        q_demote_vol=float(dm.get("adaptive_q_demote_vol", 0.78)),
        q_demote_stab=float(dm.get("adaptive_q_demote_stab", 0.28)),
        q_demote_reuse=float(dm.get("adaptive_q_demote_reuse", 0.30)),
        drift_aware=True,
        drift_recent_days=14,
        drift_baseline_days=120,
        drift_weight=0.45,
    )


def _cache_get(
    cache: dict[Any, tuple[float, dict[str, Any]]],
    key: Any,
    *,
    now: float,
    ttl_s: float,
) -> dict[str, Any] | None:
    hit = cache.get(key)
    if not hit:
        return None
    ts, val = hit
    if (now - float(ts)) > float(ttl_s):
        cache.pop(key, None)
        return None
    return val


def _cache_set(
    cache: dict[Any, tuple[float, dict[str, Any]]],
    key: Any,
    value: dict[str, Any],
    *,
    now: float,
    max_items: int,
) -> None:
    cache[key] = (float(now), value)
    overflow = len(cache) - max(1, int(max_items))
    if overflow <= 0:
        return
    # Evict oldest entries first to keep cache bounded.
    evict_keys = [k for k, _ in sorted(cache.items(), key=lambda kv: float(kv[1][0]))[:overflow]]
    for k in evict_keys:
        cache.pop(k, None)


def _dedup_memory_items(items: list[dict[str, Any]], *, mode: str) -> list[dict[str, Any]]:
    dedup_mode = _normalize_dedup_mode(mode)
    if dedup_mode == "off":
        return list(items or [])
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for x in (items or []):
        kind = str(x.get("kind") or "").strip().lower()
        summary = re.sub(r"\s+", " ", str(x.get("summary") or "").strip().lower())
        if dedup_mode == "summary_kind":
            key = f"{kind}|{summary}"
        else:
            key = str(x.get("id") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out


def _aggregate_event_stats(
    rows: list[dict[str, Any] | sqlite3.Row],
    *,
    project_id: str,
    session_id: str,
    days: int,
) -> dict[str, Any]:
    # Aggregate in Python because memory_events doesn't store project/session columns.
    type_counts: dict[str, int] = {}
    day_counts: dict[str, int] = {}
    total = 0
    day_allow: set[str] | None = None
    # Only keep last N days keys if present; compute by seen days.
    seen_days: list[str] = []

    def accept_event(payload: dict[str, Any]) -> tuple[str, str]:
        env = payload.get("envelope") if isinstance(payload, dict) else None
        if not isinstance(env, dict):
            env = {}
        scope = env.get("scope") if isinstance(env.get("scope"), dict) else {}
        source = env.get("source") if isinstance(env.get("source"), dict) else {}
        pid = str(scope.get("project_id", "") or payload.get("project_id", "") or "").strip()
        sid = str(source.get("session_id", "") or payload.get("session_id", "") or "").strip()
        return pid, sid

    for r in rows:
        et = str(r["event_type"] or "")
        ts = str(r["event_time"] or "")
        day = ts[:10] if len(ts) >= 10 else ""
        if not day:
            continue
        if day_allow is None:
            if day not in seen_days:
                seen_days.append(day)
            if len(seen_days) > days:
                day_allow = set(seen_days[:days])
        if day_allow is not None and day not in day_allow:
            continue

        try:
            payload = json.loads(r["payload_json"] or "{}")
        except Exception:
            payload = {}
        pid, sid = accept_event(payload if isinstance(payload, dict) else {})
        if project_id and pid != project_id:
            continue
        if session_id and sid != session_id:
            continue

        total += 1
        type_counts[et] = type_counts.get(et, 0) + 1
        day_counts[day] = day_counts.get(day, 0) + 1

    types = [{"event_type": k, "count": int(v)} for k, v in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)]
    days_out = [{"day": k, "count": int(v)} for k, v in sorted(day_counts.items(), key=lambda x: x[0])]
    return {"total": int(total), "types": types, "days": days_out}


from .daemon import _daemon_should_attempt_push
def _run_health_check(paths, daemon_state: dict[str, Any]) -> dict[str, Any]:
    checked_at = utc_now()
    db_ok = False
    db_error = ""
    db_exists = bool(paths.sqlite_path.exists())
    try:
        with sqlite3.connect(paths.sqlite_path, timeout=2.0) as conn:
            conn.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    fds_open = _safe_open_fd_count()
    fd_soft, fd_hard = _safe_fd_limits()
    fd_ratio = None
    if fds_open is not None and fd_soft and fd_soft > 0:
        fd_ratio = float(fds_open) / float(fd_soft)

    issues: list[str] = []
    actions: list[str] = []
    level = "ok"
    if not db_ok:
        level = "error"
        issues.append(f"sqlite unavailable: {db_error or 'open failed'}")
        actions.append("check sqlite path permissions and file locks")
    if fds_open is not None and fd_soft and fds_open >= int(fd_soft * 0.80):
        if level != "error":
            level = "warn"
        issues.append(f"file descriptors high: {fds_open}/{fd_soft}")
        actions.append("inspect daemon logs for fd leak and reduce maintenance load temporarily")
    if str(daemon_state.get("last_error_kind", "none")) not in {"none", ""}:
        if level == "ok":
            level = "warn"
        issues.append(
            f"daemon last_error_kind={daemon_state.get('last_error_kind')} last_error={daemon_state.get('last_error','')}"
        )
        actions.append(str(daemon_state.get("remediation_hint") or "check daemon failure details"))

    return {
        "ok": True,
        "checked_at": checked_at,
        "health_level": level,
        "storage": {
            "sqlite_path": str(paths.sqlite_path),
            "sqlite_exists": db_exists,
            "sqlite_ok": db_ok,
            "sqlite_error": db_error,
            "markdown_root_exists": bool(paths.markdown_root.exists()),
            "jsonl_root_exists": bool(paths.jsonl_root.exists()),
        },
        "process": {
            "threads": int(threading.active_count()),
            "fds_open": fds_open,
            "fd_soft_limit": fd_soft,
            "fd_hard_limit": fd_hard,
            "fd_ratio": fd_ratio,
        },
        "daemon": {
            "running": bool(daemon_state.get("running", False)),
            "enabled": bool(daemon_state.get("enabled", False)),
            "cycles": int(daemon_state.get("cycles", 0)),
            "success_count": int(daemon_state.get("success_count", 0)),
            "failure_count": int(daemon_state.get("failure_count", 0)),
            "last_success_at": str(daemon_state.get("last_success_at", "")),
            "last_failure_at": str(daemon_state.get("last_failure_at", "")),
            "last_error_kind": str(daemon_state.get("last_error_kind", "")),
            "last_error": str(daemon_state.get("last_error", "")),
        },
        "diagnosis": {
            "issues": issues,
            "actions": actions,
        },
    }


def _quality_window_summary(conn: sqlite3.Connection, *, start_iso: str, end_iso: str, project_id: str, session_id: str) -> dict[str, Any]:
    where_scope = ""
    args_scope: list[Any] = []
    if project_id:
        where_scope += " AND json_extract(scope_json, '$.project_id') = ?"
        args_scope.append(project_id)
    if session_id:
        where_scope += " AND COALESCE(json_extract(source_json, '$.session_id'), '') = ?"
        args_scope.append(session_id)

    mem_row = conn.execute(
        f"""
        SELECT
          COALESCE(AVG(importance_score), 0.0) AS avg_importance,
          COALESCE(AVG(confidence_score), 0.0) AS avg_confidence,
          COALESCE(AVG(stability_score), 0.0) AS avg_stability,
          COALESCE(AVG(volatility_score), 0.0) AS avg_volatility
        FROM memories
        WHERE updated_at >= ? AND updated_at < ?
        {where_scope}
        """,
        (start_iso, end_iso, *args_scope),
    ).fetchone()

    if project_id or session_id:
        # Project/session are stored in payload envelope; use a join to filter robustly.
        ev_rows = conn.execute(
            """
            SELECT event_type, payload_json
            FROM memory_events
            WHERE event_time >= ? AND event_time < ?
            ORDER BY event_time DESC
            LIMIT 20000
            """,
            (start_iso, end_iso),
        ).fetchall()
    else:
        ev_rows = conn.execute(
            """
            SELECT event_type, payload_json
            FROM memory_events
            WHERE event_time >= ? AND event_time < ?
            ORDER BY event_time DESC
            LIMIT 20000
            """,
            (start_iso, end_iso),
        ).fetchall()

    counts = {
        "conflicts": 0,
        "reuse_events": 0,
        "decay_events": 0,
        "writes": 0,
    }
    for r in ev_rows:
        et = str(r["event_type"] or "")
        payload = {}
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except Exception:
            payload = {}
        env = payload.get("envelope") if isinstance(payload, dict) else {}
        env = env if isinstance(env, dict) else {}
        scope = env.get("scope") if isinstance(env.get("scope"), dict) else {}
        source = env.get("source") if isinstance(env.get("source"), dict) else {}
        pid = str(scope.get("project_id") or payload.get("project_id") or "").strip()
        sid = str(source.get("session_id") or payload.get("session_id") or "").strip()
        if project_id and pid != project_id:
            continue
        if session_id and sid != session_id:
            continue
        if et == "memory.sync":
            kind = str((payload.get("daemon") or {}).get("last_error_kind", ""))
            if kind == "conflict":
                counts["conflicts"] += 1
        elif et == "memory.reuse":
            counts["reuse_events"] += 1
        elif et == "memory.decay":
            counts["decay_events"] += 1
        elif et == "memory.write":
            counts["writes"] += 1

    return {
        **counts,
        "avg_importance": float(mem_row["avg_importance"] or 0.0),
        "avg_confidence": float(mem_row["avg_confidence"] or 0.0),
        "avg_stability": float(mem_row["avg_stability"] or 0.0),
        "avg_volatility": float(mem_row["avg_volatility"] or 0.0),
    }


def _quality_alerts(cur: dict[str, Any], prev: dict[str, Any]) -> list[str]:
    alerts: list[str] = []
    if int(cur.get("conflicts", 0) or 0) > int(prev.get("conflicts", 0) or 0):
        alerts.append("conflicts increased week-over-week; run sync conflict recovery and inspect memory.sync events")
    if int(cur.get("decay_events", 0) or 0) > int(prev.get("decay_events", 0) or 0) + 10:
        alerts.append("decay pressure increased; reduce volatility and review maintenance thresholds")
    if float(cur.get("avg_stability", 0.0) or 0.0) < 0.45:
        alerts.append("avg stability is low (<0.45); consider promoting fewer volatile items")
    if float(cur.get("avg_volatility", 0.0) or 0.0) > 0.65:
        alerts.append("avg volatility is high (>0.65); run consolidate preview and demote noisy long memories")
    if int(cur.get("reuse_events", 0) or 0) < int(prev.get("reuse_events", 0) or 0):
        alerts.append("reuse decreased week-over-week; tune retrieval route/ranking and refresh links")
    return alerts


def _maintenance_impact_forecast(
    *,
    decay_count: int,
    promote_count: int,
    demote_count: int,
    compress_count: int,
    dry_run: bool,
    approval_required: bool,
    session_id: str,
) -> dict[str, Any]:
    decay_n = max(0, int(decay_count))
    promote_n = max(0, int(promote_count))
    demote_n = max(0, int(demote_count))
    compress_n = max(0, int(compress_count))
    layer_moves = promote_n + demote_n
    total_touches = decay_n + layer_moves + compress_n

    risk_level = "low"
    if decay_n >= 80 or layer_moves >= 24 or compress_n >= 3:
        risk_level = "warn"
    if decay_n >= 180 or layer_moves >= 60 or compress_n >= 8:
        risk_level = "high"

    if not dry_run and approval_required and total_touches > 0 and risk_level == "low":
        risk_level = "warn"

    scope = "single session" if session_id else "project/hot sessions"
    summary = (
        f"{'preview' if dry_run else 'apply'} forecast ({scope}): "
        f"decay={decay_n}, promote={promote_n}, demote={demote_n}, compress={compress_n}, "
        f"total_touches={total_touches}"
    )
    next_actions = [
        "keep preview mode if risk is high",
        "review governance thresholds before apply",
        "apply with ack token when approval is required",
    ]
    if dry_run:
        next_actions[2] = "apply after checking forecast details and recommendations"

    return {
        "risk_level": risk_level,
        "summary": summary,
        "expected": {
            "decay": decay_n,
            "promote": promote_n,
            "demote": demote_n,
            "compress": compress_n,
            "total_touches": total_touches,
        },
        "scope": scope,
        "next_actions": next_actions,
    }


def _maintenance_status_feedback(
    *,
    dry_run: bool,
    approval_required: bool,
    approval_met: bool,
    risk_level: str,
    total_touches: int,
) -> dict[str, Any]:
    phase = "preview" if dry_run else "apply"
    ready = bool(dry_run or (not approval_required) or approval_met)
    pressure = max(0.0, min(1.0, float(max(0, int(total_touches))) / 240.0))
    status_line = (
        f"{phase} mode: "
        f"{'ready' if ready else 'approval pending'}; "
        f"risk={str(risk_level or 'low')}; "
        f"estimated touches={int(max(0, int(total_touches)))}"
    )
    approval_state = "skipped"
    if approval_required:
        approval_state = "ok" if approval_met else "required"
    apply_state = "preview-only" if dry_run else ("ready" if ready else "blocked")
    return {
        "phase": phase,
        "ready": ready,
        "approval_required": bool(approval_required),
        "approval_met": bool(approval_met),
        "pressure": pressure,
        "status_line": status_line,
        "steps": [
            {"name": "forecast", "state": "done"},
            {"name": "approval", "state": approval_state},
            {"name": "apply", "state": apply_state},
        ],
    }


def _rollback_preview_items(conn: sqlite3.Connection, *, memory_id: str, cutoff_iso: str, limit: int = 200) -> tuple[list[dict[str, Any]], str]:
    conn.row_factory = sqlite3.Row
    now_layer = conn.execute("SELECT layer FROM memories WHERE id = ?", (memory_id,)).fetchone()
    current_layer = str(now_layer["layer"]) if now_layer else ""
    rows = conn.execute(
        """
        SELECT event_id, event_time, payload_json
        FROM memory_events
        WHERE memory_id = ?
          AND event_type = 'memory.promote'
          AND event_time > ?
        ORDER BY event_time DESC, event_id DESC
        LIMIT ?
        """,
        (memory_id, cutoff_iso, max(1, min(200, int(limit)))),
    ).fetchall()
    items: list[dict[str, Any]] = []
    predicted_layer = current_layer
    for r in rows:
        payload = {}
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except Exception:
            payload = {}
        from_layer = str(payload.get("from_layer", "")).strip()
        to_layer = str(payload.get("to_layer", "")).strip()
        if from_layer and to_layer and from_layer != to_layer:
            predicted_layer = from_layer
        items.append(
            {
                "event_id": str(r["event_id"]),
                "event_time": str(r["event_time"]),
                "from_layer": from_layer,
                "to_layer": to_layer,
            }
        )
    return items, predicted_layer


def _is_local_bind_host(host: str) -> bool:
    v = host.strip().lower()
    return v in {"127.0.0.1", "localhost", "::1"}


def _endpoint_key(host: str, port: int) -> str:
    raw = f"{str(host).strip().lower()}_{int(port)}"
    return "".join(ch if ch.isalnum() else "_" for ch in raw)


def _resolve_runtime_dir(paths) -> Path:
    env_dir = os.getenv("OMNIMEM_RUNTIME_DIR", "").strip()
    candidates: list[Path] = []
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
    candidates.append(paths.root / "runtime")
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".probe"
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return d
        except Exception:
            continue
    return paths.root / "runtime"


def _resolve_auth_token(cfg: dict[str, Any], explicit_token: str | None) -> str:
    if explicit_token:
        return explicit_token
    env_token = os.getenv("OMNIMEM_WEBUI_TOKEN", "").strip()
    if env_token:
        return env_token
    token = str(cfg.get("webui", {}).get("auth_token", "")).strip()
    return token


def _validate_webui_bind_security(
    *,
    host: str,
    allow_non_localhost: bool,
    resolved_auth_token: str,
) -> None:
    is_local = _is_local_bind_host(host)
    if not allow_non_localhost and not is_local:
        raise ValueError(
            f"refuse to bind non-local host without --allow-non-localhost: {host}"
        )
    # If the user opted into a non-local bind, require auth so the API is not wide open on a LAN/WAN.
    if not is_local and not resolved_auth_token:
        raise ValueError(
            "non-local bind requires an API token; set OMNIMEM_WEBUI_TOKEN or pass --webui-token"
        )


def run_webui(
    *,
    host: str,
    port: int,
    cfg: dict[str, Any],
    cfg_path: Path,
    schema_sql_path: Path,
    sync_runner,
    daemon_runner=None,
    enable_daemon: bool = True,
    daemon_scan_interval: int = 8,
    daemon_pull_interval: int = 30,
    daemon_retry_max_attempts: int = 3,
    daemon_retry_initial_backoff: int = 1,
    daemon_retry_max_backoff: int = 8,
    daemon_maintenance_enabled: bool = True,
    daemon_maintenance_interval: int = 300,
    daemon_maintenance_decay_days: int = 14,
    daemon_maintenance_decay_limit: int = 120,
    daemon_maintenance_prune_enabled: bool = False,
    daemon_maintenance_prune_days: int = 45,
    daemon_maintenance_prune_limit: int = 300,
    daemon_maintenance_prune_layers: str = "instant,short",
    daemon_maintenance_prune_keep_kinds: str = "decision,checkpoint",
    daemon_maintenance_consolidate_limit: int = 80,
    daemon_maintenance_compress_sessions: int = 2,
    daemon_maintenance_compress_min_items: int = 8,
    daemon_maintenance_temporal_tree_enabled: bool = True,
    daemon_maintenance_temporal_tree_days: int = 30,
    daemon_maintenance_rehearsal_enabled: bool = True,
    daemon_maintenance_rehearsal_days: int = 45,
    daemon_maintenance_rehearsal_limit: int = 16,
    daemon_maintenance_reflection_enabled: bool = True,
    daemon_maintenance_reflection_days: int = 14,
    daemon_maintenance_reflection_limit: int = 4,
    daemon_maintenance_reflection_min_repeats: int = 2,
    daemon_maintenance_reflection_max_avg_retrieved: float = 2.0,
    auth_token: str | None = None,
    allow_non_localhost: bool = False,
) -> None:
    resolved_auth_token = _resolve_auth_token(cfg, auth_token)
    _validate_webui_bind_security(
        host=host,
        allow_non_localhost=allow_non_localhost,
        resolved_auth_token=resolved_auth_token,
    )
    paths = resolve_paths(cfg)
    ensure_storage(paths, schema_sql_path)
    runtime_dir = paths.root / "runtime"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    error_log_fp = runtime_dir / "webui.error.log"

    def _elog(line: str) -> None:
        try:
            with error_log_fp.open("ab") as f:
                f.write((line.rstrip("\n") + "\n").encode("utf-8", errors="replace"))
        except Exception:
            pass

    def _fd_count() -> int:
        # macOS/Linux best-effort open-fd counter.
        for p in ("/dev/fd", "/proc/self/fd"):
            try:
                return len(os.listdir(p))
            except Exception:
                continue
        return -1

    def _dump_threads(reason: str) -> None:
        # Useful when the server is "listening but dead": dump all thread stacks.
        try:
            _elog(f"[{utc_now()}] THREAD_DUMP reason={reason}")
            frames = sys._current_frames()
            by_tid = {t.ident: t for t in threading.enumerate()}
            for tid, frame in frames.items():
                t = by_tid.get(tid)
                tname = t.name if t else "unknown"
                _elog(f"\n--- thread {tname} tid={tid} ---")
                _elog("".join(traceback.format_stack(frame)))
        except Exception:
            _elog(f"[{utc_now()}] THREAD_DUMP failed:\n{traceback.format_exc()}")

    def _sigusr1_handler(signum, _frame) -> None:  # noqa: ANN001
        _dump_threads(f"signal:{signum}")

    # Best-effort: on macOS/Linux you can `kill -USR1 <pid>` to get a thread dump.
    try:
        if hasattr(signal, "SIGUSR1"):
            signal.signal(signal.SIGUSR1, _sigusr1_handler)
    except Exception:
        pass
    daemon_state: dict[str, Any] = {
        "schema_version": "1.1.0",
        "initialized": cfg_path.exists(),
        "enabled": bool(enable_daemon and cfg_path.exists()),
        "manually_disabled": False,
        "running": False,
        "last_result": {},
        "scan_interval": daemon_scan_interval,
        "pull_interval": daemon_pull_interval,
        "retry_max_attempts": max(1, int(daemon_retry_max_attempts)),
        "retry_initial_backoff": max(1, int(daemon_retry_initial_backoff)),
        "retry_max_backoff": max(1, int(daemon_retry_max_backoff)),
        "maintenance_enabled": bool(daemon_maintenance_enabled),
        "maintenance_interval": max(60, int(daemon_maintenance_interval)),
        "maintenance_decay_days": max(1, int(daemon_maintenance_decay_days)),
        "maintenance_decay_limit": max(1, int(daemon_maintenance_decay_limit)),
        "maintenance_prune_enabled": bool(daemon_maintenance_prune_enabled),
        "maintenance_prune_days": max(1, int(daemon_maintenance_prune_days)),
        "maintenance_prune_limit": max(1, int(daemon_maintenance_prune_limit)),
        "maintenance_prune_layers": [x.strip() for x in str(daemon_maintenance_prune_layers or "").split(",") if x.strip()] or ["instant", "short"],
        "maintenance_prune_keep_kinds": [
            x.strip() for x in str(daemon_maintenance_prune_keep_kinds or "").split(",") if x.strip()
        ]
        or ["decision", "checkpoint"],
        "maintenance_consolidate_limit": max(1, int(daemon_maintenance_consolidate_limit)),
        "maintenance_compress_sessions": max(1, int(daemon_maintenance_compress_sessions)),
        "maintenance_compress_min_items": max(2, int(daemon_maintenance_compress_min_items)),
        "maintenance_temporal_tree_enabled": bool(daemon_maintenance_temporal_tree_enabled),
        "maintenance_temporal_tree_days": max(1, int(daemon_maintenance_temporal_tree_days)),
        "maintenance_rehearsal_enabled": bool(daemon_maintenance_rehearsal_enabled),
        "maintenance_rehearsal_days": max(1, int(daemon_maintenance_rehearsal_days)),
        "maintenance_rehearsal_limit": max(1, int(daemon_maintenance_rehearsal_limit)),
        "maintenance_reflection_enabled": bool(daemon_maintenance_reflection_enabled),
        "maintenance_reflection_days": max(1, int(daemon_maintenance_reflection_days)),
        "maintenance_reflection_limit": max(1, int(daemon_maintenance_reflection_limit)),
        "maintenance_reflection_min_repeats": max(1, int(daemon_maintenance_reflection_min_repeats)),
        "maintenance_reflection_max_avg_retrieved": float(daemon_maintenance_reflection_max_avg_retrieved),
        "cycles": 0,
        "success_count": 0,
        "failure_count": 0,
        "last_run_at": "",
        "last_success_at": "",
        "last_failure_at": "",
        "last_error": "",
        "last_error_kind": "none",
        "remediation_hint": "",
    }
    stop_event = threading.Event()

    def daemon_loop() -> None:
        if daemon_runner is None:
            return
        daemon_state["running"] = True
        # `daemon_runner(..., once=True)` resets its internal timers each call.
        # So we must enforce pull cadence here; otherwise we'd run a full sync every scan tick.
        last_full_run_ts = 0.0
        while not stop_event.is_set():
            if not daemon_state.get("initialized", False):
                time.sleep(1)
                continue
            if not daemon_state.get("enabled", True):
                time.sleep(1)
                continue
            scan_every = max(1, int(daemon_state.get("scan_interval", daemon_scan_interval)))
            pull_every = max(5, int(daemon_state.get("pull_interval", daemon_pull_interval)))
            now_ts = time.time()
            if last_full_run_ts > 0 and (now_ts - last_full_run_ts) < pull_every:
                time.sleep(scan_every)
                continue
            try:
                # Operational telemetry for diagnosing long-running instability.
                try:
                    _elog(
                        f"[{utc_now()}] daemon_loop begin "
                        f"threads={len(threading.enumerate())} fds={_fd_count()}"
                    )
                except Exception:
                    pass
                daemon_state["cycles"] = int(daemon_state.get("cycles", 0)) + 1
                daemon_state["last_run_at"] = utc_now()
                gh = cfg.get("sync", {}).get("github", {})
                result = daemon_runner(
                    paths=paths,
                    schema_sql_path=schema_sql_path,
                    remote_name=gh.get("remote_name", "origin"),
                    branch=gh.get("branch", "main"),
                    remote_url=gh.get("remote_url"),
                    oauth_token_file=_sync_oauth_token_file_from_cfg(cfg),
                    sync_include_layers=_sync_options_from_cfg(cfg)[0],
                    sync_include_jsonl=_sync_options_from_cfg(cfg)[1],
                    scan_interval=scan_every,
                    pull_interval=pull_every,
                    maintenance_enabled=bool(daemon_state.get("maintenance_enabled", True)),
                    maintenance_interval=int(daemon_state.get("maintenance_interval", 300)),
                    maintenance_decay_days=int(daemon_state.get("maintenance_decay_days", 14)),
                    maintenance_decay_limit=int(daemon_state.get("maintenance_decay_limit", 120)),
                    maintenance_prune_enabled=bool(daemon_state.get("maintenance_prune_enabled", False)),
                    maintenance_prune_days=int(daemon_state.get("maintenance_prune_days", 45)),
                    maintenance_prune_limit=int(daemon_state.get("maintenance_prune_limit", 300)),
                    maintenance_prune_layers=list(daemon_state.get("maintenance_prune_layers", ["instant", "short"]) or ["instant", "short"]),
                    maintenance_prune_keep_kinds=list(
                        daemon_state.get("maintenance_prune_keep_kinds", ["decision", "checkpoint"])
                        or ["decision", "checkpoint"]
                    ),
                    maintenance_consolidate_limit=int(daemon_state.get("maintenance_consolidate_limit", 80)),
                    maintenance_compress_sessions=int(daemon_state.get("maintenance_compress_sessions", 2)),
                    maintenance_compress_min_items=int(daemon_state.get("maintenance_compress_min_items", 8)),
                    maintenance_temporal_tree_enabled=bool(daemon_state.get("maintenance_temporal_tree_enabled", True)),
                    maintenance_temporal_tree_days=int(daemon_state.get("maintenance_temporal_tree_days", 30)),
                    maintenance_rehearsal_enabled=bool(daemon_state.get("maintenance_rehearsal_enabled", True)),
                    maintenance_rehearsal_days=int(daemon_state.get("maintenance_rehearsal_days", 45)),
                    maintenance_rehearsal_limit=int(daemon_state.get("maintenance_rehearsal_limit", 16)),
                    maintenance_reflection_enabled=bool(daemon_state.get("maintenance_reflection_enabled", True)),
                    maintenance_reflection_days=int(daemon_state.get("maintenance_reflection_days", 14)),
                    maintenance_reflection_limit=int(daemon_state.get("maintenance_reflection_limit", 4)),
                    maintenance_reflection_min_repeats=int(daemon_state.get("maintenance_reflection_min_repeats", 2)),
                    maintenance_reflection_max_avg_retrieved=float(
                        daemon_state.get("maintenance_reflection_max_avg_retrieved", 2.0)
                    ),
                    maintenance_adaptive_q_promote_imp=float(cfg.get("daemon", {}).get("adaptive_q_promote_imp", 0.68)),
                    maintenance_adaptive_q_promote_conf=float(cfg.get("daemon", {}).get("adaptive_q_promote_conf", 0.60)),
                    maintenance_adaptive_q_promote_stab=float(cfg.get("daemon", {}).get("adaptive_q_promote_stab", 0.62)),
                    maintenance_adaptive_q_promote_vol=float(cfg.get("daemon", {}).get("adaptive_q_promote_vol", 0.42)),
                    maintenance_adaptive_q_demote_vol=float(cfg.get("daemon", {}).get("adaptive_q_demote_vol", 0.78)),
                    maintenance_adaptive_q_demote_stab=float(cfg.get("daemon", {}).get("adaptive_q_demote_stab", 0.28)),
                    maintenance_adaptive_q_demote_reuse=float(cfg.get("daemon", {}).get("adaptive_q_demote_reuse", 0.30)),
                    retry_max_attempts=int(daemon_state.get("retry_max_attempts", daemon_retry_max_attempts)),
                    retry_initial_backoff=int(daemon_state.get("retry_initial_backoff", daemon_retry_initial_backoff)),
                    retry_max_backoff=int(daemon_state.get("retry_max_backoff", daemon_retry_max_backoff)),
                    once=True,
                )
                last_full_run_ts = time.time()
                daemon_state["last_result"] = result
                if result.get("ok"):
                    daemon_state["success_count"] = int(daemon_state.get("success_count", 0)) + 1
                    daemon_state["last_success_at"] = utc_now()
                    daemon_state["last_error"] = ""
                    daemon_state["last_error_kind"] = "none"
                    daemon_state["remediation_hint"] = ""
                else:
                    daemon_state["failure_count"] = int(daemon_state.get("failure_count", 0)) + 1
                    daemon_state["last_failure_at"] = utc_now()
                    daemon_state["last_error"] = str(result.get("error", "sync failed"))
                    daemon_state["last_error_kind"] = str(result.get("last_error_kind", "unknown"))
                    daemon_state["remediation_hint"] = str(
                        result.get("remediation_hint", sync_error_hint(daemon_state["last_error_kind"]))
                    )
                try:
                    _elog(
                        f"[{utc_now()}] daemon_loop end ok={bool(result.get('ok'))} "
                        f"threads={len(threading.enumerate())} fds={_fd_count()}"
                    )
                except Exception:
                    pass
            except Exception as exc:  # pragma: no cover
                daemon_state["last_result"] = {"ok": False, "error": str(exc)}
                daemon_state["failure_count"] = int(daemon_state.get("failure_count", 0)) + 1
                daemon_state["last_failure_at"] = utc_now()
                daemon_state["last_error"] = str(exc)
                daemon_state["last_error_kind"] = "unknown"
                daemon_state["remediation_hint"] = sync_error_hint("unknown")
                _elog(f"[{utc_now()}] daemon_loop exception: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
            time.sleep(scan_every)
        daemon_state["running"] = False

    daemon_thread: threading.Thread | None = None
    if enable_daemon and daemon_runner is not None:
        daemon_thread = threading.Thread(target=daemon_loop, name="omnimem-daemon", daemon=True)
        daemon_thread.start()

    @contextmanager
    def _db_connect():
        # Keep DB waits short so the WebUI stays responsive even if the daemon is doing a heavy write
        # (reindex/weave). Longer waits can cause request threads to pile up.
        conn = sqlite3.connect(paths.sqlite_path, timeout=1.2)
        try:
            conn.execute('PRAGMA busy_timeout = 1200')
        except Exception:
            pass
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # Micro-cache for expensive aggregations (ThreadingHTTPServer may call handlers concurrently).
    event_stats_cache: dict[tuple[str, str, int], tuple[float, dict[str, Any]]] = {}
    event_stats_lock = threading.Lock()
    events_cache: dict[tuple[str, str, str, int], tuple[float, dict[str, Any]]] = {}
    events_cache_lock = threading.Lock()
    smart_retrieve_cache: dict[
        tuple[str, str, str, int, int, str, bool, float, int, bool, float],
        tuple[float, dict[str, Any]],
    ] = {}
    smart_retrieve_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:  # noqa: A002
            # Default writes to stderr; persist errors for debugging.
            try:
                msg = fmt % args
            except Exception:
                msg = fmt
            _elog(f"[{utc_now()}] access {self.client_address} {msg}")

        def _authorized(self, parsed) -> bool:
            if parsed.path == "/api/health":
                return True
            if not parsed.path.startswith("/api/"):
                return True
            if not resolved_auth_token:
                return True
            supplied = self.headers.get("X-OmniMem-Token", "").strip()
            return supplied == resolved_auth_token

        def _send_json(self, data: dict[str, Any], code: int = 200) -> None:
            b = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _send_html(self, html: str, code: int = 200) -> None:
            b = html.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(HTML_PAGE)
                return

            if not self._authorized(parsed):
                self._send_json({"ok": False, "error": "unauthorized"}, 401)
                return

            if parsed.path == "/api/health":
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/health/check":
                try:
                    self._send_json(_run_health_check(paths, daemon_state))
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/version":
                self._send_json(
                    {
                        "ok": True,
                        "version": OMNIMEM_VERSION,
                        "webui_schema_version": str(daemon_state.get("schema_version", "")),
                    }
                )
                return

            if parsed.path == "/api/config":
                self._send_json(_cfg_to_ui(cfg, cfg_path))
                return

            if parsed.path == "/api/github/status":
                self._send_json(_github_status(cfg))
                return

            if parsed.path == "/api/github/setup-plan":
                self._send_json(_github_setup_plan(cfg=cfg, initialized=bool(cfg_path.exists())))
                return

            if parsed.path == "/api/github/repos":
                q = parse_qs(parsed.query)
                limit = _parse_int_param(q.get("limit", ["80"])[0], default=80, lo=1, hi=200)
                query = str(q.get("query", [""])[0] or "").strip()
                self._send_json(_github_repo_list(cfg=cfg, query=query, limit=limit))
                return

            if parsed.path == "/api/route-templates":
                try:
                    items = _normalize_route_templates(cfg.get("webui", {}).get("route_templates", []))
                    self._send_json({"ok": True, "items": items})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/daemon":
                self._send_json({"ok": True, **daemon_state})
                return

            if parsed.path == "/api/context-runtime":
                try:
                    q = parse_qs(parsed.query)
                    project_id = str(q.get("project_id", [""])[0] or "").strip()
                    tool = str(q.get("tool", [""])[0] or "").strip()
                    window = _parse_int_param(q.get("window", ["12"])[0], default=12, lo=1, hi=120)
                    out = _context_runtime_summary(
                        paths_root=paths.root,
                        project_id=project_id,
                        tool=tool,
                        window=window,
                    )
                    out["project_id"] = project_id
                    out["tool"] = tool
                    out["window"] = int(window)
                    self._send_json(out)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/fs/cwd":
                self._send_json({"ok": True, "cwd": str(Path.cwd())})
                return

            if parsed.path == "/api/fs/list":
                q = parse_qs(parsed.query)
                raw_path = q.get("path", [""])[0].strip()
                base = Path(raw_path).expanduser() if raw_path else Path.home()
                try:
                    p = base.resolve()
                    if not p.exists() or not p.is_dir():
                        self._send_json({"ok": False, "error": f"not a directory: {p}"}, 400)
                        return
                    items = []
                    for child in sorted(p.iterdir(), key=lambda x: x.name.lower()):
                        if child.is_dir() and not child.name.startswith("."):
                            items.append({"name": child.name, "path": str(child)})
                        if len(items) >= 200:
                            break
                    self._send_json({"ok": True, "path": str(p), "items": items})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/project/defaults":
                self._send_json(
                    {
                        "ok": True,
                        "project_path": "",
                        "project_id": "",
                    }
                )
                return

            if parsed.path == "/api/projects":
                items = _load_projects_registry(str(cfg.get("home", "")))
                for it in items:
                    p = Path(str(it.get("project_path", ""))).expanduser()
                    it["exists"] = p.exists() and p.is_dir()
                items.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
                self._send_json({"ok": True, "items": items})
                return

            if parsed.path == "/api/memories":
                req = _parse_memories_request(parse_qs(parsed.query))
                req_limit = max(1, min(200, int(req["limit"])))
                req_offset = max(0, min(10000, int(req.get("offset", 0))))
                if str(req["mode"]) == "smart" and str(req["query"]):
                    cache_key = _build_smart_memories_cache_key(req)
                    depth_i = int(req["depth"])
                    hop_i = int(req["per_hop"])
                    rank_i = str(req["ranking_mode"]).lower()
                    if rank_i not in {"path", "ppr", "hybrid"}:
                        rank_i = "hybrid"
                    limit_i = _resolve_memories_scan_limit(
                        req_limit=req_limit,
                        req_offset=req_offset,
                        sort_mode=str(req.get("sort_mode", "server")),
                        mode="smart",
                    )
                    out: dict[str, Any] | None = None
                    now = time.time()
                    with smart_retrieve_lock:
                        out = _cache_get(smart_retrieve_cache, cache_key, now=now, ttl_s=12.0)
                    if out is None:
                        out = retrieve_thread(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            query=str(req["query"]),
                            project_id=str(req["project_id"]),
                            session_id=str(req["session_id"]),
                            seed_limit=limit_i,
                            depth=depth_i,
                            per_hop=hop_i,
                            ranking_mode=rank_i,
                            diversify=bool(req["diversify"]),
                            mmr_lambda=float(req["mmr_lambda"]),
                            max_items=limit_i,
                            self_check=True,
                            adaptive_feedback=True,
                            feedback_reuse_step=1,
                            profile_aware=bool(req["profile_aware"]),
                            profile_weight=float(req["profile_weight"]),
                            include_core_blocks=bool(req["include_core_blocks"]),
                            core_block_limit=int(req["core_block_limit"]),
                            core_merge_by_topic=bool(req["core_merge_by_topic"]),
                            drift_aware=bool(req["drift_aware"]),
                            drift_recent_days=int(req["drift_recent_days"]),
                            drift_baseline_days=int(req["drift_baseline_days"]),
                            drift_weight=float(req["drift_weight"]),
                        )
                        with smart_retrieve_lock:
                            _cache_set(smart_retrieve_cache, cache_key, out, now=now, max_items=96)
                    pre_items = list(out.get("items") or [])
                    scan_count = len(pre_items)
                    scan_capped = bool(scan_count >= max(1, int(limit_i)))
                    items = list(pre_items)
                    if req["layer"]:
                        items = [x for x in items if str(x.get("layer") or "") == str(req["layer"])]
                    items, before_dedup = _process_memories_items(
                        paths=paths,
                        items=items,
                        route=str(req["route"]),
                        kind_filter=str(req["kind_filter"]),
                        tag_filter=str(req["tag_filter"]),
                        since_days=int(req["since_days"]),
                        dedup_mode=str(req["dedup_mode"]),
                    )
                    items = _sort_memory_items(items, sort_mode=str(req.get("sort_mode", "server")))
                    if bool(req.get("include_preview", True)):
                        items = _attach_memory_previews(paths, items, max_chars=300, max_items=120)
                    total_available = len(items)
                    shown_items = items[req_offset : req_offset + req_limit]
                    next_offset = req_offset + len(shown_items)
                    remaining_count = max(0, total_available - next_offset)
                    self._send_json(
                        {
                            "ok": True,
                            "items": shown_items,
                            "mode": "smart",
                            "route": str(req["route"]),
                            "dedup": {"mode": str(req["dedup_mode"]), "before": before_dedup, "after": len(items)},
                            "requested_limit": req_limit,
                            "requested_offset": req_offset,
                            "total_available": total_available,
                            "displayed_count": len(shown_items),
                            "scan_limit": int(limit_i),
                            "scan_count": int(scan_count),
                            "scan_capped": bool(scan_capped),
                            "truncated": bool(total_available > next_offset),
                            "has_more": bool(total_available > next_offset),
                            "next_offset": next_offset,
                            "remaining_count": remaining_count,
                            "explain": out.get("explain", {}),
                        }
                    )
                else:
                    basic_limit = _resolve_memories_scan_limit(
                        req_limit=req_limit,
                        req_offset=req_offset,
                        sort_mode=str(req.get("sort_mode", "server")),
                        mode="basic",
                    )
                    items = find_memories(
                        paths,
                        schema_sql_path,
                        query=str(req["query"]),
                        layer=str(req["layer"] or "") or None,
                        limit=basic_limit,
                        project_id=str(req["project_id"]),
                        session_id=str(req["session_id"]),
                    )
                    scan_count = len(items)
                    scan_capped = bool(scan_count >= max(1, int(basic_limit)))
                    items, before_dedup = _process_memories_items(
                        paths=paths,
                        items=items,
                        route=str(req["route"]),
                        kind_filter=str(req["kind_filter"]),
                        tag_filter=str(req["tag_filter"]),
                        since_days=int(req["since_days"]),
                        dedup_mode=str(req["dedup_mode"]),
                    )
                    items = _sort_memory_items(items, sort_mode=str(req.get("sort_mode", "server")))
                    if bool(req.get("include_preview", True)):
                        items = _attach_memory_previews(paths, items, max_chars=300, max_items=120)
                    total_available = len(items)
                    shown_items = items[req_offset : req_offset + req_limit]
                    next_offset = req_offset + len(shown_items)
                    remaining_count = max(0, total_available - next_offset)
                    self._send_json(
                        {
                            "ok": True,
                            "items": shown_items,
                            "mode": "basic",
                            "route": str(req["route"]),
                            "dedup": {"mode": str(req["dedup_mode"]), "before": before_dedup, "after": len(items)},
                            "requested_limit": req_limit,
                            "requested_offset": req_offset,
                            "total_available": total_available,
                            "displayed_count": len(shown_items),
                            "scan_limit": int(basic_limit),
                            "scan_count": int(scan_count),
                            "scan_capped": bool(scan_capped),
                            "truncated": bool(total_available > next_offset),
                            "has_more": bool(total_available > next_offset),
                            "next_offset": next_offset,
                            "remaining_count": remaining_count,
                        }
                    )
                return

            if parsed.path == "/api/layer-stats":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                try:
                    with _db_connect() as conn:
                        where = ""
                        args: list[Any] = []
                        if project_id:
                            where = "WHERE json_extract(scope_json, '$.project_id') = ?"
                            args.append(project_id)
                        if session_id:
                            where = (where + " AND " if where else "WHERE ") + "COALESCE(json_extract(source_json, '$.session_id'), '') = ?"
                            args.append(session_id)
                        rows = conn.execute(
                            f"""
                            SELECT layer, count(*) AS c
                            FROM memories
                            {where}
                            GROUP BY layer
                            ORDER BY layer
                            """,
                            args,
                        ).fetchall()
                    items = [{"layer": r[0], "count": int(r[1])} for r in rows]
                    self._send_json({"ok": True, "project_id": project_id, "session_id": session_id, "items": items})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/governance":
                req = _parse_governance_request(parse_qs(parsed.query))
                project_id = str(req["project_id"])
                session_id = str(req["session_id"])
                limit = int(req["limit"])
                thresholds = dict(req["thresholds"])
                p_imp = float(thresholds["p_imp"])
                p_conf = float(thresholds["p_conf"])
                p_stab = float(thresholds["p_stab"])
                p_vol = float(thresholds["p_vol"])
                d_vol = float(thresholds["d_vol"])
                d_stab = float(thresholds["d_stab"])
                d_reuse = int(thresholds["d_reuse"])
                try:
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        scope_where, scope_args = _governance_scope_filters(project_id, session_id)

                        promote = conn.execute(
                            f"""
                            SELECT id, layer, kind, summary, updated_at,
                                   importance_score, confidence_score, stability_score, reuse_count, volatility_score
                            FROM memories
                            WHERE layer IN ('instant','short')
                              AND importance_score >= ?
                              AND confidence_score >= ?
                              AND stability_score >= ?
                              AND volatility_score <= ?
                              {scope_where}
                            ORDER BY importance_score DESC, stability_score DESC, updated_at DESC
                            LIMIT ?
                            """,
                            (p_imp, p_conf, p_stab, p_vol, *scope_args, limit),
                        ).fetchall()

                        demote = conn.execute(
                            f"""
                            SELECT id, layer, kind, summary, updated_at,
                                   importance_score, confidence_score, stability_score, reuse_count, volatility_score
                            FROM memories
                            WHERE layer = 'long'
                              AND (volatility_score >= ? OR stability_score <= ?)
                              AND reuse_count <= ?
                              {scope_where}
                            ORDER BY volatility_score DESC, stability_score ASC, updated_at DESC
                            LIMIT ?
                            """,
                            (d_vol, d_stab, d_reuse, *scope_args, limit),
                        ).fetchall()

                    recommended: dict[str, Any] = {}
                    try:
                        rec = _infer_governance_thresholds(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            cfg=cfg,
                            project_id=project_id,
                            session_id=session_id,
                            days=14,
                        )
                        if rec.get("ok"):
                            recommended = {
                                "thresholds": dict(rec.get("thresholds") or {}),
                                "quantiles": dict(rec.get("quantiles") or {}),
                                "feedback": dict(rec.get("feedback") or {}),
                                "drift": dict(rec.get("drift") or {}),
                                "sample_size": int(rec.get("sample_size", 0) or 0),
                                "window_days": int(rec.get("days", 14) or 14),
                            }
                    except Exception:
                        recommended = {}

                    self._send_json(
                        {
                            "ok": True,
                            "project_id": project_id,
                            "session_id": session_id,
                            "thresholds": {
                                "p_imp": p_imp,
                                "p_conf": p_conf,
                                "p_stab": p_stab,
                                "p_vol": p_vol,
                                "d_vol": d_vol,
                                "d_stab": d_stab,
                                "d_reuse": d_reuse,
                            },
                            "promote": _pack_governance_rows(promote),
                            "demote": _pack_governance_rows(demote),
                            "recommended": recommended,
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/governance/explain":
                q = parse_qs(parsed.query)
                mem_id = q.get("id", [""])[0].strip()
                adaptive = _parse_bool_param(q.get("adaptive", ["1"])[0], default=True)
                days = max(1, min(60, int(float(q.get("days", ["14"])[0]))))
                if not mem_id:
                    self._send_json({"ok": False, "error": "missing id"}, 400)
                    return
                try:
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        row = conn.execute(
                            """
                            SELECT id, layer,
                                   importance_score, confidence_score, stability_score, reuse_count, volatility_score,
                                   source_json, scope_json
                            FROM memories
                            WHERE id = ?
                            """,
                            (mem_id,),
                        ).fetchone()
                    if not row:
                        self._send_json({"ok": False, "error": "not found"}, 404)
                        return

                    source = json.loads(row["source_json"] or "{}")
                    scope = json.loads(row["scope_json"] or "{}")
                    project_id = str(scope.get("project_id", "") or "")
                    session_id = str(source.get("session_id", "") or "")
                    thresholds: dict[str, Any] = {
                        "p_imp": 0.75,
                        "p_conf": 0.65,
                        "p_stab": 0.65,
                        "p_vol": 0.65,
                        "d_vol": 0.75,
                        "d_stab": 0.45,
                        "d_reuse": 1,
                    }
                    quantiles: dict[str, Any] = {}
                    if adaptive:
                        inf = _infer_governance_thresholds(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            cfg=cfg,
                            project_id=project_id,
                            session_id=session_id,
                            days=days,
                        )
                        if inf.get("ok"):
                            thresholds = dict(inf.get("thresholds") or thresholds)
                            quantiles = dict(inf.get("quantiles") or {})
                            drift_info = dict(inf.get("drift") or {})
                        else:
                            drift_info = {}
                    else:
                        drift_info = {}

                    explain = _evaluate_governance_action(
                        layer=str(row["layer"] or ""),
                        signals={
                            "importance_score": float(row["importance_score"] or 0.0),
                            "confidence_score": float(row["confidence_score"] or 0.0),
                            "stability_score": float(row["stability_score"] or 0.0),
                            "reuse_count": int(row["reuse_count"] or 0),
                            "volatility_score": float(row["volatility_score"] or 0.0),
                        },
                        thresholds=thresholds,
                    )
                    self._send_json(
                        {
                            "ok": True,
                            "memory_id": mem_id,
                            "project_id": project_id,
                            "session_id": session_id,
                            "adaptive": adaptive,
                            "days": days,
                            "quantiles": quantiles,
                            "drift": drift_info,
                            "explain": explain,
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/timeline":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                limit = int(q.get("limit", ["80"])[0])

                def extract_drift(body_text: str) -> float | None:
                    m = re.search(r"\\bdrift=([0-9]*\\.?[0-9]+)\\b", body_text)
                    if not m:
                        return None
                    try:
                        return float(m.group(1))
                    except Exception:
                        return None

                try:
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        rows = conn.execute(
                            """
                            SELECT id, layer, kind, summary, updated_at, body_text, source_json, tags_json
                            FROM memories
                            WHERE (? = '' OR json_extract(scope_json, '$.project_id') = ?)
                              AND (? = '' OR COALESCE(json_extract(source_json, '$.session_id'), '') = ?)
                              AND (
                                kind = 'checkpoint'
                                OR EXISTS (SELECT 1 FROM json_each(memories.tags_json) WHERE value IN ('auto:turn','auto:checkpoint','auto:retrieve'))
                              )
                            ORDER BY updated_at DESC
                            LIMIT ?
                            """,
                            (project_id, project_id, session_id, session_id, limit),
                        ).fetchall()

                    items = []
                    for r in rows:
                        src = json.loads(r["source_json"] or "{}")
                        body = r["body_text"] or ""
                        drift = extract_drift(body)
                        switched = ("old_session_id" in body) or ("topic switch" in (r["summary"] or "").lower())
                        items.append(
                            {
                                "id": r["id"],
                                "layer": r["layer"],
                                "kind": r["kind"],
                                "summary": r["summary"],
                                "updated_at": r["updated_at"],
                                "session_id": src.get("session_id", ""),
                                "tool": src.get("tool", ""),
                                "drift": drift,
                                "switched": bool(switched),
                            }
                        )
                    self._send_json({"ok": True, "project_id": project_id, "session_id": session_id, "items": items})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/memory":
                q = parse_qs(parsed.query)
                mem_id = q.get("id", [""])[0]
                if not mem_id:
                    self._send_json({"ok": False, "error": "missing id"}, 400)
                    return
                try:
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        row = conn.execute(
                            """
                            SELECT id, layer, kind, summary, created_at, updated_at, body_md_path,
                                   tags_json, importance_score, confidence_score, stability_score, reuse_count, volatility_score,
                                   source_json, scope_json
                            FROM memories
                            WHERE id = ?
                            """,
                            (mem_id,),
                        ).fetchone()
                        refs = (
                            conn.execute(
                                "SELECT ref_type, target, note FROM memory_refs WHERE memory_id = ?",
                                (mem_id,),
                            ).fetchall()
                            if row
                            else []
                        )
                    if not row:
                        self._send_json({"ok": False, "error": "not found"}, 404)
                        return

                    md_path = paths.markdown_root / row["body_md_path"]
                    body = md_path.read_text(encoding="utf-8")
                    mem = {
                        "id": row["id"],
                        "layer": row["layer"],
                        "kind": row["kind"],
                        "summary": row["summary"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "body_md_path": row["body_md_path"],
                        "tags": json.loads(row["tags_json"] or "[]"),
                        "signals": {
                            "importance_score": float(row["importance_score"]),
                            "confidence_score": float(row["confidence_score"]),
                            "stability_score": float(row["stability_score"]),
                            "reuse_count": int(row["reuse_count"]),
                            "volatility_score": float(row["volatility_score"]),
                        },
                        "source": json.loads(row["source_json"] or "{}"),
                        "scope": json.loads(row["scope_json"] or "{}"),
                        "refs": [{"type": r["ref_type"], "target": r["target"], "note": r["note"]} for r in refs],
                    }
                    self._send_json({"ok": True, "memory": mem, "body": body})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/profile":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                limit = _parse_int_param(q.get("limit", ["240"])[0], default=240, lo=20, hi=1200)
                try:
                    out = build_user_profile(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        project_id=project_id,
                        session_id=session_id,
                        limit=limit,
                    )
                    self._send_json(out)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/profile/drift":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                recent_days = _parse_int_param(q.get("recent_days", ["14"])[0], default=14, lo=1, hi=60)
                baseline_days = _parse_int_param(q.get("baseline_days", ["120"])[0], default=120, lo=2, hi=720)
                limit = _parse_int_param(q.get("limit", ["800"])[0], default=800, lo=80, hi=4000)
                try:
                    out = analyze_profile_drift(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        project_id=project_id,
                        session_id=session_id,
                        recent_days=recent_days,
                        baseline_days=baseline_days,
                        limit=limit,
                    )
                    self._send_json(out)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/core-blocks":
                q = parse_qs(parsed.query)
                name = q.get("name", [""])[0].strip()
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                limit = _parse_int_param(q.get("limit", ["64"])[0], default=64, lo=1, hi=200)
                include_expired = _parse_bool_param(q.get("include_expired", ["0"])[0], default=False)
                try:
                    if name:
                        out = get_core_block(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            name=name,
                            project_id=project_id,
                            session_id=session_id,
                        )
                    else:
                        out = list_core_blocks(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            project_id=project_id,
                            session_id=session_id,
                            limit=limit,
                            include_expired=bool(include_expired),
                        )
                    self._send_json(out, 200 if out.get("ok") else 404)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/memory/move-history":
                q = parse_qs(parsed.query)
                mem_id = q.get("id", [""])[0].strip()
                limit = max(1, min(50, int(float(q.get("limit", ["8"])[0]))))
                if not mem_id:
                    self._send_json({"ok": False, "error": "missing id"}, 400)
                    return
                try:
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        rows = conn.execute(
                            """
                            SELECT event_id, event_time, payload_json
                            FROM memory_events
                            WHERE memory_id = ? AND event_type = 'memory.promote'
                            ORDER BY event_time DESC
                            LIMIT ?
                            """,
                            (mem_id, limit),
                        ).fetchall()
                    items = []
                    for r in rows:
                        payload = {}
                        try:
                            payload = json.loads(r["payload_json"] or "{}")
                        except Exception:
                            payload = {}
                        items.append(
                            {
                                "event_id": str(r["event_id"]),
                                "event_time": str(r["event_time"]),
                                "from_layer": str(payload.get("from_layer", "")),
                                "to_layer": str(payload.get("to_layer", "")),
                            }
                        )
                    self._send_json({"ok": True, "memory_id": mem_id, "items": items})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/memory/rollback-preview":
                q = parse_qs(parsed.query)
                mem_id = q.get("id", [""])[0].strip()
                to_event_time = q.get("to_event_time", [""])[0].strip()
                if not mem_id or not to_event_time:
                    self._send_json({"ok": False, "error": "id and to_event_time are required"}, 400)
                    return
                ttxt = to_event_time[:-1] + "+00:00" if to_event_time.endswith("Z") else to_event_time
                try:
                    tdt = datetime.fromisoformat(ttxt)
                    if tdt.tzinfo is None:
                        tdt = tdt.replace(tzinfo=timezone.utc)
                    cutoff = tdt.astimezone(timezone.utc).replace(microsecond=0).isoformat()
                except Exception:
                    self._send_json({"ok": False, "error": "invalid to_event_time (ISO-8601 required)"}, 400)
                    return
                try:
                    with _db_connect() as conn:
                        rows, predicted = _rollback_preview_items(conn, memory_id=mem_id, cutoff_iso=cutoff)
                        cur = conn.execute("SELECT layer FROM memories WHERE id = ?", (mem_id,)).fetchone()
                        before = str(cur["layer"]) if cur else ""
                    self._send_json(
                        {
                            "ok": True,
                            "memory_id": mem_id,
                            "to_event_time": cutoff,
                            "before_layer": before,
                            "after_layer": predicted,
                            "items": rows,
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/events":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                event_type = q.get("event_type", [""])[0].strip()
                limit = _parse_int_param(q.get("limit", ["60"])[0], default=60, lo=1, hi=200)
                fetch_limit = max(400, min(2000, limit * 20))
                cache_key = (project_id, session_id, event_type, limit)
                now = time.time()
                with events_cache_lock:
                    out_cached = _cache_get(events_cache, cache_key, now=now, ttl_s=2.0)
                    if out_cached is not None:
                        self._send_json(out_cached)
                        return
                try:
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        args: list[Any] = []
                        where = ""
                        if event_type:
                            where = "WHERE event_type = ?"
                            args.append(event_type)
                        rows = conn.execute(
                            f"""
                            SELECT event_id, event_type, event_time, memory_id, payload_json
                            FROM memory_events
                            {where}
                            ORDER BY event_time DESC
                            LIMIT ?
                            """,
                            (*args, fetch_limit),
                        ).fetchall()

                    items = []
                    for r in rows:
                        try:
                            payload = json.loads(r["payload_json"] or "{}")
                        except Exception:
                            payload = {}
                        env = payload.get("envelope") if isinstance(payload, dict) else None
                        if not isinstance(env, dict):
                            env = {}
                        scope = env.get("scope") if isinstance(env.get("scope"), dict) else {}
                        source = env.get("source") if isinstance(env.get("source"), dict) else {}

                        pid = ""
                        sid = ""
                        if isinstance(payload, dict):
                            pid = str(scope.get("project_id", "") or payload.get("project_id", "") or "").strip()
                            sid = str(source.get("session_id", "") or payload.get("session_id", "") or "").strip()
                        if project_id and pid != project_id:
                            continue
                        if session_id and sid != session_id:
                            continue

                        summary = ""
                        if isinstance(payload, dict):
                            summary = str(payload.get("summary", "") or env.get("summary", "") or "")
                            if not summary and r["event_type"] == "memory.promote":
                                fr = payload.get("from_layer", "")
                                to = payload.get("to_layer", "")
                                summary = f"{fr}->{to}"
                            if not summary and r["event_type"] == "memory.reuse":
                                summary = f"delta={payload.get('delta','')}, count={payload.get('count','')}"
                            if not summary and r["event_type"] == "memory.sync":
                                d2 = payload.get("daemon") or {}
                                if isinstance(d2, dict):
                                    summary = f"ok={d2.get('ok')}, err={d2.get('last_error_kind','')}"

                        items.append(
                            {
                                "event_id": r["event_id"],
                                "event_type": r["event_type"],
                                "event_time": r["event_time"],
                                "memory_id": r["memory_id"],
                                "project_id": pid,
                                "session_id": sid,
                                "summary": summary,
                            }
                        )
                        if len(items) >= limit:
                            break

                    out = {
                        "ok": True,
                        "project_id": project_id,
                        "session_id": session_id,
                        "event_type": event_type,
                        "items": items,
                    }
                    with events_cache_lock:
                        _cache_set(events_cache, cache_key, out, now=now, max_items=128)
                    self._send_json(out)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/event":
                q = parse_qs(parsed.query)
                event_id = q.get("event_id", [""])[0].strip()
                if not event_id:
                    self._send_json({"ok": False, "error": "missing event_id"}, 400)
                    return
                try:
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        r = conn.execute(
                            """
                            SELECT event_id, event_type, event_time, memory_id, payload_json
                            FROM memory_events
                            WHERE event_id = ?
                            """,
                            (event_id,),
                        ).fetchone()
                    if not r:
                        self._send_json({"ok": False, "error": "not found"}, 404)
                        return
                    try:
                        payload = json.loads(r["payload_json"] or "{}")
                    except Exception:
                        payload = {}
                    self._send_json(
                        {
                            "ok": True,
                            "item": {
                                "event_id": r["event_id"],
                                "event_type": r["event_type"],
                                "event_time": r["event_time"],
                                "memory_id": r["memory_id"],
                                "payload": payload,
                            },
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/event-stats":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                days = _parse_int_param(q.get("days", ["14"])[0], default=14, lo=1, hi=60)
                limit = _parse_int_param(q.get("limit", ["8000"])[0], default=8000, lo=200, hi=20000)
                cache_key = (project_id, session_id, days)
                now = time.time()
                with event_stats_lock:
                    out_cached = _cache_get(event_stats_cache, cache_key, now=now, ttl_s=3.0)
                    if out_cached is not None:
                        self._send_json(out_cached)
                        return
                try:
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        rows = conn.execute(
                            """
                            SELECT event_type, event_time, payload_json
                            FROM memory_events
                            ORDER BY event_time DESC
                            LIMIT ?
                            """,
                            (limit,),
                        ).fetchall()

                    agg = _aggregate_event_stats(
                        rows,
                        project_id=project_id,
                        session_id=session_id,
                        days=days,
                    )
                    out = {
                        "ok": True,
                        "project_id": project_id,
                        "session_id": session_id,
                        "total": int(agg.get("total", 0) or 0),
                        "types": list(agg.get("types") or []),
                        "days": list(agg.get("days") or []),
                    }
                    with event_stats_lock:
                        _cache_set(event_stats_cache, cache_key, out, now=now, max_items=64)
                    self._send_json(out)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/maintenance/summary":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                days = max(1, min(60, int(float(q.get("days", ["7"])[0]))))
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
                try:
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        rows = conn.execute(
                            """
                            SELECT body_text, updated_at
                            FROM memories
                            WHERE kind='summary'
                              AND updated_at >= ?
                              AND EXISTS (SELECT 1 FROM json_each(memories.tags_json) WHERE value='governance:auto-maintenance')
                              AND (?='' OR json_extract(scope_json, '$.project_id') = ?)
                            ORDER BY updated_at DESC
                            LIMIT 300
                            """,
                            (cutoff, project_id, project_id),
                        ).fetchall()
                        runs = 0
                        decay_total = 0
                        promoted_total = 0
                        demoted_total = 0
                        for r in rows:
                            body = str(r["body_text"] or "")
                            if session_id and f"- session_id: {session_id}" not in body:
                                continue
                            runs += 1
                            m1 = re.search(r"- decay_count: (\d+)", body)
                            m2 = re.search(r"- promoted: (\d+)", body)
                            m3 = re.search(r"- demoted: (\d+)", body)
                            if m1:
                                decay_total += int(m1.group(1))
                            if m2:
                                promoted_total += int(m2.group(1))
                            if m3:
                                demoted_total += int(m3.group(1))

                        ev_rows = conn.execute(
                            """
                            SELECT event_type, COUNT(*) AS c
                            FROM memory_events
                            WHERE event_time >= ?
                              AND event_type IN ('memory.decay','memory.update')
                            GROUP BY event_type
                            """,
                            (cutoff,),
                        ).fetchall()
                        event_counts = {str(x["event_type"]): int(x["c"]) for x in ev_rows}
                    self._send_json(
                        {
                            "ok": True,
                            "project_id": project_id,
                            "session_id": session_id,
                            "days": days,
                            "auto_maintenance": {
                                "runs": runs,
                                "decay_total": decay_total,
                                "promoted_total": promoted_total,
                                "demoted_total": demoted_total,
                            },
                            "event_counts": event_counts,
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/quality/summary":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                days = max(3, min(60, int(float(q.get("days", ["7"])[0]))))
                now = datetime.now(timezone.utc).replace(microsecond=0)
                cur_start = (now - timedelta(days=days)).isoformat()
                prev_start = (now - timedelta(days=(2 * days))).isoformat()
                cur_end = now.isoformat()
                try:
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        cur = _quality_window_summary(
                            conn,
                            start_iso=cur_start,
                            end_iso=cur_end,
                            project_id=project_id,
                            session_id=session_id,
                        )
                        prev = _quality_window_summary(
                            conn,
                            start_iso=prev_start,
                            end_iso=cur_start,
                            project_id=project_id,
                            session_id=session_id,
                        )
                    self._send_json(
                        {
                            "ok": True,
                            "project_id": project_id,
                            "session_id": session_id,
                            "days": days,
                            "current_window": {"start": cur_start, "end": cur_end},
                            "previous_window": {"start": prev_start, "end": cur_start},
                            "current": cur,
                            "previous": prev,
                            "alerts": _quality_alerts(cur, prev),
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/sessions":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                limit = int(q.get("limit", ["20"])[0])

                def extract_drift(body_text: str) -> float | None:
                    m = re.search(r"\\bdrift=([0-9]*\\.?[0-9]+)\\b", body_text)
                    if not m:
                        return None
                    try:
                        return float(m.group(1))
                    except Exception:
                        return None

                try:
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        rows = conn.execute(
                            """
                            SELECT id, kind, summary, updated_at, body_text, source_json, scope_json, tags_json
                            FROM memories
                            WHERE (? = '' OR json_extract(scope_json, '$.project_id') = ?)
                              AND (
                                kind IN ('checkpoint','retrieve')
                                OR EXISTS (SELECT 1 FROM json_each(memories.tags_json) WHERE value IN ('auto:turn','auto:checkpoint','auto:retrieve'))
                              )
                            ORDER BY updated_at DESC
                            LIMIT 2000
                            """,
                            (project_id, project_id),
                        ).fetchall()

                    stats: dict[str, dict[str, Any]] = {}
                    for r in rows:
                        src = json.loads(r["source_json"] or "{}")
                        sid = (src.get("session_id") or "").strip() or "session-unknown"
                        st = stats.get(sid)
                        if st is None:
                            st = {
                                "session_id": sid,
                                "last_updated_at": r["updated_at"],
                                "turns": 0,
                                "retrieves": 0,
                                "checkpoints": 0,
                                "switches": 0,
                                "_drift_sum": 0.0,
                                "_drift_n": 0,
                            }
                            stats[sid] = st
                        if r["updated_at"] and str(r["updated_at"]) > str(st["last_updated_at"]):
                            st["last_updated_at"] = r["updated_at"]

                        body = r["body_text"] or ""
                        drift = extract_drift(body)
                        if drift is not None:
                            st["_drift_sum"] += float(drift)
                            st["_drift_n"] += 1

                        kind = (r["kind"] or "").lower()
                        tags = []
                        try:
                            tags = json.loads(r["tags_json"] or "[]")
                        except Exception:
                            tags = []
                        tags_set = set(str(t) for t in tags)
                        if kind == "retrieve" or "auto:retrieve" in tags_set:
                            st["retrieves"] += 1
                        if kind == "checkpoint" or "auto:checkpoint" in tags_set:
                            st["checkpoints"] += 1
                        if "auto:turn" in tags_set:
                            st["turns"] += 1
                        if "old_session_id" in body or "topic switch" in (r["summary"] or "").lower():
                            st["switches"] += 1

                    items = []
                    for sid, st in stats.items():
                        dn = int(st.pop("_drift_n", 0))
                        ds = float(st.pop("_drift_sum", 0.0))
                        st["avg_drift"] = (ds / dn) if dn > 0 else None
                        items.append(st)
                    items.sort(key=lambda x: str(x.get("last_updated_at", "")), reverse=True)
                    self._send_json({"ok": True, "project_id": project_id, "items": items[: max(1, limit)]})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/analytics":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                try:
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        where = ""
                        args: list[Any] = []
                        if project_id:
                            where = "WHERE json_extract(scope_json, '$.project_id') = ?"
                            args.append(project_id)
                        if session_id:
                            where = (where + " AND " if where else "WHERE ") + "COALESCE(json_extract(source_json, '$.session_id'), '') = ?"
                            args.append(session_id)

                        layers = conn.execute(
                            f"SELECT layer, count(*) AS c FROM memories {where} GROUP BY layer ORDER BY layer",
                            args,
                        ).fetchall()
                        kinds = conn.execute(
                            f"SELECT kind, count(*) AS c FROM memories {where} GROUP BY kind ORDER BY c DESC",
                            args,
                        ).fetchall()
                        activity = conn.execute(
                            f"""
                            SELECT substr(created_at,1,10) AS day, count(*) AS c
                            FROM memories
                            {where}
                            GROUP BY substr(created_at,1,10)
                            ORDER BY day DESC
                            LIMIT 14
                            """,
                            args,
                        ).fetchall()
                        tags = conn.execute(
                            f"""
                            SELECT value AS tag, count(*) AS c
                            FROM memories, json_each(memories.tags_json)
                            {where}
                            GROUP BY value
                            ORDER BY c DESC
                            LIMIT 20
                            """,
                            args,
                        ).fetchall()

                        chk_where = "WHERE kind='checkpoint'"
                        chk_args: list[Any] = []
                        if project_id:
                            chk_where += " AND json_extract(scope_json, '$.project_id') = ?"
                            chk_args.append(project_id)
                        if session_id:
                            chk_where += " AND COALESCE(json_extract(source_json, '$.session_id'), '') = ?"
                            chk_args.append(session_id)
                        checkpoints = conn.execute(
                            f"""
                            SELECT id, summary, updated_at
                            FROM memories
                            {chk_where}
                            ORDER BY updated_at DESC
                            LIMIT 6
                            """,
                            chk_args,
                        ).fetchall()

                    act_items = [{"day": r["day"], "count": int(r["c"])} for r in activity]
                    act_max = max([x["count"] for x in act_items], default=0)
                    self._send_json(
                        {
                            "ok": True,
                            "project_id": project_id,
                            "session_id": session_id,
                            "layers": [{"layer": r["layer"], "count": int(r["c"])} for r in layers],
                            "kinds": [{"kind": r["kind"], "count": int(r["c"])} for r in kinds],
                            "activity": act_items,
                            "activity_max": act_max,
                            "tags": [{"tag": r["tag"], "count": int(r["c"])} for r in tags],
                            "checkpoints": [dict(r) for r in checkpoints],
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            self._send_json({"ok": False, "error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not self._authorized(parsed):
                self._send_json({"ok": False, "error": "unauthorized"}, 401)
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")

            if parsed.path == "/api/config":
                cfg["home"] = data.get("home", cfg.get("home", ""))
                cfg.setdefault("storage", {})
                cfg["storage"]["markdown"] = data.get("markdown", cfg["storage"].get("markdown", ""))
                cfg["storage"]["jsonl"] = data.get("jsonl", cfg["storage"].get("jsonl", ""))
                cfg["storage"]["sqlite"] = data.get("sqlite", cfg["storage"].get("sqlite", ""))
                cfg.setdefault("sync", {}).setdefault("github", {})
                cfg["sync"]["github"]["remote_name"] = data.get("remote_name", "origin")
                cfg["sync"]["github"]["remote_url"] = data.get("remote_url", "")
                cfg["sync"]["github"]["branch"] = data.get("branch", "main")
                if not isinstance(cfg["sync"]["github"].get("oauth"), dict):
                    cfg["sync"]["github"]["oauth"] = {}
                cfg["sync"]["github"]["oauth"]["client_id"] = str(data.get("gh_oauth_client_id", cfg["sync"]["github"]["oauth"].get("client_id", "")) or "").strip()
                cfg["sync"]["github"]["oauth"]["broker_url"] = _normalize_broker_url(
                    str(data.get("gh_oauth_broker_url", cfg["sync"]["github"]["oauth"].get("broker_url", "")) or "").strip()
                )
                if "sync_include_layers" in data:
                    raw_layers = data.get("sync_include_layers")
                    if isinstance(raw_layers, list):
                        cfg["sync"]["github"]["include_layers"] = [str(x).strip() for x in raw_layers if str(x).strip()]
                    else:
                        cfg["sync"]["github"]["include_layers"] = [
                            x.strip() for x in str(raw_layers or "").split(",") if x.strip()
                        ]
                if "sync_include_jsonl" in data:
                    cfg["sync"]["github"]["include_jsonl"] = bool(data.get("sync_include_jsonl"))
                cfg.setdefault("daemon", {})
                dm = cfg["daemon"]

                def _to_int(name: str, default: int, mn: int, mx: int) -> int:
                    raw = data.get(name, dm.get(name, default))
                    try:
                        v = int(raw)
                    except Exception:
                        v = default
                    return max(mn, min(mx, v))

                def _to_bool(name: str, default: bool) -> bool:
                    raw = data.get(name, dm.get(name, default))
                    if isinstance(raw, bool):
                        return raw
                    s = str(raw).strip().lower()
                    if s in {"1", "true", "yes", "on"}:
                        return True
                    if s in {"0", "false", "no", "off"}:
                        return False
                    return bool(default)

                dm["scan_interval"] = _to_int("daemon_scan_interval", int(daemon_state.get("scan_interval", 8)), 1, 3600)
                dm["pull_interval"] = _to_int("daemon_pull_interval", int(daemon_state.get("pull_interval", 30)), 5, 86400)
                dm["retry_max_attempts"] = _to_int("daemon_retry_max_attempts", int(daemon_state.get("retry_max_attempts", 3)), 1, 20)
                dm["retry_initial_backoff"] = _to_int("daemon_retry_initial_backoff", int(daemon_state.get("retry_initial_backoff", 1)), 1, 120)
                dm["retry_max_backoff"] = _to_int("daemon_retry_max_backoff", int(daemon_state.get("retry_max_backoff", 8)), 1, 600)
                dm["maintenance_enabled"] = _to_bool("daemon_maintenance_enabled", bool(daemon_state.get("maintenance_enabled", True)))
                dm["maintenance_interval"] = _to_int("daemon_maintenance_interval", int(daemon_state.get("maintenance_interval", 300)), 60, 86400)
                dm["maintenance_decay_days"] = _to_int("daemon_maintenance_decay_days", int(daemon_state.get("maintenance_decay_days", 14)), 1, 365)
                dm["maintenance_decay_limit"] = _to_int("daemon_maintenance_decay_limit", int(daemon_state.get("maintenance_decay_limit", 120)), 1, 2000)
                dm["maintenance_prune_enabled"] = _to_bool(
                    "daemon_maintenance_prune_enabled", bool(daemon_state.get("maintenance_prune_enabled", False))
                )
                dm["maintenance_prune_days"] = _to_int(
                    "daemon_maintenance_prune_days", int(daemon_state.get("maintenance_prune_days", 45)), 1, 3650
                )
                dm["maintenance_prune_limit"] = _to_int(
                    "daemon_maintenance_prune_limit", int(daemon_state.get("maintenance_prune_limit", 300)), 1, 5000
                )
                raw_prune_layers = str(
                    data.get(
                        "daemon_maintenance_prune_layers",
                        ",".join(list(daemon_state.get("maintenance_prune_layers", ["instant", "short"]))),
                    )
                ).strip()
                dm["maintenance_prune_layers"] = [x.strip() for x in raw_prune_layers.split(",") if x.strip()]
                raw_prune_keep = str(
                    data.get(
                        "daemon_maintenance_prune_keep_kinds",
                        ",".join(list(daemon_state.get("maintenance_prune_keep_kinds", ["decision", "checkpoint"]))),
                    )
                ).strip()
                dm["maintenance_prune_keep_kinds"] = [x.strip() for x in raw_prune_keep.split(",") if x.strip()]
                dm["maintenance_consolidate_limit"] = _to_int("daemon_maintenance_consolidate_limit", int(daemon_state.get("maintenance_consolidate_limit", 80)), 1, 1000)
                dm["maintenance_compress_sessions"] = _to_int("daemon_maintenance_compress_sessions", int(daemon_state.get("maintenance_compress_sessions", 2)), 1, 20)
                dm["maintenance_compress_min_items"] = _to_int("daemon_maintenance_compress_min_items", int(daemon_state.get("maintenance_compress_min_items", 8)), 2, 200)
                dm["maintenance_temporal_tree_enabled"] = _to_bool("daemon_maintenance_temporal_tree_enabled", bool(daemon_state.get("maintenance_temporal_tree_enabled", True)))
                dm["maintenance_temporal_tree_days"] = _to_int("daemon_maintenance_temporal_tree_days", int(daemon_state.get("maintenance_temporal_tree_days", 30)), 1, 365)
                dm["maintenance_rehearsal_enabled"] = _to_bool("daemon_maintenance_rehearsal_enabled", bool(daemon_state.get("maintenance_rehearsal_enabled", True)))
                dm["maintenance_rehearsal_days"] = _to_int("daemon_maintenance_rehearsal_days", int(daemon_state.get("maintenance_rehearsal_days", 45)), 1, 365)
                dm["maintenance_rehearsal_limit"] = _to_int("daemon_maintenance_rehearsal_limit", int(daemon_state.get("maintenance_rehearsal_limit", 16)), 1, 200)
                dm["maintenance_reflection_enabled"] = _to_bool("daemon_maintenance_reflection_enabled", bool(daemon_state.get("maintenance_reflection_enabled", True)))
                dm["maintenance_reflection_days"] = _to_int("daemon_maintenance_reflection_days", int(daemon_state.get("maintenance_reflection_days", 14)), 1, 365)
                dm["maintenance_reflection_limit"] = _to_int("daemon_maintenance_reflection_limit", int(daemon_state.get("maintenance_reflection_limit", 4)), 1, 20)
                dm["maintenance_reflection_min_repeats"] = _to_int("daemon_maintenance_reflection_min_repeats", int(daemon_state.get("maintenance_reflection_min_repeats", 2)), 1, 12)
                mrar = data.get("daemon_maintenance_reflection_max_avg_retrieved", dm.get("maintenance_reflection_max_avg_retrieved", 2.0))
                try:
                    dm["maintenance_reflection_max_avg_retrieved"] = max(0.0, min(20.0, float(mrar)))
                except Exception:
                    dm["maintenance_reflection_max_avg_retrieved"] = float(daemon_state.get("maintenance_reflection_max_avg_retrieved", 2.0))
                cfg.setdefault("webui", {})
                cfg["webui"]["approval_required"] = _to_bool("webui_approval_required", bool(cfg.get("webui", {}).get("approval_required", False)))
                cfg["webui"]["maintenance_preview_only_until"] = str(data.get("webui_maintenance_preview_only_until", cfg.get("webui", {}).get("maintenance_preview_only_until", ""))).strip()
                try:
                    save_config(cfg_path, cfg)
                    nonlocal paths
                    paths = resolve_paths(cfg)
                    ensure_storage(paths, schema_sql_path)
                    daemon_state["scan_interval"] = int(dm["scan_interval"])
                    daemon_state["pull_interval"] = int(dm["pull_interval"])
                    daemon_state["retry_max_attempts"] = int(dm["retry_max_attempts"])
                    daemon_state["retry_initial_backoff"] = int(dm["retry_initial_backoff"])
                    daemon_state["retry_max_backoff"] = int(dm["retry_max_backoff"])
                    daemon_state["maintenance_enabled"] = bool(dm["maintenance_enabled"])
                    daemon_state["maintenance_interval"] = int(dm["maintenance_interval"])
                    daemon_state["maintenance_decay_days"] = int(dm["maintenance_decay_days"])
                    daemon_state["maintenance_decay_limit"] = int(dm["maintenance_decay_limit"])
                    daemon_state["maintenance_prune_enabled"] = bool(dm["maintenance_prune_enabled"])
                    daemon_state["maintenance_prune_days"] = int(dm["maintenance_prune_days"])
                    daemon_state["maintenance_prune_limit"] = int(dm["maintenance_prune_limit"])
                    daemon_state["maintenance_prune_layers"] = list(dm["maintenance_prune_layers"] or ["instant", "short"])
                    daemon_state["maintenance_prune_keep_kinds"] = list(
                        dm["maintenance_prune_keep_kinds"] or ["decision", "checkpoint"]
                    )
                    daemon_state["maintenance_consolidate_limit"] = int(dm["maintenance_consolidate_limit"])
                    daemon_state["maintenance_compress_sessions"] = int(dm["maintenance_compress_sessions"])
                    daemon_state["maintenance_compress_min_items"] = int(dm["maintenance_compress_min_items"])
                    daemon_state["maintenance_temporal_tree_enabled"] = bool(dm["maintenance_temporal_tree_enabled"])
                    daemon_state["maintenance_temporal_tree_days"] = int(dm["maintenance_temporal_tree_days"])
                    daemon_state["maintenance_rehearsal_enabled"] = bool(dm["maintenance_rehearsal_enabled"])
                    daemon_state["maintenance_rehearsal_days"] = int(dm["maintenance_rehearsal_days"])
                    daemon_state["maintenance_rehearsal_limit"] = int(dm["maintenance_rehearsal_limit"])
                    daemon_state["maintenance_reflection_enabled"] = bool(dm["maintenance_reflection_enabled"])
                    daemon_state["maintenance_reflection_days"] = int(dm["maintenance_reflection_days"])
                    daemon_state["maintenance_reflection_limit"] = int(dm["maintenance_reflection_limit"])
                    daemon_state["maintenance_reflection_min_repeats"] = int(dm["maintenance_reflection_min_repeats"])
                    daemon_state["maintenance_reflection_max_avg_retrieved"] = float(dm["maintenance_reflection_max_avg_retrieved"])
                    was_initialized = daemon_state.get("initialized", False)
                    daemon_state["initialized"] = True
                    if not was_initialized and enable_daemon:
                        daemon_state["enabled"] = not daemon_state.get("manually_disabled", False)
                    self._send_json({"ok": True})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/sync":
                if not daemon_state.get("initialized", False):
                    self._send_json({"ok": False, "error": "config not initialized; save config first"}, 400)
                    return
                mode = data.get("mode", "github-status")
                gh = cfg.get("sync", {}).get("github", {})
                try:
                    sync_layers, sync_include_jsonl = _sync_options_from_cfg(cfg)
                    out = sync_runner(
                        paths,
                        schema_sql_path,
                        mode,
                        remote_name=gh.get("remote_name", "origin"),
                        branch=gh.get("branch", "main"),
                        remote_url=gh.get("remote_url"),
                        oauth_token_file=_sync_oauth_token_file_from_cfg(cfg),
                        commit_message="chore(memory): sync from webui",
                        sync_include_layers=sync_layers,
                        sync_include_jsonl=sync_include_jsonl,
                    )
                    self._send_json(out)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/github/quick-setup":
                try:
                    out = _github_quick_setup(
                        cfg=cfg,
                        cfg_path=cfg_path,
                        owner=str(data.get("owner", "") or ""),
                        repo=str(data.get("repo", "") or ""),
                        full_name=str(data.get("full_name", "") or ""),
                        protocol=str(data.get("protocol", "ssh") or "ssh"),
                        remote_name=str(data.get("remote_name", "origin") or "origin"),
                        branch=str(data.get("branch", "main") or "main"),
                        create_if_missing=bool(data.get("create_if_missing", False)),
                        private_repo=bool(data.get("private_repo", True)),
                    )
                    self._send_json(out)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return

            if parsed.path == "/api/github/auth/start":
                try:
                    protocol = str(data.get("protocol", "https") or "https").strip().lower()
                    client_id = str(data.get("client_id", "") or "").strip()
                    broker_url = str(data.get("broker_url", "") or "").strip()
                    self._send_json(
                        _github_auth_start(
                            cfg=cfg,
                            cfg_path=cfg_path,
                            protocol=protocol,
                            client_id=client_id,
                            broker_url=broker_url,
                        )
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return

            if parsed.path == "/api/github/auth/poll":
                try:
                    self._send_json(_github_oauth_poll(cfg=cfg, cfg_path=cfg_path))
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return

            if parsed.path == "/api/daemon/toggle":
                desired = bool(data.get("enabled", True))
                daemon_state["manually_disabled"] = not desired
                daemon_state["enabled"] = bool(desired and daemon_state.get("initialized", False))
                self._send_json(
                    {
                        "ok": True,
                        "enabled": daemon_state["enabled"],
                        "initialized": daemon_state["initialized"],
                        "running": daemon_state["running"],
                        "last_result": daemon_state.get("last_result", {}),
                    }
                )
                return

            if parsed.path == "/api/maintenance/decay":
                try:
                    project_id = str(data.get("project_id", "")).strip()
                    days = int(data.get("days", 14))
                    limit = int(data.get("limit", 200))
                    dry_run = bool(data.get("dry_run", True))
                    layers = data.get("layers")
                    if layers is None:
                        raw = str(data.get("layers_csv", "")).strip()
                        layers = [x.strip() for x in raw.split(",") if x.strip()] if raw else None
                    if layers is not None and (not isinstance(layers, list) or not all(isinstance(x, (str, int, float)) for x in layers)):
                        self._send_json({"ok": False, "error": "layers must be a list of strings"}, 400)
                        return
                    if layers is not None:
                        layers = [str(x).strip() for x in layers if str(x).strip()]
                    out = apply_decay(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        days=days,
                        limit=limit,
                        project_id=project_id,
                        layers=layers,
                        dry_run=dry_run,
                        tool="webui",
                        session_id="webui-session",
                    )
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/maintenance/consolidate":
                try:
                    project_id = str(data.get("project_id", "")).strip()
                    session_id = str(data.get("session_id", "")).strip()
                    limit = int(data.get("limit", 80))
                    dry_run = bool(data.get("dry_run", True))
                    adaptive = bool(data.get("adaptive", True))
                    out = consolidate_memories(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        project_id=project_id,
                        session_id=session_id,
                        limit=limit,
                        dry_run=dry_run,
                        adaptive=adaptive,
                        adaptive_days=14,
                        adaptive_q_promote_imp=float(cfg.get("daemon", {}).get("adaptive_q_promote_imp", 0.68)),
                        adaptive_q_promote_conf=float(cfg.get("daemon", {}).get("adaptive_q_promote_conf", 0.60)),
                        adaptive_q_promote_stab=float(cfg.get("daemon", {}).get("adaptive_q_promote_stab", 0.62)),
                        adaptive_q_promote_vol=float(cfg.get("daemon", {}).get("adaptive_q_promote_vol", 0.42)),
                        adaptive_q_demote_vol=float(cfg.get("daemon", {}).get("adaptive_q_demote_vol", 0.78)),
                        adaptive_q_demote_stab=float(cfg.get("daemon", {}).get("adaptive_q_demote_stab", 0.28)),
                        adaptive_q_demote_reuse=float(cfg.get("daemon", {}).get("adaptive_q_demote_reuse", 0.30)),
                        tool="webui",
                        actor_session_id="webui-session",
                    )
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/maintenance/compress":
                try:
                    project_id = str(data.get("project_id", "")).strip()
                    session_id = str(data.get("session_id", "")).strip()
                    min_items = int(data.get("min_items", 8))
                    dry_run = bool(data.get("dry_run", True))
                    out = compress_session_context(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        project_id=project_id,
                        session_id=session_id,
                        limit=120,
                        min_items=min_items,
                        target_layer="short",
                        dry_run=dry_run,
                        tool="webui",
                        actor_session_id="webui-session",
                    )
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/maintenance/auto":
                try:
                    project_id = str(data.get("project_id", "")).strip()
                    session_id = str(data.get("session_id", "")).strip()
                    dry_run = bool(data.get("dry_run", True))
                    ack_token = str(data.get("ack_token", "")).strip()
                    approval_required = bool(cfg.get("webui", {}).get("approval_required", False))
                    approval_met = bool(ack_token == "APPLY")
                    preview_until = str(cfg.get("webui", {}).get("maintenance_preview_only_until", "") or "").strip()
                    if not dry_run and preview_until:
                        try:
                            ptxt = preview_until[:-1] + "+00:00" if preview_until.endswith("Z") else preview_until
                            pdt = datetime.fromisoformat(ptxt)
                            if pdt.tzinfo is None:
                                pdt = pdt.replace(tzinfo=timezone.utc)
                            if datetime.now(timezone.utc) < pdt.astimezone(timezone.utc):
                                self._send_json({"ok": False, "error": f"preview-only window active until {preview_until}"}, 403)
                                return
                        except Exception:
                            pass
                    if not dry_run and approval_required and not approval_met:
                        self._send_json({"ok": False, "error": "approval required: set ack_token=APPLY"}, 403)
                        return
                    decay_out = apply_decay(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        days=14,
                        limit=120,
                        project_id=project_id,
                        layers=["instant", "short", "long"],
                        dry_run=dry_run,
                        tool="webui",
                        session_id="webui-session",
                    )
                    cons_out = consolidate_memories(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        project_id=project_id,
                        session_id=session_id,
                        limit=80,
                        dry_run=dry_run,
                        adaptive=True,
                        adaptive_days=14,
                        adaptive_q_promote_imp=float(cfg.get("daemon", {}).get("adaptive_q_promote_imp", 0.68)),
                        adaptive_q_promote_conf=float(cfg.get("daemon", {}).get("adaptive_q_promote_conf", 0.60)),
                        adaptive_q_promote_stab=float(cfg.get("daemon", {}).get("adaptive_q_promote_stab", 0.62)),
                        adaptive_q_promote_vol=float(cfg.get("daemon", {}).get("adaptive_q_promote_vol", 0.42)),
                        adaptive_q_demote_vol=float(cfg.get("daemon", {}).get("adaptive_q_demote_vol", 0.78)),
                        adaptive_q_demote_stab=float(cfg.get("daemon", {}).get("adaptive_q_demote_stab", 0.28)),
                        adaptive_q_demote_reuse=float(cfg.get("daemon", {}).get("adaptive_q_demote_reuse", 0.30)),
                        tool="webui",
                        actor_session_id="webui-session",
                    )
                    if session_id:
                        comp_out = compress_session_context(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            project_id=project_id,
                            session_id=session_id,
                            limit=120,
                            min_items=8,
                            target_layer="short",
                            dry_run=dry_run,
                            tool="webui",
                            actor_session_id="webui-session",
                        )
                    else:
                        comp_out = compress_hot_sessions(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            project_id=project_id,
                            max_sessions=2,
                            per_session_limit=120,
                            min_items=8,
                            dry_run=dry_run,
                            tool="webui",
                            actor_session_id="webui-session",
                        )
                    promote_n = len(cons_out.get("promote") or []) if dry_run else len(cons_out.get("promoted") or [])
                    demote_n = len(cons_out.get("demote") or []) if dry_run else len(cons_out.get("demoted") or [])
                    compress_n = 0
                    if session_id:
                        compress_n = 1 if bool(comp_out.get("compressed")) or bool(comp_out.get("summary_preview")) else 0
                    else:
                        for it in (comp_out.get("items") or []):
                            if bool((it or {}).get("compressed")) or bool((it or {}).get("summary_preview")):
                                compress_n += 1
                    forecast = _maintenance_impact_forecast(
                        decay_count=int(decay_out.get("count", 0) or 0),
                        promote_count=int(promote_n),
                        demote_count=int(demote_n),
                        compress_count=int(compress_n),
                        dry_run=bool(dry_run),
                        approval_required=bool(approval_required),
                        session_id=session_id,
                    )
                    status_feedback = _maintenance_status_feedback(
                        dry_run=bool(dry_run),
                        approval_required=bool(approval_required),
                        approval_met=bool(approval_met),
                        risk_level=str(forecast.get("risk_level", "low")),
                        total_touches=int((forecast.get("expected") or {}).get("total_touches", 0) or 0),
                    )
                    out = {
                        "ok": bool(decay_out.get("ok") and cons_out.get("ok") and comp_out.get("ok")),
                        "dry_run": dry_run,
                        "project_id": project_id,
                        "session_id": session_id,
                        "approval_required": approval_required,
                        "status_feedback": status_feedback,
                        "forecast": forecast,
                        "decay": {
                            "ok": decay_out.get("ok"),
                            "count": decay_out.get("count", 0),
                        },
                        "consolidate": {
                            "ok": cons_out.get("ok"),
                            "promote_candidates": len(cons_out.get("promote") or []),
                            "demote_candidates": len(cons_out.get("demote") or []),
                            "promoted": len(cons_out.get("promoted") or []),
                            "demoted": len(cons_out.get("demoted") or []),
                            "promote_forecast": int(promote_n),
                            "demote_forecast": int(demote_n),
                            "thresholds": cons_out.get("thresholds", {}),
                        },
                        "compress": comp_out,
                    }
                    if not dry_run and out.get("ok"):
                        try:
                            write_memory(
                                paths=paths,
                                schema_sql_path=schema_sql_path,
                                layer="short",
                                kind="summary",
                                summary=f"Auto maintenance applied ({project_id or 'all'})",
                                body=(
                                    "WebUI auto-maintenance run.\n\n"
                                    f"- project_id: {project_id or '(all)'}\n"
                                    f"- session_id: {session_id or '(auto hot sessions)'}\n"
                                    f"- decay_count: {out['decay'].get('count', 0)}\n"
                                    f"- promoted: {out['consolidate'].get('promoted', 0)}\n"
                                    f"- demoted: {out['consolidate'].get('demoted', 0)}\n"
                                    f"- approval_required: {approval_required}\n"
                                ),
                                tags=["governance:auto-maintenance", "audit:webui"],
                                refs=[],
                                cred_refs=[],
                                tool="webui",
                                account="default",
                                device="local",
                                session_id="webui-session",
                                project_id=project_id or "global",
                                workspace="",
                                importance=0.65,
                                confidence=0.9,
                                stability=0.8,
                                reuse_count=0,
                                volatility=0.2,
                                event_type="memory.write",
                            )
                        except Exception:
                            pass
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/project/attach":
                try:
                    project_path = str(data.get("project_path", "")).strip()
                    project_id = str(data.get("project_id", "")).strip()
                    out = _attach_project_in_webui(
                        project_path=project_path,
                        project_id=project_id,
                        cfg_home=str(cfg.get("home", "")).strip(),
                    )
                    if out.get("ok"):
                        pid = str(out.get("project_id", "")).strip() or "global"
                        _register_project(str(cfg.get("home", "")), pid, str(out.get("project_path", project_path)))
                        write_memory(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            layer="short",
                            kind="summary",
                            summary=f"Project attached: {pid}",
                            body=(
                                "Project integration completed via WebUI.\n\n"
                                f"- project_id: {pid}\n"
                                f"- project_path: {project_path}\n"
                            ),
                            tags=[f"project:{pid}", "integration:webui"],
                            refs=[],
                            cred_refs=[],
                            tool="webui",
                            account="default",
                            device="local",
                            session_id="webui-session",
                            project_id=pid,
                            workspace=project_path,
                            importance=0.7,
                            confidence=0.9,
                            stability=0.8,
                            reuse_count=0,
                            volatility=0.2,
                            event_type="memory.write",
                        )
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/project/detach":
                try:
                    proj_path = str(data.get("project_path", "")).strip()
                    out = _detach_project_in_webui(proj_path)
                    if out.get("ok"):
                        _unregister_project(str(cfg.get("home", "")), proj_path)
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/memory/move":
                try:
                    mem_id = str(data.get("id", "")).strip()
                    layer = str(data.get("layer", "")).strip()
                    if not mem_id or not layer:
                        self._send_json({"ok": False, "error": "id and layer are required"}, 400)
                        return
                    out = move_memory_layer(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        memory_id=mem_id,
                        new_layer=layer,
                        tool="webui",
                        account="default",
                        device="local",
                        session_id="webui-session",
                    )
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/memory/undo-last-move":
                try:
                    mem_id = str(data.get("id", "")).strip()
                    if not mem_id:
                        self._send_json({"ok": False, "error": "id is required"}, 400)
                        return
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        ev = conn.execute(
                            """
                            SELECT event_id, payload_json, event_time
                            FROM memory_events
                            WHERE memory_id = ? AND event_type = 'memory.promote'
                            ORDER BY event_time DESC
                            LIMIT 1
                            """,
                            (mem_id,),
                        ).fetchone()
                    if not ev:
                        self._send_json({"ok": False, "error": "no layer-move event found"}, 404)
                        return
                    payload = json.loads(ev["payload_json"] or "{}")
                    from_layer = str(payload.get("from_layer", "")).strip()
                    to_layer = str(payload.get("to_layer", "")).strip()
                    if not from_layer or not to_layer or from_layer == to_layer:
                        self._send_json({"ok": False, "error": "invalid layer-move payload"}, 400)
                        return
                    out = move_memory_layer(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        memory_id=mem_id,
                        new_layer=from_layer,
                        tool="webui",
                        account="default",
                        device="local",
                        session_id="webui-session",
                    )
                    if not out.get("ok"):
                        self._send_json(out, 400)
                        return
                    self._send_json(
                        {
                            **out,
                            "undo_of_event_id": str(ev["event_id"]),
                            "undo_of_event_time": str(ev["event_time"]),
                            "from_layer": from_layer,
                            "to_layer": to_layer,
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/memory/undo-move-event":
                try:
                    mem_id = str(data.get("id", "")).strip()
                    event_id = str(data.get("event_id", "")).strip()
                    if not mem_id or not event_id:
                        self._send_json({"ok": False, "error": "id and event_id are required"}, 400)
                        return
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        ev = conn.execute(
                            """
                            SELECT event_id, payload_json, event_time
                            FROM memory_events
                            WHERE memory_id = ? AND event_id = ? AND event_type = 'memory.promote'
                            LIMIT 1
                            """,
                            (mem_id, event_id),
                        ).fetchone()
                    if not ev:
                        self._send_json({"ok": False, "error": "event not found"}, 404)
                        return
                    payload = json.loads(ev["payload_json"] or "{}")
                    from_layer = str(payload.get("from_layer", "")).strip()
                    to_layer = str(payload.get("to_layer", "")).strip()
                    if not from_layer or not to_layer or from_layer == to_layer:
                        self._send_json({"ok": False, "error": "invalid layer-move payload"}, 400)
                        return
                    out = move_memory_layer(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        memory_id=mem_id,
                        new_layer=from_layer,
                        tool="webui",
                        account="default",
                        device="local",
                        session_id="webui-session",
                    )
                    self._send_json(
                        {
                            **out,
                            "undo_of_event_id": str(ev["event_id"]),
                            "undo_of_event_time": str(ev["event_time"]),
                            "from_layer": from_layer,
                            "to_layer": to_layer,
                        },
                        200 if out.get("ok") else 400,
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/memory/rollback-to-time":
                try:
                    mem_id = str(data.get("id", "")).strip()
                    to_event_time = str(data.get("to_event_time", "")).strip()
                    if not mem_id or not to_event_time:
                        self._send_json({"ok": False, "error": "id and to_event_time are required"}, 400)
                        return
                    ttxt = to_event_time[:-1] + "+00:00" if to_event_time.endswith("Z") else to_event_time
                    try:
                        tdt = datetime.fromisoformat(ttxt)
                        if tdt.tzinfo is None:
                            tdt = tdt.replace(tzinfo=timezone.utc)
                        cutoff = tdt.astimezone(timezone.utc).replace(microsecond=0).isoformat()
                    except Exception:
                        self._send_json({"ok": False, "error": "invalid to_event_time (ISO-8601 required)"}, 400)
                        return
                    with _db_connect() as conn:
                        rows, predicted = _rollback_preview_items(conn, memory_id=mem_id, cutoff_iso=cutoff, limit=200)
                        cur = conn.execute("SELECT layer FROM memories WHERE id = ?", (mem_id,)).fetchone()
                        before_layer = str(cur["layer"]) if cur else ""
                    if not rows:
                        self._send_json(
                            {
                                "ok": True,
                                "memory_id": mem_id,
                                "to_event_time": cutoff,
                                "rolled_back": 0,
                                "before_layer": before_layer,
                                "after_layer": before_layer,
                                "steps": [],
                            }
                        )
                        return
                    snapshot_id = ""
                    try:
                        snap = write_memory(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            layer="short",
                            kind="summary",
                            summary=f"Rollback snapshot: {mem_id[:10]}...",
                            body=(
                                "Pre-rollback snapshot\n\n"
                                f"- memory_id: {mem_id}\n"
                                f"- rollback_to: {cutoff}\n"
                                f"- before_layer: {before_layer}\n"
                                f"- predicted_after: {predicted}\n"
                                f"- moves_to_undo: {len(rows)}\n"
                            ),
                            tags=["rollback:snapshot", "audit:webui"],
                            refs=[],
                            cred_refs=[],
                            tool="webui",
                            account="default",
                            device="local",
                            session_id="webui-session",
                            project_id="OM",
                            workspace="",
                            importance=0.6,
                            confidence=0.85,
                            stability=0.7,
                            reuse_count=0,
                            volatility=0.2,
                            event_type="memory.write",
                        )
                        snapshot_id = str((snap.get("memory") or {}).get("id") or "")
                    except Exception:
                        snapshot_id = ""
                    steps: list[dict[str, Any]] = []
                    failed: list[dict[str, Any]] = []
                    for r in rows:
                        from_layer = str(r.get("from_layer", "")).strip()
                        to_layer = str(r.get("to_layer", "")).strip()
                        if not from_layer or not to_layer or from_layer == to_layer:
                            failed.append(
                                {
                                    "event_id": str(r.get("event_id", "")),
                                    "event_time": str(r.get("event_time", "")),
                                    "error": "invalid payload",
                                }
                            )
                            continue
                        out = move_memory_layer(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            memory_id=mem_id,
                            new_layer=from_layer,
                            tool="webui",
                            account="default",
                            device="local",
                            session_id="webui-session",
                        )
                        if out.get("ok"):
                            steps.append(
                                {
                                    "event_id": str(r.get("event_id", "")),
                                    "event_time": str(r.get("event_time", "")),
                                    "undo_to_layer": from_layer,
                                    "undo_from_layer": to_layer,
                                }
                            )
                        else:
                            failed.append(
                                {
                                    "event_id": str(r.get("event_id", "")),
                                    "event_time": str(r.get("event_time", "")),
                                    "error": str(out.get("error", "move failed")),
                                }
                            )
                    after_layer = before_layer
                    try:
                        with _db_connect() as conn2:
                            conn2.row_factory = sqlite3.Row
                            rr = conn2.execute("SELECT layer FROM memories WHERE id = ?", (mem_id,)).fetchone()
                            after_layer = str(rr["layer"]) if rr else before_layer
                    except Exception:
                        after_layer = before_layer
                    self._send_json(
                        {
                            "ok": len(failed) == 0,
                            "memory_id": mem_id,
                            "to_event_time": cutoff,
                            "rolled_back": len(steps),
                            "before_layer": before_layer,
                            "after_layer": after_layer,
                            "predicted_after_layer": predicted,
                            "snapshot_memory_id": snapshot_id,
                            "steps": steps,
                            "failed": failed,
                        },
                        200 if len(failed) == 0 else 400,
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/route-templates":
                try:
                    mode = str(data.get("mode", "upsert")).strip().lower()
                    items = _normalize_route_templates(data.get("items", []))
                    cfg.setdefault("webui", {})
                    existing = _normalize_route_templates(cfg.get("webui", {}).get("route_templates", []))
                    if mode == "replace":
                        merged = items
                    else:
                        by_name = {str(x["name"]).lower(): dict(x) for x in existing}
                        for x in items:
                            by_name[str(x["name"]).lower()] = dict(x)
                        merged = list(by_name.values())
                    cfg["webui"]["route_templates"] = merged
                    save_config(cfg_path, cfg)
                    self._send_json({"ok": True, "items": merged})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/memory/tag-batch":
                try:
                    raw_ids = data.get("ids")
                    route = _normalize_memory_route(str(data.get("route", "auto")))
                    if route not in {"episodic", "semantic", "procedural"}:
                        self._send_json({"ok": False, "error": "route must be episodic|semantic|procedural"}, 400)
                        return
                    if not isinstance(raw_ids, list):
                        self._send_json({"ok": False, "error": "ids must be a list"}, 400)
                        return
                    ids = [str(x).strip() for x in raw_ids if str(x).strip()]
                    ids = list(dict.fromkeys(ids))[:200]
                    if not ids:
                        self._send_json({"ok": False, "error": "no ids"}, 400)
                        return
                    updated = 0
                    failed: list[str] = []
                    placeholders = ",".join(["?"] * len(ids))
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        rows = conn.execute(
                            f"""
                            SELECT id, summary, body_text, tags_json
                            FROM memories
                            WHERE id IN ({placeholders})
                            """,
                            tuple(ids),
                        ).fetchall()
                    row_by_id = {str(r["id"]): r for r in rows}
                    for mid in ids:
                        r = row_by_id.get(mid)
                        if not r:
                            failed.append(mid)
                            continue
                        summary = str(r["summary"] or "").strip()
                        body_text = str(r["body_text"] or "")
                        m = re.match(r"^# .*\n\n([\s\S]*)$", body_text)
                        body_plain = m.group(1) if m else body_text
                        try:
                            old_tags = [str(t).strip() for t in (json.loads(r["tags_json"] or "[]") or []) if str(t).strip()]
                        except Exception:
                            old_tags = []
                        kept = [t for t in old_tags if not re.match(r"^mem:(episodic|semantic|procedural)$", t, flags=re.IGNORECASE)]
                        next_tags = kept + [_route_tag(route)]
                        out = update_memory_content(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            memory_id=mid,
                            summary=summary,
                            body=body_plain,
                            tags=next_tags,
                            tool="webui",
                            account="default",
                            device="local",
                            session_id="webui-session",
                        )
                        if out.get("ok"):
                            updated += 1
                        else:
                            failed.append(mid)
                    self._send_json(
                        {
                            "ok": True,
                            "route": route,
                            "updated": updated,
                            "failed": failed,
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/memory/update":
                try:
                    mem_id = str(data.get("id", "")).strip()
                    summary = str(data.get("summary", "")).strip()
                    body = str(data.get("body", ""))
                    raw_tags = data.get("tags")
                    if raw_tags is None:
                        raw = str(data.get("tags_csv", "") or "")
                        tags = [x.strip() for x in raw.split(",") if x.strip()]
                    else:
                        if not isinstance(raw_tags, list):
                            self._send_json({"ok": False, "error": "tags must be a list of strings"}, 400)
                            return
                        tags = [str(x).strip() for x in raw_tags if str(x).strip()]
                    if not mem_id:
                        self._send_json({"ok": False, "error": "id is required"}, 400)
                        return
                    out = update_memory_content(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        memory_id=mem_id,
                        summary=summary,
                        body=body,
                        tags=tags,
                        tool="webui",
                        account="default",
                        device="local",
                        session_id="webui-session",
                    )
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/core-blocks/upsert":
                try:
                    name = str(data.get("name", "")).strip()
                    content = str(data.get("content", "") or "")
                    project_id = str(data.get("project_id", "") or "").strip()
                    session_id = str(data.get("session_id", "system") or "").strip()
                    layer = str(data.get("layer", "short") or "short").strip().lower()
                    topic = str(data.get("topic", "") or "").strip()
                    priority = _parse_int_param(data.get("priority", 50), default=50, lo=0, hi=100)
                    ttl_days = _parse_int_param(data.get("ttl_days", 0), default=0, lo=0, hi=3650)
                    expires_at = str(data.get("expires_at", "") or "").strip()
                    raw_tags = data.get("tags", [])
                    tags = [str(x).strip() for x in (raw_tags if isinstance(raw_tags, list) else []) if str(x).strip()]
                    if not name:
                        self._send_json({"ok": False, "error": "name is required"}, 400)
                        return
                    out = upsert_core_block(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        name=name,
                        content=content,
                        project_id=project_id,
                        session_id=session_id,
                        layer=layer,
                        tags=tags,
                        topic=topic,
                        priority=priority,
                        ttl_days=ttl_days,
                        expires_at=expires_at,
                        tool="webui",
                        account="default",
                        device="local",
                    )
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/memory/feedback":
                try:
                    mem_id = str(data.get("id", "")).strip()
                    fb = str(data.get("feedback", "")).strip().lower()
                    note = str(data.get("note", "") or "")
                    correction = str(data.get("correction", "") or "")
                    delta = _parse_int_param(data.get("delta", 1), default=1, lo=1, hi=10)
                    if not mem_id:
                        self._send_json({"ok": False, "error": "id is required"}, 400)
                        return
                    if fb not in {"positive", "negative", "forget", "correct"}:
                        self._send_json({"ok": False, "error": "feedback must be positive|negative|forget|correct"}, 400)
                        return
                    out = apply_memory_feedback(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        memory_id=mem_id,
                        feedback=fb,
                        note=note,
                        correction=correction,
                        delta=delta,
                        tool="webui",
                        account="default",
                        device="local",
                        session_id="webui-session",
                    )
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/session/archive":
                try:
                    project_id = str(data.get("project_id", "")).strip()
                    session_id = str(data.get("session_id", "")).strip()
                    to_layer = str(data.get("to_layer", "archive")).strip() or "archive"
                    from_layers = data.get("from_layers") or ["instant", "short"]
                    limit = int(data.get("limit", 400))
                    if not session_id:
                        self._send_json({"ok": False, "error": "session_id is required"}, 400)
                        return
                    if to_layer not in LAYER_SET:
                        self._send_json({"ok": False, "error": f"invalid to_layer: {to_layer}"}, 400)
                        return
                    if not isinstance(from_layers, list) or not from_layers:
                        self._send_json({"ok": False, "error": "from_layers must be a non-empty list"}, 400)
                        return
                    from_layers = [str(x).strip() for x in from_layers if str(x).strip()]
                    if any(x not in LAYER_SET for x in from_layers):
                        self._send_json({"ok": False, "error": "invalid from_layers"}, 400)
                        return
                    limit = max(1, min(2000, limit))

                    placeholders = ",".join(["?"] * len(from_layers))
                    ids: list[str] = []
                    with _db_connect() as conn:
                        conn.row_factory = sqlite3.Row
                        ids = [
                            str(r["id"])
                            for r in conn.execute(
                                f"""
                                SELECT id
                                FROM memories
                                WHERE layer IN ({placeholders})
                                  AND (? = '' OR json_extract(scope_json, '$.project_id') = ?)
                                  AND COALESCE(json_extract(source_json, '$.session_id'), '') = ?
                                ORDER BY updated_at DESC
                                LIMIT ?
                                """,
                                (*from_layers, project_id, project_id, session_id, limit),
                            ).fetchall()
                        ]

                    moved = 0
                    failed: list[str] = []
                    for mid in ids:
                        out = move_memory_layer(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            memory_id=mid,
                            new_layer=to_layer,
                            tool="webui",
                            account="default",
                            device="local",
                            session_id="webui-session",
                        )
                        if out.get("ok"):
                            moved += 1
                        else:
                            failed.append(mid)

                    # Governance audit record (stored as a memory so it shows up in UI and sync).
                    try:
                        write_memory(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            layer="archive",
	                            kind="summary",
	                            summary=f"Session archived: {session_id[:12]}… ({moved}/{len(ids)})",
	                            body=(
	                                "Session archive executed via WebUI.\n\n"
	                                f"- project_id: {project_id or '(all)'}\n"
	                                f"- session_id: {session_id}\n"
	                                f"- from_layers: {', '.join(from_layers)}\n"
	                                f"- to_layer: {to_layer}\n"
	                                f"- requested: {len(ids)}\n"
	                                f"- moved: {moved}\n"
	                                f"- failed_first20: {failed[:20]}\n"
	                            ),
                            tags=[
                                "governance:session-archive",
                                f"session:{session_id}",
                                *([f"project:{project_id}"] if project_id else []),
                            ],
                            refs=[],
                            cred_refs=[],
                            tool="webui",
                            account="default",
                            device="local",
                            session_id="webui-session",
                            project_id=project_id or "global",
                            workspace="",
                            importance=0.55,
                            confidence=0.9,
                            stability=0.8,
                            reuse_count=0,
                            volatility=0.15,
                            event_type="memory.write",
                        )
                    except Exception:
                        pass

                    self._send_json(
                        {
                            "ok": True,
                            "project_id": project_id,
                            "session_id": session_id,
                            "from_layers": from_layers,
                            "to_layer": to_layer,
                            "moved": moved,
                            "requested": len(ids),
                            "failed": failed[:20],
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            self._send_json({"ok": False, "error": "not found"}, 404)

    class _Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 64

        def __init__(self, server_address, RequestHandlerClass):  # noqa: N803
            super().__init__(server_address, RequestHandlerClass)
            self._slots = threading.BoundedSemaphore(value=48)

        def process_request(self, request, client_address):  # noqa: ANN001
            # Cap concurrent handlers to avoid unbounded thread/socket growth under load.
            if not self._slots.acquire(blocking=False):
                try:
                    _elog(f"[{utc_now()}] overload: drop client={client_address} threads={len(threading.enumerate())} fds={_fd_count()}")
                    request.close()
                except Exception:
                    pass
                return

            def _run():
                try:
                    super(_Server, self).process_request_thread(request, client_address)
                finally:
                    self._slots.release()

            t = threading.Thread(target=_run, daemon=self.daemon_threads)
            t.start()

        def handle_error(self, request, client_address) -> None:  # noqa: ANN001
            # Exceptions inside request handler threads end up here; capture to a file so
            # "connection reset by peer" has a root cause.
            _elog(f"[{utc_now()}] handle_error client={client_address}\n{traceback.format_exc()}")

    server = _Server((host, port), Handler)
    print(
        f"WebUI running on http://{host}:{port} "
        f"(daemon={'on' if enable_daemon else 'off'}, auth={'on' if resolved_auth_token else 'off'})"
    )
    # PID file enables wrappers (e.g. `omnimem codex --webui-on-demand`) to stop the WebUI
    # when no active sessions remain. Best-effort; failure should not prevent startup.
    runtime_dir = _resolve_runtime_dir(paths)
    pid_fp = runtime_dir / f"webui-{_endpoint_key(host, port)}.pid"
    try:
        pid_fp.parent.mkdir(parents=True, exist_ok=True)
        pid_fp.write_text(
            json.dumps(
                {
                    "pid": int(os.getpid()),
                    "host": str(host),
                    "port": int(port),
                    "started_at": utc_now(),
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass
    try:
        server.serve_forever()
    finally:
        stop_event.set()
        if daemon_thread is not None:
            daemon_thread.join(timeout=1.5)
        try:
            if pid_fp.exists():
                obj = json.loads(pid_fp.read_text(encoding="utf-8"))
                if int(obj.get("pid") or 0) == int(os.getpid()):
                    pid_fp.unlink(missing_ok=True)
        except Exception:
            pass
