from __future__ import annotations

from typing import Any


def build_research_intelligence(snapshot: dict[str, Any], *, role_id: str | None = None) -> dict[str, Any]:
    """
    Compact Research Intelligence Package for Council / Chairman.
    Never invent PE/consensus; mark unavailable fields explicitly.
    """
    news = snapshot.get("news_package") or {}
    news_view = news
    if role_id and isinstance(news.get("role_views"), dict):
        news_view = news["role_views"].get(role_id) or news

    hyps = list(snapshot.get("research_hypotheses") or [])
    nd = snapshot.get("news_discovery") or {}
    pi = snapshot.get("profit_inflection") or {}
    price_rx = nd.get("price_reaction") if isinstance(nd, dict) else None
    if not isinstance(price_rx, dict):
        price_rx = snapshot.get("price_reaction")
    if not isinstance(price_rx, dict):
        price_rx = {"available": False, "note": "no_bars_or_not_computed"}
    price_in = "UNKNOWN"
    if isinstance(nd, dict) and nd.get("price_in_risk"):
        price_in = str(nd.get("price_in_risk"))
    elif snapshot.get("price_in_risk"):
        price_in = str(snapshot.get("price_in_risk"))
    elif isinstance(price_rx, dict) and price_rx.get("price_in_risk"):
        price_in = str(price_rx.get("price_in_risk"))

    value_ok = bool(snapshot.get("value_available", False))
    quality_ok = bool(snapshot.get("quality_available", False))
    news_incomplete = bool(news.get("news_data_incomplete"))
    exp = news.get("expectation") or {}
    exp_ok = bool(exp.get("available"))

    data_availability = {
        "value": {"available": value_ok, "note": None if value_ok else "无 as-of 估值，禁止伪造 PE/PB"},
        "quality": {"available": quality_ok, "note": None if quality_ok else "无 as-of 质量财务"},
        "consensus_expectation": {
            "available": exp_ok,
            "note": None if exp_ok else (exp.get("note") or "无一致预期"),
        },
        "news": {
            "available": not news_incomplete and bool(news.get("news_ids") or news.get("last_7d") or hyps),
            "incomplete": news_incomplete,
            "note": "新闻不完整" if news_incomplete else None,
        },
        "industry_map": {"available": False, "note": "无行业/产业链映射"},
        "price_reaction": {
            "available": bool(price_rx.get("available")),
            "note": price_rx.get("note") or ("unavailable" if not price_rx.get("available") else None),
        },
        "historical_event_outcomes": {"available": False, "note": "无可靠历史事件库"},
    }

    evidence_ids: list[str] = []
    for h in hyps:
        if isinstance(h, dict):
            evidence_ids.extend([str(x) for x in (h.get("evidence_ids") or []) if x])
    evidence_ids.extend([str(x) for x in (news.get("news_ids") or [])[:20]])
    evidence_ids.extend([str(x) for x in (news.get("event_ids") or [])[:20]])
    # dedupe preserve order
    seen: set[str] = set()
    evid_out = []
    for e in evidence_ids:
        if e not in seen:
            seen.add(e)
            evid_out.append(e)

    return {
        "symbol": snapshot.get("symbol"),
        "name": snapshot.get("name"),
        "candidate_sources": list(snapshot.get("candidate_sources") or []),
        "quant_context": snapshot.get("quant") or {},
        "factor_context": (snapshot.get("quant") or {}).get("factors") or {},
        "profit_context": pi,
        "event_context": snapshot.get("event") or {},
        "news_context": {
            "counts": news.get("counts"),
            "net_event_score": news.get("net_event_score"),
            "conflicts": news.get("conflicts") or [],
            "timeline": (news.get("timeline") or [])[:12],
            "role_view": news_view if role_id else None,
            "last_7d": (news.get("last_7d") or news_view.get("news") if isinstance(news_view, dict) else None) or [],
        },
        "news_event_context": nd if isinstance(nd, dict) and nd else None,
        "research_hypotheses": hyps[:12],
        "price_reaction": price_rx,
        "price_in_risk": price_in,
        "risk_context": {
            "market_regime": snapshot.get("market_regime"),
            "market": snapshot.get("market") or {},
            "trigger": snapshot.get("trigger") or {},
        },
        "data_availability": data_availability,
        "evidence_ids": evid_out[:40],
        "rules": [
            "News ≠ BUY",
            "FACT ≠ INFERENCE ≠ HYPOTHESIS",
            "available=false fields must not be invented",
            "price_in_risk is a warning only, not auto PASS/SELL",
        ],
    }
