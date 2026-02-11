#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from omnimem.core import load_config_with_path, save_config


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def main() -> int:
    ap = argparse.ArgumentParser(description="Tune daemon adaptive governance quantiles from retrieval eval report")
    ap.add_argument("--report", required=True, help="report json from scripts/eval_retrieval.py")
    ap.add_argument("--config", default=None, help="omnimem config path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    basic = report.get("basic") or {}
    smart = report.get("smart") or {}
    hit_delta = float(smart.get("hit_at_k", 0.0) or 0.0) - float(basic.get("hit_at_k", 0.0) or 0.0)
    mrr_delta = float(smart.get("mrr", 0.0) or 0.0) - float(basic.get("mrr", 0.0) or 0.0)

    cfg, cfg_path = load_config_with_path(Path(args.config) if args.config else None)
    dm = cfg.setdefault("daemon", {})
    q = {
        "adaptive_q_promote_imp": float(dm.get("adaptive_q_promote_imp", 0.68)),
        "adaptive_q_promote_conf": float(dm.get("adaptive_q_promote_conf", 0.60)),
        "adaptive_q_promote_stab": float(dm.get("adaptive_q_promote_stab", 0.62)),
        "adaptive_q_promote_vol": float(dm.get("adaptive_q_promote_vol", 0.42)),
        "adaptive_q_demote_vol": float(dm.get("adaptive_q_demote_vol", 0.78)),
        "adaptive_q_demote_stab": float(dm.get("adaptive_q_demote_stab", 0.28)),
        "adaptive_q_demote_reuse": float(dm.get("adaptive_q_demote_reuse", 0.30)),
    }

    # Heuristic: if smart retrieval improves, slightly strengthen promotion and keep noisy demotion.
    # If it regresses, become conservative and reduce demotion aggressiveness.
    if (hit_delta + mrr_delta) >= 0.03:
        q["adaptive_q_promote_imp"] = clamp(q["adaptive_q_promote_imp"] - 0.03, 0.45, 0.90)
        q["adaptive_q_promote_conf"] = clamp(q["adaptive_q_promote_conf"] - 0.02, 0.40, 0.90)
        q["adaptive_q_promote_stab"] = clamp(q["adaptive_q_promote_stab"] - 0.02, 0.40, 0.92)
        q["adaptive_q_demote_vol"] = clamp(q["adaptive_q_demote_vol"] + 0.02, 0.55, 0.98)
    elif (hit_delta + mrr_delta) <= -0.01:
        q["adaptive_q_promote_imp"] = clamp(q["adaptive_q_promote_imp"] + 0.03, 0.45, 0.92)
        q["adaptive_q_promote_conf"] = clamp(q["adaptive_q_promote_conf"] + 0.02, 0.40, 0.92)
        q["adaptive_q_promote_stab"] = clamp(q["adaptive_q_promote_stab"] + 0.02, 0.40, 0.95)
        q["adaptive_q_demote_vol"] = clamp(q["adaptive_q_demote_vol"] - 0.02, 0.55, 0.98)

    for k, v in q.items():
        dm[k] = float(round(v, 3))

    out = {
        "ok": True,
        "config_path": str(cfg_path),
        "hit_delta": hit_delta,
        "mrr_delta": mrr_delta,
        "daemon_quantiles": q,
        "dry_run": bool(args.dry_run),
    }
    if not args.dry_run:
        save_config(cfg_path, cfg)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
