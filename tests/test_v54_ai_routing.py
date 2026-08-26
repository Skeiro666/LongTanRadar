"""V5.4 AI routing - 0 LLM conflict score."""

from __future__ import annotations

from ashare.research.ai_routing import compute_ai_routing, compute_conflict_score, quant_only_decision


def test_conflict_high_when_signals_disagree():
    c = {
        "candidate_score": 0.4,
        "leader_score": 0.6,
        "event_score": 0.05,
        "news_score": 0.05,
        "ml_prediction": 0.001,
        "profit_inflection": {"score": -0.2, "available": True},
    }
    pack = compute_conflict_score(c, {})
    assert 0 <= pack["conflict_score"] <= 1


def test_low_routing_skips_council():
    c = {
        "candidate_score": 0.85,
        "leader_score": 0.8,
        "event_score": 0.7,
        "news_score": 0.1,
        "ml_prediction": 0.01,
        "profit_inflection": {"score": 0.5, "available": True},
        "value_available": True,
    }
    r = compute_ai_routing(c, {"research": {"ai_routing": {"enabled": True}}})
    assert r["routing_level"] in {"LOW", "MEDIUM", "HIGH"}
    if r["routing_level"] == "LOW":
        assert r["skip_council"] is True


def test_quant_only_decision_no_llm():
    d = quant_only_decision({"candidate_score": 0.6})
    assert d["source"] == "quant_routing_skip"
    assert d["rating"] in {"BUY", "WATCH", "PASS"}
    assert d["trading_action"] != "SMALL_POSITION"
