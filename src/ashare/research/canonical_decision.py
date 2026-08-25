from __future__ import annotations

from typing import Any

from ashare.symbols import to_symbol

DECISION_SOURCE_PLATFORM = "platform_council"
DECISION_SOURCE_ROUNDTABLE = "roundtable_benchmark"
DECISION_SOURCE_NONE = "none"


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


def _risk_fields(allow: bool, reason: str) -> tuple[str, list[str]]:
    if allow:
        return "pass", []
    flags = [reason] if reason and reason != "ok" else ["risk_blocked"]
    return "blocked", flags


def build_canonical_decision(
    rep: dict[str, Any],
    *,
    as_of: str,
    universe_row: dict[str, Any] | None,
    bar_like: dict[str, Any] | None,
    risk_allow_fn,
    decision_source: str = DECISION_SOURCE_PLATFORM,
) -> dict[str, Any]:
    """Build one Canonical Decision from a platform council report."""
    sym = to_symbol(rep["symbol"])
    decision = dict(rep.get("decision") or {})
    chairman = dict(rep.get("chairman") or {})
    rating = str(decision.get("research_rating") or chairman.get("rating") or "WATCH").upper()
    action = str(decision.get("action") or chairman.get("trading_action") or "WATCH").upper()
    conflict = dict(rep.get("news_conflict") or {})
    if float(conflict.get("conflict_score") or 0) >= 0.65 and str(conflict.get("reason") or "") in {
        "news_weak_quant_strong",
        "news_negative_price_strong",
    }:
        if rating in {"BUY", "STRONG_BUY"}:
            rating = "WATCH"
        if action in {"SMALL_POSITION", "BUY"}:
            action = "WAIT_FOR_CONFIRMATION"
    gate = dict(rep.get("gate") or {})
    gate_passed = bool(gate.get("passed", True)) and rating not in {"GATE_SKIP", "SKIP"}

    allow, risk_reason = (True, "ok")
    if bar_like is not None and gate_passed:
        allow, risk_reason = risk_allow_fn(bar_like)

    approve = (
        gate_passed
        and allow
        and action == "SMALL_POSITION"
        and rating in {"BUY", "STRONG_BUY"}
    )
    risk_status, risk_flags = _risk_fields(allow, risk_reason)
    if not gate_passed:
        risk_status = "skipped"
        risk_flags = [str(gate.get("reason") or "GATE_REJECT")]

    uni = universe_row or {}
    versions = _versions_from_report(rep)
    verdict = "buy" if approve else ("watch" if rating in {"BUY", "WATCH", "STRONG_BUY"} else "pass")

    return {
        "symbol": sym,
        "name": rep.get("name"),
        "as_of": as_of,
        "research_rating": rating,
        "trading_action": action,
        "committee_approve": approve,
        "committee_verdict": verdict,
        "risk_status": risk_status,
        "risk_flags": risk_flags,
        "confidence": chairman.get("confidence"),
        "decision_source": decision_source,
        "research_session_id": rep.get("research_id"),
        "snapshot_id": rep.get("research_id"),
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
            )
        )
    return out


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
                "research_id": d.get("research_session_id"),
                "reason": d.get("decision_source"),
                "decision_source": d.get("decision_source"),
                "candidate_sources": d.get("candidate_sources") or [],
                "candidate_score": d.get("candidate_score"),
                "risk_status": d.get("risk_status"),
                "risk_flags": d.get("risk_flags"),
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
        return [d for d in canonical if d.get("committee_approve")]
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
