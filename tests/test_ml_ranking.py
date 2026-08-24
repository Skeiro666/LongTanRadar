"""V5 Phase 2 â€?ML ranking before Top-N cutoff."""

from __future__ import annotations

from ashare.ml.candidate_ranking import (
    apply_ml_rank_scores,
    compute_candidate_score,
    resolve_ml_weight,
    winsorize_rank_percentile,
)


def test_winsorize_rank_percentile_basic():
    vals = {f"S{i}": float(i) for i in range(10)}
    ranks = winsorize_rank_percentile(vals)
    assert len(ranks) == 10
    assert min(ranks.values()) >= 0.0
    assert max(ranks.values()) <= 1.0
    assert ranks["S9"] > ranks["S0"]


def test_winsorize_rank_single():
    ranks = winsorize_rank_percentile({"600000.SH": 0.01})
    assert ranks["600000.SH"] == 0.5


def test_apply_ml_rank_scores():
    rows = [
        {"symbol": "600000.SH", "ml_prediction": 0.01},
        {"symbol": "000001.SZ", "ml_prediction": 0.05},
        {"symbol": "000002.SZ", "ml_prediction": -0.02},
    ]
    out = apply_ml_rank_scores(rows)
    by_sym = {r["symbol"]: r["ml_rank_score"] for r in out}
    assert by_sym["600000.SH"] < by_sym["000001.SZ"]
    assert all(0 <= v <= 1 for v in by_sym.values())


def test_compute_candidate_score_uses_ml_rank():
    cw = {"leader": 0.35, "profit_inflection": 0.25, "event": 0.15, "news": 0.15, "ml": 0.10}
    base = {
        "leader_score": 0.5,
        "profit_inflection": {"score": 0.4},
        "event_score": 0.3,
        "news_score": 0.2,
    }
    low = compute_candidate_score({**base, "ml_rank_score": 0.1}, cw, ml_weight=0.10)
    high = compute_candidate_score({**base, "ml_rank_score": 0.9}, cw, ml_weight=0.10)
    assert high > low


def test_compute_candidate_score_zero_ml_weight():
    cw = {"leader": 0.35, "profit_inflection": 0.25, "event": 0.15, "news": 0.15, "ml": 0.10}
    item = {
        "leader_score": 0.8,
        "profit_inflection": {"score": 0.0},
        "event_score": 0.0,
        "news_score": 0.0,
        "ml_rank_score": 0.99,
    }
    with_ml = compute_candidate_score(item, cw, ml_weight=0.10)
    without_ml = compute_candidate_score(item, cw, ml_weight=0.0)
    assert with_ml > without_ml


def test_resolve_ml_weight_from_research_yaml():
    cfg = {"_root": ".", "research": {"ml_ranking": {"enabled": True, "weight_in_candidate_score": 0.15}}}
    assert resolve_ml_weight(cfg, {"ml": 0.10}) == 0.15


def test_resolve_ml_weight_disabled():
    cfg = {"_root": ".", "research": {"ml_ranking": {"enabled": False, "weight_in_candidate_score": 0.15}}}
    assert resolve_ml_weight(cfg, {"ml": 0.10}) == 0.0


def test_ml_ranking_changes_sort_order():
    """Higher ml_rank_score should lift candidate in ranking when ML weight > 0."""
    cw = {"leader": 0.35, "profit_inflection": 0.25, "event": 0.15, "news": 0.15, "ml": 0.10}
    rows = [
        {
            "symbol": "A",
            "leader_score": 0.5,
            "profit_inflection": {"score": 0.3},
            "event_score": 0.2,
            "news_score": 0.1,
            "ml_rank_score": 0.2,
        },
        {
            "symbol": "B",
            "leader_score": 0.48,
            "profit_inflection": {"score": 0.3},
            "event_score": 0.2,
            "news_score": 0.1,
            "ml_rank_score": 0.95,
        },
    ]
    scored = [{**r, "candidate_score": compute_candidate_score(r, cw, ml_weight=0.15)} for r in rows]
    scored.sort(key=lambda x: x["candidate_score"], reverse=True)
    assert scored[0]["symbol"] == "B"
