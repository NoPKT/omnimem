from __future__ import annotations

from dataclasses import dataclass


PROFILE_SET = {"balanced", "low_quota", "deep_research", "high_throughput"}
QUOTA_MODE_SET = {"normal", "low", "critical", "auto"}


@dataclass(frozen=True)
class ContextPlan:
    profile: str
    quota_mode: str
    context_budget_tokens: int
    retrieve_limit: int
    prefer_delta_context: bool
    stable_prefix: bool
    decision_reason: str


def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def resolve_context_plan(
    *,
    profile: str,
    quota_mode: str,
    context_budget_tokens: int,
    retrieve_limit: int,
    prompt_tokens_estimate: int = 0,
    recent_transient_failures: int = 0,
    recent_context_utilization: float = 0.0,
) -> ContextPlan:
    p = str(profile or "balanced").strip().lower()
    q_raw = str(quota_mode or "normal").strip().lower()
    if p not in PROFILE_SET:
        p = "balanced"
    if q_raw not in QUOTA_MODE_SET:
        q_raw = "normal"
    q = q_raw
    auto_reason = ""
    if q == "auto":
        n = max(0, int(prompt_tokens_estimate))
        if n >= 1200:
            q = "critical"
            auto_reason = f"auto quota: prompt_tokens_estimate={n} >= 1200 -> critical"
        elif n >= 520:
            q = "low"
            auto_reason = f"auto quota: prompt_tokens_estimate={n} >= 520 -> low"
        else:
            q = "normal"
            auto_reason = f"auto quota: prompt_tokens_estimate={n} < 520 -> normal"
        # Keep low-quota profile conservative even with short prompts.
        if p == "low_quota" and q == "normal":
            q = "low"
            auto_reason += "; profile=low_quota enforces at least low"
        rt = max(0, int(recent_transient_failures))
        if rt >= 7 and q != "critical":
            q = "critical"
            auto_reason += f"; recent transient failures={rt} -> critical"
        elif rt >= 3 and q == "normal":
            q = "low"
            auto_reason += f"; recent transient failures={rt} -> low"
        cu = float(recent_context_utilization or 0.0)
        if cu >= 0.96 and q != "critical":
            q = "critical"
            auto_reason += f"; recent context utilization={cu:.2f} -> critical"
        elif cu >= 0.88 and q == "normal":
            q = "low"
            auto_reason += f"; recent context utilization={cu:.2f} -> low"

    base_budget = max(120, int(context_budget_tokens))
    base_limit = max(1, int(retrieve_limit))

    # Profile: user intent / workload shape.
    p_budget_mul = {
        "balanced": 1.0,
        "low_quota": 0.72,
        "deep_research": 1.35,
        "high_throughput": 0.88,
    }[p]
    p_limit_mul = {
        "balanced": 1.0,
        "low_quota": 0.75,
        "deep_research": 1.40,
        "high_throughput": 0.90,
    }[p]
    p_delta = {
        "balanced": True,
        "low_quota": True,
        "deep_research": True,
        "high_throughput": False,
    }[p]

    # Quota mode: operational pressure.
    q_budget_mul = {
        "normal": 1.0,
        "low": 0.82,
        "critical": 0.62,
    }[q]
    q_limit_mul = {
        "normal": 1.0,
        "low": 0.86,
        "critical": 0.72,
    }[q]

    budget = _clamp_int(round(base_budget * p_budget_mul * q_budget_mul), 160, 1400)
    limit = _clamp_int(round(base_limit * p_limit_mul * q_limit_mul), 4, 24)
    prefer_delta = bool(p_delta or q in {"low", "critical"})

    # Stable prefix improves provider-side KV/prompt cache hit rate.
    return ContextPlan(
        profile=p,
        quota_mode=q,
        context_budget_tokens=budget,
        retrieve_limit=limit,
        prefer_delta_context=prefer_delta,
        stable_prefix=True,
        decision_reason=auto_reason or f"manual quota mode: {q}; profile={p}",
    )
