"""Canonical trading decision — Platform Council is the sole trading SSOT."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ashare.symbols import to_symbol

DECISION_SOURCE_PLATFORM = "platform_council"
DECISION_SOURCE_ROUNDTABLE = "roundtable_benchmark"
DECISION_SOURCE_NONE = "none"
DECISION_VERSION = "canonical_v2"


def _versions_from_report(rep: dict[str, Any]) -> dict[str, str]:
    vers = dict(rep.get("versions") or {})
    news_snap = rep.get("news_snapshot") or {}
    news_pkg = rep.get("news_package") or {}
    pkg_vers = news_pkg.get("versions") or {}
    chair = rep.get("chairman") or {}
    return {
        "factor_version": str(vers.get("factor_version") or "factor_v1"),
        "news_version": str(
            news_snap.get("news_data_version")
            or pkg_vers.get("news_data_version")
            or pkg_vers.get("provider_version")
            or "news_v1"
        ),
        "model_version": str(vers.get("model_bundle") or "models_v1"),
        "prompt_version": str(chair.get("prompt_version") or vers.get("prompt_bundle") or "prompts_v1"),
    }


def _risk_from_eval(ev: dict[str, Any] | None, allow: bool, reason: str) -> tuple[str, list[str]]:
    if ev:
        status = str(ev.get("status") or "UNKNOWN").upper()
        reasons = list(ev.get("reasons") or [])
        if not reasons and reason and reason != "ok":
            reasons = [reason]
        return status, reasons
    if allow:
        return "PASS", []
    flags = [reason] if reason and reason != "ok" else ["risk_blocked"]
    return "BLOCK", flags


def build_decision_explanation(
    *,
    rating: str,
    action: str,
    approve: bool,
    gate_passed: bool,
    risk_status: str,
    risk_flags: list[str],
    chairman: dict[str, Any],
    missing_data: list[str],
    entry_setup: str,
) -> dict[str, Any]:
    positive: list[str] = []
    negative: list[str] = []
    rejected_by: list[str] = []
    if rating in {"BUY", "STRONG_BUY"}:
        positive.append(f"research_rating={rating}")
    if action == "SMALL_POSITION":
        positive.append("entry_setup_ready")
    if chairman.get("bull_case"):
        positive.append(str(chairman.get("bull_case"))[:120])
    for r in chairman.get("risks") or []:
        negative.append(str(r)[:120])
    if not gate_passed:
        rejected_by.append("ResearchGate")
    if risk_status == "BLOCK":
        rejected_by.append("RiskFilter")
        negative.extend(risk_flags)
    if risk_status == "UNKNOWN":
        rejected_by.append("RiskFilter_UNKNOWN")
    if rating in {"BUY", "STRONG_BUY"} and action != "SMALL_POSITION":
        rejected_by.append("EntrySetup")
        negative.append(f"entry_setup={entry_setup or 'CONFIRMATION_REQUIRED'}")
    if approve:
        final_reason = "COMMITTEE_APPROVED"
    elif not gate_passed:
        final_reason = "GATE_REJECT" if rating is not None else f"GATE_SKIP_{entry_setup or 'SKIPPED'}"
    elif risk_status == "BLOCK":
        final_reason = risk_flags[0] if risk_flags else "RISK_BLOCK"
    elif risk_status == "UNKNOWN":
        final_reason = "RISK_UNKNOWN"
    elif rating is None:
        final_reason = "GATE_SKIP"
    elif rating not in {"BUY", "STRONG_BUY"}:
        final_reason = f"NO_BUY_RATING_{rating}"
    elif action != "SMALL_POSITION":
        final_reason = f"NO_VALID_ENTRY_SETUP_{entry_setup or action}"
    else:
        final_reason = "NO_BUY"
    return {
        "positive_factors": positive[:12],
        "negative_factors": negative[:12],
        "missing_data": missing_data[:12],
        "risk_factors": list(risk_flags)[:12],
        "market_state": [str(chairman.get("market_state") or "UNKNOWN")],
        "entry_setup": [entry_setup or action],
        "rejected_by": rejected_by,
        "final_reason": final_reason,
    }


def build_canonical_decision(
    rep: dict[str, Any],
    *,
    as_of: str,
    universe_row: dict[str, Any] | None,
    bar_like: dict[str, Any] | None,
    risk_allow_fn,
    decision_source: str = DECISION_SOURCE_PLATFORM,
    risk_evaluate_fn=None,
) -> dict[str, Any]:
    """Build one Canonical Decision from a platform council report."""
    sym = to_symbol(rep["symbol"])
    decision = dict(rep.get("decision") or {})
    chairman = dict(rep.get("chairman") or {})
    decision_status = str(decision.get("decision_status") or "").upper()
    skip_reason = str(decision.get("skip_reason") or (rep.get("gate") or {}).get("reason") or "")
    raw_rating = decision.get("research_rating")
    if decision_status == "SKIPPED" or raw_rating in {"GATE_SKIP", "SKIP"}:
        decision_status = "SKIPPED"
        rating = None
        action = None
        entry_setup = "SKIPPED"
    else:
        decision_status = decision_status or "COMPLETED"
        rating = str(raw_rating or chairman.get("rating") or "WATCH").upper()
        action = str(decision.get("action") or chairman.get("trading_action") or "WATCH").upper()
        entry_setup = str(chairman.get("entry_setup") or decision.get("entry_setup") or "").upper()
        if not entry_setup:
            if action == "SMALL_POSITION":
                entry_setup = "READY"
            elif action == "WAIT_FOR_CONFIRMATION":
                entry_setup = "CONFIRMATION_REQUIRED"
            elif action in {"NO_ACTION", "AVOID"}:
                entry_setup = "NO_SETUP"
            else:
                entry_setup = "WATCH"

    conflict = dict(rep.get("news_conflict") or {})
    if rating and float(conflict.get("conflict_score") or 0) >= 0.65 and str(conflict.get("reason") or "") in {
        "news_weak_quant_strong",
        "news_negative_price_strong",
    }:
        if rating in {"BUY", "STRONG_BUY"}:
            rating = "WATCH"
        if action in {"SMALL_POSITION", "BUY"}:
            action = "WAIT_FOR_CONFIRMATION"
            entry_setup = "CONFIRMATION_REQUIRED"

    gate = dict(rep.get("gate") or {})
    if decision_status == "SKIPPED":
        gate_passed = False
    else:
        gate_passed = bool(gate.get("passed", True)) and rating not in {"GATE_SKIP", "SKIP", None}

    allow, risk_reason = (True, "ok")
    risk_ev: dict[str, Any] | None = None
    if bar_like is not None and gate_passed:
        if risk_evaluate_fn is not None:
            risk_ev = risk_evaluate_fn(bar_like)
            allow = bool(risk_ev.get("allow"))
            risk_reason = str(risk_ev.get("reason") or "ok")
        else:
            allow, risk_reason = risk_allow_fn(bar_like)

    # Fence: only platform_council may approve trades; quant_routing_skip cannot.
    chair_source = str(chairman.get("source") or chairman.get("chairman_source") or "")
    routing_skip = chair_source.lower() in {"quant_routing_skip", "leader_scan", "research_gate", "skipped"}
    if routing_skip and action == "SMALL_POSITION":
        action = "WAIT_FOR_CONFIRMATION"
        entry_setup = "CONFIRMATION_REQUIRED"

    approve = (
        decision_status != "SKIPPED"
        and gate_passed
        and allow
        and action == "SMALL_POSITION"
        and rating in {"BUY", "STRONG_BUY"}
        and decision_source == DECISION_SOURCE_PLATFORM
        and not routing_skip
    )
    risk_status, risk_flags = _risk_from_eval(risk_ev, allow, risk_reason)
    if decision_status == "SKIPPED" or not gate_passed:
        risk_status = "SKIPPED"
        risk_flags = [skip_reason or str(gate.get("reason") or "GATE_REJECT")]

    uni = universe_row or {}
    timing_action = str(uni.get("trade_timing_action") or "").upper()
    timing_ready = timing_action == "BUY_READY" and gate_passed and allow
    versions = _versions_from_report(rep)
    if decision_status == "SKIPPED":
        verdict = "skip"
    else:
        verdict = "buy" if approve else ("watch" if rating in {"BUY", "WATCH", "STRONG_BUY"} else "pass")

    missing_data: list[str] = []
    for k in ("ml_prediction", "profit_score", "event_score", "news_score"):
        st = uni.get(f"{k}_status") or (rep.get("quant") or {}).get(f"{k}_status")
        if st in {"MISSING", "UNAVAILABLE", "FAILED"} or uni.get(f"{k}_available") is False:
            missing_data.append(k)
    if not (rep.get("snapshot") or {}).get("value_available", rep.get("value_available", True)):
        missing_data.append("valuation")

    created_at = datetime.now(timezone.utc).isoformat()
    decision_id = f"D{as_of.replace('-', '')}{uuid4().hex[:8].upper()}"
    context_id = str(rep.get("research_id") or decision_id)
    explanation = build_decision_explanation(
        rating=rating,
        action=action,
        approve=approve,
        gate_passed=gate_passed,
        risk_status=risk_status,
        risk_flags=risk_flags,
        chairman=chairman,
        missing_data=missing_data,
        entry_setup=entry_setup,
    )
    final_action = "BUY" if approve else "NO_ACTION"

    return {
        "symbol": sym,
        "name": rep.get("name"),
        "as_of": as_of,
        "research_date": as_of,
        "decision_id": decision_id,
        "context_id": context_id,
        "created_at": created_at,
        "decision_version": DECISION_VERSION,
        "decision_status": decision_status,
        "skip_reason": skip_reason or None,
        "research_rating": rating,
        "rating_confidence": chairman.get("confidence"),
        "trading_action": action,
        "entry_setup": entry_setup,
        "market_state": chairman.get("market_state") or "UNKNOWN",
        "reconciliation_state": (rep.get("market_state_context_meta") or {}).get("reconciliation_state"),
        "committee_approve": approve,
        "committee_verdict": verdict,
        "committee_reasons": [explanation["final_reason"]],
        "risk_status": risk_status,
        "risk_flags": risk_flags,
        "risk_reasons": risk_flags,
        "final_action": final_action,
        "confidence": chairman.get("confidence"),
        "decision_source": decision_source,
        "research_session_id": rep.get("research_id"),
        "snapshot_id": rep.get("snapshot_id") or rep.get("research_id"),
        "research_snapshot_id": rep.get("snapshot_id") or rep.get("research_id"),
        "production_run_id": rep.get("production_run_id"),
        "council_decision_id": rep.get("research_id"),
        "risk_decision_id": f"RISK-{decision_id}",
        "committee_decision_id": decision_id,
        "chairman_source": chairman.get("chairman_source") or chairman.get("source"),
        "fallback_reason": chairman.get("fallback_reason"),
        "candidate_score": uni.get("candidate_score") or (rep.get("quant") or {}).get("factor_score"),
        "candidate_sources": list(rep.get("candidate_sources") or uni.get("candidate_sources") or []),
        "factor_version": versions["factor_version"],
        "news_version": versions["news_version"],
        "model_version": versions["model_version"],
        "prompt_version": versions["prompt_version"],
        "committee_thesis": chairman.get("base_case"),
        "committee_risks": ",".join(chairman.get("risks") or []),
        "committee_horizon": chairman.get("time_horizon"),
        "ai_approve": approve,
        "ai_confidence": chairman.get("confidence"),
        "research_id": rep.get("research_id"),
        "gate_passed": gate_passed,
        "weight": 0.0,
        "explanation": explanation,
        "no_buy_reason": None if approve else explanation["final_reason"],
        "leader_timing": {
            "lifecycle": uni.get("lifecycle"),
            "stage": uni.get("stage"),
            "chase_score": uni.get("chase_score"),
            "chase_level": uni.get("chase_level"),
            "trade_timing_score": uni.get("trade_timing_score"),
            "trade_timing_action": timing_action or None,
            "leader_score": uni.get("leader_score"),
            "board_count": uni.get("board_count"),
            "timing_buy_ready": timing_ready,
            "council_approve": approve,
        },
    }


def build_canonical_decisions(
    platform_reports: list[dict[str, Any]],
    *,
    as_of: str,
    universe_by_sym: dict[str, dict[str, Any]],
    bars_by_sym: dict[str, Any],
    risk_engine,
    decision_source: str = DECISION_SOURCE_PLATFORM,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    evaluate = getattr(risk_engine, "evaluate", None)
    for rep in platform_reports:
        sym = to_symbol(rep.get("symbol") or "")
        if not sym:
            continue
        bar = bars_by_sym.get(sym)
        bar_like = None
        if bar is not None:
            bar_like = {
                "is_st": getattr(bar, "is_st", False),
                "is_halt": getattr(bar, "is_halt", False),
                "limit_up": getattr(bar, "limit_up", False),
                "amount": getattr(bar, "amount", 0),
            }

        def _allow(bl: dict[str, Any]) -> tuple[bool, str]:
            return risk_engine.allow_open(bl)

        out.append(
            build_canonical_decision(
                rep,
                as_of=as_of,
                universe_row=universe_by_sym.get(sym),
                bar_like=bar_like,
                risk_allow_fn=_allow,
                decision_source=decision_source,
                risk_evaluate_fn=evaluate,
            )
        )
    # Prefer newest decision_id per symbol (created_at desc) — never let stale BUY overwrite WAIT
    by_sym: dict[str, dict[str, Any]] = {}
    for d in out:
        prev = by_sym.get(d["symbol"])
        if prev is None or str(d.get("created_at") or "") >= str(prev.get("created_at") or ""):
            by_sym[d["symbol"]] = d
    return list(by_sym.values())


def canonical_to_picks(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Backward-compatible picks list derived only from canonical decisions."""
    picks: list[dict[str, Any]] = []
    for d in decisions:
        picks.append(
            {
                "symbol": d["symbol"],
                "name": d.get("name"),
                "committee_verdict": d.get("committee_verdict"),
                "committee_approve": d.get("committee_approve"),
                "ai_approve": d.get("ai_approve"),
                "ai_confidence": d.get("confidence"),
                "committee_thesis": d.get("committee_thesis"),
                "committee_risks": d.get("committee_risks"),
                "committee_horizon": d.get("committee_horizon"),
                "research_rating": d.get("research_rating"),
                "trading_action": d.get("trading_action"),
                "entry_setup": d.get("entry_setup"),
                "final_action": d.get("final_action"),
                "research_id": d.get("research_session_id"),
                "decision_id": d.get("decision_id"),
                "reason": d.get("decision_source"),
                "decision_source": d.get("decision_source"),
                "candidate_sources": d.get("candidate_sources") or [],
                "candidate_score": d.get("candidate_score"),
                "risk_status": d.get("risk_status"),
                "risk_flags": d.get("risk_flags"),
                "no_buy_reason": d.get("no_buy_reason"),
                "explanation": d.get("explanation"),
                "weight": float(d.get("weight") or 0.0),
            }
        )
    return picks


