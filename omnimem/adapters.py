from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def resolve_cred_ref(ref: str) -> str:
    if ref.startswith("env://"):
        key = ref[len("env://") :]
        val = os.getenv(key)
        if val is None:
            raise ValueError(f"environment variable not found: {key}")
        return val

    if ref.startswith("op://"):
        try:
            proc = subprocess.run(["op", "read", ref], check=True, capture_output=True, text=True)
            return proc.stdout.strip()
        except FileNotFoundError:
            raise ValueError("1Password CLI ('op') not found in PATH")
        except subprocess.CalledProcessError as e:
            raise ValueError(f"1Password CLI error: {e.stderr.strip() if e.stderr else 'auth failed or item not found'}")

    raise ValueError("unsupported cred ref, expected env:// or op://")


def _http_json(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url=url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network error: {exc.reason}") from exc


def notion_write_page(
    *,
    token: str,
    database_id: str,
    title: str,
    content: str,
    title_property: str = "Name",
    dry_run: bool = False,
) -> dict[str, Any]:
    payload = {
        "parent": {"database_id": database_id},
        "properties": {
            title_property: {
                "title": [{"text": {"content": title}}]
            }
        },
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content[:1900]}}]
                },
            }
        ],
    }
    if dry_run:
        return {"ok": True, "mode": "dry_run", "payload": payload}

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    data = _http_json("POST", f"{NOTION_API_BASE}/pages", headers, payload)
    return {"ok": True, "id": data.get("id"), "url": data.get("url")}


def notion_query_database(
    *,
    token: str,
    database_id: str,
    page_size: int = 5,
    dry_run: bool = False,
) -> dict[str, Any]:
    payload = {"page_size": page_size}
    if dry_run:
        return {"ok": True, "mode": "dry_run", "payload": payload}

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    data = _http_json("POST", f"{NOTION_API_BASE}/databases/{database_id}/query", headers, payload)
    results = data.get("results", [])
    slim = [{"id": x.get("id"), "url": x.get("url")} for x in results]
    return {"ok": True, "count": len(slim), "items": slim}


def r2_put_presigned(*, file_path: Path, presigned_url: str, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"ok": True, "mode": "dry_run", "file": str(file_path), "url_prefix": presigned_url[:40]}

    proc = subprocess.run(
        ["curl", "-sS", "-X", "PUT", "--upload-file", str(file_path), presigned_url],
        check=True,
        capture_output=True,
        text=True,
    )
    return {"ok": True, "response": proc.stdout.strip()}


def r2_get_presigned(*, presigned_url: str, out_path: Path, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"ok": True, "mode": "dry_run", "out": str(out_path), "url_prefix": presigned_url[:40]}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["curl", "-sS", "-L", "-o", str(out_path), presigned_url], check=True)
    return {"ok": True, "out": str(out_path)}
