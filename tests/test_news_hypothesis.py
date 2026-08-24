from __future__ import annotations

from ashare.news.enrich import hypothesis_from_intel
from ashare.news.opportunity import NewsOpportunityEngine

from news_intel_fakes import FakeNewsClient, sample_news


def test_hypothesis_not_buy(tmp_path):
    n = sample_news("AI数据中心建设加速，服务器与光模块需求上升")
    intel = {
        "hypothesis": "AI数据中心建设加速",
        "beneficiary_industries": ["服务器", "光模块"],
        "event_confidence": 0.68,
    }
    hyp = hypothesis_from_intel(intel, n)
    assert hyp["hypothesis"]
    assert "服务器" in hyp["beneficiary_industries"]
    assert hyp["confidence"] <= 0.68
    assert "BUY" not in str(hyp)


def test_unmapped_high_value_goes_to_hypothesis(tmp_path, monkeypatch):
    client = FakeNewsClient(
        intel={
            "event_type": "industry",
            "direction": "positive",
            "importance": 0.7,
            "novelty": 0.6,
            "market_relevance": 0.5,
            "impact_horizon": "medium",
            "event_confidence": 0.6,
            "summary": "行业景气",
            "evidence": ["数据中心建设加速"],
            "hypothesis": "AI数据中心建设加速",
            "beneficiary_industries": ["服务器"],
        }
    )
    monkeypatch.setattr("ashare.news.llm_mapping.news_llm_client", lambda cfg: client)
    monkeypatch.setattr("ashare.news.llm_mapping.infer_entities_from_news", lambda *a, **k: [])
    eng = NewsOpportunityEngine(
        {
            "_root": str(tmp_path),
            "news": {
                "discovery": {"llm_mapping": True, "enabled": True},
                "intelligence": {"enabled": True, "max_concurrency": 1},
                "llm": {"model": "qwen3.5:4b", "base_url": "http://127.0.0.1:11434/v1"},
            },
        }
    )
    out = eng.discover(persist=False, news=[n := sample_news("水泥行业价格波动政策支持")])
    assert all(c.get("discovery_grade") != "INFERRED" or c.get("status") == "REJECTED" for c in out["news_candidates"])
    assert "BUY" not in str(out)
    _ = n
