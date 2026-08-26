"""Production SSOT remediations: signal contract, bear, risk, canonical fence."""

from __future__ import annotations

from pathlib import Path

from ashare.portfolio import RiskFilterEngine
from ashare.research.ai_routing import quant_only_decision
from ashare.research.canonical_decision import (
    DECISION_SOURCE_PLATFORM,
    DECISION_SOURCE_ROUNDTABLE,
    build_canonical_decision,
    extract_trading_decisions,
)
from ashare.research.council import AICouncilEngine, ChairmanEngine
from ashare.research.gate import evaluate_research_gate
from ashare.research.signal_contract import (
    STATUS_MISSING,
    STATUS_UNAVAILABLE,
    STATUS_ZERO,
    attach_signal_contract,
    classify_numeric,
    extract_candidate_signals,
)
from ashare.research.snapshot import build_snapshot


def _cfg() -> dict:
    return {"_root": str(Path(__file__).resolve().parents[1])}


def test_missing_not_zero():
    assert classify_numeric(None)["status"] == STATUS_MISSING
    assert classify_numeric(None)["value"] is None
    assert classify_numeric(0)["status"] == STATUS_ZERO
    assert classify_numeric(0)["value"] == 0.0
    assert classify_numeric(None, unavailable=True)["status"] == STATUS_UNAVAILABLE


def test_candidate_contract_profit_unavailable():
    c = {
        "symbol": "600000.SH",
        "candidate_score": 0.2,
        "leader_score": 0.3,
        "profit_inflection": {"available": False, "quality": "unavailable", "score": None},
        "profit_status": "UNAVAILABLE",
        "ml_status": "no_model",
        "event_score": 0.0,
        "event_status": "ZERO",
    }
    attach_signal_contract(c)
    sig = extract_candidate_signals(c)
    assert sig["profit_score"]["available"] is False
    assert sig["profit_score"]["status"] == STATUS_UNAVAILABLE
    assert sig["ml_prediction"]["available"] is False
    assert sig["event_score"]["status"] == STATUS_ZERO
    assert sig["event_score"]["value"] == 0.0


def test_gate_missing_ml_not_treated_as_zero_pass():
    """Missing ML must not satisfy min_ml via coerced 0; other strong signal can still pass."""
    cfg = _cfg()
    row = {
        "symbol": "600000.SH",
        "candidate_score": 0.2,
        "leader_score": 0.5,
        "ml_prediction": None,
        "ml_status": "no_model",
        "event_score": 0.0,
        "candidate_sources": ["quant"],
        "profit_inflection": {"available": False, "score": None},
        "news_package": {},
        "research_hypotheses": [],
    }
    dec = evaluate_research_gate(row, cfg, rank=5)
    assert dec.passed is True  # leader strong
    assert dec.signals.get("ml_prediction") is None


def test_bear_neutral_without_evidence():
    eng = AICouncilEngine(_cfg())
    out = eng._bear_heuristic({"value_available": False, "quant": {"leader_score": 0.4}}, 0.4, None, "bear_v1", "ok")
    assert out["stance"] == "neutral"
    assert float(out["score"]) == 0.0
    assert int(out["evidence_count"]) == 0


def test_valuation_unavailable_not_bearish_score():
    eng = AICouncilEngine(_cfg())
    out = eng._heuristic("valuation", {"value_available": False, "quant": {}}, "valuation_v1", "ok")
    assert out["status"] == "unavailable"
    assert out["stance"] == "neutral"
    assert out["score"] is None


def test_chairman_entry_setup_mapping():
    chair = ChairmanEngine(_cfg())
    opinions = {
        "fundamental": {"score": 0.5, "status": "ok", "stance": "bull"},
        "quant": {"score": 0.45, "status": "ok", "stance": "bull"},
        "event": {"score": 0.4, "status": "ok", "stance": "bull"},
        "bear": {"score": 0.0, "status": "ok", "stance": "neutral", "evidence_count": 0, "top_risks": []},
    }
    wait = chair._heuristic(opinions, [], "chairman_v1", snapshot={"trade_timing_action": "WAIT"})
    assert wait["rating"] == "BUY"
    assert wait["trading_action"] == "WAIT_FOR_CONFIRMATION"
    assert wait["entry_setup"] == "CONFIRMATION_REQUIRED"

    ready = chair._heuristic(opinions, [], "chairman_v1", snapshot={"trade_timing_action": "BUY_READY"})
    assert ready["trading_action"] == "SMALL_POSITION"
    assert ready["entry_setup"] == "READY"


def test_risk_filter_pass_block_unknown():
    risk = RiskFilterEngine({"pool": {"min_amount": 1e7}})
    assert risk.evaluate({"is_st": False, "is_halt": False, "limit_up": False, "amount": 2e7})["status"] == "PASS"
    lu = risk.evaluate({"is_st": False, "is_halt": False, "limit_up": True, "amount": 2e7})
    assert lu["status"] == "BLOCK"
    assert "LIMIT_UP_NO_ENTRY" in lu["reasons"]
    unk = risk.evaluate({"is_st": False, "is_halt": False, "limit_up": False, "amount": None})
    assert unk["status"] == "UNKNOWN"
    assert risk.evaluate(None)["status"] == "UNKNOWN"


