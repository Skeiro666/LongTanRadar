from __future__ import annotations

from typing import Any

from ashare.research.historical_cohort import build_historical_cohort
from ashare.research.news_alpha import news_alpha_bucket
from ashare.research.snapshot import SnapshotStore
from ashare.services.research import latest_research


def _discovery_source(sources: list[str] | None) -> str:
    srcs = {str(s).lower() for s in (sources or []) if s}
    has_news = "news" in srcs
    has_quant = bool(srcs & {"quant", "event", "profit", "ml"})
    if has_news and has_quant:
        return "量化+新闻"
    if has_news:
        return "新闻"
    if "event" in srcs:
        return "事件"
    if "ml" in srcs:
        return "机器学习"
    if "quant" in srcs or "profit" in srcs:
        return "量化"
    return "未知"


def _news_discovery_labels(candidate: dict[str, Any], quant_top_n: set[str]) -> list[str]:
    sym = str(candidate.get("symbol") or "")
    srcs = {str(s).lower() for s in (candidate.get("candidate_sources") or [])}
    labels: list[str] = []
    if "news" in srcs:
        labels.append("新闻发现")
        if sym in quant_top_n or candidate.get("quant_top_n_at_signal"):
            labels.append("量化确认")
        else:
            labels.append("纯新闻")
    return labels


def _quadrant(candidate: dict[str, Any], *, news_thr: float = 0.12, quant_thr: float = 0.15) -> str:
    ns = float(candidate.get("news_score") or 0)
    qs = float(candidate.get("leader_score") or candidate.get("candidate_score") or 0)
    nk = "strong" if ns >= news_thr else "weak"
    qk = "strong" if qs >= quant_thr else "weak"
    return f"news_{nk}_quant_{qk}"


