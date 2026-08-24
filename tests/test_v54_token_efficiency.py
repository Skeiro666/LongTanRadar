"""V5.4 token efficiency metrics."""

from __future__ import annotations

from ashare.research.token_efficiency import compute_token_efficiency


def test_token_reduction_estimate():
    te = compute_token_efficiency(
        {"_root": "."},
        gate_summary={"n_passed": 10, "llm_budget": {"used": {"llm_calls": 5, "total_tokens": 40000, "estimated_usd": 1.0}}},
        routing_summary={"n_skip_low": 3, "avg_tokens_per_call": 8000},
        outcome_pack={"portfolio_attribution": {"available": True, "mean_selection_alpha": 0.01}},
    )
    assert te["available"] is True
    assert te["token_reduction_pct"] is not None
    assert te["routing_skips"] == 3
