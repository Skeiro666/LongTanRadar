"""V5.4 Adaptive AI Routing — 0 LLM conflict score and council tier selection."""

from __future__ import annotations

from typing import Any

from ashare.config_loaders import load_yaml_config
from ashare.research.gate import _signal_values


def routing_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(load_yaml_config(cfg, "research").get("ai_routing") or {})
    return {
        "enabled": bool(base.get("enabled", True)),
        "low_conflict_max": float(base.get("low_conflict_max", 0.25)),
        "high_conflict_min": float(base.get("high_conflict_min", 0.55)),
        "low_score_skip_above": float(base.get("low_score_skip_above", 0.72)),
        "low_score_skip_below": float(base.get("low_score_skip_below", 0.18)),
        "weights": dict(
            base.get("weights")
            or {
                "quant": 0.25,
                "event": 0.2,
                "profit": 0.2,
                "news": 0.15,
                "ml": 0.1,
                "data_quality": 0.1,
            }
        ),
    }


def _direction(score: float, *, bullish_at: float = 0.35, bearish_at: float = 0.12) -> int:
    if score >= bullish_at:
        return 1
    if score <= bearish_at:
        return -1
    return 0


def compute_conflict_score(candidate: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """0~1 conflict from directional disagreement across core signals. No LLM."""
    sig = _signal_values(candidate)
    pi = candidate.get("profit_inflection") or {}
    profit_score = float(pi.get("score") or 0) if pi.get("available", True) else 0.0
    dirs = {
        "quant": _direction(float(sig.get("leader_score") or sig.get("candidate_score") or 0)),
        "event": _direction(float(sig.get("event_score") or 0)),
        "profit": _direction(profit_score),
        "news": _direction(float(sig.get("news_score") or 0)),
        "ml": _direction(float(sig.get("ml_prediction") or 0), bullish_at=0.004, bearish_at=0.0),
    }
    active = [d for d in dirs.values() if d != 0]
    if len(active) < 2:
        conflict = 0.0
    else:
        pos = sum(1 for d in active if d > 0)
        neg = sum(1 for d in active if d < 0)
        conflict = min(1.0, (min(pos, neg) * 2) / max(len(active), 1))
    return {"conflict_score": round(conflict, 4), "directions": dirs, "signals": sig}


def compute_ai_routing(candidate: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    LOW — clear strong/weak, skip full council.
    MEDIUM — moderate conflict → full council (light research reserved).
    HIGH — high conflict → full council priority.
    """
    rc = routing_cfg(cfg)
    if not rc["enabled"]:
        return {
            "available": True,
            "routing_level": "HIGH",
            "routing_score": 1.0,
            "ai_called": True,
            "skip_council": False,
            "reason": "routing_disabled",
        }

    conflict_pack = compute_conflict_score(candidate, cfg)
    conflict = float(conflict_pack["conflict_score"])
    cs = float(conflict_pack["signals"].get("candidate_score") or 0)

    dq = 1.0
    pi = candidate.get("profit_inflection") or {}
    if pi.get("quality") == "D":
        dq *= 0.5
    if not candidate.get("value_available"):
        dq *= 0.85

    w = rc["weights"]
    routing_score = round(
        conflict * float(w.get("quant", 0.25) + w.get("event", 0.2) + w.get("profit", 0.2))
        + (1.0 - min(1.0, cs)) * float(w.get("data_quality", 0.1))
        + dq * 0.1,
        4,
    )

    skip = False
    level = "MEDIUM"
    reason = "moderate_conflict"

    if conflict <= rc["low_conflict_max"] and (cs >= rc["low_score_skip_above"] or cs <= rc["low_score_skip_below"]):
        level = "LOW"
        skip = True
        reason = "clear_signal_low_conflict"
    elif conflict >= rc["high_conflict_min"]:
        level = "HIGH"
        reason = "high_signal_conflict"
    else:
        level = "MEDIUM"
        reason = "medium_conflict_full_council"

    return {
        "available": True,
        "routing_level": level,
        "routing_score": routing_score,
        "conflict_score": conflict,
        "conflict_detail": conflict_pack,
        "ai_called": not skip,
        "skip_council": skip,
        "reason": reason,
        "data_quality": round(dq, 3),
        "candidate_score": cs,
    }


def quant_only_decision(candidate: dict[str, Any]) -> dict[str, Any]:
    """Heuristic chairman output when council skipped — 0 LLM."""
    cs = float(candidate.get("candidate_score") or 0)
    if cs >= 0.55:
        rating, action = "BUY", "SMALL_POSITION"
    elif cs >= 0.35:
        rating, action = "WATCH", "WATCH"
    else:
        rating, action = "PASS", "NO_ACTION"
    return {
        "source": "quant_routing_skip",
        "rating": rating,
        "trading_action": action,
        "confidence": min(0.75, max(0.35, cs)),
        "rationale": "Adaptive routing LOW — quant-only decision, no council LLM",
        "status": "ok",
    }
