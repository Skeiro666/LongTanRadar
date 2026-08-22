"""V5 Phase 1 — Canonical Decision chain consistency."""

from __future__ import annotations

from ashare.research.canonical_decision import (
    DECISION_SOURCE_PLATFORM,
    DECISION_SOURCE_ROUNDTABLE,
    apply_portfolio_weights,
    build_canonical_decision,
    build_canonical_decisions,
    canonical_to_picks,
    extract_trading_decisions,
    validate_decision_consistency,
)


class _RiskStub:
    def allow_open(self, bar_like: dict) -> tuple[bool, str]:
        if bar_like.get("is_st"):
            return False, "st"
        if bar_like.get("is_halt"):
            return False, "halt"
        if bar_like.get("limit_up"):
            return False, "limit_up"
        return True, "ok"


def _platform_report(
    sym: str,
    *,
    rating: str = "BUY",
    action: str = "SMALL_POSITION",
    gate_passed: bool = True,
) -> dict:
    return {
        "research_id": f"RTEST{sym[:6]}",
        "symbol": sym,
        "name": f"Name-{sym}",
        "decision": {"research_rating": rating, "action": action},
        "chairman": {
            "rating": rating,
            "trading_action": action,
            "confidence": 0.72,
            "base_case": "test thesis",
            "risks": ["macro"],
            "time_horizon": "T+5",
            "prompt_version": "chairman_v1",
        },
        "versions": {
            "factor_version": "factor_v1",
            "model_bundle": "models_v1",
            "prompt_bundle": "prompts_v1",
        },
        "gate": {"passed": gate_passed, "reason": "OK" if gate_passed else "LOW_SCORE"},
        "candidate_sources": ["quant"],
        "news_snapshot": {"news_data_version": "news_v1"},
    }


def test_build_canonical_decision_approve():
    rep = _platform_report("600000.SH")
    cd = build_canonical_decision(
        rep,
        as_of="2024-06-10",
        universe_row={"candidate_score": 0.55, "candidate_sources": ["quant"]},
        bar_like={"is_st": False, "is_halt": False, "limit_up": False, "amount": 1e8},
        risk_allow_fn=_RiskStub().allow_open,
    )
    assert cd["committee_approve"] is True
    assert cd["decision_source"] == DECISION_SOURCE_PLATFORM
    assert cd["research_rating"] == "BUY"
    assert cd["trading_action"] == "SMALL_POSITION"
    assert cd["factor_version"] == "factor_v1"
    assert cd["news_version"] == "news_v1"


def test_build_canonical_decision_risk_blocked():
    rep = _platform_report("600000.SH")
    cd = build_canonical_decision(
        rep,
        as_of="2024-06-10",
        universe_row={},
        bar_like={"is_st": True, "is_halt": False, "limit_up": False, "amount": 1e8},
        risk_allow_fn=_RiskStub().allow_open,
    )
    assert cd["committee_approve"] is False
    assert cd["risk_status"] == "blocked"
    assert "st" in cd["risk_flags"]


def test_build_canonical_decision_gate_skip():
    rep = _platform_report("600000.SH", rating="GATE_SKIP", action="NO_ACTION", gate_passed=False)
    cd = build_canonical_decision(
        rep,
        as_of="2024-06-10",
        universe_row={},
        bar_like=None,
        risk_allow_fn=_RiskStub().allow_open,
    )
    assert cd["committee_approve"] is False
    assert cd["risk_status"] == "skipped"


def test_canonical_to_picks_matches_fields():
    rep = _platform_report("000001.SZ")
    cd = build_canonical_decision(
        rep,
        as_of="2024-06-10",
        universe_row={"candidate_score": 0.4},
        bar_like={"is_st": False, "is_halt": False, "limit_up": False, "amount": 1e8},
        risk_allow_fn=_RiskStub().allow_open,
    )
    picks = canonical_to_picks([cd])
    assert picks[0]["committee_approve"] == cd["committee_approve"]
    assert picks[0]["decision_source"] == cd["decision_source"]
    assert picks[0]["research_rating"] == cd["research_rating"]


def test_validate_decision_consistency_ok():
    reports = [_platform_report("600000.SH"), _platform_report("000001.SZ", rating="WATCH", action="WATCH")]
    risk = _RiskStub()
    bars = {
        "600000.SH": type("B", (), {"is_st": False, "is_halt": False, "limit_up": False, "amount": 1e8})(),
        "000001.SZ": type("B", (), {"is_st": False, "is_halt": False, "limit_up": False, "amount": 1e8})(),
    }
    canonical = build_canonical_decisions(
        reports,
        as_of="2024-06-10",
        universe_by_sym={},
        bars_by_sym=bars,
        risk_engine=risk,
    )
    picks = canonical_to_picks(canonical)
    payload = {
        "canonical_decisions": canonical,
        "picks": picks,
        "decision_chain": {"roundtable_controls_trading": False},
        "roundtable": {
            "reviews": [
                {"symbol": "600000.SH", "committee_verdict": "pass", "committee_approve": False},
            ],
        },
    }
    assert validate_decision_consistency(payload) == []


def test_validate_decision_consistency_picks_mismatch():
    canonical = [
        build_canonical_decision(
            _platform_report("600000.SH"),
            as_of="2024-06-10",
            universe_row={},
            bar_like={"is_st": False, "is_halt": False, "limit_up": False, "amount": 1e8},
            risk_allow_fn=_RiskStub().allow_open,
        )
    ]
    picks = canonical_to_picks(canonical)
    picks[0]["committee_approve"] = False  # simulate UI/trade drift
    payload = {
        "canonical_decisions": canonical,
        "picks": picks,
        "decision_chain": {"roundtable_controls_trading": False},
        "roundtable": {"reviews": []},
    }
    errors = validate_decision_consistency(payload)
    assert any("committee_approve" in e for e in errors)


def test_extract_trading_decisions_ignores_roundtable_only():
    payload = {
        "canonical_decisions": [
            {
                "symbol": "600000.SH",
                "committee_approve": False,
                "decision_source": DECISION_SOURCE_PLATFORM,
            }
        ],
        "picks": [
            {"symbol": "600000.SH", "committee_approve": False, "decision_source": DECISION_SOURCE_PLATFORM},
        ],
        "roundtable": {
            "reviews": [
                {"symbol": "000001.SZ", "committee_verdict": "buy", "committee_approve": True},
            ],
        },
    }
    trading = extract_trading_decisions(payload)
    assert trading == []


def test_extract_trading_decisions_legacy_non_roundtable():
    payload = {
        "picks": [
            {
                "symbol": "600000.SH",
                "committee_approve": True,
                "committee_verdict": "buy",
                "decision_source": DECISION_SOURCE_PLATFORM,
            },
        ],
    }
    trading = extract_trading_decisions(payload)
    assert len(trading) == 1
    assert trading[0]["symbol"] == "600000.SH"


def test_apply_portfolio_weights():
    cfg = {"_root": ".", "risk": {"max_name_weight": 0.5, "max_gross_weight": 0.95}}
    decisions = [
        {
            "symbol": "600000.SH",
            "committee_approve": True,
            "leader_score": 0.5,
            "weight": 0.0,
            "confidence": 0.8,
        },
        {
            "symbol": "000001.SZ",
            "committee_approve": True,
            "leader_score": 0.5,
            "weight": 0.0,
            "confidence": 0.8,
        },
    ]
    out = apply_portfolio_weights(decisions, cfg)
    assert len(out) == 2
    assert all("weight" in d for d in out)
