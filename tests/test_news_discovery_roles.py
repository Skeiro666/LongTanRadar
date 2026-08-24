from __future__ import annotations

from ashare.news.opportunity import NewsOpportunityEngine
from ashare.news.schema import discovery_grade

from news_intel_fakes import sample_news


def test_direct_discovery_code_mapping(tmp_path):
    eng = NewsOpportunityEngine({"_root": str(tmp_path)})
    out = eng.discover(
        persist=False,
        news=[sample_news("000786签订重大合同订单金额10亿")],
    )
    assert any(c["symbol"] == "000786.SZ" for c in out["news_candidates"])
    cand = next(c for c in out["news_candidates"] if c["symbol"] == "000786.SZ")
    assert cand["discovery_grade"] == "DIRECT"
    assert cand["news_role"] == "discovery"
    assert cand["entity_source"] in {"explicit_code", "explicit_company"}
    assert "BUY" not in cand.get("status", "")


def test_discovery_grade_helper():
    assert discovery_grade("explicit_code") == "DIRECT"
    assert discovery_grade("llm_inferred") == "INFERRED"
    assert discovery_grade("unknown") == "NONE"


def test_inferred_not_ordinary_candidate(tmp_path, monkeypatch):
    from news_intel_fakes import FakeNewsClient

    client = FakeNewsClient()
    monkeypatch.setattr("ashare.news.llm_mapping.news_llm_client", lambda cfg: client)
    eng = NewsOpportunityEngine(
        {
            "_root": str(tmp_path),
            "news": {
                "discovery": {"llm_mapping": True, "enabled": True, "aliases": {}},
                "intelligence": {"enabled": True, "max_concurrency": 1},
                "llm": {"model": "qwen3.5:4b", "base_url": "http://127.0.0.1:11434/v1"},
            },
        }
    )
    out = eng.discover(persist=False, news=[sample_news("某材料价格大幅上涨")])
    assert all(c.get("discovery_grade") != "INFERRED" for c in out["news_candidates"])
    watch = out.get("news_watchlist") or []
    rejected = out.get("rejected") or []
    inferred = [x for x in watch + rejected if x.get("entity_source") == "llm_inferred"]
    assert inferred
    assert all(x.get("status") == "REJECTED" or x.get("reject_reason") == "INFERRED_DISCOVERY" for x in inferred)
    assert "BUY" not in str(out)
