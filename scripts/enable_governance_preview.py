#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from omnimem.core import load_config_with_path, save_config


def main() -> int:
    ap = argparse.ArgumentParser(description="Enable governance preview-only window")
    ap.add_argument("--config", default=None)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    days = max(1, min(90, int(args.days)))
    until = (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()

    cfg, cfg_path = load_config_with_path(Path(args.config) if args.config else None)
    cfg.setdefault("webui", {})
    cfg["webui"]["approval_required"] = True
    cfg["webui"]["maintenance_preview_only_until"] = until

    out = {
        "ok": True,
        "config_path": str(cfg_path),
        "approval_required": True,
        "maintenance_preview_only_until": until,
        "dry_run": bool(args.dry_run),
    }
    if not args.dry_run:
        save_config(cfg_path, cfg)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
