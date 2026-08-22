"""V5.4 AI council ablation tests."""

from __future__ import annotations

from ashare.research.ai_ablation import run_council_ablation


def _report(sym: str, score: float, rating: str = "BUY", conf: float = 0.7):
    return {
        "symbol": sym,
        "decision": {"research_rating": rating},
        "chairman": {"rating": rating, "confidence": conf},
        "quant": {"factor_score": score},
        "candidate_score": score,
    }


def _outcome(sym: str, sel: float):
    return {
        "symbol": sym,
        "primary_horizons": {"5": {"selection_alpha": sel, "actual_return": sel}},
    }


def test_council_ablation_incremental():
    reports = [_report("600000.SH", 0.9), _report("600001.SH", 0.5, "WATCH", 0.5)]
    outcomes = [_outcome("600000.SH", 0.04), _outcome("600001.SH", 0.02)]
    cfg = {"research": {"attribution": {"minimum_sample": 2, "horizons_days": [5]}, "role_ablation": {"top_k": 2}}}
    r = run_council_ablation(reports, outcomes, cfg, top_k=2, llm_cost_usd=2.0)
    assert r["available"] is True
    assert "horizons" in r
    assert r["llm_cost_usd"] == 2.0


def test_zero_cost_no_division_by_zero():
    reports = [_report("600000.SH", 0.9), _report("600001.SH", 0.5)]
    outcomes = [_outcome("600000.SH", 0.04), _outcome("600001.SH", 0.02)]
    cfg = {"research": {"attribution": {"minimum_sample": 2, "horizons_days": [5]}}}
    r = run_council_ablation(reports, outcomes, cfg, llm_cost_usd=0)
    assert r["cost_unavailable"] is True
    assert r["ai_efficiency"] is None


def test_insufficient_sample():
    r = run_council_ablation([], [], {"research": {"attribution": {"minimum_sample": 5}}})
    assert r["available"] is False
