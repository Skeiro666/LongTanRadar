from __future__ import annotations

from datetime import datetime, timezone

from ashare.news.engine import NewsIntelligenceEngine
from ashare.news.models import RawNews, make_id, title_hash
from ashare.news.opportunity import NewsOpportunityEngine

from news_intel_fakes import FakeNewsClient, sample_news


def test_collect_stock_merges_intel_into_events(monkeypatch, tmp_path):
    good = RawNews(
        id=make_id("N"),
        source="baidu",
        title="北新建材000786签订重大合同订单金额10亿",
        fetched_at="2026-08-20T00:00:00+00:00",
        summary="签订重大合同",
        published_at="2026-08-20 00:00:00",
        title_hash=title_hash("北新建材000786签订重大合同订单金额10亿"),
        media="证券时报",
    )

    class FakeP:
        name = "fake"
        version = "fake_v1"

        def fetch_stock_news(self, symbol, *, name="", limit=20):
            return [good]

    client = FakeNewsClient()
    monkeypatch.setattr("ashare.news.llm_mapping.news_llm_client", lambda cfg: client)
    eng = NewsIntelligenceEngine(
        {
            "_root": str(tmp_path),
            "news": {
                "fetch": {"min_link_confidence": 0.5},
                "intelligence": {"enabled": True},
                "llm": {"model": "qwen3.5:4b", "base_url": "http://127.0.0.1:11434/v1"},
            },
        }
    )
    monkeypatch.setattr(eng, "providers", [FakeP()])
    pkg = eng.collect_stock("000786.SZ", name="北新建材", persist=False)
    assert pkg.get("compact_news_package")
    events = pkg.get("events") or []
    assert events
    assert events[0].get("normalized_event_type") or events[0].get("news_intelligence")
    assert client.calls >= 1


def test_discover_merge_intel_and_stats(monkeypatch, tmp_path):
    client = FakeNewsClient()
    monkeypatch.setattr("ashare.news.llm_mapping.news_llm_client", lambda cfg: client)
    eng = NewsOpportunityEngine(
        {
            "_root": str(tmp_path),
            "news": {
                "discovery": {"llm_mapping": True, "enabled": True},
                "intelligence": {"enabled": True},
                "llm": {"model": "qwen3.5:4b", "base_url": "http://127.0.0.1:11434/v1"},
            },
        }
    )
    out = eng.discover(persist=False, news=[sample_news("000786签订重大合同订单金额10亿")])
    assert out["n_events"] >= 1
    assert "intel_stats" in out
    ev = out["events"][0]
    assert ev.get("intel_source") in {"merged", "rule", ""} or ev.get("news_intelligence_score") is not None
