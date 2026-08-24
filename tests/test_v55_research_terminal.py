from __future__ import annotations

from ashare.research.historical_cohort import build_historical_cohort, cohort_key
from ashare.services.alpha_lab import build_alpha_lab, build_experiment_lab
from ashare.services.research_terminal import build_candidate_card, build_research_terminal, _discovery_source


def test_discovery_source():
    assert _discovery_source(["news", "quant"]) == "量化+新闻"
    assert _discovery_source(["news"]) == "新闻"
    assert _discovery_source(["quant"]) == "量化"


def test_cohort_key_buckets():
    key = cohort_key({"news_score": 0.35, "news_intelligence": {"importance": 0.5, "event_type": "order"}})
    assert key["event_type"] == "order"
    assert "0.2-0.4" in key["news_score_bucket"]


def test_historical_cohort_insufficient():
    cand = {"news_score": 0.4, "news_intelligence": {"importance": 0.6, "event_type": "order"}}
    out = build_historical_cohort(cand, [], {})
    assert out["label"] == "历史同类信号"
    assert out["horizons"]["5"]["status"] == "INSUFFICIENT_SAMPLE"


def test_candidate_card_fields():
    card = build_candidate_card(
        {
            "symbol": "600000.SH",
            "name": "Test",
            "candidate_sources": ["news"],
            "news_score": 0.3,
            "news_conflict": {"news_conflict": True, "conflict_score": 0.6, "signals": {"rs_weak": True}},
        },
        quant_top_n=set(),
        report={"rating": "WATCH", "action": "NONE", "research_id": "RTEST"},
        outcomes=[],
        cfg={},
    )
    assert card["news_labels"] == ["新闻发现", "纯新闻"]
    assert card["conflict"]["display"] == "新闻/量化冲突"
    assert "相对强弱偏弱" in card["conflict"]["reason_labels"]


def test_experiment_lab_delta():
    fake_ablation = {
        "arms": {
            "no_news": {"5": {"status": "INSUFFICIENT_SAMPLE", "sample_count": 2}},
            "discovery_only": {"5": {"status": "INSUFFICIENT_SAMPLE", "sample_count": 1}},
        }
    }
    lab = build_experiment_lab(fake_ablation, min_n=30)
    assert lab["baseline"] == "no_news"
    assert len(lab["experiments"]) == 1


def test_alpha_lab_has_performance_dashboard():
    pack = build_alpha_lab({"_root": "."}, window="all")
    assert "performance_dashboard" in pack
    assert "experiment_lab" in pack
    assert "calibration_charts" in pack


def test_research_terminal_shape():
    term = build_research_terminal({"_root": "."})
    assert "candidates" in term
    assert "matrix" in term
    assert "counts" in term


def test_v55_api_endpoints():
    from fastapi.testclient import TestClient

    from ashare.api.app import create_app

    with TestClient(create_app()) as client:
        for path in (
            "/api/research/terminal",
            "/api/token-dashboard",
            "/api/notifications/history?limit=3",
            "/api/alpha-lab?window=all",
        ):
            r = client.get(path)
            assert r.status_code == 200, path
