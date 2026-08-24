"""V5.4 AI ablation — delegates to council ablation suite."""

from tests.test_v5_4_ablation import test_council_ablation_available  # noqa: F401


def test_v54_ai_ablation_reexport():
    from ashare.research.ai_ablation import run_council_ablation

    reports = [
        {"symbol": "A", "decision": {"research_rating": "BUY"}, "quant": {"factor_score": 1.0}, "chairman": {"confidence": 0.8}},
        {"symbol": "B", "decision": {"research_rating": "WATCH"}, "quant": {"factor_score": 0.5}, "chairman": {"confidence": 0.5}},
    ]
    outcomes = [
        {"symbol": "A", "primary_horizons": {"5": {"actual_return": 0.02, "selection_alpha": 0.01}}},
        {"symbol": "B", "primary_horizons": {"5": {"actual_return": 0.01, "selection_alpha": 0.005}}},
    ]
    out = run_council_ablation(reports, outcomes, {"research": {"attribution": {"minimum_sample_size": 2}}}, llm_cost_usd=1.0)
    assert out.get("available") or out.get("insufficient_sample")