def apply_portfolio_weights(decisions: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    from ashare.portfolio import PortfolioEngine

    approved = [d for d in decisions if d.get("committee_approve")]
    if not approved:
        return decisions
    port = PortfolioEngine(cfg)
    weighted = port.suggest_weights(
        [{**d, "leader_score": 0.5 if d.get("committee_approve") else 0.0} for d in decisions]
    )
    wmap = {w["symbol"]: w.get("target_weight", 0) for w in weighted}
    for d in decisions:
        d["weight"] = float(wmap.get(d["symbol"]) or 0.0) if d.get("committee_approve") else 0.0
    return decisions


def extract_trading_decisions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Decisions approved for paper trading — canonical only."""
    canonical = list(payload.get("canonical_decisions") or [])
    if canonical:
        return [
            d
            for d in canonical
            if d.get("committee_approve")
            and str(d.get("decision_source") or "") == DECISION_SOURCE_PLATFORM
            and str(d.get("final_action") or "").upper() in {"BUY", ""}
        ]
    # Legacy payloads without canonical_decisions: only trust platform-tagged picks
    picks = list(payload.get("picks") or [])
    return [
        p
        for p in picks
        if (p.get("committee_approve") or str(p.get("committee_verdict") or "").lower() == "buy")
        and str(p.get("decision_source") or p.get("reason") or "") != DECISION_SOURCE_ROUNDTABLE
    ]


def validate_decision_consistency(payload: dict[str, Any]) -> list[str]:
    """
    Verify Research display picks match canonical decisions and roundtable cannot drive trading.
    Returns human-readable inconsistency messages (empty = OK).
    """
    errors: list[str] = []
    canonical = list(payload.get("canonical_decisions") or [])
    picks = list(payload.get("picks") or [])

    if not canonical:
        rt_buys = {
            to_symbol(r["symbol"])
            for r in (payload.get("roundtable") or {}).get("reviews") or []
            if r.get("committee_approve") or str(r.get("committee_verdict") or "").lower() == "buy"
        }
        pick_buys = {
            to_symbol(p["symbol"])
            for p in picks
            if p.get("committee_approve") or str(p.get("committee_verdict") or "").lower() == "buy"
        }
        if rt_buys and pick_buys & rt_buys and not payload.get("decision_chain"):
            errors.append("roundtable buy overlaps picks without canonical_decisions")
        return errors

    canon_by_sym = {to_symbol(d["symbol"]): d for d in canonical}
    pick_by_sym = {to_symbol(p["symbol"]): p for p in picks}

    if set(canon_by_sym) != set(pick_by_sym):
        errors.append(
            f"picks symbols {sorted(pick_by_sym)} != canonical {sorted(canon_by_sym)}"
        )

    for sym, cd in canon_by_sym.items():
        pk = pick_by_sym.get(sym)
        if not pk:
            continue
        for field in ("committee_approve", "committee_verdict", "research_rating", "trading_action", "decision_source"):
            cv = cd.get(field)
            pv = pk.get(field)
            if field == "decision_source" and pv in (None, "") and pk.get("reason"):
                pv = pk.get("reason")
            if cv != pv:
                errors.append(f"{sym}.{field}: picks={pv!r} canonical={cv!r}")

    rt = payload.get("roundtable") or {}
    rt_buys = {
        to_symbol(r["symbol"])
        for r in rt.get("reviews") or []
        if r.get("committee_approve") or str(r.get("committee_verdict") or "").lower() == "buy"
    }
    canon_buys = {sym for sym, d in canon_by_sym.items() if d.get("committee_approve")}
    roundtable_only_buys = rt_buys - canon_buys
    if roundtable_only_buys and payload.get("decision_chain", {}).get("roundtable_controls_trading"):
        errors.append(f"roundtable-only buys would trade: {sorted(roundtable_only_buys)}")

    trading = extract_trading_decisions(payload)
    trading_syms = {to_symbol(t["symbol"]) for t in trading}
    if trading_syms != canon_buys:
        errors.append(f"trading syms {sorted(trading_syms)} != canonical buys {sorted(canon_buys)}")

    return errors
