from __future__ import annotations

from typing import Any


def _compression_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not cfg:
        return {"enabled": True, "max_news_headlines": 5, "max_timeline_events": 6, "max_hypotheses": 8}
    from ashare.config_loaders import load_yaml_config

    research = load_yaml_config(cfg, "research")
    cc = dict(research.get("context_compression") or {})
    return {
        "enabled": bool(cc.get("enabled", True)),
        "max_news_headlines": int(cc.get("max_news_headlines") or 5),
        "max_timeline_events": int(cc.get("max_timeline_events") or 6),
        "max_hypotheses": int(cc.get("max_hypotheses") or 8),
    }


def context_compression_enabled(cfg: dict[str, Any] | None) -> bool:
    return _compression_cfg(cfg).get("enabled", True)


def _compact_news_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    out: dict[str, Any] = {}
    for k in ("title", "date", "event_type", "score", "source", "link_method", "news_id", "event_id"):
        if item.get(k) is not None:
            out[k] = item[k]
    if not out and item.get("headline"):
        out["title"] = item.get("headline")
    return out or None


def _compact_news_list(items: list[Any] | None, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in items or []:
        row = _compact_news_item(raw)
        if row:
            out.append(row)
        if len(out) >= limit:
            break
    return out


def _slim_profit(profit: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(profit, dict):
        return {}
    keep = ("available", "score", "yoy_pct", "forecast_type", "material", "note", "gap_score")
    return {k: profit[k] for k in keep if k in profit}


def _slim_quant(quant: dict[str, Any] | None, *, detail: str = "minimal") -> dict[str, Any]:
    if not isinstance(quant, dict):
        return {}
    if detail == "full":
        return dict(quant)
    keys = ("leader_score", "ml_prediction", "score", "close", "factors", "ml_z", "mr_z", "agreement")
    if detail == "score_only":
        keys = ("leader_score", "ml_prediction", "score", "close")
    return {k: quant[k] for k in keys if k in quant}


def _slim_news_event_context(nd: dict[str, Any] | None, limit: int = 4) -> dict[str, Any] | None:
    if not isinstance(nd, dict) or not nd:
        return None
    out: dict[str, Any] = {}
    for k in ("price_in_risk", "price_reaction", "net_event_score", "trigger", "candidate_sources"):
        if nd.get(k) is not None:
            out[k] = nd[k]
    events = nd.get("events") or nd.get("news_candidates")
    if events:
        compact = []
        for ev in events[:limit]:
            if not isinstance(ev, dict):
                continue
            compact.append(
                {
                    k: ev.get(k)
                    for k in ("symbol", "event_type", "score", "title", "news_id", "reject_reason")
                    if ev.get(k) is not None
                }
            )
        if compact:
            out["events"] = compact
    return out or None


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
            "event_clusters": (news.get("event_clusters") or [])[:12],
            "role_view": news_view if role_id else None,
            "last_7d": (news.get("last_7d") or news_view.get("news") if isinstance(news_view, dict) else None) or [],
            "compact_news_package": news.get("compact_news_package"),
            "news_intelligence_score": (news.get("compact_news_package") or {}).get("news_intelligence_score"),
            "evidence_direction": (news.get("compact_news_package") or {}).get("evidence_direction"),
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
            "candidate_score is cross-sectional rank — NOT probability or expected return",
        ],
    }


