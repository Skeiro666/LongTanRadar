from __future__ import annotations

from typing import Any

COUNCIL_ROLE_IDS = ("fundamental", "quant", "event", "valuation", "bear")


def _dynamic_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not cfg:
        return {}
    from ashare.config_loaders import load_yaml_config

    return dict(load_yaml_config(cfg, "research").get("dynamic_council") or {})


def select_council_roles(snapshot: dict[str, Any], cfg: dict[str, Any] | None = None) -> tuple[str, ...]:
    """
    Rule-based role selection (no LLM). Bear always runs; valuation only if data exists.
    """
    dc = _dynamic_cfg(cfg)
    if not bool(dc.get("enabled", True)):
        return COUNCIL_ROLE_IDS

    roles: list[str] = []
    sources = set(snapshot.get("candidate_sources") or [])
    quant = snapshot.get("quant") or {}
    leader = float(quant.get("leader_score") or 0)
    ml = float(quant.get("ml_prediction") or 0)
    pi = snapshot.get("profit_inflection") or {}
    profit_score = float(pi.get("score") or 0)
    event = snapshot.get("event") or {}
    event_score = float(event.get("score") or 0)
    news = snapshot.get("news_package") or {}
    net_event = float(news.get("net_event_score") or 0)
    hyps = list(snapshot.get("research_hypotheses") or [])

    min_profit = float(dc.get("min_profit_score") or 0.2)
    min_quant = float(dc.get("min_leader_score") or 0.15)
    min_ml = float(dc.get("min_ml_prediction") or 0.005)
    min_event = float(dc.get("min_event_score") or 0.1)

    if profit_score >= min_profit or "profit" in sources or pi.get("material"):
        roles.append("fundamental")
    if leader >= min_quant or ml >= min_ml or "quant" in sources:
        roles.append("quant")
    if hyps or net_event >= min_event or event_score >= min_event or "news" in sources or "event" in sources:
        roles.append("event")
    if snapshot.get("value_available", False):
        roles.append("valuation")
    roles.append("bear")

    # preserve canonical order
    order = list(COUNCIL_ROLE_IDS)
    return tuple(r for r in order if r in roles)


def skipped_role_opinion(role_id: str, reason: str) -> dict[str, Any]:
    return {
        "role": role_id,
        "score": 0.0,
        "stance": "neutral",
        "points": [reason],
        "status": "skipped",
        "source": "dynamic_council",
    }
