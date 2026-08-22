"""V5.4 AI efficiency tests."""

from __future__ import annotations

from ashare.research.ai_ablation import _efficiency_status, run_council_ablation


def test_efficiency_status_unproven_low_sample():
    assert _efficiency_status(0.05, 1.0, 2, 5) == "UNPROVEN"


def test_efficiency_status_zero_cost():
    reports = [
        {"symbol": "A", "decision": {"research_rating": "BUY"}, "chairman": {"confidence": 0.8}, "quant": {"factor_score": 1}},
        {"symbol": "B", "decision": {"research_rating": "WATCH"}, "chairman": {"confidence": 0.5}, "quant": {"factor_score": 0.5}},
    ]
    outcomes = [
        {"symbol": "A", "primary_horizons": {"5": {"selection_alpha": 0.03}}},
        {"symbol": "B", "primary_horizons": {"5": {"selection_alpha": 0.01}}},
    ]
    cfg = {"research": {"attribution": {"minimum_sample": 2, "horizons_days": [5]}}}
    r = run_council_ablation(reports, outcomes, cfg, llm_cost_usd=0)
    assert r.get("cost_unavailable") is True
    assert r.get("ai_efficiency") is None


def test_efficiency_strong_when_high():
    assert _efficiency_status(0.6, 1.0, 10, 5) == "STRONG"
