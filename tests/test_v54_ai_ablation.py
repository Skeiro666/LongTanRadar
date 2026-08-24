"""V5.4 AI ablation — council on/off replay."""

from __future__ import annotations

from ashare.research.ai_ablation import run_council_ablation


def test_v54_ai_ablation_incremental():
    reports = [
        {"symbol": "A", "decision": {"research_rating": "BUY"}, "quant": {"factor_score": 1.0}, "chairman": {"confidence": 0.8}},
        {"symbol": "B", "decision": {"research_rating": "WATCH"}, "quant": {"factor_score": 0.5}, "chairman": {"confidence": 0.5}},
    ]
    outcomes = [
        {"symbol": "A", "primary_horizons": {"5": {"actual_return": 0.02, "selection_alpha": 0.01}}},
        {"symbol": "B", "primary_horizons": {"5": {"actual_return": 0.01, "selection_alpha": 0.005}}},
    ]
    out = run_council_ablation(reports, outcomes, {"research": {"attribution": {"minimum_sample_size": 2}}}, llm_cost_usd=1.0)
    assert "available" in out
    h5 = (out.get("horizons") or {}).get("5") or {}
    if out.get("available"):
        assert h5.get("ai_incremental_alpha") is not None or h5.get("insufficient_sample")