def test_quant_only_never_small_position():
    d = quant_only_decision({"candidate_score": 0.9})
    assert d["rating"] == "BUY"
    assert d["trading_action"] != "SMALL_POSITION"
    assert d["trading_action"] == "WAIT_FOR_CONFIRMATION"


def test_canonical_fence_routing_skip_no_approve():
    rep = {
        "research_id": "RTEST1",
        "symbol": "600000.SH",
        "decision": {"research_rating": "BUY", "action": "SMALL_POSITION"},
        "chairman": {
            "source": "quant_routing_skip",
            "rating": "BUY",
            "trading_action": "SMALL_POSITION",
            "confidence": 0.7,
            "base_case": "x",
            "risks": [],
            "time_horizon": "5D",
        },
        "gate": {"passed": True},
        "candidate_sources": ["quant"],
        "versions": {},
        "news_snapshot": {},
    }
    cd = build_canonical_decision(
        rep,
        as_of="2024-06-10",
        universe_row={},
        bar_like={"is_st": False, "is_halt": False, "limit_up": False, "amount": 1e8},
        risk_allow_fn=lambda b: (True, "ok"),
    )
    assert cd["committee_approve"] is False
    assert cd["trading_action"] == "WAIT_FOR_CONFIRMATION"
    assert cd["explanation"]["final_reason"]
    assert cd["final_action"] == "NO_ACTION"


def test_legacy_roundtable_not_in_trading():
    payload = {
        "canonical_decisions": [
            {
                "symbol": "600000.SH",
                "committee_approve": False,
                "decision_source": DECISION_SOURCE_PLATFORM,
                "final_action": "NO_ACTION",
            }
        ],
        "roundtable": {
            "reviews": [{"symbol": "000001.SZ", "committee_approve": True, "committee_verdict": "buy"}],
        },
    }
    assert extract_trading_decisions(payload) == []


def test_research_snapshot_immutable_asof_and_signals():
    snap = build_snapshot(
        {
            "symbol": "600000.SH",
            "name": "测试",
            "as_of": "2024-06-10",
            "candidate_score": 0.3,
            "leader_score": 0.4,
            "ml_prediction": None,
            "ml_status": "no_model",
            "profit_status": "UNAVAILABLE",
            "profit_inflection": {"available": False},
            "event_score": 0.0,
            "event_status": "ZERO",
            "value_available": False,
        },
        _cfg(),
    )
    assert snap["as_of"] == "2024-06-10"
    assert snap["research_date"] == "2024-06-10"
    assert snap["versions"]["as_of"] == "2024-06-10"
    assert snap["ml_prediction_status"] in {None, "UNAVAILABLE", "MISSING", "FAILED"} or snap.get("quant", {}).get(
        "ml_status"
    ) == "no_model"
    # Live fields must not be baked into research snapshot builder
    assert "live_price" not in snap
    assert "live_status" not in snap


def test_council_context_includes_research_candidate_live():
    from ashare.research.council_context import build_council_context

    ctx = build_council_context(
        research={"symbol": "600000.SH", "as_of": "2024-06-10", "quant": {"leader_score": 0.5}, "value_available": False},
        candidate={"candidate_score": 0.4, "ml_status": "no_model", "profit_status": "UNAVAILABLE"},
        live={"live_price": 10.1, "live_status": "BREAK_LIMIT", "live_updated_at": "2024-06-11T01:00:00Z"},
        reconciliation={"state": "DEGRADED"},
    )
    assert ctx["research_date"] == "2024-06-10"
    assert ctx["candidate"]["signals"]
    assert ctx["live"]["live_status"] == "BREAK_LIMIT"
    assert ctx["reconciliation"]["state"] == "DEGRADED"
    assert ctx["data_quality"]


def test_canonical_has_decision_id_and_explanation():
    rep = {
        "research_id": "RTEST2",
        "symbol": "600000.SH",
        "decision": {"research_rating": "BUY", "action": "WAIT_FOR_CONFIRMATION"},
        "chairman": {
            "source": "heuristic",
            "rating": "BUY",
            "trading_action": "WAIT_FOR_CONFIRMATION",
            "entry_setup": "CONFIRMATION_REQUIRED",
            "confidence": 0.5,
            "base_case": "wait",
            "risks": [],
            "time_horizon": "5D",
        },
        "gate": {"passed": True},
        "candidate_sources": ["quant"],
        "versions": {},
        "news_snapshot": {},
    }
    cd = build_canonical_decision(
        rep,
        as_of="2024-06-10",
        universe_row={},
        bar_like={"is_st": False, "is_halt": False, "limit_up": False, "amount": 1e8},
        risk_allow_fn=lambda b: (True, "ok"),
    )
    assert cd["decision_id"]
    assert cd["no_buy_reason"]
    assert "NO_VALID_ENTRY_SETUP" in str(cd["no_buy_reason"])
