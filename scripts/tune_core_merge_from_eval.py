#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from omnimem.core import load_config_with_path, save_config


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _metric(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(metrics.get(key, default) or default)
    except Exception:
        return float(default)


def _mode_score(metrics: dict[str, Any]) -> float:
    # Prefer strong quality/support and information-dense non-redundant synthesis.
    q = _metric(metrics, "avg_quality")
    sup = _metric(metrics, "avg_support")
    uniq = _metric(metrics, "avg_unique_line_ratio")
    chars = _metric(metrics, "avg_guidance_chars")
    brevity_penalty = _clamp(chars / 1200.0, 0.0, 0.25)
    return (0.58 * q) + (0.24 * sup) + (0.18 * uniq) - (0.08 * brevity_penalty)


def main() -> int:
    ap = argparse.ArgumentParser(description="Tune core-merge defaults from eval_core_merge report")
    ap.add_argument("--report", required=True, help="report json from scripts/eval_core_merge.py")
    ap.add_argument("--config", default=None, help="omnimem config path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    metrics = dict(report.get("metrics") or {})
    if not metrics:
        raise ValueError("report has no metrics")

    supported = [m for m in ("concat", "synthesize", "semantic") if m in metrics]
    if not supported:
        raise ValueError("report has no supported modes")

    scored = []
    for mode in supported:
        m = dict(metrics.get(mode) or {})
        scored.append((mode, _mode_score(m), m))
    scored.sort(key=lambda t: t[1], reverse=True)

    best_mode, best_score, best_metrics = scored[0]
    best_quality = _metric(best_metrics, "avg_quality", 0.0)
    best_lines = _metric(best_metrics, "avg_guidance_lines", 0.0)

    # Keep line budget compact but not too short.
    recommended_lines = int(round(_clamp(best_lines + 1.0, 4.0, 10.0)))
    # Apply threshold should trail observed quality to keep rollout safe.
    recommended_min_apply_quality = round(_clamp((best_quality * 0.7) - 0.02, 0.12, 0.85), 3)
    recommended_loser_action = "deprioritize" if recommended_min_apply_quality >= 0.24 else "none"

    cfg, cfg_path = load_config_with_path(Path(args.config) if args.config else None)
    core_merge = cfg.setdefault("core_merge", {})
    if not isinstance(core_merge, dict):
        core_merge = {}
        cfg["core_merge"] = core_merge

    before = {
        "default_merge_mode": str(core_merge.get("default_merge_mode", "synthesize") or "synthesize"),
        "default_max_merged_lines": int(core_merge.get("default_max_merged_lines", 8) or 8),
        "default_min_apply_quality": float(core_merge.get("default_min_apply_quality", 0.0) or 0.0),
        "default_loser_action": str(core_merge.get("default_loser_action", "none") or "none"),
    }

    core_merge["default_merge_mode"] = str(best_mode)
    core_merge["default_max_merged_lines"] = int(recommended_lines)
    core_merge["default_min_apply_quality"] = float(recommended_min_apply_quality)
    core_merge["default_loser_action"] = str(recommended_loser_action)

    after = {
        "default_merge_mode": str(core_merge.get("default_merge_mode")),
        "default_max_merged_lines": int(core_merge.get("default_max_merged_lines")),
        "default_min_apply_quality": float(core_merge.get("default_min_apply_quality")),
        "default_loser_action": str(core_merge.get("default_loser_action")),
    }

    out = {
        "ok": True,
        "config_path": str(cfg_path),
        "chosen_mode": best_mode,
        "chosen_mode_score": round(float(best_score), 4),
        "chosen_mode_metrics": {
            "avg_quality": round(best_quality, 4),
            "avg_support": round(_metric(best_metrics, "avg_support"), 4),
            "avg_unique_line_ratio": round(_metric(best_metrics, "avg_unique_line_ratio"), 4),
            "avg_guidance_lines": round(best_lines, 3),
            "avg_guidance_chars": round(_metric(best_metrics, "avg_guidance_chars"), 2),
        },
        "core_merge_before": before,
        "core_merge_after": after,
        "dry_run": bool(args.dry_run),
    }
    if not args.dry_run:
        save_config(cfg_path, cfg)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