def build_role_context(
    snapshot: dict[str, Any],
    role_id: str,
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Role-specific slim Research Intelligence Package for council LLM calls.
    Preserves evidence_ids and data_availability; drops cross-role noise.
    """
    cc = _compression_cfg(cfg)
    if not cc.get("enabled", True):
        return build_research_intelligence(snapshot, role_id=role_id)

    full = build_research_intelligence(snapshot, role_id=role_id)
    max_news = int(cc["max_news_headlines"])
    max_tl = int(cc["max_timeline_events"])
    max_hy = int(cc["max_hypotheses"])

    base = {
        "symbol": full.get("symbol"),
        "name": full.get("name"),
        "candidate_sources": full.get("candidate_sources"),
        "data_availability": full.get("data_availability"),
        "evidence_ids": full.get("evidence_ids"),
        "rules": full.get("rules"),
        "price_in_risk": full.get("price_in_risk"),
    }
    news_ctx = dict(full.get("news_context") or {})
    hyps = list(full.get("research_hypotheses") or [])[:max_hy]

    if role_id == "quant":
        base.update(
            {
                "quant_context": _slim_quant(full.get("quant_context"), detail="full"),
                "factor_context": full.get("factor_context") or {},
                "risk_context": full.get("risk_context"),
                "news_context": {
                    "counts": news_ctx.get("counts"),
                    "net_event_score": news_ctx.get("net_event_score"),
                },
            }
        )
        return base

    if role_id == "fundamental":
        base.update(
            {
                "quant_context": _slim_quant(full.get("quant_context"), detail="score_only"),
                "profit_context": _slim_profit(full.get("profit_context")),
                "research_hypotheses": hyps[:4],
                "news_context": {
                    "counts": news_ctx.get("counts"),
                    "timeline": _compact_news_list(news_ctx.get("timeline"), max_tl),
                    "role_view": news_ctx.get("role_view"),
                },
                "risk_context": {"market_regime": (full.get("risk_context") or {}).get("market_regime")},
            }
        )
        return base

    if role_id == "event":
        last_7d = news_ctx.get("last_7d")
        if isinstance(news_ctx.get("role_view"), dict):
            last_7d = news_ctx["role_view"].get("news") or last_7d
        compact = news_ctx.get("compact_news_package") or full.get("news_context", {}).get("compact_news_package")
        base.update(
            {
                "quant_context": _slim_quant(full.get("quant_context"), detail="score_only"),
                "event_context": full.get("event_context") or {},
                "research_hypotheses": hyps,
                "news_context": {
                    "counts": news_ctx.get("counts"),
                    "net_event_score": news_ctx.get("net_event_score"),
                    "conflicts": (news_ctx.get("conflicts") or [])[:6],
                    "timeline": _compact_news_list(news_ctx.get("timeline"), max_tl),
                    "event_clusters": (news_ctx.get("event_clusters") or [])[:max_tl],
                    "compact_news_package": compact,
                    "last_7d": _compact_news_list(last_7d if isinstance(last_7d, list) else None, max(2, max_news // 2)),
                },
                "news_event_context": _slim_news_event_context(full.get("news_event_context")),
                "price_reaction": full.get("price_reaction"),
            }
        )
        return base

    if role_id == "valuation":
        base.update(
            {
                "quant_context": _slim_quant(full.get("quant_context"), detail="score_only"),
                "profit_context": _slim_profit(full.get("profit_context")),
            }
        )
        return base

    if role_id == "bear":
        base.update(
            {
                "quant_context": _slim_quant(full.get("quant_context"), detail="score_only"),
                "risk_context": full.get("risk_context"),
                "price_reaction": full.get("price_reaction"),
                "research_hypotheses": hyps[:4],
                "news_context": {
                    "counts": news_ctx.get("counts"),
                    "net_event_score": news_ctx.get("net_event_score"),
                    "conflicts": (news_ctx.get("conflicts") or [])[:8],
                    "timeline": _compact_news_list(news_ctx.get("timeline"), max_tl),
                },
            }
        )
        return base

    # unknown role — return full package capped
    full["research_hypotheses"] = hyps
    nc = dict(full.get("news_context") or {})
    nc["timeline"] = _compact_news_list(nc.get("timeline"), max_tl)
    nc["last_7d"] = _compact_news_list(nc.get("last_7d") if isinstance(nc.get("last_7d"), list) else None, max_news)
    full["news_context"] = nc
    return full


def build_chairman_context(
    snapshot: dict[str, Any],
    opinions: dict[str, Any],
    debate: list[dict[str, Any]],
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Slim chairman payload: opinions carry role scores; avoid duplicate fat quant/news."""
    cc = _compression_cfg(cfg)
    intel = snapshot.get("research_intelligence") or build_research_intelligence(snapshot)
    if not cc.get("enabled", True):
        return {
            "research_intelligence": {
                "candidate_sources": intel.get("candidate_sources"),
                "research_hypotheses": intel.get("research_hypotheses"),
                "data_availability": intel.get("data_availability"),
                "price_in_risk": intel.get("price_in_risk"),
                "evidence_ids": intel.get("evidence_ids"),
                "rules": intel.get("rules"),
                "quant_context": intel.get("quant_context"),
            },
            "snapshot_quant": snapshot.get("quant"),
            "opinions": opinions,
            "debate": debate,
            "missing_roles": [k for k, v in opinions.items() if v.get("status") in {"failed", "unavailable"}],
        }

    slim_opinions = {}
    for rid, op in opinions.items():
        if not isinstance(op, dict):
            continue
        slim_opinions[rid] = {
            k: op.get(k)
            for k in ("role", "score", "stance", "points", "top_risks", "facts", "status", "source", "falsify")
            if op.get(k) is not None
        }

    return {
        "role_reports": slim_opinions,
        "evidence_ids": intel.get("evidence_ids") or [],
        "candidate_sources": intel.get("candidate_sources"),
        "price_in_risk": intel.get("price_in_risk"),
        "rules": intel.get("rules"),
        "missing_roles": [k for k, v in opinions.items() if v.get("status") in {"failed", "unavailable"}],
        "debate": debate,
    }


def slim_roundtable_candidate(candidate: dict[str, Any], role_id: str, *, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Per-role candidate row for roundtable LLM payloads."""
    cc = _compression_cfg(cfg)
    sym = candidate.get("symbol")
    name = candidate.get("name") or ""
    quant = dict(candidate.get("quant") or {})
    if not cc.get("enabled", True):
        return candidate

    pkg = candidate.get("news_package") or {}
    headlines = _compact_news_list(candidate.get("news") or pkg.get("legacy_headlines"), int(cc["max_news_headlines"]))
    slim_pkg = {
        "news_data_incomplete": pkg.get("news_data_incomplete"),
        "net_event_score": pkg.get("net_event_score"),
        "counts": pkg.get("counts"),
        "timeline": _compact_news_list(pkg.get("timeline"), int(cc["max_timeline_events"])),
    }

    base = {"symbol": sym, "name": name, "thesis": candidate.get("thesis")}

    if role_id == "dragon":
        base.update(
            {
                "quant": {k: quant.get(k) for k in ("score", "factors_z", "why", "close") if quant.get(k) is not None},
                "board_count": candidate.get("board_count"),
                "sources": candidate.get("sources"),
                "kline": candidate.get("kline"),
                "news": headlines[:3],
            }
        )
        return base

    if role_id == "event":
        base.update(
            {
                "profit_gap_score": candidate.get("profit_gap_score"),
                "event_score": candidate.get("event_score"),
                "event_tags": candidate.get("event_tags"),
                "yoy_pct": candidate.get("yoy_pct"),
                "forecast_type": candidate.get("forecast_type"),
                "news_package": slim_pkg,
                "news": headlines,
            }
        )
        return base

    if role_id == "risk":
        kline = candidate.get("kline") or {}
        base.update(
            {
                "quant": {k: quant.get(k) for k in ("score", "close") if quant.get(k) is not None},
                "board_count": candidate.get("board_count"),
                "kline": {
                    k: kline.get(k)
                    for k in ("last_close", "ret_1d_pct", "ret_5d_pct", "from_20d_high_pct", "gap_ma60_pct", "recent_bars")
                    if kline.get(k) is not None
                },
                "news": headlines,
            }
        )
        return base

    # chair / default
    base.update(
        {
            "quant": quant,
            "board_count": candidate.get("board_count"),
            "profit_gap_score": candidate.get("profit_gap_score"),
            "event_score": candidate.get("event_score"),
            "sources": candidate.get("sources"),
            "kline": candidate.get("kline"),
            "news_package": slim_pkg,
            "news": headlines,
        }
    )
    return base

