"""V5.4 Unified Alpha Attribution — one row per candidate with explicit availability."""

from __future__ import annotations

from typing import Any

from ashare.research.signal_attribution import (
    attribution_cfg,
    enrich_outcome_sources,
    horizon_metrics,
    resolve_primary_source,
)


def _avail_price(v: Any) -> dict[str, Any]:
    if v is None:
        return {"available": False, "value": None}
    try:
        fv = float(v)
        if fv <= 0:
            return {"available": False, "value": None}
        return {"available": True, "value": fv}
    except (TypeError, ValueError):
        return {"available": False, "value": None}


def _avail_eer(report: dict[str, Any] | None) -> dict[str, Any]:
    rep = report or {}
    hyps = list(rep.get("research_hypotheses") or [])
    for h in hyps:
        if not isinstance(h, dict):
            continue
        inv = dict(h.get("investment_hypothesis") or {})
        eer = dict(inv.get("expected_excess_return") or {})
        if eer.get("available") and eer.get("value") is not None:
            return {"available": True, "value": float(eer["value"]), "confidence": eer.get("confidence")}
    snap = dict((rep.get("snapshot") or {}).get("candidate_score_meta") or {})
    eer = dict(snap.get("expected_excess_return") or {})
    if eer.get("available") and eer.get("value") is not None:
        return {"available": True, "value": float(eer["value"]), "confidence": eer.get("confidence")}
    return {"available": False, "value": None, "confidence": None}


def _confidence(report: dict[str, Any] | None) -> dict[str, Any]:
    rep = report or {}
    raw = (rep.get("chairman") or {}).get("confidence")
    if raw is None:
        raw = (rep.get("decision") or {}).get("confidence")
    if raw is None:
        return {"available": False, "value": None}
    try:
        v = float(raw)
        if v > 1.0:
            v = v / 100.0
        return {"available": True, "value": max(0.0, min(1.0, v))}
    except (TypeError, ValueError):
        return {"available": False, "value": None}


def _horizon_block(outcome: dict[str, Any], h: int) -> dict[str, Any]:
    m = horizon_metrics(outcome, h)
    if not m:
        return {"available": False, "horizon": h}
    return {
        "available": True,
        "horizon": h,
        "return": m.get("realized_return"),
        "market_alpha": m.get("market_alpha"),
        "selection_alpha": m.get("selection_alpha"),
    }


def build_unified_record(
    report: dict[str, Any],
    outcome: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge report + outcome into Phase-1 attribution schema."""
    acfg = attribution_cfg(cfg)
    horizons = list(acfg.get("horizons_days") or [1, 5, 10, 20])
    enrich_outcome_sources(outcome, cfg)
    sym = str(outcome.get("symbol") or report.get("symbol") or "")
    rid = str(
        outcome.get("research_session_id")
        or outcome.get("research_id")
        or report.get("research_id")
        or ""
    )
    srcs = list(outcome.get("candidate_sources") or report.get("candidate_sources") or [])
    resolved = resolve_primary_source(srcs, acfg.get("primary_source_priority"))
    decision = str(
        (report.get("decision") or {}).get("research_rating")
        or (report.get("chairman") or {}).get("rating")
        or outcome.get("rating")
        or ""
    )
    exec_block = outcome.get("execution") or {}
    hz_out: dict[str, Any] = {}
    for h in horizons:
        hz_out[str(h)] = _horizon_block(outcome, h)

    routing = dict(report.get("ai_routing") or outcome.get("ai_routing") or {})
    nd = report.get("news_discovery") or {}
    pkg = report.get("news_package") or report.get("snapshot", {}).get("news_package") or {}
    intel = report.get("news_intelligence") or nd.get("news_intelligence") or {}
    quant_top = bool(report.get("quant_top_n_at_signal") or outcome.get("quant_top_n_at_signal"))

    from ashare.research.news_alpha import news_alpha_bucket

    bucket = news_alpha_bucket(
        {
            **outcome,
            "candidate_sources": srcs,
            "discovery_primary_source": resolved["primary_source"],
            "secondary_sources": resolved["secondary_sources"],
        },
        {sym} if quant_top else set(),
    )

    return {
        "candidate_id": f"{sym}:{rid}" if sym and rid else sym or rid,
        "symbol": sym,
        "as_of": report.get("research_time") or outcome.get("signal_time"),
        "research_session_id": rid,
        "snapshot_id": rid,
        "discovery_primary_source": resolved["primary_source"],
        "secondary_sources": resolved["secondary_sources"],
        "candidate_sources": srcs,
        "decision": decision,
        "confidence": _confidence(report),
        "expected_excess_return": _avail_eer(report),
        "signal_price": _avail_price(outcome.get("signal_price")),
        "notification_price": _avail_price(outcome.get("notification_price")),
        "paper_fill_price": _avail_price(outcome.get("paper_fill_price") or exec_block.get("fill_price")),
        "primary_entry_source": outcome.get("primary_entry_source"),
        "horizons": hz_out,
        "ai_routing": routing if routing else {"available": False},
        "news_role": nd.get("news_role") or pkg.get("news_role") or "none",
        "discovery_grade": nd.get("discovery_grade") or "NONE",
        "news_intelligence_score": float(
            report.get("news_intelligence_score") or intel.get("news_intelligence_score") or 0
        ),
        "evidence_direction": str(report.get("evidence_direction") or intel.get("direction") or "unknown"),
        "news_intelligence": intel if isinstance(intel, dict) else {},
        "news_alpha_bucket": bucket,
        "news_published_at": nd.get("published_at") or intel.get("published_at"),
        "quant_top_n_at_signal": quant_top,
    }


def build_unified_attribution(
    reports: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_sym = {str(r.get("symbol")): r for r in reports}
    records = []
    for o in outcomes:
        rep = by_sym.get(str(o.get("symbol"))) or {}
        records.append(build_unified_record(rep, o, cfg))
    return {"available": bool(records), "sample_count": len(records), "records": records}
