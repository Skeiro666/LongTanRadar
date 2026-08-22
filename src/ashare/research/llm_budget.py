from __future__ import annotations

from typing import Any


def llm_budget_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not cfg:
        return {
            "enabled": True,
            "max_llm_calls": 30,
            "max_input_tokens": 0,
            "max_output_tokens": 0,
            "max_cost_usd": 0.0,
        }
    from ashare.config_loaders import load_yaml_config

    research = load_yaml_config(cfg, "research")
    gate = dict(research.get("research_gate") or {})
    raw = dict(research.get("llm_budget") or {})
    max_calls = raw.get("max_llm_calls")
    if max_calls is None:
        max_calls = gate.get("max_llm_calls", 30)
    return {
        "enabled": bool(raw.get("enabled", True)),
        "max_llm_calls": int(max_calls),
        "max_input_tokens": int(raw.get("max_input_tokens") or 0),
        "max_output_tokens": int(raw.get("max_output_tokens") or 0),
        "max_cost_usd": float(raw.get("max_cost_usd") or 0.0),
    }


def budget_snapshot(cycle_summary: dict[str, Any], cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Compare cycle usage vs configured caps. 0 cap = unlimited."""
    bc = llm_budget_cfg(cfg)
    used_calls = int(cycle_summary.get("n_calls") or cycle_summary.get("total_calls") or 0)
    in_tok = int(cycle_summary.get("input_tokens") or 0)
    out_tok = int(cycle_summary.get("output_tokens") or 0)
    cost = float(cycle_summary.get("estimated_usd") or 0.0)
    cache_hits = int(cycle_summary.get("cache_hits") or cycle_summary.get("n_cache_events") or 0)
    total_calls = used_calls + cache_hits
    hit_rate = round(cache_hits / total_calls, 4) if total_calls else 0.0

    exceeded: list[str] = []
    if bc["max_llm_calls"] > 0 and used_calls >= bc["max_llm_calls"]:
        exceeded.append("max_llm_calls")
    if bc["max_input_tokens"] > 0 and in_tok >= bc["max_input_tokens"]:
        exceeded.append("max_input_tokens")
    if bc["max_output_tokens"] > 0 and out_tok >= bc["max_output_tokens"]:
        exceeded.append("max_output_tokens")
    if bc["max_cost_usd"] > 0 and cost >= bc["max_cost_usd"]:
        exceeded.append("max_cost_usd")

    return {
        "enabled": bc["enabled"],
        "limits": bc,
        "used": {
            "llm_calls": used_calls,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": int(cycle_summary.get("total_tokens") or in_tok + out_tok),
            "estimated_usd": round(cost, 6),
            "cache_hits": cache_hits,
            "cache_hit_rate": hit_rate,
        },
        "exceeded": exceeded,
        "hard_stop": bool(bc["enabled"] and exceeded),
    }


def budget_allows_llm_call(cycle_summary: dict[str, Any], cfg: dict[str, Any] | None) -> tuple[bool, str]:
    snap = budget_snapshot(cycle_summary, cfg)
    if not snap["enabled"]:
        return True, "budget_disabled"
    if snap["hard_stop"]:
        return False, str(snap["exceeded"][0])
    return True, "ok"
