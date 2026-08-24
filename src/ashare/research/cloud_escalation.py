from __future__ import annotations

from typing import Any

from ashare.config_loaders import load_yaml_config

_MAJOR_TYPES = frozenset(
    {
        "order",
        "contract",
        "merger",
        "acquisition",
        "restructuring",
        "earnings",
        "earnings_preannouncement",
        "regulatory",
        "litigation",
    }
)


def escalation_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    return dict(load_yaml_config(cfg, "research").get("cloud_escalation") or {})


def should_escalate_news(
    candidate: dict[str, Any] | None,
    intel: dict[str, Any] | None,
    conflict: dict[str, Any] | None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Selective Cloud deep context — default conservative (no escalation)."""
    ecfg = escalation_cfg(cfg)
    if not bool(ecfg.get("enabled", True)):
        return {"escalate": False, "escalation_reason": "disabled", "extra_context": {}}

    c = candidate or {}
    intel = intel or {}
    conflict = conflict or {}
    reasons: list[str] = []

    imp_thr = float(ecfg.get("importance_threshold") or 0.75)
    conf_thr = float(ecfg.get("low_event_confidence") or 0.45)
    conflict_thr = float(ecfg.get("conflict_threshold") or 0.55)
    score_thr = float(ecfg.get("candidate_score_threshold") or 0.35)

    imp = float(intel.get("importance") or 0)
    ev_conf = float(intel.get("event_confidence") or 1.0)
    et = str(intel.get("event_type") or intel.get("normalized_event_type") or "")

    if imp >= imp_thr:
        reasons.append("high_importance")
    if ev_conf < conf_thr:
        reasons.append("low_event_confidence")
    if float(conflict.get("conflict_score") or 0) >= conflict_thr:
        reasons.append("news_quant_conflict")
    if et in _MAJOR_TYPES:
        reasons.append(f"major_event:{et}")
    if float(c.get("candidate_score") or 0) >= score_thr:
        reasons.append("high_priority_candidate")

    escalate = len(reasons) >= int(ecfg.get("min_triggers") or 2)
    extra: dict[str, Any] = {}
    if escalate:
        extra = {
            "compact_news": c.get("compact_news") or (c.get("news_package") or {}).get("compact_news_package"),
            "news_intelligence": intel,
            "news_conflict": conflict,
            "evidence_direction": intel.get("direction") or intel.get("evidence_direction"),
        }

    return {
        "escalate": escalate,
        "escalation_reason": "+".join(reasons) if reasons else "none",
        "extra_context": extra,
    }
