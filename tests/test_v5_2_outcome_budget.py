"""V5.2 — outcome truth + LLM budget tests."""

from __future__ import annotations

import pandas as pd

from ashare.research.llm_budget import budget_allows_llm_call, budget_snapshot, llm_budget_cfg
from ashare.research.outcome_truth import (
    PRIMARY_PAPER_FILL,
    PRIMARY_SIGNAL_CLOSE,
    apply_primary_truth,
    resolve_primary_horizons,
    summarize_portfolio_attribution,
)


def test_primary_horizons_prefers_paper_fill():
    outcome = {
        "horizons": {"5": {"actual_return": 0.1, "market_alpha": 0.05}},
        "execution": {
            "available": True,
            "horizons_from_fill": {"5": {"actual_return": 0.08, "market_alpha": 0.03}},
        },
    }
    hz, src = resolve_primary_horizons(outcome)
    assert src == PRIMARY_PAPER_FILL
    assert hz["5"]["actual_return"] == 0.08


def test_primary_horizons_fallback_signal():
    outcome = {"horizons": {"5": {"actual_return": 0.1}}, "execution": {"available": False}}
    _, src = resolve_primary_horizons(outcome)
    assert src == PRIMARY_SIGNAL_CLOSE


def test_portfolio_attribution_summary():
    outcomes = apply_primary_truth(
        [
            {"horizons": {"5": {"actual_return": 0.1, "market_alpha": 0.04, "selection_alpha": 0.02}}},
            {"horizons": {"5": {"actual_return": 0.06, "market_alpha": 0.01, "selection_alpha": 0.01}}},
        ]
    )
    summary = summarize_portfolio_attribution(outcomes, horizon="5")
    assert summary["available"] is True
    assert abs(summary["mean_total_return"] - 0.08) < 1e-9


def test_llm_budget_hard_stop():
    cfg = {
        "_root": ".",
        "research": {"llm_budget": {"enabled": True, "max_llm_calls": 2, "max_cost_usd": 0.01}},
    }
    cycle = {"n_calls": 3, "input_tokens": 100, "output_tokens": 50, "estimated_usd": 0.02}
    snap = budget_snapshot(cycle, cfg)
    assert snap["hard_stop"] is True
    assert "max_llm_calls" in snap["exceeded"] or "max_cost_usd" in snap["exceeded"]
    ok, reason = budget_allows_llm_call(cycle, cfg)
    assert ok is False
    assert reason in {"max_llm_calls", "max_cost_usd", "max_input_tokens", "max_output_tokens"}


def test_llm_budget_zero_means_unlimited():
    cfg = {
        "_root": ".",
        "research": {
            "llm_budget": {
                "enabled": True,
                "max_llm_calls": 0,
                "max_input_tokens": 0,
                "max_output_tokens": 0,
                "max_cost_usd": 0,
            }
        },
    }
    snap = budget_snapshot({"n_calls": 999, "input_tokens": 999999, "estimated_usd": 99}, cfg)
    assert snap["hard_stop"] is False
