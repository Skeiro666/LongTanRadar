from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

COUNCIL_ROLE_IDS = ("fundamental", "quant", "event", "valuation", "bear")

SKIP_REASONS = {
    "LOW_SCORE": "LOW_SCORE",
    "NO_NEW_INFORMATION": "NO_NEW_INFORMATION",
    "DATA_UNAVAILABLE": "DATA_UNAVAILABLE",
    "NOT_RELEVANT_ROLE": "NOT_RELEVANT_ROLE",
    "NO_FINANCIAL_CATALYST": "NO_FINANCIAL_CATALYST",
    "VALUATION_UNAVAILABLE": "VALUATION_UNAVAILABLE",
    "NO_MAJOR_EVENT": "NO_MAJOR_EVENT",
    "WEAK_QUANT_SIGNAL": "WEAK_QUANT_SIGNAL",
}


def _dynamic_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not cfg:
        return {}
    from ashare.config_loaders import load_yaml_config

    return dict(load_yaml_config(cfg, "research").get("dynamic_council") or {})


@dataclass
class CouncilPlan:
    roles: tuple[str, ...]
    profile: str
    call_reasons: dict[str, str] = field(default_factory=dict)
    skip_reasons: dict[str, str] = field(default_factory=dict)


def _detect_profile(snapshot: dict[str, Any], sources: set[str]) -> str:
    pi = snapshot.get("profit_inflection") or {}
    profit_score = float(pi.get("score") or 0)
    event = snapshot.get("event") or {}
    event_score = float(event.get("score") or 0)
    news = snapshot.get("news_package") or {}
    net_event = float(news.get("net_event_score") or 0)
    if profit_score >= 0.2 or "profit" in sources or pi.get("material"):
        return "profit_inflection"
    if "news" in sources and (net_event >= 0.1 or snapshot.get("research_hypotheses")):
        return "major_news"
    if "event" in sources or event_score >= 0.15:
        return "major_event"
    if snapshot.get("value_available", False):
        return "valuation_available"
    return "default"


def plan_council(snapshot: dict[str, Any], cfg: dict[str, Any] | None = None) -> CouncilPlan:
    """
    V5 dynamic council profiles with explicit call/skip reasons.
    Chairman is always scheduled separately after roles.
    """
    dc = _dynamic_cfg(cfg)
    if not bool(dc.get("enabled", True)):
        return CouncilPlan(
            roles=COUNCIL_ROLE_IDS,
            profile="full_council",
            call_reasons={r: "FULL_COUNCIL" for r in COUNCIL_ROLE_IDS},
        )

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
    cs = float(snapshot.get("candidate_score") or quant.get("factor_score") or 0)
    price_risk = str(snapshot.get("price_in_risk") or "UNKNOWN").upper()

    min_profit = float(dc.get("min_profit_score") or 0.2)
    min_quant = float(dc.get("min_leader_score") or 0.15)
    min_ml = float(dc.get("min_ml_prediction") or 0.005)
    min_event = float(dc.get("min_event_score") or 0.1)

    profile = _detect_profile(snapshot, sources)
    roles: list[str] = []
    call: dict[str, str] = {}
    skip: dict[str, str] = {}

    # Bear: high candidate/news score or price risk
    bear_needed = cs >= 0.15 or net_event >= 0.1 or price_risk in {"HIGH", "MEDIUM"} or leader >= min_quant
    if bear_needed:
        roles.append("bear")
        call["bear"] = "HIGH_RISK" if price_risk in {"HIGH", "MEDIUM"} else "HIGH_CANDIDATE_SCORE"
    else:
        roles.append("bear")
        call["bear"] = "DEFAULT_BEAR"

    if profile == "profit_inflection":
        roles.extend(["fundamental", "quant"])
        call["fundamental"] = "PROFIT_INFLECTION"
        call["quant"] = "PROFIT_INFLECTION"
        skip["event"] = SKIP_REASONS["NOT_RELEVANT_ROLE"]
        skip["valuation"] = SKIP_REASONS["VALUATION_UNAVAILABLE"] if not snapshot.get("value_available") else ""
    elif profile == "major_news":
        roles.append("event")
        call["event"] = "NEW_MAJOR_NEWS"
        if leader >= min_quant or ml >= min_ml or "quant" in sources:
            roles.append("quant")
            call["quant"] = "NEW_MAJOR_NEWS"
        else:
            skip["quant"] = SKIP_REASONS["WEAK_QUANT_SIGNAL"]
        skip["fundamental"] = SKIP_REASONS["NO_FINANCIAL_CATALYST"]
    elif profile == "major_event":
        roles.append("event")
        call["event"] = "NEW_MAJOR_EVENT"
        skip["fundamental"] = SKIP_REASONS["NO_FINANCIAL_CATALYST"]
        if leader >= min_quant or ml >= min_ml:
            roles.append("quant")
            call["quant"] = "NEW_MAJOR_EVENT"
        else:
            skip["quant"] = SKIP_REASONS["WEAK_QUANT_SIGNAL"]
    elif profile == "valuation_available":
        roles.extend(["quant", "valuation"])
        call["quant"] = "VALUATION_AVAILABLE"
        call["valuation"] = "VALUATION_AVAILABLE"
        skip["fundamental"] = SKIP_REASONS["NO_FINANCIAL_CATALYST"]
        skip["event"] = SKIP_REASONS["NO_MAJOR_EVENT"]
    else:
        # default: quant + bear (+ chairman later)
        if leader >= min_quant or ml >= min_ml or "quant" in sources:
            roles.append("quant")
            call["quant"] = "HIGH_CANDIDATE_SCORE" if cs >= 0.15 else "QUANT_SOURCE"
        else:
            skip["quant"] = SKIP_REASONS["WEAK_QUANT_SIGNAL"]
        skip["fundamental"] = SKIP_REASONS["NO_FINANCIAL_CATALYST"]
        skip["event"] = SKIP_REASONS["NO_MAJOR_EVENT"]

    # Profile-specific event/fundamental rules
    if profile not in {"major_news", "major_event", "profit_inflection"}:
        if hyps or net_event >= min_event or event_score >= min_event or "news" in sources:
            if "event" not in roles:
                roles.append("event")
                call["event"] = "NEW_INFORMATION"
        if profit_score >= min_profit or "profit" in sources:
            if "fundamental" not in roles:
                roles.append("fundamental")
                call["fundamental"] = "NEW_INFORMATION"

    if snapshot.get("value_available", False) and "valuation" not in roles and profile != "valuation_available":
        roles.append("valuation")
        call["valuation"] = "VALUATION_AVAILABLE"
    elif not snapshot.get("value_available", False):
        skip["valuation"] = SKIP_REASONS["VALUATION_UNAVAILABLE"]

    skip = {k: v for k, v in skip.items() if v and k not in roles}
    order = list(COUNCIL_ROLE_IDS)
    ordered = tuple(dict.fromkeys(r for r in order if r in roles))
    return CouncilPlan(roles=ordered, profile=profile, call_reasons=call, skip_reasons=skip)


def select_council_roles(snapshot: dict[str, Any], cfg: dict[str, Any] | None = None) -> tuple[str, ...]:
    return plan_council(snapshot, cfg).roles


def skipped_role_opinion(role_id: str, reason: str) -> dict[str, Any]:
    return {
        "role": role_id,
        "score": 0.0,
        "stance": "neutral",
        "points": [reason],
        "status": "skipped",
        "source": "dynamic_council",
        "skip_reason": reason,
    }
