"""V5.2 Phase 4 — Role × Model token/cost benchmark."""

from __future__ import annotations

from typing import Any


def build_model_benchmark(
    cfg: dict[str, Any] | None,
    *,
    cycle_summary: dict[str, Any] | None = None,
    ai_incremental_alpha: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Aggregate LLM usage by model/role for the latest research cycle.
    Alpha per token is descriptive when incremental alpha is available.
    """
    from ashare.ai.cost_tracker import get_cost_tracker

    if cycle_summary is None:
        cost = get_cost_tracker(cfg).summary()
        cycle_summary = dict(cost.get("cycle_cost") or cost.get("cycle") or {})

    by_model: dict[str, int] = dict(cycle_summary.get("by_model") or {})
    by_role: dict[str, int] = dict(cycle_summary.get("by_role") or {})
    model_cost: dict[str, float] = dict(cycle_summary.get("model_cost") or {})
    role_cost: dict[str, float] = dict(cycle_summary.get("role_cost") or {})

    if not by_model and not by_role:
        return {"available": False, "note": "no_llm_usage_in_cycle"}

    incr = None
    if isinstance(ai_incremental_alpha, dict):
        incr = ai_incremental_alpha.get("ai_incremental_alpha")
    total_tokens = int(cycle_summary.get("total_tokens") or 0)

    models = []
    for model, tokens in sorted(by_model.items(), key=lambda x: -x[1]):
        row: dict[str, Any] = {
            "model": model,
            "tokens": int(tokens),
            "cost_usd": round(float(model_cost.get(model) or 0), 6),
            "share_of_cycle_tokens": round(tokens / total_tokens, 4) if total_tokens else None,
        }
        if incr is not None and tokens > 0:
            row["alpha_per_100k_tokens"] = round(float(incr) / (tokens / 100_000.0), 6)
        models.append(row)

    roles = []
    for role, tokens in sorted(by_role.items(), key=lambda x: -x[1]):
        roles.append(
            {
                "role": role,
                "tokens": int(tokens),
                "cost_usd": round(float(role_cost.get(role) or 0), 6),
                "share_of_cycle_tokens": round(tokens / total_tokens, 4) if total_tokens else None,
            }
        )

    alpha_per_100k = None
    if incr is not None and total_tokens > 0:
        alpha_per_100k = round(float(incr) / (total_tokens / 100_000.0), 6)

    return {
        "available": True,
        "experimental": True,
        "method": "cycle_token_rollup",
        "total_tokens": total_tokens,
        "estimated_usd": cycle_summary.get("estimated_usd"),
        "alpha_per_100k_tokens": alpha_per_100k,
        "canonical_alpha_method": (ai_incremental_alpha or {}).get("method"),
        "models": models,
        "roles": roles,
        "note": "Descriptive cost routing — not proof of model quality.",
    }
