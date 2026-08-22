"""V5.2 Phase 4 — unified alpha + role ablation + model benchmark."""

from __future__ import annotations

import pandas as pd

from ashare.research.model_benchmark import build_model_benchmark
from ashare.research.role_ablation import compute_role_ablation, synthetic_chair_score
from ashare.research.tracking import ReviewEngine


def _panel(sym: str, closes: list[float]) -> dict[str, pd.DataFrame]:
    dates = pd.bdate_range("2024-01-02", periods=len(closes))
    return {sym: pd.DataFrame({"date": dates, "close": closes, "volume": [1e6] * len(closes)})}


def test_canonical_ai_incremental_alpha_is_topk():
    sym_a, sym_b, sym_c = "000001.SZ", "600000.SH", "000002.SZ"
    dates = pd.bdate_range("2024-01-02", periods=12)
    panel = {}
    panel.update(_panel(sym_a, [10.0] * 3 + [12.0] * 9))
    panel.update(_panel(sym_b, [20.0] * 3 + [21.0] * 9))
    panel.update(_panel(sym_c, [15.0] * 3 + [14.0] * 9))
    reports = [
        {"symbol": sym_a, "research_time": str(dates[2].date()), "quant": {"factor_score": 0.9}, "decision": {"research_rating": "WATCH"}, "candidate_sources": ["quant"]},
        {"symbol": sym_b, "research_time": str(dates[2].date()), "quant": {"factor_score": 0.5}, "decision": {"research_rating": "BUY"}, "chairman": {"confidence": 0.8}, "candidate_sources": ["quant"]},
        {"symbol": sym_c, "research_time": str(dates[2].date()), "quant": {"factor_score": 0.7}, "decision": {"research_rating": "PASS"}, "candidate_sources": ["quant"]},
    ]
    pack = ReviewEngine({"_root": "."}).attribution_report(reports, panel, horizon="5", benchmark_returns={"5": 0.0}, persist=False)
    canon = pack["ai_incremental_alpha"]
    topk = pack["ai_topk_ablation"]
    legacy = pack["ai_incremental_alpha_legacy"]
    assert canon.get("canonical") is True
    assert canon.get("method") == "same_universe_topk_ablation"
    assert canon["ai_incremental_alpha"] == topk["ai_incremental_alpha"]
    assert legacy.get("note", "").startswith("legacy cohort")


def test_role_ablation_replay():
    sym_a, sym_b = "000001.SZ", "600000.SH"
    dates = pd.bdate_range("2024-01-02", periods=12)
    panel = {}
    panel.update(_panel(sym_a, [10.0] * 3 + [12.0] * 9))
    panel.update(_panel(sym_b, [20.0] * 3 + [19.0] * 9))
    reports = [
        {
            "symbol": sym_a,
            "research_time": str(dates[2].date()),
            "decision": {"research_rating": "BUY"},
            "chairman": {"rating": "BUY", "confidence": 0.7},
            "council": {
                "quant": {"score": 0.6, "status": "ok"},
                "bear": {"score": -0.1, "status": "ok"},
                "event": {"score": 0.4, "status": "ok"},
            },
        },
        {
            "symbol": sym_b,
            "research_time": str(dates[2].date()),
            "decision": {"research_rating": "WATCH"},
            "chairman": {"rating": "WATCH", "confidence": 0.5},
            "council": {
                "quant": {"score": 0.2, "status": "ok"},
                "bear": {"score": -0.2, "status": "ok"},
                "event": {"score": 0.1, "status": "ok"},
            },
        },
    ]
    outcomes = [ReviewEngine({"_root": "."}).tracking.outcomes_for_report(r, panel, benchmark_returns={"5": 0.0}) for r in reports]
    ab = compute_role_ablation(reports, outcomes, horizon="5", top_k=2)
    assert ab["available"] is True
    assert ab["experimental"] is True
    assert "quant" in ab["by_role"]


def test_synthetic_chair_score_drops_role():
    opinions = {
        "quant": {"score": 0.8, "status": "ok"},
        "event": {"score": 0.2, "status": "ok"},
        "bear": {"score": -0.1, "status": "ok"},
    }
    full = synthetic_chair_score(opinions)
    without_quant = synthetic_chair_score(opinions, exclude_role="quant")
    assert full != without_quant


def test_model_benchmark_from_cycle():
    cycle = {
        "total_tokens": 100_000,
        "estimated_usd": 0.05,
        "by_model": {"model-a": 60_000, "model-b": 40_000},
        "by_role": {"quant": 30_000, "chairman": 20_000},
        "model_cost": {"model-a": 0.03, "model-b": 0.02},
        "role_cost": {"quant": 0.015, "chairman": 0.01},
    }
    mb = build_model_benchmark({}, cycle_summary=cycle, ai_incremental_alpha={"ai_incremental_alpha": 0.02, "method": "same_universe_topk_ablation"})
    assert mb["available"] is True
    assert len(mb["models"]) == 2
    assert mb["alpha_per_100k_tokens"] == 0.02
