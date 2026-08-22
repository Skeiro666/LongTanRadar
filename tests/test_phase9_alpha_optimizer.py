"""V5 Phase 9 — Top-K ablation alpha + optimizer experiment gate."""

from __future__ import annotations

import pandas as pd

from ashare.ai.optimizer_experiment import approve_experiment, create_experiment, list_experiments
from ashare.research.tracking import ReviewEngine


def _panel(sym: str, closes: list[float]) -> dict[str, pd.DataFrame]:
    dates = pd.bdate_range("2024-01-02", periods=len(closes))
    return {sym: pd.DataFrame({"date": dates, "close": closes})}


def test_topk_ablation_same_universe():
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
    eng = ReviewEngine({"_root": "."})
    outcomes = [eng.tracking.outcomes_for_report(r, panel, benchmark_returns={"5": 0.0}) for r in reports]
    ab = eng.compute_topk_ablation_alpha(reports, outcomes, horizon="5", top_k=2)
    assert ab["available"] is True
    assert ab["method"] == "same_universe_topk_ablation"
    assert ab["ai_incremental_alpha"] is not None
    assert len(ab["baseline_topk"]["symbols"]) == 2
    assert len(ab["ai_topk"]["symbols"]) == 2


def test_optimizer_experiment_no_auto_apply(tmp_path):
    cfg = {"_root": str(tmp_path), "strategy": {"top_n": 3}, "pool": {}, "factors": {}, "ml": {}, "optimizer": {"auto_apply": False}}
    proposal = {"rationale": "test", "top_n": 4}
    exp = create_experiment(cfg, proposal, persist=True)
    assert exp["status"] == "proposed"
    assert list_experiments(cfg)[-1]["experiment_id"] == exp["experiment_id"]
    applied = approve_experiment(cfg, exp)
    assert applied["ok"] is True
    assert applied["cfg"]["strategy"]["top_n"] == 4