def _signal_contribution(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    leader = float(candidate.get("leader_score") or 0)
    profit = float((candidate.get("profit_inflection") or {}).get("score") or 0)
    event = float(candidate.get("event_score") or 0)
    news = abs(float(candidate.get("news_score") or 0))
    ml = abs(float(candidate.get("ml_prediction") or candidate.get("ml_rank_score") or 0))
    council = float((candidate.get("chairman") or {}).get("confidence") or 0) / 100.0 if isinstance(
        (candidate.get("chairman") or {}).get("confidence"), (int, float)
    ) and (candidate.get("chairman") or {}).get("confidence", 0) > 1 else float(
        (candidate.get("chairman") or {}).get("confidence") or 0
    )
    parts = [
        ("龙头", leader),
        ("利润", profit),
        ("事件", event),
        ("新闻", news),
        ("机器学习", ml),
        ("投委会", council),
    ]
    total = sum(v for _, v in parts) or 1.0
    return [
        {"name": n, "score": round(v, 4), "relative_contribution": round(v / total, 4)}
        for n, v in parts
    ]


def _top_reasons(candidate: dict[str, Any], limit: int = 3) -> list[str]:
    reasons: list[tuple[float, str]] = []
    thesis = str(candidate.get("thesis") or "").strip()
    if thesis:
        reasons.append((0.9, thesis[:120]))
    board = int(candidate.get("board_count") or 0)
    if board > 0:
        reasons.append((0.85, f"连板 {board} 天（事件/情绪驱动，需防回撤）"))
    tags = [str(t) for t in (candidate.get("event_tags") or []) if t][:3]
    if tags:
        reasons.append((0.8, "事件标签：" + "、".join(tags)))
    pi = candidate.get("profit_inflection") or {}
    if pi.get("reason") and pi.get("available"):
        reasons.append((float(pi.get("score") or 0.5), str(pi["reason"])[:100]))
    tr = candidate.get("trigger") or {}
    if tr.get("reason"):
        reasons.append((float(tr.get("score") or 0.5), str(tr["reason"])[:80]))
    nd = candidate.get("news_discovery") or {}
    intel = candidate.get("news_intelligence") or nd.get("news_intelligence") or {}
    if intel.get("importance"):
        reasons.append((float(intel["importance"]), f"新闻重要性 +{float(intel['importance']):.2f}"))
    if intel.get("novelty"):
        reasons.append((float(intel["novelty"]), f"新闻新颖度 +{float(intel['novelty']):.2f}"))
    if nd.get("reason"):
        reasons.append((float(nd.get("news_score") or nd.get("event_impact") or 0.5), str(nd["reason"])[:80]))
    reasons.sort(key=lambda x: x[0], reverse=True)
    return [r[1] for r in reasons[:limit]]


def _research_priority(candidate: dict[str, Any]) -> dict[str, Any]:
    score = float(candidate.get("candidate_score") or 0)
    conflict = float((candidate.get("news_conflict") or {}).get("conflict_score") or candidate.get("conflict_score") or 0)
    intel = float(candidate.get("news_intelligence_score") or 0)
    rating = str((candidate.get("decision") or {}).get("research_rating") or candidate.get("rating") or "")
    reasons: list[str] = []
    if rating in {"BUY", "STRONG_BUY"}:
        reasons.append("主席买入")
    if intel >= 0.7:
        reasons.append("新闻智能分高")
    if conflict >= 0.55:
        reasons.append("新闻/量化冲突")
    if score >= 0.35:
        reasons.append("候选分高")
    level = "低"
    if rating in {"STRONG_BUY", "BUY"} or score >= 0.4 or intel >= 0.75:
        level = "高"
    elif score >= 0.22 or intel >= 0.5 or conflict >= 0.4:
        level = "中"
    return {"level": level, "reasons": reasons[:4] or ["常规研究池"]}


def _news_card(candidate: dict[str, Any]) -> dict[str, Any] | None:
    pkg = candidate.get("news_package") or {}
    compact = pkg.get("compact_news_package") or candidate.get("compact_news") or {}
    intel = candidate.get("news_intelligence") or {}
    if not intel and pkg.get("news_intelligence"):
        rows = pkg.get("news_intelligence") or []
        intel = rows[0] if rows else {}
    nd = candidate.get("news_discovery") or {}
    if not intel:
        intel = nd.get("news_intelligence") or {}
    if not intel and not compact and not nd:
        return None
    media = ""
    last = (pkg.get("last_7d") or [])[:1]
    if last and isinstance(last[0], dict):
        media = str(last[0].get("media") or last[0].get("source") or "")
    return {
        "event_type": intel.get("event_type") or compact.get("evidence_direction") or nd.get("event_type"),
        "direction": intel.get("direction") or compact.get("evidence_direction") or nd.get("evidence_direction"),
        "importance": intel.get("importance"),
        "novelty": intel.get("novelty"),
        "market_relevance": intel.get("market_relevance"),
        "impact_horizon": intel.get("impact_horizon"),
        "event_confidence": intel.get("event_confidence"),
        "summary": intel.get("summary") or nd.get("reason"),
        "source_quality": nd.get("source_quality") or intel.get("source_quality") or "C",
        "media": media,
        "published_at": nd.get("published_at") or intel.get("published_at"),
        "news_intelligence_score": intel.get("news_intelligence_score") or candidate.get("news_intelligence_score"),
        "compact": compact,
    }


def _conflict_detail(candidate: dict[str, Any]) -> dict[str, Any]:
    c = candidate.get("news_conflict") or {}
    if not c:
        return {"news_conflict": False, "conflict_score": 0}
    reason = str(c.get("reason") or "")
    display = None
    if c.get("news_conflict"):
        if reason == "news_weak_quant_strong":
            display = "弱新闻强量化（纯事件/因子驱动，缺新闻确认）"
        else:
            display = "新闻/量化冲突"
    return {
        **c,
        "display": display,
        "reason_labels": [
            lbl
            for lbl, flag in (
                ("相对强弱偏弱", (c.get("signals") or {}).get("rs_weak")),
                ("动量偏弱", (c.get("signals") or {}).get("momentum_weak")),
                ("量能偏弱", (c.get("signals") or {}).get("volume_weak")),
                ("价格偏强", (c.get("signals") or {}).get("price_strong")),
            )
            if flag
        ],
    }


def _council_summary(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not report:
        return []
    council = report.get("council") or {}
    out = []
    role_names = {
        "fundamental": "基本面",
        "quant": "量化",
        "event": "事件",
        "valuation": "估值",
        "bear": "空方",
    }
    for rid in ("fundamental", "quant", "event", "valuation", "bear", "chair"):
        if rid == "chair":
            ch = report.get("chairman") or {}
            out.append(
                {
                    "role": "主席",
                    "stance": ch.get("rating") or ch.get("stance") or "NEUTRAL",
                    "confidence": ch.get("confidence"),
                    "summary": (ch.get("base_case") or ch.get("summary") or "")[:160],
                    "expandable": True,
                }
            )
            continue
        row = council.get(rid) or {}
        if not row:
            continue
        out.append(
            {
                "role": role_names.get(rid, rid),
                "stance": row.get("stance") or row.get("rating") or "NEUTRAL",
                "confidence": row.get("confidence"),
                "summary": (row.get("summary") or row.get("base_case") or "")[:160],
                "expandable": True,
                "full": row,
            }
        )
    return out


def _rating_counts(reports: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"BUY": 0, "STRONG_BUY": 0, "WATCH": 0, "PASS": 0, "OTHER": 0}
    for r in reports:
        rating = str(r.get("rating") or (r.get("decision") or {}).get("research_rating") or "PASS").upper()
        if rating in counts:
            counts[rating] += 1
        elif rating in {"HOLD", "NEUTRAL"}:
            counts["WATCH"] += 1
        else:
            counts["OTHER"] += 1
    return counts


def build_candidate_card(
    candidate: dict[str, Any],
    *,
    quant_top_n: set[str],
    report: dict[str, Any] | None = None,
    outcomes: list[dict[str, Any]] | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rep = report or {}
    decision = rep.get("decision") or {}
    gate = candidate.get("gate") or rep.get("gate") or {}
    return {
        "symbol": candidate.get("symbol"),
        "name": candidate.get("name"),
        "price": candidate.get("close") or (rep.get("snapshot") or {}).get("market", {}).get("price"),
        "research_rating": rep.get("rating") or decision.get("research_rating"),
        "trading_action": rep.get("action") or decision.get("action") or "NONE",
        "risk_status": gate.get("status") or ("BLOCKED" if gate.get("blocked") else "PASS"),
        "risk_reasons": gate.get("reasons") or gate.get("reject_reasons") or [],
        "discovery_source": _discovery_source(candidate.get("candidate_sources")),
        "news_labels": _news_discovery_labels(candidate, quant_top_n),
        "news_alpha_bucket": news_alpha_bucket(
            {**candidate, "candidate_sources": candidate.get("candidate_sources") or []},
            quant_top_n,
        ),
        "quadrant": _quadrant(candidate),
        "signal_contribution": _signal_contribution({**candidate, **rep}),
        "top_reasons": _top_reasons(candidate),
        "research_priority": _research_priority({**candidate, **rep}),
        "news": _news_card(candidate),
        "conflict": _conflict_detail(candidate),
        "council_summary": _council_summary(rep),
        "research_id": rep.get("research_id"),
        "degraded": {
            "news": bool((candidate.get("news_package") or {}).get("news_data_incomplete")),
            "reason": (candidate.get("news_package") or {}).get("provider_status"),
        },
        "historical_cohort": build_historical_cohort(candidate, outcomes or [], cfg) if outcomes else None,
    }


def _enrich_report_from_snapshot(store: SnapshotStore, report: dict[str, Any]) -> dict[str, Any]:
    rid = report.get("research_id")
    if not rid:
        return report
    import json

    path = store.dir / f"{rid}.json"
    if not path.exists():
        return report
    try:
        snap = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return report
    inner = snap.get("report") or {}
    return {
        **report,
        **{k: v for k, v in inner.items() if k not in report or not report.get(k)},
        "council": snap.get("council") or report.get("council"),
        "chairman": snap.get("chairman") or report.get("chairman"),
        "decision": inner.get("decision") or report.get("decision"),
    }


def build_research_terminal(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    data = latest_research(cfg) or {}
    cfg = cfg or {}
    store = SnapshotStore(cfg)
    uni = data.get("candidate_union") or {}
    universe = list(uni.get("universe") or [])
    quant_top_n = set(data.get("quant_top_n_symbols") or uni.get("quant_top_n_symbols") or [])
    reports = {str(r.get("symbol")): r for r in (data.get("platform_reports") or [])}
    outcomes = list((data.get("research_outcomes") or {}).get("outcomes") or [])
    cards = []
    matrix: dict[str, list[str]] = {
        "news_strong_quant_strong": [],
        "news_strong_quant_weak": [],
        "news_weak_quant_strong": [],
        "news_weak_quant_weak": [],
    }
    for c in universe:
        sym = str(c.get("symbol") or "")
        rep = _enrich_report_from_snapshot(store, reports.get(sym) or {})
        card = build_candidate_card(
            c,
            quant_top_n=quant_top_n,
            report=rep,
            outcomes=outcomes,
            cfg=cfg,
        )
        cards.append(card)
        q = card.get("quadrant") or "news_weak_quant_weak"
        if q in matrix:
            matrix[q].append(sym)
    cards.sort(
        key=lambda x: (
            0 if (x.get("research_priority") or {}).get("level") == "高" else 1,
            -float((reports.get(str(x.get("symbol"))) or {}).get("candidate_score") or 0),
        )
    )
    n_with_news = sum(1 for c in universe if (c.get("news_package") or {}).get("news_ids") or c.get("news_score"))
    return {
        "as_of": data.get("as_of"),
        "generated_at": data.get("generated_at"),
        "market_status": data.get("screen", {}).get("sources"),
        "counts": {
            "candidates": len(universe),
            "council": sum(1 for c in universe if c.get("in_council")),
            "news_discovery": (data.get("news_discovery") or {}).get("n_candidates") or 0,
            "ratings": _rating_counts(list(reports.values())),
        },
        "data_completeness": {
            "news_coverage": f"{n_with_news}/{len(universe)}" if universe else "0/0",
            "pct": round(n_with_news / len(universe) * 100, 1) if universe else 0,
        },
        "quant_top_n_symbols": sorted(quant_top_n),
        "candidates": cards,
        "matrix": matrix,
        "news_discovery_status": {
            "available": (data.get("news_discovery") or {}).get("available"),
            "degraded": (data.get("news_discovery") or {}).get("news_data_incomplete"),
            "provider_status": (data.get("news_discovery") or {}).get("provider_status"),
        },
    }


def build_research_detail(
    cfg: dict[str, Any] | None,
    research_id: str,
    symbol: str,
) -> dict[str, Any]:
    cfg = cfg or {}
    store = SnapshotStore(cfg)
    snap = None
    path = store.dir / f"{research_id}.json"
    if path.exists():
        import json

        snap = json.loads(path.read_text(encoding="utf-8"))
    if not snap:
        snap = store.load_latest_for_symbol(symbol)
    data = latest_research(cfg) or {}
    uni = {str(c.get("symbol")): c for c in (data.get("candidate_union") or {}).get("universe") or []}
    candidate = uni.get(symbol) or {}
    reports = {str(r.get("symbol")): r for r in (data.get("platform_reports") or [])}
    report = reports.get(symbol) or (snap or {}).get("report") or {}
    quant_top_n = set(data.get("quant_top_n_symbols") or [])
    outcomes = list((data.get("research_outcomes") or {}).get("outcomes") or [])
    card = build_candidate_card(candidate, quant_top_n=quant_top_n, report=report, outcomes=outcomes, cfg=cfg)
    return {
        **card,
        "snapshot": snap,
        "versions": (snap or {}).get("versions") or report.get("versions"),
        "cloud_escalation": report.get("cloud_escalation") or candidate.get("cloud_escalation"),
        "chairman": report.get("chairman") or (snap or {}).get("chairman"),
        "council_full": (snap or {}).get("council") or report.get("council"),
        "debate": (snap or {}).get("debate") or report.get("debate"),
        "news_package_frozen": (snap or {}).get("news_package") or candidate.get("news_package"),
        "note": "优先展示快照数据，非今日重算。",
    }
